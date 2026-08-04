from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from core.actions.adapters.calc import CalcSnapshot, calc_advanced_capabilities
from core.actions.adapters.calc.capabilities import calc_capabilities
from core.actions.adapters.excel import excel_advanced_capabilities
from core.actions.adapters.excel.capabilities import excel_capabilities
from core.actions.adapters.spreadsheet_advanced import (
    SpreadsheetAdvancedActionExecutor,
    build_conditional_format_plan,
    build_filter_plan,
    build_formula_plan,
    build_pivot_summary_plan,
    build_remove_duplicates_plan,
    build_sort_rows_plan,
    render_spreadsheet_advanced_preview,
    validate_spreadsheet_advanced_plan,
)
from core.actions.errors import ActionValidationError
from core.actions.providers import detected_picker_context
from ui.addon_presentations import sanitize_presentation_html


def _snapshot() -> CalcSnapshot:
    return CalcSnapshot.from_selection(
        {
            "app": "libreoffice_calc",
            "document_title": "Sales.ods — LibreOffice Calc",
            "window_id": 7,
            "pid": 8,
            "range": "A1:C5",
            "values": (
                ("Region", "Sales", "Tax"),
                ("West", "10", ""),
                ("West", "10", ""),
                ("East", "20", ""),
                ("North", "30", ""),
            ),
            "typed_values": (
                ("Region", "Sales", "Tax"),
                ("West", 10.0, ""),
                ("West", 10.0, ""),
                ("East", 20.0, ""),
                ("North", 30.0, ""),
            ),
            "formulas": (
                ("Region", "Sales", "Tax"),
                ("West", "10", ""),
                ("West", "10", ""),
                ("East", "20", ""),
                ("North", "30", ""),
            ),
            "fingerprint": "fresh",
        }
    )


def test_advanced_capabilities_stay_separate_from_current_executors() -> None:
    calc_advanced = {item.type for item in calc_advanced_capabilities()}
    excel_advanced = {item.type for item in excel_advanced_capabilities()}
    assert calc_advanced >= {"calc.set_formulas@1", "calc.pivot_summary@1"}
    assert excel_advanced >= {
        "excel.remove_duplicates@1",
        "excel.conditional_format@1",
    }
    assert calc_advanced.isdisjoint(item.type for item in calc_capabilities())
    assert excel_advanced.isdisjoint(item.type for item in excel_capabilities())


def test_spreadsheet_plans_are_typed_bounded_and_previewed() -> None:
    snapshot = _snapshot()
    plans = (
        build_formula_plan(snapshot, ({"row_offset": 1, "column_offset": 2, "formula": "=B2*0.05"},)),
        build_filter_plan(snapshot, column_label="Region", operator="equals", value="West"),
        build_sort_rows_plan(snapshot, column_label="Sales"),
        build_remove_duplicates_plan(snapshot, key_columns=("Region", "Sales")),
        build_conditional_format_plan(snapshot, column_label="Sales", preset="data_bar"),
        build_pivot_summary_plan(snapshot, row_field="Region", value_field="Sales", aggregate="sum"),
    )
    for plan in plans:
        assert not validate_spreadsheet_advanced_plan(plan, snapshot)
        preview = render_spreadsheet_advanced_preview(plan, snapshot)
        assert "action-canvas-preview" in preview.html
        assert "Nothing has changed" not in preview.html
        assert sanitize_presentation_html(preview.html) == preview.html
    assert "1 duplicate row" in render_spreadsheet_advanced_preview(plans[3], snapshot).html


def test_formula_plan_rejects_external_data_and_out_of_range_targets() -> None:
    with pytest.raises(ActionValidationError, match="external-data"):
        build_formula_plan(
            _snapshot(), ({"row_offset": 1, "column_offset": 2, "formula": '=WEBSERVICE("https://example.test")'},)
        )
    with pytest.raises(ActionValidationError, match="outside"):
        build_formula_plan(_snapshot(), ({"row_offset": 99, "column_offset": 2, "formula": "=1+1"},))


@dataclass
class _API:
    current: CalcSnapshot
    verify_result: tuple[str, ...] = ("Verified exact result",)
    rolled_back: bool = False
    applied: int = 0

    def snapshot(self):
        return self.current

    def apply(self, _plan):
        self.applied += 1
        return {"message": "Applied", "focus_unchanged": True, "journal": ({"kind": "formula", "rollback": "api"},)}

    def verify(self, _plan, _before, _outcome):
        return self.verify_result

    def rollback(self, _journal):
        self.rolled_back = True
        return True


def test_injected_spreadsheet_executor_revalidates_verifies_and_rolls_back() -> None:
    snapshot = _snapshot()
    plan = build_conditional_format_plan(snapshot, column_label="Sales", preset="data_bar")
    api = _API(snapshot)
    executor = SpreadsheetAdvancedActionExecutor(api)
    result = executor.execute(plan, confirmed=True, idempotency_key="one")
    assert result.verification == ("Verified exact result",)
    assert executor.execute(plan, confirmed=True, idempotency_key="one") is result
    assert api.applied == 1

    failing = _API(snapshot, verify_result=())
    with pytest.raises(RuntimeError, match="verification"):
        SpreadsheetAdvancedActionExecutor(failing).execute(plan, confirmed=True, idempotency_key="two")
    assert failing.rolled_back is True

    stale = replace(snapshot, fingerprint="changed")
    with pytest.raises(ActionValidationError, match="changed after preview"):
        SpreadsheetAdvancedActionExecutor(_API(stale)).execute(plan, confirmed=True, idempotency_key="three")


def test_google_sheets_picker_is_detected_and_marks_missing_bridge() -> None:
    provider = detected_picker_context({
        "active_app": {"name": "Budget - Google Sheets", "process_name": "chrome.exe"},
        "browser_url": "https://docs.google.com/spreadsheets/d/sheet/edit",
    })

    assert provider["display_name"] == "Google Sheets"
    assert [item["label"] for item in provider["suggested_intents"]] == [
        "Clean up this table",
        "Sort these rows",
    ]
    assert all(item["available"] is False for item in provider["suggested_intents"])

    title_only = detected_picker_context({
        "active_app": {
            "name": "Budget - Google Sheets - Google Chrome",
            "process_name": "chrome.exe",
        }
    })
    assert title_only["id"] == "google_sheets"
