"""Exact LibreOffice Writer and Impress Rewrite contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def libreoffice_rewrite_surface(active_app: dict[str, Any] | None) -> str:
    """Return ``writer`` or ``impress`` for a captured LibreOffice window."""
    app = active_app if isinstance(active_app, dict) else {}
    process = str(app.get("process_name") or "").strip().casefold()
    title = str(app.get("name") or app.get("title") or "").casefold()
    if process not in _LIBREOFFICE_PROCESSES:
        return ""
    if "libreoffice writer" in title or process in {"swriter", "swriter.exe"}:
        return "writer"
    if "libreoffice impress" in title or process in {"simpress", "simpress.exe"}:
        return "impress"
    return ""


@dataclass(frozen=True)
class LibreOfficeRewriteSnapshot:
    """A serializable UNO text-container selection."""

    surface: str
    document_title: str
    container_kind: str
    container_name: str
    page_index: int
    shape_path: tuple[int, ...]
    start: int
    length: int
    selected_text: str
    container_text: str
    fingerprint: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LibreOfficeRewriteSnapshot:
        surface = str(value.get("surface") or "")
        if surface not in {"writer", "impress"}:
            raise ValueError("LibreOffice returned an unsupported Rewrite surface.")
        selected_text = str(value.get("selected_text") or "")
        container_text = str(value.get("container_text") or "")
        start = int(value.get("start") or 0)
        length = int(value.get("length") or 0)
        if not selected_text or length < 1 or start < 0:
            raise ValueError("LibreOffice returned an invalid selected text range.")
        if container_text[start : start + length] != selected_text:
            raise ValueError("LibreOffice selected text does not match its exact container range.")
        return cls(
            surface=surface,
            document_title=str(value.get("document_title") or ""),
            container_kind=str(value.get("container_kind") or ""),
            container_name=str(value.get("container_name") or ""),
            page_index=int(value.get("page_index") or 0),
            shape_path=tuple(int(item) for item in (value.get("shape_path") or ())),
            start=start,
            length=length,
            selected_text=selected_text,
            container_text=container_text,
            fingerprint=str(value.get("fingerprint") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "document_title": self.document_title,
            "container_kind": self.container_kind,
            "container_name": self.container_name,
            "page_index": self.page_index,
            "shape_path": list(self.shape_path),
            "start": self.start,
            "length": self.length,
            "selected_text": self.selected_text,
            "container_text": self.container_text,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class LibreOfficeRewritePlan:
    snapshot: LibreOfficeRewriteSnapshot
    replacement_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "replacement_text": self.replacement_text,
        }


def build_libreoffice_rewrite_plan(
    snapshot: LibreOfficeRewriteSnapshot,
    replacement_text: str,
) -> LibreOfficeRewritePlan:
    replacement = str(replacement_text or "")
    if not replacement:
        raise ValueError("LibreOffice Rewrite returned an empty replacement.")
    return LibreOfficeRewritePlan(snapshot=snapshot, replacement_text=replacement)


_LIBREOFFICE_PROCESSES = {
    "soffice",
    "soffice.exe",
    "soffice.bin",
    "swriter",
    "swriter.exe",
    "simpress",
    "simpress.exe",
}


__all__ = [
    "LibreOfficeRewritePlan",
    "LibreOfficeRewriteSnapshot",
    "build_libreoffice_rewrite_plan",
    "libreoffice_rewrite_surface",
]
