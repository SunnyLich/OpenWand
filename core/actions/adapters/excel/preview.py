"""HTML/CSS preview generated from the exact validated Excel action plan."""

from __future__ import annotations

from html import escape
from typing import Any

from core.actions.adapters.excel.capabilities import ADD_CHART, CREATE_TABLE
from core.actions.adapters.excel.snapshot import PREVIEW_COLUMNS, PREVIEW_ROWS, ExcelSnapshot
from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import canvas_preview, chips, focus_field, focus_preview


def render_excel_preview(plan: ActionPlan, snapshot: ExcelSnapshot) -> ActionPreview:
    """Render a compact preview without changing Excel."""
    detail_rows: list[dict[str, Any]] = []
    for operation in plan.operations:
        if operation.type == CREATE_TABLE:
            label = f"Create table {operation.args['name']} from {operation.args['range']}"
        elif operation.type == ADD_CHART:
            label = f"Add {operation.args['kind']} chart {operation.args['name']}"
        else:
            label = operation.type
        detail_rows.append({"operation_id": operation.id, "type": operation.type, "label": label})

    table_rows = []
    for row in snapshot.preview_values:
        cells = "".join(f"<td>{escape(_display_cell(value))}</td>" for value in row)
        table_rows.append(f"<tr>{cells}</tr>")
    truncation = ""
    if snapshot.row_count > PREVIEW_ROWS or snapshot.column_count > PREVIEW_COLUMNS:
        truncation = (
            f'<p class="muted">Showing a preview of {snapshot.row_count} rows × '
            f"{snapshot.column_count} columns.</p>"
        )

    table_html = f'<div class="table-wrap"><table><tbody>{"".join(table_rows)}</tbody></table></div>{truncation}'
    chart_operation = next((operation for operation in plan.operations if operation.type == ADD_CHART), None)
    if chart_operation is not None:
        html = focus_preview(
            app="Microsoft Excel",
            target=f"{plan.target.display_name} · {snapshot.selection_address}",
            title=plan.summary,
            change_html=_chart_preview(snapshot, str(chart_operation.args["title"])),
            details_html=(
                '<div class="action-focus-grid">'
                + focus_field("Table", str(plan.operations[0].args["name"]), accent=True)
                + focus_field("Range", snapshot.selection_address)
                + focus_field("Chart", f"{str(chart_operation.args['kind']).title()} chart", accent=True)
                + focus_field("Title", str(chart_operation.args["title"]))
                + "</div>"
                + table_html
            ),
            badge="XL",
        )
    else:
        change_items = "".join(
            '<div class="action-change-item"><span class="action-change-mark">✓</span>'
            f'<div class="action-change-copy"><div class="action-change-title">{escape(item["label"])}</div></div></div>'
            for item in detail_rows
        )
        html = canvas_preview(
            app="Microsoft Excel",
            target=f"{plan.target.display_name} · {snapshot.selection_address}",
            title=plan.summary,
            hero_html=table_html,
            chips_html=chips((f"{snapshot.row_count} rows", f"{snapshot.column_count} columns")),
            body_html=f'<div class="action-change-list">{change_items}</div>',
            badge="XL",
        )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Excel changes",
        summary=plan.summary,
        html=html,
        details=tuple(detail_rows),
        warnings=("Creating the table cannot yet be completely undone by Wisp.",),
    )


def _display_cell(value: Any) -> str:
    """Keep the HTML preview readable and bounded."""
    text = "" if value is None else str(value)
    return text if len(text) <= 80 else f"{text[:77]}…"


def _chart_preview(snapshot: ExcelSnapshot, title: str) -> str:
    values: list[float] = []
    labels: list[str] = []
    for row in snapshot.preview_values[1:7]:
        if len(row) < 2 or not isinstance(row[1], (int, float)):
            continue
        labels.append(str(row[0]))
        values.append(float(row[1]))
    if not values:
        return f'<div class="action-slide-card"><div class="action-slide-title">{escape(title)}</div><div class="action-slide-copy">Column chart</div></div>'
    maximum = max(max(values), 1.0)
    bars: list[str] = []
    slot = 460.0 / len(values)
    for index, value in enumerate(values):
        height = max(3.0, 130.0 * value / maximum)
        x = 60.0 + slot * index + slot * 0.18
        width = slot * 0.64
        y = 170.0 - height
        bars.append(
            f'<rect class="action-bar action-series-1" x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="3"></rect>'
        )
        bars.append(
            f'<text class="action-axis-label" x="{x + width / 2:.1f}" y="191" text-anchor="middle">{escape(labels[index][:10])}</text>'
        )
    return (
        f'<h2>{escape(title)}</h2><svg class="reply-graphic action-chart" viewBox="0 0 580 205" role="img" aria-label="{escape(title)}">'
        '<line class="action-axis" x1="50" y1="170" x2="540" y2="170"></line>'
        + "".join(bars)
        + "</svg>"
    )
