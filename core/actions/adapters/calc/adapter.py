"""Preview-first Calc actions through the captured desktop window."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.actions.adapters.calc.capabilities import ADD_CHART, CLEAN_RANGE, FORMAT_TABLE, SORT_RANGE, calc_capabilities
from core.actions.adapters.calc.plans import _reviewed_cleanup_changes
from core.actions.adapters.calc.preview import render_calc_preview
from core.actions.adapters.calc.reader import CalcSelectionReader
from core.actions.adapters.calc.snapshot import CalcSnapshot
from core.actions.contracts import (
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ActionRisk,
    ActionTarget,
    ValidationIssue,
)
from core.actions.errors import ActionValidationError

CalcExecutor = Callable[[ActionPlan], dict[str, Any]]

_CHART_NAMES = {
    "chart", "insert chart", "graph", "diagramm", "graphique", "gráfico", "grafico",
    "\u5716\u8868", "\u56fe\u8868",
}
_FINISH_NAMES = {
    "finish", "create", "done", "terminer", "finalizar", "fertigstellen", "\u5b8c\u6210",
}
_UNDO_NAMES = {"undo", "annuler", "rückgängig", "deshacer", "\u5fa9\u539f", "\u64a4\u9500"}


class CalcActionAdapter:
    """Validate and execute one bounded action against a recorded Calc range."""

    def __init__(
        self,
        *,
        reader: CalcSelectionReader | None = None,
        chart_executor: CalcExecutor | None = None,
        action_executor: CalcExecutor | None = None,
    ) -> None:
        self.reader = reader or CalcSelectionReader()
        self.action_executor = action_executor or chart_executor or self._default_action_executor
        # Compatibility for existing callers and tests that injected the first
        # chart-only executor by this name.
        self.chart_executor = self.action_executor
        self._idempotent_results: dict[str, ActionExecutionResult] = {}

    def capabilities(self):
        return calc_capabilities()

    def validate(self, plan: ActionPlan, snapshot: CalcSnapshot) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if plan.app != "libreoffice_calc":
            issues.append(ValidationIssue("wrong_adapter", "This action is not for LibreOffice Calc."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(ValidationIssue("target_changed", "The Calc window or selected range has changed."))
        if plan.target.version != snapshot.fingerprint:
            issues.append(ValidationIssue("target_stale", "The selected Calc data changed after the preview."))
        if snapshot.row_count > 2_000 or snapshot.column_count > 50:
            issues.append(ValidationIssue("selection_too_large", "Select at most 2,000 rows and 50 columns."))
        if len(plan.operations) != 1:
            issues.append(ValidationIssue("unsupported_plan", "Calc actions must contain exactly one reviewed operation."))
            return tuple(issues)
        operation = plan.operations[0]
        if operation.type == ADD_CHART:
            if operation.args.get("kind") != "column":
                issues.append(ValidationIssue("unsupported_chart", "Only vertical bar charts are currently available."))
        elif operation.type == FORMAT_TABLE:
            if operation.args.get("preset") != "clean_table" or not isinstance(operation.args.get("has_header"), bool):
                issues.append(ValidationIssue("invalid_format", "The table formatting plan is not valid."))
        elif operation.type == SORT_RANGE:
            column_index = operation.args.get("column_index")
            direction = operation.args.get("direction")
            if snapshot.row_count < 2 or not operation.args.get("has_header"):
                issues.append(ValidationIssue("invalid_sort", "Sorting requires a header and at least one data row."))
            if not isinstance(column_index, int) or not 0 <= column_index < snapshot.column_count:
                issues.append(ValidationIssue("invalid_sort_column", "The sort column is outside the selected range."))
            elif str(operation.args.get("column_label") or "") != snapshot.values[0][column_index]:
                issues.append(ValidationIssue("sort_header_changed", "The selected sort header no longer matches."))
            if direction not in {"ascending", "descending"}:
                issues.append(ValidationIssue("invalid_sort_direction", "The sort direction is invalid."))
            if any(str(formula).startswith("=") for row in snapshot.formulas[1:] for formula in row):
                issues.append(ValidationIssue(
                    "sort_formulas_unsupported",
                    "Sorting selected rows containing formulas is not yet supported safely.",
                ))
        elif operation.type == CLEAN_RANGE:
            if str(operation.args.get("range") or "") != snapshot.selection_address:
                issues.append(ValidationIssue("cleanup_range_changed", "The reviewed cleanup range no longer matches."))
            changes = operation.args.get("changes")
            if not isinstance(changes, (list, tuple)):
                issues.append(ValidationIssue("invalid_cleanup", "Cleanup changes must be a structured list."))
            else:
                try:
                    expected = _reviewed_cleanup_changes(snapshot, changes)
                except ValueError as exc:
                    issues.append(ValidationIssue("invalid_cleanup", str(exc), operation.id))
                else:
                    if tuple(changes) != expected:
                        issues.append(ValidationIssue(
                            "cleanup_snapshot_mismatch",
                            "A cleanup cell no longer matches the exact reviewed before-content.",
                            operation.id,
                        ))
        else:
            issues.append(ValidationIssue("unsupported_plan", "This Calc operation is not registered."))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_calc_preview(plan, snapshot)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        if plan.requires_confirmation and not confirmed:
            raise ActionValidationError(
                (ValidationIssue("confirmation_required", "Review and Apply the Calc preview first."),)
            )
        if not idempotency_key.strip():
            raise ActionValidationError(
                (ValidationIssue("idempotency_required", "The Calc action is missing its execution key."),)
            )
        cached = self._idempotent_results.get(idempotency_key)
        if cached is not None:
            return cached

        locator = plan.target.locator
        selection = self.reader.inspect_selection(
            {
                "name": plan.target.display_name,
                "process_name": "soffice.bin",
                "window_id": int(locator.get("window_id") or 0),
                "pid": int(locator.get("pid") or 0),
            }
        )
        current = CalcSnapshot.from_selection(selection)
        issues = self.validate(plan, current)
        if issues:
            raise ActionValidationError(issues)

        outcome = self.action_executor(plan)
        created = tuple(
            {str(key): str(value) for key, value in item.items()}
            for item in (outcome.get("created") or ())
            if isinstance(item, dict)
        )
        if not created and plan.operations[0].type == ADD_CHART:
            created = ({"kind": "chart", "name": str(outcome.get("name") or "Chart")},)
        journal_kind = {
            ADD_CHART: "chart",
            FORMAT_TABLE: "formatting",
            SORT_RANGE: "row_sort",
            CLEAN_RANGE: "cell_cleanup",
        }.get(plan.operations[0].type, "calc_action")
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message=str(outcome.get("message") or "Calc action applied and verified."),
            created=created,
            journal=tuple(outcome.get("journal") or ({
                "kind": journal_kind,
                "window_id": locator["window_id"],
                "rollback": "calc_undo",
            },)),
            verification=tuple(outcome.get("verification") or ("Calc verified the reviewed operation.",)),
        )
        self._idempotent_results[idempotency_key] = result
        return result

    @staticmethod
    def _default_chart_executor(plan: ActionPlan) -> dict[str, Any]:
        """Compatibility alias for the original chart-only executor."""
        return CalcActionAdapter._default_action_executor(plan)

    @staticmethod
    def _default_action_executor(plan: ActionPlan) -> dict[str, Any]:
        """Use a focusless API session; never silently fall back to UI automation."""
        pipe_name = str(os.environ.get("WISP_CALC_UNO_PIPE") or "").strip()
        if pipe_name:
            return CalcActionAdapter._execute_uno_action(plan, pipe_name=pipe_name)
        raise RuntimeError(
            "Wisp's local Calc action pipe is not loaded in this runtime. "
            "Restart Wisp once; Wisp refused to use the obsolete socket or the chart wizard."
        )

    @staticmethod
    def _execute_uno_chart(
        plan: ActionPlan,
        *,
        pipe_name: str,
    ) -> dict[str, Any]:
        """Compatibility alias for the original chart-only helper."""
        return CalcActionAdapter._execute_uno_action(plan, pipe_name=pipe_name)

    @staticmethod
    def _execute_uno_action(
        plan: ActionPlan,
        *,
        pipe_name: str,
    ) -> dict[str, Any]:
        """Run the built-in LibreOffice API helper without opening any UI."""
        if sys.platform != "win32":
            raise RuntimeError("The first managed Calc automation transport is available on Windows only.")
        libreoffice_python = Path(
            os.environ.get("LIBREOFFICE_PYTHON")
            or r"C:\Program Files\LibreOffice\program\python.exe"
        )
        helper = Path(__file__).resolve().parents[4] / "runtime" / "helpers" / "calc_uno_action.py"
        if not libreoffice_python.is_file() or not helper.is_file():
            raise RuntimeError("LibreOffice's automation runtime is unavailable.")
        if not str(pipe_name or "").strip():
            raise RuntimeError("Wisp's local Calc action pipe is missing.")
        operation = plan.operations[0]
        command = [
                str(libreoffice_python),
                str(helper),
                "--pipe",
                pipe_name,
                "--title",
                plan.target.display_name,
                "--range",
                str(plan.target.locator.get("range") or ""),
                "--fingerprint",
                plan.target.version,
                "--action",
                {
                    ADD_CHART: "chart",
                    FORMAT_TABLE: "format_table",
                    SORT_RANGE: "sort_range",
                    CLEAN_RANGE: "clean_range",
                }.get(operation.type, ""),
            ]
        if operation.type == ADD_CHART:
            command.extend(["--chart-title", str(operation.args.get("title") or "Chart from selected data")])
        elif operation.type == FORMAT_TABLE:
            command.extend(["--has-header", "true" if operation.args.get("has_header") else "false"])
        elif operation.type == SORT_RANGE:
            command.extend([
                "--sort-column", str(operation.args.get("column_index")),
                "--sort-direction", str(operation.args.get("direction") or "ascending"),
                "--has-header", "true",
            ])
        elif operation.type == CLEAN_RANGE:
            command.extend([
                "--changes-json",
                json.dumps(operation.args.get("changes") or (), ensure_ascii=False, separators=(",", ":")),
            ])
        else:
            raise RuntimeError("The requested Calc operation is not implemented.")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12.0,
            check=False,
        )
        output = next((line for line in reversed(completed.stdout.splitlines()) if line.strip()), "")
        try:
            result = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Calc automation returned invalid output: {completed.stderr.strip()}") from exc
        if completed.returncode != 0 or not result.get("ok"):
            raise RuntimeError(str(result.get("error") or completed.stderr.strip() or "Calc automation failed."))
        return result

    @staticmethod
    def _execute_background_chart(plan: ActionPlan) -> dict[str, Any]:
        """Invoke Calc's semantic Chart command without activating its window."""
        if sys.platform != "win32":
            raise RuntimeError("Calc background actions are currently implemented on Windows only.")
        import comtypes.gen.UIAutomationClient as uiac  # type: ignore[import-not-found]

        from core.capture import _get_uia

        hwnd = int(plan.target.locator.get("window_id") or 0)
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            raise RuntimeError("The Calc window from the preview is no longer open.")
        uia = _get_uia()
        if uia is None:
            raise RuntimeError("Windows UI Automation is unavailable.")
        root = uia.ElementFromHandle(hwnd)
        if root is None:
            raise RuntimeError("Windows cannot inspect the recorded Calc window.")
        chart_button = _named_button(uia, root, uiac, _CHART_NAMES)
        if chart_button is None:
            raise RuntimeError("Calc's accessible Chart command was not found.")
        _invoke(chart_button, uiac)

        deadline = time.monotonic() + 3.0
        finished = False
        while time.monotonic() < deadline:
            finish = _find_process_button(uia, uiac, int(plan.target.locator.get("pid") or 0), _FINISH_NAMES)
            if finish is not None:
                _invoke(finish, uiac)
                finished = True
                break
            if _chart_evidence(uia, root, uiac):
                finished = True
                break
            time.sleep(0.05)
        if not finished:
            _try_undo(uia, root, uiac)
            raise RuntimeError("Calc opened the chart tool but Wisp could not finish it safely.")

        verify_deadline = time.monotonic() + 2.0
        while time.monotonic() < verify_deadline:
            if _chart_evidence(uia, root, uiac):
                return {
                    "name": "Chart",
                    "message": f"Created a vertical bar chart from {plan.target.locator.get('range') or 'the selection'}.",
                    "verification": ("Chart appeared in the same recorded Calc window.",),
                }
            time.sleep(0.05)
        _try_undo(uia, root, uiac)
        raise RuntimeError("Calc did not expose the new chart, so Wisp rolled the action back.")


def action_plan_from_dict(value: dict[str, Any]) -> ActionPlan:
    """Deserialize the trusted plan contract received over local IPC."""
    target_value = value.get("target") if isinstance(value.get("target"), dict) else {}
    operations = tuple(
        ActionOperation(
            id=str(item.get("id") or ""),
            type=str(item.get("type") or ""),
            args=dict(item.get("args") or {}),
            depends_on=tuple(item.get("depends_on") or ()),
        )
        for item in (value.get("operations") or ())
        if isinstance(item, dict)
    )
    return ActionPlan(
        plan_id=str(value.get("plan_id") or ""),
        app=str(value.get("app") or ""),
        target=ActionTarget(
            app=str(target_value.get("app") or ""),
            display_name=str(target_value.get("display_name") or ""),
            locator={str(key): str(item) for key, item in dict(target_value.get("locator") or {}).items()},
            version=str(target_value.get("version") or ""),
        ),
        summary=str(value.get("summary") or ""),
        operations=operations,
        risk=ActionRisk(str(value.get("risk") or ActionRisk.MEDIUM.value)),
        requires_confirmation=bool(value.get("requires_confirmation", True)),
    )


def _named_button(uia: Any, root: Any, uiac: Any, names: set[str]) -> Any | None:
    buttons = root.FindAll(uiac.TreeScope_Descendants, uia.CreatePropertyCondition(30003, 50000))
    for index in range(int(getattr(buttons, "Length", 0) or 0)):
        button = buttons.GetElement(index)
        try:
            if str(button.CurrentName or "").strip().casefold() in names:
                return button
        except Exception:
            continue
    return None


def _find_process_button(uia: Any, uiac: Any, pid: int, names: set[str]) -> Any | None:
    desktop = uia.GetRootElement()
    windows = desktop.FindAll(uiac.TreeScope_Children, uia.CreateTrueCondition())
    for index in range(int(getattr(windows, "Length", 0) or 0)):
        window = windows.GetElement(index)
        try:
            if pid and int(window.CurrentProcessId or 0) != pid:
                continue
        except Exception:
            continue
        button = _named_button(uia, window, uiac, names)
        if button is not None:
            return button
    return None


def _invoke(element: Any, uiac: Any) -> None:
    raw = element.GetCurrentPattern(10000)
    raw.QueryInterface(uiac.IUIAutomationInvokePattern).Invoke()


def _chart_evidence(uia: Any, root: Any, uiac: Any) -> bool:
    elements = root.FindAll(uiac.TreeScope_Descendants, uia.CreateTrueCondition())
    for index in range(min(int(getattr(elements, "Length", 0) or 0), 2500)):
        element = elements.GetElement(index)
        try:
            name = str(element.CurrentName or "").strip().casefold()
            if name and any(
                token in name
                for token in ("chart", "diagram", "graphique", "gráfico", "\u5716\u8868", "\u56fe\u8868")
            ):
                if int(element.CurrentControlType or 0) != 50000:  # ignore the toolbar button itself
                    return True
        except Exception:
            continue
    return False


def _try_undo(uia: Any, root: Any, uiac: Any) -> None:
    try:
        undo = _named_button(uia, root, uiac, _UNDO_NAMES)
        if undo is not None:
            _invoke(undo, uiac)
    except Exception:
        pass
