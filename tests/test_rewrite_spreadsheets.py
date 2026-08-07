from __future__ import annotations

import pytest

from core.rewrite_spreadsheets import spreadsheet_grid_text, spreadsheet_rewrite_changes


def test_grid_text_preserves_formulas_and_quotes_tabs() -> None:
    rendered = spreadsheet_grid_text(
        (("Name", "Amount"), ("A\tB", 12.5)),
        (("", ""), ("", "=SUM(B1:B1)")),
    )

    assert rendered == 'Name\tAmount\n"A\tB"\t=SUM(B1:B1)'


def test_changes_keep_dimensions_and_preserve_numeric_types() -> None:
    changes = spreadsheet_rewrite_changes(
        (("Name", "Amount"), ("Old", 12.5)),
        (("", ""), ("", "")),
        "Name\tAmount\nNew\t14.25",
        allow_boolean_values=True,
    )

    assert changes == [
        {
            "row_offset": 1,
            "column_offset": 0,
            "after_kind": "value",
            "after_value": "New",
            "replace_formula": False,
        },
        {
            "row_offset": 1,
            "column_offset": 1,
            "after_kind": "value",
            "after_value": 14.25,
            "replace_formula": False,
        },
    ]


def test_changes_require_explicit_formula_replacement() -> None:
    changes = spreadsheet_rewrite_changes(
        ((3,),),
        (("=1+2",),),
        "plain text",
        allow_boolean_values=True,
    )

    assert changes[0]["replace_formula"] is True
    assert changes[0]["after_kind"] == "value"


def test_changes_reject_reshaped_or_markdown_output() -> None:
    with pytest.raises(ValueError, match="same row and column counts|keep the selected range"):
        spreadsheet_rewrite_changes(
            (("A", "B"),),
            (("", ""),),
            "A\nB",
            allow_boolean_values=False,
        )

    with pytest.raises(ValueError, match="plain TSV"):
        spreadsheet_rewrite_changes(
            (("A",),),
            (("",),),
            "```tsv\nB\n```",
            allow_boolean_values=False,
        )
