"""Shared typed foundations for bounded spreadsheet mutations.

The module deliberately depends on an injected application API.  It does not
fall back to keyboard automation and therefore can be reused by Calc, Excel,
and a future Google Sheets provider without pretending those bridges exist.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from html import escape
from typing import Any, Protocol

from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ActionRisk,
    ValidationIssue,
)
from core.actions.errors import ActionValidationError
from core.actions.preview_templates import app_name, canvas_preview, chips

_APP_PREFIXES = {
    "libreoffice_calc": "calc",
    "excel": "excel",
    "google_sheets": "google_sheets",
}
_SAFE_FORMULA_BLOCKLIST = re.compile(
    r"\b(?:WEBSERVICE|FILTERXML|RTD|DDE|HYPERLINK|IMPORTXML|IMPORTRANGE)\s*\(",
    re.IGNORECASE,
)
_SAFE_SHEET_NAME = re.compile(r"^[^\\/:?*\[\]]{1,31}$")


class SpreadsheetSnapshotLike(Protocol):
    row_count: int
    column_count: int
    values: tuple[tuple[Any, ...], ...]
    target: Any


class SpreadsheetApplicationAPI(Protocol):
    """App-owned mutation boundary used by the shared executor."""

    def snapshot(self) -> SpreadsheetSnapshotLike: ...

    def apply(self, plan: ActionPlan) -> dict[str, Any]: ...

    def verify(
        self,
        plan: ActionPlan,
        before: SpreadsheetSnapshotLike,
        outcome: dict[str, Any],
    ) -> Sequence[str]: ...

    def rollback(self, journal: Sequence[dict[str, Any]]) -> bool: ...


def _action_type(app: str, suffix: str) -> str:
    try:
        return f"{_APP_PREFIXES[app]}.{suffix}@1"
    except KeyError as exc:
        raise ValueError(f"Unsupported spreadsheet app: {app!r}.") from exc


def spreadsheet_advanced_capabilities(app: str) -> tuple[ActionCapability, ...]:
    """Return app-specific schemas for the bounded shared operations."""
    prefix = _APP_PREFIXES.get(app)
    if not prefix:
        raise ValueError(f"Unsupported spreadsheet app: {app!r}.")

    def capability(
        suffix: str,
        title: str,
        description: str,
        properties: dict[str, Any],
        required: list[str],
        *,
        risk: ActionRisk = ActionRisk.MEDIUM,
    ) -> ActionCapability:
        return ActionCapability(
            type=f"{prefix}.{suffix}@1",
            app=app,
            title=title,
            description=description,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            risk=risk,
            reversible=True,
        )

    return (
        capability(
            "set_formulas",
            "Set reviewed formulas",
            "Write only explicitly reviewed formulas at offsets inside the captured range.",
            {"assignments": {"type": "array"}},
            ["assignments"],
        ),
        capability(
            "filter_rows",
            "Filter table rows",
            "Apply one reviewed filter to a uniquely named header in the captured table.",
            {
                "column_index": {"type": "number"},
                "column_label": {"type": "string"},
                "operator": {
                    "type": "string",
                    "enum": ["equals", "not_equals", "contains", "greater_than", "less_than"],
                },
                "value": {},
                "has_header": {"type": "boolean"},
            },
            ["column_index", "column_label", "operator", "value", "has_header"],
        ),
        capability(
            "sort_rows",
            "Sort complete rows",
            "Sort complete captured rows by one reviewed header.",
            {
                "column_index": {"type": "number"},
                "column_label": {"type": "string"},
                "direction": {"type": "string", "enum": ["ascending", "descending"]},
                "has_header": {"type": "boolean"},
            },
            ["column_index", "column_label", "direction", "has_header"],
        ),
        capability(
            "remove_duplicates",
            "Remove exact duplicate rows",
            "Remove only rows whose reviewed key columns are exact duplicates.",
            {"key_columns": {"type": "array"}, "has_header": {"type": "boolean"}},
            ["key_columns", "has_header"],
            risk=ActionRisk.HIGH,
        ),
        capability(
            "conditional_format",
            "Apply conditional formatting",
            "Apply one reviewed built-in formatting preset to a selected column.",
            {
                "column_index": {"type": "number"},
                "column_label": {"type": "string"},
                "preset": {"type": "string", "enum": ["negative_red", "data_bar", "color_scale"]},
            },
            ["column_index", "column_label", "preset"],
            risk=ActionRisk.LOW,
        ),
        capability(
            "pivot_summary",
            "Create pivot summary",
            "Create a reviewed summary on a new sheet without changing source rows.",
            {
                "row_field": {"type": "string"},
                "value_field": {"type": "string"},
                "aggregate": {"type": "string", "enum": ["sum", "count", "average"]},
                "output_sheet": {"type": "string"},
            },
            ["row_field", "value_field", "aggregate", "output_sheet"],
            risk=ActionRisk.MEDIUM,
        ),
    )


def _plan(
    snapshot: SpreadsheetSnapshotLike,
    suffix: str,
    summary: str,
    args: dict[str, Any],
    *,
    risk: ActionRisk = ActionRisk.MEDIUM,
) -> ActionPlan:
    app = str(snapshot.target.app)
    plan = ActionPlan(
        plan_id=uuid.uuid4().hex,
        app=app,
        target=snapshot.target,
        summary=" ".join(summary.split())[:180],
        operations=(ActionOperation(id=suffix, type=_action_type(app, suffix), args=args),),
        risk=risk,
        requires_confirmation=True,
    )
    issues = validate_spreadsheet_advanced_plan(plan, snapshot)
    if issues:
        raise ActionValidationError(issues)
    return plan


def build_formula_plan(snapshot: SpreadsheetSnapshotLike, assignments: Sequence[dict[str, Any]]) -> ActionPlan:
    normalized = tuple(
        {
            "row_offset": int(item.get("row_offset", -1)),
            "column_offset": int(item.get("column_offset", -1)),
            "formula": str(item.get("formula") or ""),
        }
        for item in assignments
    )
    return _plan(
        snapshot,
        "set_formulas",
        f"Set {len(normalized)} reviewed formula{'s' if len(normalized) != 1 else ''}",
        {"assignments": normalized},
    )


def build_filter_plan(snapshot: SpreadsheetSnapshotLike, *, column_label: str, operator: str, value: Any) -> ActionPlan:
    index = _header_index(snapshot, column_label)
    return _plan(
        snapshot,
        "filter_rows",
        f"Filter rows where {column_label} {operator.replace('_', ' ')} {value}",
        {"column_index": index, "column_label": column_label, "operator": operator, "value": value, "has_header": True},
    )


def build_sort_rows_plan(
    snapshot: SpreadsheetSnapshotLike, *, column_label: str, direction: str = "ascending"
) -> ActionPlan:
    index = _header_index(snapshot, column_label)
    return _plan(
        snapshot,
        "sort_rows",
        f"Sort complete rows by {column_label} ({direction})",
        {"column_index": index, "column_label": column_label, "direction": direction, "has_header": True},
    )


def build_remove_duplicates_plan(snapshot: SpreadsheetSnapshotLike, *, key_columns: Sequence[str]) -> ActionPlan:
    keys = tuple({"index": _header_index(snapshot, label), "label": str(label)} for label in key_columns)
    return _plan(
        snapshot,
        "remove_duplicates",
        f"Remove exact duplicate rows using {', '.join(key_columns)}",
        {"key_columns": keys, "has_header": True},
        risk=ActionRisk.HIGH,
    )


def build_conditional_format_plan(snapshot: SpreadsheetSnapshotLike, *, column_label: str, preset: str) -> ActionPlan:
    index = _header_index(snapshot, column_label)
    return _plan(
        snapshot,
        "conditional_format",
        f"Apply {preset.replace('_', ' ')} formatting to {column_label}",
        {"column_index": index, "column_label": column_label, "preset": preset},
        risk=ActionRisk.LOW,
    )


def build_pivot_summary_plan(
    snapshot: SpreadsheetSnapshotLike,
    *,
    row_field: str,
    value_field: str,
    aggregate: str,
    output_sheet: str = "Wisp Summary",
) -> ActionPlan:
    _header_index(snapshot, row_field)
    _header_index(snapshot, value_field)
    return _plan(
        snapshot,
        "pivot_summary",
        f"Create a {aggregate} summary of {value_field} by {row_field}",
        {"row_field": row_field, "value_field": value_field, "aggregate": aggregate, "output_sheet": output_sheet},
    )


def validate_spreadsheet_advanced_plan(
    plan: ActionPlan, snapshot: SpreadsheetSnapshotLike
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if plan.app != snapshot.target.app or plan.target.app != snapshot.target.app:
        issues.append(ValidationIssue("wrong_adapter", "The plan is for a different spreadsheet application."))
    if plan.target.locator != snapshot.target.locator:
        issues.append(ValidationIssue("target_changed", "The workbook, sheet, or captured range changed."))
    if plan.target.version != snapshot.target.version:
        issues.append(ValidationIssue("target_stale", "The captured spreadsheet data changed after preview."))
    if len(plan.operations) != 1:
        issues.append(ValidationIssue("unsupported_plan", "Use one reviewed spreadsheet mutation at a time."))
        return tuple(issues)
    operation = plan.operations[0]
    prefix = _APP_PREFIXES.get(plan.app, "")
    if not prefix or not operation.type.startswith(f"{prefix}."):
        issues.append(
            ValidationIssue("unsupported_action", "The spreadsheet action type is not registered.", operation.id)
        )
        return tuple(issues)
    args = operation.args
    if operation.type == _action_type(plan.app, "set_formulas"):
        assignments = args.get("assignments")
        if not isinstance(assignments, (list, tuple)) or not 1 <= len(assignments) <= 50:
            issues.append(
                ValidationIssue("invalid_formulas", "Review between 1 and 50 formula assignments.", operation.id)
            )
        else:
            seen: set[tuple[int, int]] = set()
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    issues.append(
                        ValidationIssue("invalid_formula", "Each formula assignment must be structured.", operation.id)
                    )
                    continue
                row = assignment.get("row_offset")
                column = assignment.get("column_offset")
                formula = str(assignment.get("formula") or "")
                if (
                    not isinstance(row, int)
                    or not isinstance(column, int)
                    or not (0 <= row < snapshot.row_count and 0 <= column < snapshot.column_count)
                ):
                    issues.append(
                        ValidationIssue(
                            "formula_outside_range", "A formula target is outside the captured range.", operation.id
                        )
                    )
                elif (row, column) in seen:
                    issues.append(
                        ValidationIssue(
                            "duplicate_formula_target", "A cell can receive only one reviewed formula.", operation.id
                        )
                    )
                else:
                    seen.add((row, column))
                if not formula.startswith("=") or len(formula) > 512 or _SAFE_FORMULA_BLOCKLIST.search(formula):
                    issues.append(
                        ValidationIssue(
                            "unsafe_formula",
                            "A formula is empty, oversized, or uses an external-data function.",
                            operation.id,
                        )
                    )
    elif operation.type in {
        _action_type(plan.app, "filter_rows"),
        _action_type(plan.app, "sort_rows"),
        _action_type(plan.app, "conditional_format"),
    }:
        _validate_header_args(args, snapshot, issues, operation.id)
        if operation.type == _action_type(plan.app, "filter_rows") and args.get("operator") not in {
            "equals",
            "not_equals",
            "contains",
            "greater_than",
            "less_than",
        }:
            issues.append(ValidationIssue("invalid_filter", "The filter operator is not allow-listed.", operation.id))
        if operation.type == _action_type(plan.app, "sort_rows") and args.get("direction") not in {
            "ascending",
            "descending",
        }:
            issues.append(
                ValidationIssue("invalid_sort", "Sort direction must be ascending or descending.", operation.id)
            )
        if operation.type == _action_type(plan.app, "conditional_format") and args.get("preset") not in {
            "negative_red",
            "data_bar",
            "color_scale",
        }:
            issues.append(
                ValidationIssue("invalid_format", "The conditional-format preset is not allow-listed.", operation.id)
            )
    elif operation.type == _action_type(plan.app, "remove_duplicates"):
        keys = args.get("key_columns")
        if not isinstance(keys, (list, tuple)) or not keys:
            issues.append(
                ValidationIssue(
                    "invalid_duplicate_keys", "Choose at least one exact header for duplicate detection.", operation.id
                )
            )
        else:
            for item in keys:
                if not isinstance(item, dict):
                    issues.append(
                        ValidationIssue("invalid_duplicate_keys", "Duplicate keys must be structured.", operation.id)
                    )
                    continue
                _validate_header_args(
                    {"column_index": item.get("index"), "column_label": item.get("label")},
                    snapshot,
                    issues,
                    operation.id,
                )
    elif operation.type == _action_type(plan.app, "pivot_summary"):
        for field in ("row_field", "value_field"):
            try:
                _header_index(snapshot, str(args.get(field) or ""))
            except ValueError as exc:
                issues.append(ValidationIssue("invalid_pivot_field", str(exc), operation.id))
        if args.get("aggregate") not in {"sum", "count", "average"}:
            issues.append(
                ValidationIssue("invalid_aggregate", "The pivot aggregate is not allow-listed.", operation.id)
            )
        if not _SAFE_SHEET_NAME.fullmatch(str(args.get("output_sheet") or "")):
            issues.append(ValidationIssue("unsafe_sheet_name", "The output sheet name is not safe.", operation.id))
    else:
        issues.append(
            ValidationIssue("unsupported_action", "The spreadsheet action type is not registered.", operation.id)
        )
    return tuple(issues)


def render_spreadsheet_advanced_preview(plan: ActionPlan, snapshot: SpreadsheetSnapshotLike) -> ActionPreview:
    issues = validate_spreadsheet_advanced_plan(plan, snapshot)
    if issues:
        raise ActionValidationError(issues)
    operation = plan.operations[0]
    args = operation.args
    suffix = operation.type.split(".", 1)[1].rsplit("@", 1)[0]
    details = _preview_details(suffix, args, snapshot)
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row[:6]) + "</tr>" for row in snapshot.values[:8]
    )
    html = canvas_preview(
        app=app_name(plan.target.app, fallback="Spreadsheet"),
        target=plan.target.display_name,
        title=plan.summary,
        hero_html=f'<div class="table-wrap"><table><tbody>{rows}</tbody></table></div>',
        chips_html=chips(
            (
                suffix.replace("_", " ").title(),
                f"{snapshot.row_count} rows",
                f"{snapshot.column_count} columns",
            )
        ),
        body_html=details,
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Spreadsheet change",
        summary=plan.summary,
        html=html,
        details=({"operation_id": operation.id, "type": operation.type, "label": plan.summary},),
        warnings=(),
    )


class SpreadsheetAdvancedActionExecutor:
    """Confirmation, freshness, verification, and rollback around an injected API."""

    def __init__(self, api: SpreadsheetApplicationAPI) -> None:
        self.api = api
        self._idempotent_results: dict[str, ActionExecutionResult] = {}

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        if not confirmed:
            raise ActionValidationError(
                (ValidationIssue("confirmation_required", "Review and Apply the spreadsheet preview first."),)
            )
        if not idempotency_key.strip():
            raise ActionValidationError(
                (ValidationIssue("idempotency_required", "The spreadsheet action is missing its execution key."),)
            )
        if idempotency_key in self._idempotent_results:
            return self._idempotent_results[idempotency_key]
        current = self.api.snapshot()
        issues = validate_spreadsheet_advanced_plan(plan, current)
        if issues:
            raise ActionValidationError(issues)
        outcome = self.api.apply(plan)
        journal = tuple(item for item in (outcome.get("journal") or ()) if isinstance(item, dict))
        try:
            verification = tuple(str(item) for item in self.api.verify(plan, current, outcome))
            if not verification or outcome.get("focus_unchanged") is not True:
                raise RuntimeError("The spreadsheet API did not prove verification and unchanged focus.")
        except Exception as exc:
            if not self.api.rollback(journal):
                raise RuntimeError(
                    "Spreadsheet verification failed and rollback could not be verified."
                ) from exc
            raise
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message=str(outcome.get("message") or "Spreadsheet action applied and verified."),
            created=tuple(outcome.get("created") or ()),
            journal=journal,
            verification=verification,
        )
        self._idempotent_results[idempotency_key] = result
        return result


def _header_index(snapshot: SpreadsheetSnapshotLike, label: str) -> int:
    if snapshot.row_count < 2 or not snapshot.values:
        raise ValueError("The captured table needs a header and at least one data row.")
    headers = [str(value).strip() for value in snapshot.values[0]]
    matches = [index for index, value in enumerate(headers) if value == str(label).strip()]
    if len(matches) != 1:
        raise ValueError("The field must match one unique captured header exactly.")
    return matches[0]


def _validate_header_args(
    args: dict[str, Any], snapshot: SpreadsheetSnapshotLike, issues: list[ValidationIssue], operation_id: str
) -> None:
    index = args.get("column_index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < snapshot.column_count:
        issues.append(
            ValidationIssue("invalid_column", "The reviewed column is outside the captured range.", operation_id)
        )
        return
    if str(args.get("column_label") or "") != str(snapshot.values[0][index]):
        issues.append(
            ValidationIssue(
                "header_changed", "The reviewed header no longer matches the captured column.", operation_id
            )
        )


def _preview_details(suffix: str, args: dict[str, Any], snapshot: SpreadsheetSnapshotLike) -> str:
    if suffix == "set_formulas":
        items = "".join(
            f"<li>Row {item['row_offset'] + 1}, column {item['column_offset'] + 1}: <code>{escape(item['formula'])}</code></li>"
            for item in args["assignments"]
        )
        return f"<h2>Exact formula writes</h2><ul>{items}</ul>"
    if suffix == "remove_duplicates":
        keys = [int(item["index"]) for item in args["key_columns"]]
        seen: set[tuple[Any, ...]] = set()
        removed = 0
        for row in snapshot.values[1:]:
            key = tuple(row[index] for index in keys)
            if key in seen:
                removed += 1
            seen.add(key)
        return f"<h2>Exact duplicate scan</h2><p>{removed} duplicate row{'s' if removed != 1 else ''} would be removed using {escape(', '.join(item['label'] for item in args['key_columns']))}.</p>"
    if suffix == "pivot_summary":
        return f"<h2>New summary sheet</h2><p>{escape(args['aggregate'].title())} of <strong>{escape(args['value_field'])}</strong> grouped by <strong>{escape(args['row_field'])}</strong>, written to <strong>{escape(args['output_sheet'])}</strong>.</p>"
    return f"<h2>Exact rule</h2><p><strong>{escape(str(args.get('column_label') or ''))}</strong>: {escape(str(args.get('operator') or args.get('direction') or args.get('preset') or ''))} {escape(str(args.get('value') or ''))}</p>"
