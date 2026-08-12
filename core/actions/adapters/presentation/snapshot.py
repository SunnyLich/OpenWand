"""Bounded presentation snapshots with revision and semantic identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from core.actions.contracts import ActionTarget
from core.actions.errors import ActionUnavailableError

MAX_SLIDES = 200
MAX_TOTAL_TEXT_CHARS = 240_000
MAX_TITLE_CHARS = 500
MAX_BODY_CHARS = 12_000
MAX_NOTES_CHARS = 12_000
PLANNER_SLIDES = 30
PLANNER_TEXT_CHARS = 1_200
SUPPORTED_BACKENDS = {"powerpoint_desktop", "powerpoint_officejs", "google_slides"}


@dataclass(frozen=True)
class SlideSnapshot:
    """API-owned state for one bounded slide."""

    slide_id: str
    index: int
    title: str
    body: str
    speaker_notes: str
    style_preset: str

    @classmethod
    def from_api_payload(cls, value: Mapping[str, Any], index: int) -> SlideSnapshot:
        slide_id = str(value.get("slide_id") or value.get("id") or "").strip()
        if not slide_id or len(slide_id) > 200:
            raise ActionUnavailableError("The presentation API returned an invalid slide identity.")
        return cls(
            slide_id=slide_id,
            index=index,
            title=_bounded_text(value.get("title"), MAX_TITLE_CHARS, "slide title"),
            body=_bounded_text(value.get("body"), MAX_BODY_CHARS, "slide body"),
            speaker_notes=_bounded_text(
                value.get("speaker_notes", value.get("notes")), MAX_NOTES_CHARS, "speaker notes"
            ),
            style_preset=_bounded_text(value.get("style_preset"), 100, "style preset"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PresentationSnapshot:
    """Complete bounded state used for planning, freshness, and verification."""

    backend: str
    presentation_id: str
    title: str
    revision: str
    selected_slide_id: str
    slides: tuple[SlideSnapshot, ...]
    semantic_fingerprint: str
    fingerprint: str

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="presentation",
            display_name=self.title,
            locator={
                "backend": self.backend,
                "presentation_id": self.presentation_id,
                "selected_slide_id": self.selected_slide_id,
            },
            version=self.fingerprint,
        )

    def slide(self, slide_id: str) -> SlideSnapshot | None:
        return next((slide for slide in self.slides if slide.slide_id == slide_id), None)

    def model_context(self) -> dict[str, Any]:
        """Return a smaller planner view while retaining the full bounded fingerprint."""
        return {
            "presentation": {
                "backend": self.backend,
                "title": self.title,
                "presentation_id": self.presentation_id,
                "revision": self.revision,
                "selected_slide_id": self.selected_slide_id,
                "slide_count": len(self.slides),
            },
            "slides": [
                {
                    "slide_id": slide.slide_id,
                    "index": slide.index,
                    "title": slide.title[:PLANNER_TEXT_CHARS],
                    "body": slide.body[:PLANNER_TEXT_CHARS],
                    "speaker_notes": slide.speaker_notes[:PLANNER_TEXT_CHARS],
                    "style_preset": slide.style_preset,
                }
                for slide in self.slides[:PLANNER_SLIDES]
            ],
            "truncated": len(self.slides) > PLANNER_SLIDES,
        }


def capture_presentation_snapshot(
    client: Any,
    *,
    backend: str,
    presentation_id: str,
    selected_slide_id: str = "",
) -> PresentationSnapshot:
    """Read a presentation through an injected COM, Office.js, or Google client."""
    if backend not in SUPPORTED_BACKENDS:
        raise ActionUnavailableError(f"Unsupported presentation API backend: {backend!r}.")
    identity = str(presentation_id or "").strip()
    if not identity or len(identity) > 1_000:
        raise ActionUnavailableError("A bounded presentation identity is required.")
    payload = client.get_presentation(identity)
    if not isinstance(payload, Mapping):
        raise ActionUnavailableError("The presentation API returned an unreadable snapshot.")
    revision = str(payload.get("revision") or payload.get("etag") or "").strip()
    if not revision or len(revision) > 1_000:
        raise ActionUnavailableError("The presentation API did not provide a revision identity.")
    title = _bounded_text(payload.get("title"), 500, "presentation title") or "Untitled presentation"
    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, list):
        raise ActionUnavailableError("The presentation API did not return a slide list.")
    if len(raw_slides) > MAX_SLIDES:
        raise ActionUnavailableError(
            f"This presentation has {len(raw_slides)} slides; OpenWand's first bounded action supports {MAX_SLIDES}."
        )
    slides = tuple(
        SlideSnapshot.from_api_payload(value, index)
        for index, value in enumerate(raw_slides)
        if isinstance(value, Mapping)
    )
    if len(slides) != len(raw_slides):
        raise ActionUnavailableError("The presentation API returned an invalid slide record.")
    total_chars = sum(
        len(slide.title) + len(slide.body) + len(slide.speaker_notes) for slide in slides
    )
    if total_chars > MAX_TOTAL_TEXT_CHARS:
        raise ActionUnavailableError("The presentation text exceeds OpenWand's bounded snapshot limit.")
    selected = str(selected_slide_id or payload.get("selected_slide_id") or "").strip()
    if selected and not any(slide.slide_id == selected for slide in slides):
        raise ActionUnavailableError("The selected slide is no longer present in the presentation.")
    semantic = _hash_payload(
        backend,
        identity,
        title,
        selected,
        [slide.to_dict() for slide in slides],
    )
    fingerprint = _hash_payload(semantic, revision)
    return PresentationSnapshot(
        backend=backend,
        presentation_id=identity,
        title=title,
        revision=revision,
        selected_slide_id=selected,
        slides=slides,
        semantic_fingerprint=semantic,
        fingerprint=fingerprint,
    )


def _bounded_text(value: Any, limit: int, label: str) -> str:
    text = str(value or "")
    if len(text) > limit:
        raise ActionUnavailableError(f"The {label} exceeds OpenWand's {limit:,}-character limit.")
    return text


def _hash_payload(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
