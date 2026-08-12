"""Immutable Calc selection snapshot captured before the action preview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.actions.contracts import ActionTarget


@dataclass(frozen=True)
class CalcSnapshot:
    """Structured values and target identity from OpenWand's background reader."""

    document_title: str
    window_id: int
    pid: int
    selection_address: str
    values: tuple[tuple[str, ...], ...]
    typed_values: tuple[tuple[Any, ...], ...]
    formulas: tuple[tuple[str, ...], ...]
    fingerprint: str

    @property
    def row_count(self) -> int:
        return len(self.values)

    @property
    def column_count(self) -> int:
        return len(self.values[0]) if self.values else 0

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="libreoffice_calc",
            display_name=self.document_title or "LibreOffice Calc",
            locator={
                "window_id": str(self.window_id),
                "pid": str(self.pid),
                "range": self.selection_address,
            },
            version=self.fingerprint,
        )

    @classmethod
    def from_selection(cls, selection: dict[str, Any]) -> CalcSnapshot:
        """Build a validated snapshot from the native worker's IPC payload."""
        values = tuple(tuple(str(cell) for cell in row) for row in (selection.get("values") or ()))
        if not values or not values[0] or any(len(row) != len(values[0]) for row in values):
            raise ValueError("Calc must expose a non-empty rectangular selection.")
        raw_typed_values = selection.get("typed_values") or selection.get("values") or ()
        typed_values = tuple(tuple(cell for cell in row) for row in raw_typed_values)
        if len(typed_values) != len(values) or any(
            len(row) != len(values[index]) for index, row in enumerate(typed_values)
        ):
            raise ValueError("Calc typed values must match the displayed selection.")
        raw_formulas = selection.get("formulas") or selection.get("values") or ()
        formulas = tuple(tuple(str(cell) for cell in row) for row in raw_formulas)
        if len(formulas) != len(values) or any(
            len(row) != len(values[index]) for index, row in enumerate(formulas)
        ):
            raise ValueError("Calc formulas must match the displayed selection.")
        address = str(selection.get("range") or "").strip().upper()
        fingerprint = str(selection.get("fingerprint") or "").strip()
        window_id = int(selection.get("window_id") or 0)
        pid = int(selection.get("pid") or 0)
        if not address or not fingerprint or not window_id or not pid:
            raise ValueError("Calc selection identity is incomplete.")
        return cls(
            document_title=str(selection.get("document_title") or "LibreOffice Calc"),
            window_id=window_id,
            pid=pid,
            selection_address=address,
            values=values,
            typed_values=typed_values,
            formulas=formulas,
            fingerprint=fingerprint,
        )
