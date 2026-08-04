"""Tests for Calc app recognition and the native structured-selection boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.actions.adapters.calc import (
    CalcActionAdapter,
    CalcSnapshot,
    build_chart_plan,
    build_format_table_plan,
    build_sort_range_plan,
    is_calc_app,
)
from core.actions.errors import ActionValidationError
from core.actions.providers import detected_picker_context
from runtime.workers import native_host
from ui.addon_presentations import sanitize_presentation_html


class _FakeOfficeProcess:
    info = {"name": "soffice.bin"}

    @staticmethod
    def cmdline() -> list[str]:
        return [r"C:\Program Files\LibreOffice\program\soffice.exe"]


def _prepare_calc_prewarm_test(monkeypatch, tmp_path, *, processes, probe_returncode=0) -> None:
    executable = tmp_path / "soffice.exe"
    python = tmp_path / "python.exe"
    executable.touch()
    python.touch()
    monkeypatch.setattr(native_host, "IS_WIN", True)
    monkeypatch.setenv("LIBREOFFICE_EXECUTABLE", str(executable))
    monkeypatch.setenv("LIBREOFFICE_PYTHON", str(python))
    monkeypatch.setenv("WISP_LIBREOFFICE_USER_PROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr("psutil.process_iter", lambda _attrs: list(processes))
    monkeypatch.setattr(
        native_host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=probe_returncode),
    )


def test_calc_prewarm_adopts_normally_started_office_from_persistent_config(
    monkeypatch,
    tmp_path,
) -> None:
    from core.actions.adapters.calc.bridge import configure_calc_connection

    _prepare_calc_prewarm_test(monkeypatch, tmp_path, processes=[_FakeOfficeProcess()])
    configure_calc_connection("wisp_calc_0123456789abcdef", tmp_path / "profile")

    status = native_host.calc_automation_prewarm()

    assert status["available"] is True
    assert status["reason"] == "ready"
    assert status["pipe_name"] == "wisp_calc_0123456789abcdef"
    assert status["transport"] == "uno_named_pipe_persisted"
    assert native_host.action_calc_status()["available"] is True


def test_calc_prewarm_reports_only_one_time_restart_when_current_process_missed_config(
    monkeypatch,
    tmp_path,
) -> None:
    _prepare_calc_prewarm_test(
        monkeypatch,
        tmp_path,
        processes=[_FakeOfficeProcess()],
        probe_returncode=1,
    )

    status = native_host.calc_automation_prewarm()

    assert status["available"] is False
    assert status["reason"] == "bridge_pending_restart"
    assert str(status["pipe_name"]).startswith("wisp_calc_")


def test_calc_prewarm_does_not_launch_libreoffice_before_user(monkeypatch, tmp_path) -> None:
    _prepare_calc_prewarm_test(monkeypatch, tmp_path, processes=[])

    status = native_host.calc_automation_prewarm()

    assert status["available"] is True
    assert status["reason"] == "ready_on_launch"


def test_calc_status_waits_for_normally_started_pipe_to_become_ready(monkeypatch, tmp_path) -> None:
    from core.actions.adapters.calc.bridge import configure_calc_connection

    _prepare_calc_prewarm_test(monkeypatch, tmp_path, processes=[_FakeOfficeProcess()])
    configure_calc_connection("wisp_calc_0123456789abcdef", tmp_path / "profile")
    return_codes = iter((1, 0))
    monkeypatch.setattr(
        native_host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=next(return_codes)),
    )
    monkeypatch.setattr(native_host.time, "sleep", lambda _seconds: None)

    status = native_host.calc_automation_prewarm(wait_for_startup=True)

    assert status["available"] is True
    assert status["reason"] == "ready"
    assert status["transport"] == "uno_named_pipe_persisted"


def test_calc_app_recognizes_supported_process_and_localized_title() -> None:
    assert is_calc_app(
        {
            "name": "Budget.ods — LibreOffice Calc",
            "process_name": "soffice.bin",
        }
    )
    assert is_calc_app(
        {
            "name": "Budget.ods - LibreOffice 試算表",
            "process_name": "soffice.bin",
        }
    )
    assert not is_calc_app({"name": "Budget.ods", "process_name": "notepad.exe"})


def test_native_app_selection_uses_calc_reader(monkeypatch) -> None:
    class FakeReader:
        def inspect_selection(self, active_app):
            assert active_app["window_id"] == 777
            return {
                "app": "libreoffice_calc",
                "range": "A1:B2",
                "selected_text": "A\tB\n1\t2",
            }

    monkeypatch.setattr(native_host, "_calc_selection_reader", FakeReader())
    result = native_host.context_app_selection(
        {
            "name": "Budget.ods — LibreOffice Calc",
            "process_name": "soffice.bin",
            "window_id": 777,
        }
    )

    assert result["supported"] is True
    assert result["selection"]["range"] == "A1:B2"
    assert result["error"] == ""


def test_native_app_selection_ignores_unsupported_apps() -> None:
    result = native_host.context_app_selection(
        {"name": "Notes", "process_name": "notepad.exe", "window_id": 777}
    )

    assert result == {"supported": False, "selection": {}}


def _selection(*, fingerprint: str = "fingerprint") -> dict:
    return {
        "app": "libreoffice_calc",
        "document_title": "Budget.ods — LibreOffice Calc",
        "window_id": 777,
        "pid": 42,
        "range": "A1:B3",
        "values": (("Month", "Revenue"), ("Jan", "12"), ("Feb", "20")),
        "typed_values": (("Month", "Revenue"), ("Jan", 12.0), ("Feb", 20.0)),
        "formulas": (("Month", "Revenue"), ("Jan", "12"), ("Feb", "20")),
        "fingerprint": fingerprint,
    }


def test_calc_chart_plan_and_preview_share_the_exact_target() -> None:
    snapshot = CalcSnapshot.from_selection(_selection())
    plan = build_chart_plan(snapshot)
    preview = CalcActionAdapter(chart_executor=lambda _plan: {}).render_preview(plan, snapshot)

    assert plan.target.locator == {"window_id": "777", "pid": "42", "range": "A1:B3"}
    assert plan.operations[0].args["range"] == "A1:B3"
    assert "A1:B3" in preview.html
    assert "action-bar" in preview.html
    assert ">Jan</text>" in preview.html
    assert ">Revenue</span>" in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_calc_chart_preview_uses_typed_numbers_when_display_values_are_currency() -> None:
    selection = _selection()
    selection["values"] = (("Month", "Sales ($)"), ("January", "$12,400"), ("February", "$14,100"))
    selection["typed_values"] = (("Month", "Sales ($)"), ("January", 12400.0), ("February", 14100.0))

    snapshot = CalcSnapshot.from_selection(selection)
    preview = CalcActionAdapter(chart_executor=lambda _plan: {}).render_preview(build_chart_plan(snapshot), snapshot)

    assert preview.html.count('<rect class="action-bar action-series-1"') == 2
    assert "could not find a numeric series" not in preview.html
    assert ">January</text>" in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_calc_provider_offers_useful_actions_and_analysis() -> None:
    context = {
        "active_app": {
            "name": "Budget.ods — LibreOffice Calc",
            "process_name": "soffice.bin",
        },
    }

    provider = detected_picker_context(context)

    assert [item["label"] for item in provider["suggested_intents"]] == [
        "Create a bar chart",
        "Clean up this table",
        "Sort this table",
        "Analyze this data",
    ]
    assert provider["suggested_intents"][-1]["mode"] == "answer"


def test_calc_format_table_plan_previews_content_preservation() -> None:
    snapshot = CalcSnapshot.from_selection(_selection())
    plan = build_format_table_plan(snapshot, has_header=True)

    preview = CalcActionAdapter(action_executor=lambda _plan: {}).render_preview(plan, snapshot)

    assert plan.operations[0].type == "calc.format_table@1"
    assert plan.operations[0].args == {
        "range": "A1:B3",
        "has_header": True,
        "preset": "clean_table",
    }
    assert "Keep every cell value, formula, and number format unchanged" in preview.html
    assert "action-canvas-preview" in preview.html
    assert "Nothing has changed" not in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_calc_sort_plan_previews_complete_rows_in_new_order() -> None:
    selection = _selection()
    selection["values"] = (("Month", "Revenue"), ("Feb", "20"), ("Jan", "12"))
    selection["typed_values"] = (("Month", "Revenue"), ("Feb", 20.0), ("Jan", 12.0))
    snapshot = CalcSnapshot.from_selection(selection)
    plan = build_sort_range_plan(snapshot, column_label="Revenue", direction="ascending")

    preview = CalcActionAdapter(action_executor=lambda _plan: {}).render_preview(plan, snapshot)

    assert plan.operations[0].args["column_index"] == 1
    assert preview.html.index("Proposed order") < preview.html.rindex("Jan") < preview.html.rindex("Feb")
    assert "Complete rows" not in preview.html
    assert "action-canvas-preview" in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_calc_sort_plan_rejects_unknown_or_duplicate_headers() -> None:
    snapshot = CalcSnapshot.from_selection(_selection())
    with pytest.raises(ValueError, match="unique selected header"):
        build_sort_range_plan(snapshot, column_label="Missing")

    selection = _selection()
    selection["values"] = (("Value", "Value"), ("A", "1"), ("B", "2"))
    selection["typed_values"] = (("Value", "Value"), ("A", 1.0), ("B", 2.0))
    with pytest.raises(ValueError, match="unique selected header"):
        build_sort_range_plan(CalcSnapshot.from_selection(selection), column_label="Value")


def test_calc_sort_preview_rejects_formula_rows_until_formula_sorting_is_verified() -> None:
    selection = _selection()
    selection["formulas"] = (("Month", "Revenue"), ("Jan", "=6*2"), ("Feb", "=10*2"))
    snapshot = CalcSnapshot.from_selection(selection)
    plan = build_sort_range_plan(snapshot, column_label="Revenue")

    with pytest.raises(ActionValidationError, match="containing formulas"):
        CalcActionAdapter(action_executor=lambda _plan: {}).render_preview(plan, snapshot)


def test_calc_non_chart_actions_execute_idempotently_after_revalidation() -> None:
    selection = _selection()

    class Reader:
        def inspect_selection(self, _active_app):
            return selection

    executions = []
    adapter = CalcActionAdapter(
        reader=Reader(),
        action_executor=lambda plan: executions.append(plan.operations[0].type) or {
            "message": "Applied",
            "verification": ["Verified"],
        },
    )
    plan = build_format_table_plan(CalcSnapshot.from_selection(selection))

    first = adapter.execute(plan, confirmed=True, idempotency_key="format-key")
    second = adapter.execute(plan, confirmed=True, idempotency_key="format-key")

    assert first == second
    assert first.created == ()
    assert first.journal[0]["kind"] == "formatting"
    assert executions == ["calc.format_table@1"]


def test_calc_chart_requires_confirmation_and_revalidates_before_execution() -> None:
    selection = _selection()

    class Reader:
        def inspect_selection(self, active_app):
            assert active_app["window_id"] == 777
            assert active_app["pid"] == 42
            return selection

    executions = []
    adapter = CalcActionAdapter(
        reader=Reader(),
        chart_executor=lambda plan: executions.append(plan.plan_id) or {"name": "Chart 1"},
    )
    plan = build_chart_plan(CalcSnapshot.from_selection(selection))

    with pytest.raises(ActionValidationError):
        adapter.execute(plan, confirmed=False, idempotency_key="key")

    first = adapter.execute(plan, confirmed=True, idempotency_key="key")
    second = adapter.execute(plan, confirmed=True, idempotency_key="key")
    assert first == second
    assert first.created == ({"kind": "chart", "name": "Chart 1"},)
    assert executions == [plan.plan_id]

    selection["fingerprint"] = "changed"
    stale_plan = build_chart_plan(CalcSnapshot.from_selection(_selection()))
    with pytest.raises(ActionValidationError):
        adapter.execute(stale_plan, confirmed=True, idempotency_key="other")


def test_calc_executor_refuses_obsolete_socket_environment(monkeypatch) -> None:
    plan = build_chart_plan(CalcSnapshot.from_selection(_selection()))
    monkeypatch.delenv("WISP_CALC_UNO_PIPE", raising=False)
    monkeypatch.setenv("WISP_CALC_UNO_PORT", "64028")

    with pytest.raises(RuntimeError, match="refused to use the obsolete socket"):
        CalcActionAdapter._default_chart_executor(plan)


def test_native_calc_snapshot_uses_uno_values_and_fingerprint(monkeypatch) -> None:
    class TargetReader:
        @staticmethod
        def inspect_target(active_app):
            assert active_app["window_id"] == 777
            return {
                "app": "libreoffice_calc",
                "document_title": active_app["name"],
                "window_id": 777,
                "pid": 42,
                "range": "A1:B3",
            }

    payload = {
        "ok": True,
        "values": [["Month", "Revenue"], ["Jan", "12"], ["Feb", "20"]],
        "typed_values": [["Month", "Revenue"], ["Jan", 12.0], ["Feb", 20.0]],
        "formulas": [["Month", "Revenue"], ["Jan", "=6*2"], ["Feb", "=10*2"]],
        "fingerprint": "uno-typed-fingerprint",
    }
    monkeypatch.setattr(native_host, "_calc_selection_reader", TargetReader())
    monkeypatch.setattr(
        native_host,
        "calc_automation_prewarm",
        lambda **_kwargs: {
            "available": True,
            "transport": "uno_named_pipe_persisted",
            "pipe_name": "wisp_calc_0123456789abcdef",
        },
    )
    monkeypatch.setattr(
        native_host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    result = native_host.action_calc_snapshot(
        {
            "name": "Budget.ods — LibreOffice Calc",
            "process_name": "soffice.bin",
            "pid": 42,
            "window_id": 777,
        }
    )

    assert result["ok"] is True
    assert result["selection"]["fingerprint"] == "uno-typed-fingerprint"
    assert result["selection"]["values"][1] == ["Jan", "12"]
    assert result["selection"]["typed_values"][1] == ["Jan", 12.0]
    assert result["selection"]["formulas"][1] == ["Jan", "=6*2"]
    assert result["selection"]["capture_method"] == "windows_uia_name_box+uno_named_pipe"


def test_calc_executor_never_rewrites_source_cells_after_chart_creation() -> None:
    helper = Path(__file__).resolve().parents[1] / "runtime" / "helpers" / "calc_uno_action.py"

    assert "source.setDataArray" not in helper.read_text(encoding="utf-8")


def test_calc_mutations_have_verified_undo_rollback_paths() -> None:
    helper = Path(__file__).resolve().parents[1] / "runtime" / "helpers" / "calc_uno_action.py"
    source = helper.read_text(encoding="utf-8")

    assert 'enterUndoContext("Wisp: clean up table")' in source
    assert 'enterUndoContext("Wisp: sort selected rows")' in source
    assert "_rollback_latest(manager, source, before)" in source
