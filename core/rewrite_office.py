"""Exact native Microsoft Office targets used by annotation Rewrite.

These adapters deliberately bind a proposal to an object-model range instead
of relying on whichever control owns keyboard focus when the user accepts it.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def is_word_desktop_app(active_app: dict[str, Any] | None) -> bool:
    """Return whether a captured window belongs to desktop Microsoft Word."""
    app = active_app if isinstance(active_app, dict) else {}
    process = str(app.get("process_name") or "").strip().casefold()
    bundle = str(app.get("bundle_id") or "").strip().casefold()
    title = str(app.get("name") or app.get("title") or "").casefold()
    return (
        process in {"winword.exe", "winword", "microsoft word"}
        or bundle == "com.microsoft.word"
        or ("microsoft word" in title and process not in _BROWSER_PROCESSES)
    )


@dataclass(frozen=True)
class WordRewriteSnapshot:
    """A Word selection identified by document and character offsets."""

    document_id: str
    document_name: str
    start: int
    end: int
    selected_text: str
    fingerprint: str


@dataclass(frozen=True)
class WordRewritePlan:
    snapshot: WordRewriteSnapshot
    replacement_text: str


@dataclass(frozen=True)
class PowerPointRewriteSnapshot:
    """A PowerPoint text selection identified by slide, shape, and range."""

    presentation_id: str
    presentation_name: str
    slide_id: str
    shape_id: int
    start: int
    length: int
    selected_text: str
    shape_text: str
    prefix_text: str
    suffix_text: str
    fingerprint: str


@dataclass(frozen=True)
class PowerPointRewritePlan:
    snapshot: PowerPointRewriteSnapshot
    replacement_text: str


class WordRewriteClient:
    """Capture and replace a stable Word COM Range with freshness checks."""

    def __init__(self, application_provider: Callable[[], Any] | None = None) -> None:
        self._application_provider = application_provider or _active_word_application

    def inspect_selection(self, active_app: dict[str, Any]) -> WordRewriteSnapshot:
        if not is_word_desktop_app(active_app):
            raise ValueError("The captured window is not Microsoft Word desktop.")
        application = self._application_provider()
        document = application.ActiveDocument
        selection = application.Selection
        text_range = selection.Range.Duplicate
        selected_text = str(text_range.Text or "")
        if any(marker in selected_text for marker in _UNSAFE_WORD_RANGE_MARKERS):
            raise ValueError(
                "The selected Word range contains a table, field, or embedded object boundary. "
                "Select only its editable text before starting Rewrite."
            )
        if not _has_editable_office_text(selected_text):
            raise ValueError("Select editable text in Word before starting Rewrite.")
        start = int(text_range.Start)
        end = int(text_range.End)
        if end <= start:
            raise ValueError("Word did not expose a non-empty text range.")
        document_id = _office_document_identity(document)
        document_name = str(getattr(document, "Name", "") or document_id)
        return WordRewriteSnapshot(
            document_id=document_id,
            document_name=document_name,
            start=start,
            end=end,
            selected_text=selected_text,
            fingerprint=_fingerprint(document_id, start, end, selected_text),
        )

    def apply(self, plan: WordRewritePlan) -> bool:
        snapshot = plan.snapshot
        application = self._application_provider()
        document = _find_office_document(application.Documents, snapshot.document_id)
        current_range = document.Range(snapshot.start, snapshot.end)
        current_text = str(current_range.Text or "")
        if current_text != snapshot.selected_text or _fingerprint(
            snapshot.document_id,
            snapshot.start,
            snapshot.end,
            current_text,
        ) != snapshot.fingerprint:
            raise RuntimeError("Word changed after preview; the exact Rewrite range was not edited.")

        replacement = _office_paragraph_text(plan.replacement_text)
        current_range.Text = replacement
        candidate_ends = {
            int(getattr(current_range, "End", snapshot.start) or snapshot.start),
            snapshot.start + len(replacement),
            snapshot.start + _office_character_units(replacement),
        }
        for candidate_end in sorted(candidate_ends):
            if candidate_end < snapshot.start:
                continue
            inserted_range = document.Range(snapshot.start, candidate_end)
            if str(inserted_range.Text or "") == replacement:
                return True

        _undo_office_mutation(application)
        raise RuntimeError("Word did not verify the exact replacement and Wisp attempted rollback.")


class PowerPointRewriteClient:
    """Capture and replace text in one exact PowerPoint slide shape."""

    def __init__(self, application_provider: Callable[[], Any] | None = None) -> None:
        self._application_provider = application_provider or _active_powerpoint_application

    def inspect_selection(self, active_app: dict[str, Any]) -> PowerPointRewriteSnapshot:
        from core.actions.adapters.presentation import is_powerpoint_desktop_app

        if not is_powerpoint_desktop_app(active_app):
            raise ValueError("The captured window is not Microsoft PowerPoint desktop.")
        application = self._application_provider()
        presentation = application.ActivePresentation
        slide = application.ActiveWindow.View.Slide
        selection = application.ActiveWindow.Selection
        selection_type = int(selection.Type)
        shape, text_range = _powerpoint_selected_shape_and_range(selection, slide)
        selected_text = str(text_range.Text or "")
        if not _has_editable_office_text(selected_text):
            raise ValueError("Select editable text in PowerPoint before starting Rewrite.")

        full_range = _powerpoint_shape_text_range(shape)
        start = int(text_range.Start)
        length = int(text_range.Length)
        if start < 1 or length < 1:
            raise ValueError("PowerPoint did not expose a stable selected text range.")
        shape_text = str(full_range.Text or "")
        prefix = str(full_range.Characters(1, start - 1).Text or "") if start > 1 else ""
        suffix_start = start + length
        suffix_length = max(0, int(full_range.Length) - suffix_start + 1)
        suffix = (
            str(full_range.Characters(suffix_start, suffix_length).Text or "")
            if suffix_length
            else ""
        )
        presentation_id = _office_document_identity(presentation)
        presentation_name = str(getattr(presentation, "Name", "") or presentation_id)
        slide_id = str(slide.SlideID)
        shape_id = int(shape.Id)
        return PowerPointRewriteSnapshot(
            presentation_id=presentation_id,
            presentation_name=presentation_name,
            slide_id=slide_id,
            shape_id=shape_id,
            start=start,
            length=length,
            selected_text=selected_text,
            shape_text=shape_text,
            prefix_text=prefix,
            suffix_text=suffix,
            fingerprint=_fingerprint(
                presentation_id,
                slide_id,
                shape_id,
                start,
                length,
                shape_text,
                selected_text,
                selection_type,
            ),
        )

    def apply(self, plan: PowerPointRewritePlan) -> bool:
        snapshot = plan.snapshot
        application = self._application_provider()
        presentation = _find_office_document(
            application.Presentations,
            snapshot.presentation_id,
        )
        slide = _powerpoint_slide_by_id(presentation, snapshot.slide_id)
        shape = _powerpoint_shape_by_id(slide, snapshot.shape_id)
        full_range = _powerpoint_shape_text_range(shape)
        current_shape_text = str(full_range.Text or "")
        current_selection = str(
            full_range.Characters(snapshot.start, snapshot.length).Text or ""
        )
        if current_shape_text != snapshot.shape_text or current_selection != snapshot.selected_text:
            raise RuntimeError(
                "PowerPoint changed after preview; the exact Rewrite range was not edited."
            )

        replacement = _office_paragraph_text(plan.replacement_text)
        target_range = full_range.Characters(snapshot.start, snapshot.length)
        target_range.Text = replacement
        readback = str(_powerpoint_shape_text_range(shape).Text or "")
        expected = snapshot.prefix_text + replacement + snapshot.suffix_text
        if readback == expected:
            return True

        _undo_office_mutation(application)
        raise RuntimeError(
            "PowerPoint did not verify the exact replacement and Wisp attempted rollback."
        )


def build_word_rewrite_plan(
    snapshot: WordRewriteSnapshot,
    replacement_text: str,
) -> WordRewritePlan:
    replacement = str(replacement_text or "")
    if not replacement:
        raise ValueError("Word Rewrite returned an empty replacement.")
    return WordRewritePlan(snapshot=snapshot, replacement_text=replacement)


def build_powerpoint_rewrite_plan(
    snapshot: PowerPointRewriteSnapshot,
    replacement_text: str,
) -> PowerPointRewritePlan:
    replacement = str(replacement_text or "")
    if not replacement:
        raise ValueError("PowerPoint Rewrite returned an empty replacement.")
    return PowerPointRewritePlan(snapshot=snapshot, replacement_text=replacement)


def _active_word_application() -> Any:
    return _active_com_application(
        "Word.Application",
        "Open the target Word document before using exact Rewrite.",
    )


def _active_powerpoint_application() -> Any:
    return _active_com_application(
        "PowerPoint.Application",
        "Open the target PowerPoint presentation before using exact Rewrite.",
    )


def _active_com_application(prog_id: str, unavailable_message: str) -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Exact Microsoft Office Rewrite is currently available on Windows only.")
    try:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        return win32com.client.GetActiveObject(prog_id)
    except Exception as exc:
        raise RuntimeError(unavailable_message) from exc


def _office_document_identity(document: Any) -> str:
    return str(
        getattr(document, "FullName", "")
        or getattr(document, "Name", "")
        or ""
    ).strip()


def _find_office_document(collection: Any, identity: str) -> Any:
    wanted = str(identity or "").strip().casefold()
    for index in range(1, int(collection.Count) + 1):
        item = collection.Item(index)
        candidates = {
            str(getattr(item, "FullName", "") or "").strip().casefold(),
            str(getattr(item, "Name", "") or "").strip().casefold(),
        }
        if wanted in candidates:
            return item
    raise RuntimeError("The captured Office document is no longer open.")


def _powerpoint_selected_shape_and_range(selection: Any, slide: Any) -> tuple[Any, Any]:
    selection_type = int(selection.Type)
    if selection_type == 3:  # ppSelectionText
        text_range = selection.TextRange
        try:
            shape = selection.ShapeRange.Item(1)
            _powerpoint_shape_text_range(shape)
            return shape, text_range
        except Exception:
            return _locate_powerpoint_text_shape(slide, text_range), text_range
    if selection_type == 2 and int(selection.ShapeRange.Count) == 1:  # ppSelectionShapes
        shape = selection.ShapeRange.Item(1)
        return shape, _powerpoint_shape_text_range(shape)
    raise ValueError("Select text in one PowerPoint text box or shape before starting Rewrite.")


def _locate_powerpoint_text_shape(slide: Any, selected_range: Any) -> Any:
    selected_text = str(selected_range.Text or "")
    start = int(selected_range.Start)
    length = int(selected_range.Length)
    matches: list[Any] = []
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        try:
            text_range = _powerpoint_shape_text_range(shape)
            if str(text_range.Characters(start, length).Text or "") == selected_text:
                matches.append(shape)
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError("PowerPoint did not expose one unambiguous selected text shape.")
    return matches[0]


def _powerpoint_shape_text_range(shape: Any) -> Any:
    if not int(shape.HasTextFrame) or not int(shape.TextFrame.HasText):
        raise ValueError("The selected PowerPoint shape does not contain editable text.")
    return shape.TextFrame.TextRange


def _powerpoint_slide_by_id(presentation: Any, slide_id: str) -> Any:
    for index in range(1, int(presentation.Slides.Count) + 1):
        slide = presentation.Slides.Item(index)
        if str(slide.SlideID) == str(slide_id):
            return slide
    raise RuntimeError("The captured PowerPoint slide is no longer present.")


def _powerpoint_shape_by_id(slide: Any, shape_id: int) -> Any:
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        if int(shape.Id) == int(shape_id):
            return shape
    raise RuntimeError("The captured PowerPoint shape is no longer present.")


def _office_paragraph_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")


def _office_character_units(text: str) -> int:
    return len(str(text).encode("utf-16-le")) // 2


def _has_editable_office_text(text: str) -> bool:
    """Reject collapsed selections and Office object-marker control characters."""
    return any(character.isprintable() and not character.isspace() for character in str(text))


def _undo_office_mutation(application: Any) -> bool:
    """Undo only the immediately preceding object-model mutation."""
    try:
        result = application.Undo()
        return result is not False
    except Exception:
        pass
    try:
        application.CommandBars.ExecuteMso("Undo")
        return True
    except Exception:
        return False


def _fingerprint(*parts: Any) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "chromium.exe",
    "firefox.exe",
    "safari",
}
_UNSAFE_WORD_RANGE_MARKERS = {"\x01", "\x07", "\x0c", "\x13", "\x14", "\x15"}


__all__ = [
    "PowerPointRewriteClient",
    "PowerPointRewritePlan",
    "PowerPointRewriteSnapshot",
    "WordRewriteClient",
    "WordRewritePlan",
    "WordRewriteSnapshot",
    "build_powerpoint_rewrite_plan",
    "build_word_rewrite_plan",
    "is_word_desktop_app",
]
