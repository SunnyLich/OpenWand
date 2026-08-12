"""Injected contracts for PowerPoint object models, Office.js, and Google Slides."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class PresentationMutationReceipt:
    """Opaque API receipt needed for readback verification and rollback."""

    change_id: str
    revision: str
    slide_id: str
    rollback_token: str

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | PresentationMutationReceipt) -> PresentationMutationReceipt:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise RuntimeError("The presentation API returned an invalid mutation receipt.")
        receipt = cls(
            change_id=str(value.get("change_id") or "").strip(),
            revision=str(value.get("revision") or value.get("etag") or "").strip(),
            slide_id=str(value.get("slide_id") or "").strip(),
            rollback_token=str(value.get("rollback_token") or "").strip(),
        )
        if not receipt.change_id or not receipt.revision or not receipt.rollback_token:
            raise RuntimeError("The presentation API receipt lacks change, revision, or rollback identity.")
        return receipt


class PresentationMutationError(RuntimeError):
    """An API mutation failed after possibly creating a rollback token."""

    def __init__(self, message: str, *, rollback_token: str = "") -> None:
        super().__init__(message)
        self.rollback_token = str(rollback_token or "")


@runtime_checkable
class PresentationApiClient(Protocol):
    """Explicit API surface; implementations may wrap COM, Office.js, or Slides REST."""

    def get_presentation(self, presentation_id: str) -> Mapping[str, Any]: ...

    def create_slide(
        self,
        presentation_id: str,
        *,
        title: str,
        body: str,
        layout: str,
        position: str,
        after_slide_id: str,
        expected_revision: str,
        idempotency_key: str,
    ) -> Mapping[str, Any] | PresentationMutationReceipt: ...

    def restyle_slide(
        self,
        presentation_id: str,
        *,
        slide_id: str,
        preset: str,
        preserve_content: bool,
        expected_revision: str,
        idempotency_key: str,
    ) -> Mapping[str, Any] | PresentationMutationReceipt: ...

    def upsert_speaker_notes(
        self,
        presentation_id: str,
        *,
        slide_id: str,
        notes: str,
        expected_revision: str,
        idempotency_key: str,
    ) -> Mapping[str, Any] | PresentationMutationReceipt: ...

    def rollback(self, presentation_id: str, *, rollback_token: str) -> bool: ...


@runtime_checkable
class OfficeJsPowerPointBridge(PresentationApiClient, Protocol):
    """OpenWand-owned Office.js add-in bridge for PowerPoint desktop/web hosts."""


@runtime_checkable
class GoogleSlidesRestClient(PresentationApiClient, Protocol):
    """Authenticated client backed by Google Slides presentations/batchUpdate REST APIs."""
