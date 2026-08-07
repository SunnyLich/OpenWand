"""Safe tabular serialization for annotation-based spreadsheet rewrites."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from typing import Any

_INTEGER = re.compile(r"^[+-]?\d+$")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_MAX_GRID_CHARS = 20_000


def spreadsheet_grid_text(
    values: Sequence[Sequence[Any]],
    formulas: Sequence[Sequence[str]],
) -> str:
    """Render a rectangular range as TSV, retaining formulas instead of results."""
    rows = _source_grid(values, formulas)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerows(rows)
    rendered = stream.getvalue().rstrip("\n")
    if len(rendered) > _MAX_GRID_CHARS:
        raise ValueError("The selected range is too large for Rewrite; select a smaller range.")
    return rendered


def spreadsheet_rewrite_changes(
    values: Sequence[Sequence[Any]],
    formulas: Sequence[Sequence[str]],
    replacement: str,
    *,
    allow_boolean_values: bool,
) -> list[dict[str, Any]]:
    """Convert a same-sized TSV proposal into typed, exact cell replacements."""
    source = _source_grid(values, formulas)
    proposed = _parse_grid(replacement)
    expected_rows = len(source)
    expected_columns = len(source[0]) if source else 0
    if len(proposed) != expected_rows or any(len(row) != expected_columns for row in proposed):
        raise ValueError(
            f"The proposal must keep the selected range at {expected_rows} row(s) by "
            f"{expected_columns} column(s)."
        )

    changes: list[dict[str, Any]] = []
    for row_index, row in enumerate(proposed):
        for column_index, after_text in enumerate(row):
            before_text = source[row_index][column_index]
            if after_text == before_text:
                continue
            before_formula = str(formulas[row_index][column_index] or "")
            after_kind = "formula" if after_text.startswith("=") else "value"
            original_value = values[row_index][column_index]
            after_value = (
                after_text
                if after_kind == "formula"
                else _typed_value(after_text, original_value, allow_boolean_values=allow_boolean_values)
            )
            before_kind = "formula" if before_formula.startswith("=") else "value"
            before_value = before_formula if before_kind == "formula" else original_value
            if before_kind == after_kind and before_value == after_value:
                # Models may normalize 12.0 to 12 in TSV. Do not turn an
                # equivalent scalar rendering into a fake cell mutation.
                continue
            changes.append(
                {
                    "row_offset": row_index,
                    "column_offset": column_index,
                    "after_kind": after_kind,
                    "after_value": after_value,
                    "replace_formula": bool(before_formula.startswith("=") and after_kind == "value"),
                }
            )
    if not changes:
        raise ValueError("The proposal did not change any selected cells.")
    return changes


def _source_grid(
    values: Sequence[Sequence[Any]],
    formulas: Sequence[Sequence[str]],
) -> list[list[str]]:
    rows = [list(row) for row in values]
    formula_rows = [list(row) for row in formulas]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("Rewrite requires a non-empty rectangular cell selection.")
    if len(formula_rows) != len(rows) or any(
        len(formula_rows[index]) != len(row) for index, row in enumerate(rows)
    ):
        raise ValueError("Rewrite could not verify formula identity for the selected range.")
    return [
        [
            str(formula_rows[row_index][column_index])
            if str(formula_rows[row_index][column_index] or "").startswith("=")
            else _display_value(value)
            for column_index, value in enumerate(row)
        ]
        for row_index, row in enumerate(rows)
    ]


def _parse_grid(value: str) -> list[list[str]]:
    text = str(value or "").strip("\r\n")
    if not text or text.lstrip().startswith("```"):
        raise ValueError("The spreadsheet proposal must be plain TSV without a Markdown fence.")
    rows = [list(row) for row in csv.reader(io.StringIO(text), delimiter="\t")]
    if not rows or not rows[0]:
        raise ValueError("The spreadsheet proposal is empty.")
    return rows


def _display_value(value: Any) -> str:
    return "" if value is None else str(value)


def _typed_value(value: str, original: Any, *, allow_boolean_values: bool) -> Any:
    if value == "":
        return None
    if allow_boolean_values and isinstance(original, bool):
        lowered = value.casefold()
        if lowered in {"true", "false"}:
            return lowered == "true"
    if isinstance(original, int) and not isinstance(original, bool) and _INTEGER.fullmatch(value):
        return int(value)
    if isinstance(original, float) and _NUMBER.fullmatch(value):
        return float(value)
    return value


__all__ = ["spreadsheet_grid_text", "spreadsheet_rewrite_changes"]
