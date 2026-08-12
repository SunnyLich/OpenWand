"""Concrete Windows PowerPoint object-model client; no UI automation."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.actions.adapters.presentation.client import PresentationMutationReceipt
from core.actions.errors import ActionUnavailableError

_LAYOUTS = {"title_body": 2, "section_header": 33, "two_column": 3, "blank": 12}
_STYLES = {
    "clean_light": {"background": (250, 250, 250), "foreground": (30, 35, 45), "font": "Aptos"},
    "clean_dark": {"background": (24, 27, 34), "foreground": (245, 247, 250), "font": "Aptos"},
    "executive_blue": {"background": (20, 48, 86), "foreground": (245, 249, 255), "font": "Aptos Display"},
    "warm_minimal": {"background": (250, 244, 234), "foreground": (66, 48, 38), "font": "Aptos"},
}
_STYLE_TAG = "OPENWAND_STYLE_PRESET"


class PowerPointComClient:
    """Wrap PowerPoint's supported COM object model through explicit methods."""

    def __init__(self, application_provider: Callable[[], Any] | None = None) -> None:
        self._application_provider = application_provider or _active_powerpoint_application
        self._rollback_tokens: dict[str, dict[str, Any]] = {}

    def get_presentation(self, presentation_id: str) -> dict[str, Any]:
        presentation = self._presentation(presentation_id)
        selected = _selected_slide_id(self._application_provider(), presentation)
        slides = [_slide_payload(presentation.Slides.Item(index)) for index in range(1, presentation.Slides.Count + 1)]
        title = str(getattr(presentation, "Name", "") or Path(presentation_id).name or "Presentation")
        revision = _revision(title, slides)
        return {
            "title": title,
            "revision": revision,
            "selected_slide_id": selected,
            "slides": slides,
        }

    def create_slide(self, presentation_id: str, **kwargs: Any) -> PresentationMutationReceipt:
        cached = self._idempotent_receipt(kwargs)
        if cached is not None:
            return cached
        presentation = self._fresh_presentation(presentation_id, str(kwargs["expected_revision"]))
        index = presentation.Slides.Count + 1
        if kwargs["position"] == "after_selected" and kwargs.get("after_slide_id"):
            selected = _slide_by_id(presentation, str(kwargs["after_slide_id"]))
            index = int(selected.SlideIndex) + 1
        slide = presentation.Slides.Add(index, _LAYOUTS[str(kwargs["layout"])])
        _set_slide_title_body(slide, str(kwargs["title"]), str(kwargs["body"]))
        slide.Tags.Add(_STYLE_TAG, str(kwargs["layout"]))
        token = self._remember({"kind": "delete_slide", "slide_id": str(slide.SlideID)})
        return self._receipt(presentation_id, str(slide.SlideID), token, kwargs)

    def restyle_slide(self, presentation_id: str, **kwargs: Any) -> PresentationMutationReceipt:
        cached = self._idempotent_receipt(kwargs)
        if cached is not None:
            return cached
        presentation = self._fresh_presentation(presentation_id, str(kwargs["expected_revision"]))
        slide = _slide_by_id(presentation, str(kwargs["slide_id"]))
        before = _format_snapshot(slide)
        _apply_style(slide, str(kwargs["preset"]))
        token = self._remember({"kind": "restore_style", "slide_id": str(slide.SlideID), "before": before})
        return self._receipt(presentation_id, str(slide.SlideID), token, kwargs)

    def upsert_speaker_notes(self, presentation_id: str, **kwargs: Any) -> PresentationMutationReceipt:
        cached = self._idempotent_receipt(kwargs)
        if cached is not None:
            return cached
        presentation = self._fresh_presentation(presentation_id, str(kwargs["expected_revision"]))
        slide = _slide_by_id(presentation, str(kwargs["slide_id"]))
        before = _speaker_notes(slide)
        _set_speaker_notes(slide, str(kwargs["notes"]))
        token = self._remember({"kind": "restore_notes", "slide_id": str(slide.SlideID), "before": before})
        return self._receipt(presentation_id, str(slide.SlideID), token, kwargs)

    def rollback(self, presentation_id: str, *, rollback_token: str) -> bool:
        record = self._rollback_tokens.get(str(rollback_token or ""))
        if not record:
            return False
        try:
            presentation = self._presentation(presentation_id)
            slide = _slide_by_id(presentation, str(record["slide_id"]))
            if record["kind"] == "delete_slide":
                slide.Delete()
            elif record["kind"] == "restore_notes":
                _set_speaker_notes(slide, str(record["before"]))
            elif record["kind"] == "restore_style":
                _restore_format(slide, record["before"])
            else:
                return False
            return True
        except Exception:
            return False

    def _presentation(self, presentation_id: str) -> Any:
        application = self._application_provider()
        wanted = str(presentation_id or "").casefold()
        for index in range(1, int(application.Presentations.Count) + 1):
            item = application.Presentations.Item(index)
            identities = {
                str(getattr(item, "Name", "") or "").casefold(),
                str(getattr(item, "FullName", "") or "").casefold(),
            }
            if wanted in identities:
                return item
        raise ActionUnavailableError("The captured PowerPoint presentation is no longer open.")

    def _fresh_presentation(self, presentation_id: str, expected_revision: str) -> Any:
        presentation = self._presentation(presentation_id)
        current = self.get_presentation(presentation_id)
        if str(current["revision"]) != expected_revision:
            raise RuntimeError("PowerPoint changed after preview; the COM mutation was refused.")
        return presentation

    def _remember(self, value: dict[str, Any]) -> str:
        token = uuid.uuid4().hex
        self._rollback_tokens[token] = value
        return token

    def _receipt(self, presentation_id: str, slide_id: str, token: str, kwargs: dict[str, Any]) -> PresentationMutationReceipt:
        receipt = PresentationMutationReceipt(
            change_id=uuid.uuid4().hex,
            revision=str(self.get_presentation(presentation_id)["revision"]),
            slide_id=slide_id,
            rollback_token=token,
        )
        self._rollback_tokens[token]["receipt"] = receipt
        self._rollback_tokens[token]["idempotency_key"] = str(kwargs.get("idempotency_key") or "")
        return receipt

    def _idempotent_receipt(self, kwargs: dict[str, Any]) -> PresentationMutationReceipt | None:
        key = str(kwargs.get("idempotency_key") or "")
        for value in self._rollback_tokens.values():
            if value.get("idempotency_key") == key and isinstance(value.get("receipt"), PresentationMutationReceipt):
                return value["receipt"]
        return None


def _active_powerpoint_application() -> Any:
    if sys.platform != "win32":
        raise ActionUnavailableError("The PowerPoint COM client is available on Windows only.")
    try:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except Exception as exc:
        raise ActionUnavailableError("Open the target PowerPoint presentation before using OpenWand.") from exc


def _slide_payload(slide: Any) -> dict[str, Any]:
    title_shape = None
    try:
        title_shape = slide.Shapes.Title
    except Exception:
        pass
    title_id = int(getattr(title_shape, "Id", 0) or 0) if title_shape is not None else 0
    title = _shape_text(title_shape)
    body_parts: list[str] = []
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        if int(getattr(shape, "Id", 0) or 0) == title_id:
            continue
        text = _shape_text(shape)
        if text:
            body_parts.append(text)
    return {
        "slide_id": str(slide.SlideID),
        "title": title,
        "body": "\n".join(body_parts),
        "speaker_notes": _speaker_notes(slide),
        "style_preset": _tag_value(slide, _STYLE_TAG),
    }


def _shape_text(shape: Any) -> str:
    if shape is None:
        return ""
    try:
        if int(shape.HasTextFrame) and int(shape.TextFrame.HasText):
            return str(shape.TextFrame.TextRange.Text or "").rstrip("\r")
    except Exception:
        pass
    return ""


def _set_slide_title_body(slide: Any, title: str, body: str) -> None:
    try:
        slide.Shapes.Title.TextFrame.TextRange.Text = title
    except Exception:
        if title:
            slide.Shapes.AddTextbox(1, 48, 36, 620, 64).TextFrame.TextRange.Text = title
    body_set = False
    for index in range(1, int(slide.Shapes.Placeholders.Count) + 1):
        shape = slide.Shapes.Placeholders.Item(index)
        try:
            if int(shape.PlaceholderFormat.Type) in {2, 7, 14}:
                shape.TextFrame.TextRange.Text = body
                body_set = True
                break
        except Exception:
            continue
    if body and not body_set:
        slide.Shapes.AddTextbox(1, 64, 120, 600, 300).TextFrame.TextRange.Text = body


def _speaker_notes(slide: Any) -> str:
    try:
        placeholders = slide.NotesPage.Shapes.Placeholders
        for index in range(1, int(placeholders.Count) + 1):
            shape = placeholders.Item(index)
            if int(shape.PlaceholderFormat.Type) == 2:
                return str(shape.TextFrame.TextRange.Text or "").rstrip("\r")
    except Exception:
        pass
    return ""


def _set_speaker_notes(slide: Any, notes: str) -> None:
    placeholders = slide.NotesPage.Shapes.Placeholders
    for index in range(1, int(placeholders.Count) + 1):
        shape = placeholders.Item(index)
        if int(shape.PlaceholderFormat.Type) == 2:
            shape.TextFrame.TextRange.Text = notes
            return
    raise RuntimeError("PowerPoint did not expose a speaker-notes text placeholder.")


def _tag_value(slide: Any, key: str) -> str:
    try:
        return str(slide.Tags.Item(key) or "")
    except Exception:
        return ""


def _format_snapshot(slide: Any) -> dict[str, Any]:
    shapes: list[dict[str, Any]] = []
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        try:
            shapes.append({
                "id": int(shape.Id),
                "font_name": str(shape.TextFrame.TextRange.Font.Name or ""),
                "font_rgb": int(shape.TextFrame.TextRange.Font.Color.RGB),
            })
        except Exception:
            continue
    try:
        background = int(slide.Background.Fill.ForeColor.RGB)
        follows_master = bool(slide.FollowMasterBackground)
    except Exception:
        background, follows_master = 0, True
    return {
        "style_preset": _tag_value(slide, _STYLE_TAG),
        "background": background,
        "follows_master": follows_master,
        "shapes": shapes,
    }


def _apply_style(slide: Any, preset: str) -> None:
    values = _STYLES[preset]
    slide.FollowMasterBackground = False
    slide.Background.Fill.Solid()
    slide.Background.Fill.ForeColor.RGB = _rgb(*values["background"])
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        try:
            if int(shape.HasTextFrame) and int(shape.TextFrame.HasText):
                shape.TextFrame.TextRange.Font.Color.RGB = _rgb(*values["foreground"])
                shape.TextFrame.TextRange.Font.Name = values["font"]
        except Exception:
            continue
    slide.Tags.Add(_STYLE_TAG, preset)


def _restore_format(slide: Any, value: dict[str, Any]) -> None:
    slide.FollowMasterBackground = bool(value.get("follows_master"))
    if not slide.FollowMasterBackground:
        slide.Background.Fill.Solid()
        slide.Background.Fill.ForeColor.RGB = int(value.get("background") or 0)
    by_id = {int(item["id"]): item for item in value.get("shapes", [])}
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = slide.Shapes.Item(index)
        record = by_id.get(int(shape.Id))
        if not record:
            continue
        try:
            shape.TextFrame.TextRange.Font.Name = record["font_name"]
            shape.TextFrame.TextRange.Font.Color.RGB = int(record["font_rgb"])
        except Exception:
            continue
    slide.Tags.Add(_STYLE_TAG, str(value.get("style_preset") or ""))


def _slide_by_id(presentation: Any, slide_id: str) -> Any:
    for index in range(1, int(presentation.Slides.Count) + 1):
        slide = presentation.Slides.Item(index)
        if str(slide.SlideID) == slide_id:
            return slide
    raise RuntimeError("The captured PowerPoint slide no longer exists.")


def _selected_slide_id(application: Any, presentation: Any) -> str:
    try:
        active = application.ActivePresentation
        active_identities = {
            str(getattr(active, "Name", "") or "").casefold(),
            str(getattr(active, "FullName", "") or "").casefold(),
        }
        target_identities = {
            str(getattr(presentation, "Name", "") or "").casefold(),
            str(getattr(presentation, "FullName", "") or "").casefold(),
        }
        if active_identities & target_identities:
            return str(application.ActiveWindow.View.Slide.SlideID)
    except Exception:
        pass
    return ""


def _revision(title: str, slides: list[dict[str, Any]]) -> str:
    payload = json.dumps([title, slides], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rgb(red: int, green: int, blue: int) -> int:
    return int(red) | (int(green) << 8) | (int(blue) << 16)
