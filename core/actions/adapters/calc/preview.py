"""Safe HTML preview generated from the exact Calc action plan."""

from __future__ import annotations

import math
import re
from html import escape
from typing import Any

from core.actions.adapters.calc.snapshot import CalcSnapshot
from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import canvas_preview, chips, focus_field, focus_preview


def render_calc_preview(plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
    """Render one supported Calc operation without changing Calc."""
    operation_type = plan.operations[0].type if plan.operations else ""
    if operation_type == "calc.add_chart@1":
        return _render_chart_preview(plan, snapshot)
    if operation_type == "calc.format_table@1":
        return _render_format_table_preview(plan, snapshot)
    if operation_type == "calc.sort_range@1":
        return _render_sort_range_preview(plan, snapshot)
    if operation_type == "calc.clean_range@1":
        return _render_cleanup_preview(plan, snapshot)
    raise ValueError("This Calc operation has no preview renderer.")


def _render_chart_preview(plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
    """Render the planned chart without changing Calc."""
    chart = plan.operations[0]
    chart_svg = _chart_svg(snapshot.values, snapshot.typed_values)
    visible = snapshot.values[:7]
    headers = visible[0] if visible else ()
    table_head = "<thead><tr>" + "".join(
        f'<th scope="col">{escape(_display(cell))}</th>' for cell in headers[:4]
    ) + "</tr></thead>"
    table_body = "<tbody>" + "".join(
        "<tr>" + "".join(f"<td>{escape(_display(cell))}</td>" for cell in row[:4]) + "</tr>"
        for row in visible[1:]
    ) + "</tbody>"
    fragment = focus_preview(
        app="LibreOffice Calc",
        target=f"{plan.target.display_name} · {snapshot.selection_address}",
        title=plan.summary,
        change_html=chart_svg,
        details_html=(
            '<div class="action-focus-grid">'
            + focus_field("Chart", "Vertical bar chart", accent=True)
            + focus_field("Source", snapshot.selection_address)
            + focus_field("Range", f"{snapshot.row_count} rows × {snapshot.column_count} columns")
            + focus_field("Cells", "Unchanged")
            + "</div>"
            + f'<div class="table-wrap"><table>{table_head}{table_body}</table></div>'
        ),
        badge="LC",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Create chart in Calc",
        summary=plan.summary,
        html=fragment,
        details=(
            {
                "operation_id": chart.id,
                "type": chart.type,
                "label": f"Vertical bar chart from {snapshot.selection_address}",
            },
        ),
        warnings=(),
    )


def _render_format_table_preview(plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
    operation = plan.operations[0]
    has_header = bool(operation.args.get("has_header"))
    changes = [
        "Fit selected columns to their contents",
        "Keep every cell value, formula, and number format unchanged",
    ]
    if has_header:
        changes.insert(0, "Make the first selected row a clear, bold header")
    change_items = "".join(
        '<div class="action-change-item"><span class="action-change-mark">✓</span>'
        f'<div class="action-change-copy"><div class="action-change-title">{escape(change)}</div></div></div>'
        for change in changes
    )
    fragment = canvas_preview(
        app="LibreOffice Calc",
        target=f"{plan.target.display_name} · {snapshot.selection_address}",
        title=plan.summary,
        hero_html=(
            '<div class="table-wrap">'
            + _preview_table(snapshot.values, table_class="action-formatted-table")
            + "</div>"
        ),
        chips_html=chips(("Cell contents unchanged", f"{snapshot.row_count} rows", f"{snapshot.column_count} columns")),
        body_html=f'<div class="action-change-list">{change_items}</div>',
        badge="LC",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Clean up table in Calc",
        summary=plan.summary,
        html=fragment,
        details=(
            {
                "operation_id": operation.id,
                "type": operation.type,
                "label": f"Format {snapshot.selection_address} without changing contents",
            },
        ),
        warnings=(),
    )


def _render_sort_range_preview(plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
    operation = plan.operations[0]
    column_index = int(operation.args.get("column_index") or 0)
    direction = str(operation.args.get("direction") or "ascending")
    sorted_values = _sorted_display_values(snapshot, column_index=column_index, direction=direction)
    label = str(operation.args.get("column_label") or snapshot.values[0][column_index])
    fragment = canvas_preview(
        app="LibreOffice Calc",
        target=f"{plan.target.display_name} · {snapshot.selection_address}",
        title=plan.summary,
        hero_html=(
            '<div class="two-column">'
            f'<div><h2>Current order</h2>{_preview_table(snapshot.values)}</div>'
            f'<div><h2>Proposed order</h2>{_preview_table(sorted_values)}</div>'
            "</div>"
        ),
        chips_html=chips((f"Sort by {label}", direction.title(), "Complete rows")),
        badge="LC",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Sort rows in Calc",
        summary=plan.summary,
        html=fragment,
        details=(
            {
                "operation_id": operation.id,
                "type": operation.type,
                "label": f"Sort by {label} ({direction})",
            },
        ),
        warnings=(),
    )


def _render_cleanup_preview(plan: ActionPlan, snapshot: CalcSnapshot) -> ActionPreview:
    operation = plan.operations[0]
    changes = operation.args["changes"]
    rows = "".join(
        "<tr>"
        f"<td>row {item['row_offset'] + 1}, column {item['column_offset'] + 1}</td>"
        f"<td>{escape(_display(item['before_value']))}</td>"
        f"<td>{escape(_display(item['after_value']))}</td>"
        f"<td>{escape(str(item['after_kind']).title())}</td>"
        "</tr>"
        for item in changes
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Cell in selection</th><th>Before</th>'
        f"<th>After</th><th>Content</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )
    fragment = canvas_preview(
        app="LibreOffice Calc",
        target=f"{plan.target.display_name} - {snapshot.selection_address}",
        title=plan.summary,
        hero_html=table,
        chips_html=chips((f"{len(changes)} exact cells", "Reviewed values", "Native Undo")),
        body_html=(
            '<div class="action-change-list"><div class="action-change-item">'
            '<span class="action-change-mark">&#10003;</span><div class="action-change-copy">'
            '<div class="action-change-title">Every other selected value and formula stays unchanged.'
            "</div></div></div></div>"
        ),
        badge="LC",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Reviewed Calc cleanup",
        summary=plan.summary,
        html=fragment,
        details=(
            {
                "operation_id": operation.id,
                "type": operation.type,
                "label": f"Replace {len(changes)} exact cells in {snapshot.selection_address}",
            },
        ),
        warnings=("The reviewed replacements remain on Calc's native Undo stack after Apply.",),
    )


def _preview_table(
    values: tuple[tuple[str, ...], ...],
    *,
    table_class: str = "",
) -> str:
    visible = values[:7]
    if not visible:
        return "<table><tbody></tbody></table>"
    head = "<thead><tr>" + "".join(
        f'<th scope="col">{escape(_display(cell))}</th>' for cell in visible[0][:4]
    ) + "</tr></thead>"
    body = "<tbody>" + "".join(
        "<tr>" + "".join(f"<td>{escape(_display(cell))}</td>" for cell in row[:4]) + "</tr>"
        for row in visible[1:]
    ) + "</tbody>"
    class_attr = f' class="{table_class}"' if table_class else ""
    return f"<table{class_attr}>{head}{body}</table>"


def _sorted_display_values(
    snapshot: CalcSnapshot,
    *,
    column_index: int,
    direction: str,
) -> tuple[tuple[str, ...], ...]:
    if not 0 <= column_index < snapshot.column_count:
        raise ValueError("The sort column is outside the selected range.")

    rows = list(zip(snapshot.values[1:], snapshot.typed_values[1:], strict=True))

    def key(item: tuple[tuple[str, ...], tuple[Any, ...]]) -> tuple[int, Any]:
        displayed_row, typed_row = item
        number = _numeric_value(typed_row[column_index], displayed_row[column_index])
        if number is not None:
            return 0, number
        return 1, str(displayed_row[column_index]).casefold()

    rows.sort(key=key, reverse=direction == "descending")
    return (snapshot.values[0], *(displayed for displayed, _typed in rows))


def _chart_svg(
    display_values: tuple[tuple[str, ...], ...],
    typed_values: tuple[tuple[Any, ...], ...],
) -> str:
    categories, series = _chart_data(display_values, typed_values)
    if not categories or not series:
        return (
            '<div class="action-chart-empty">Wisp could not find a numeric series in this selection. '
            "The final chart may be empty.</div>"
        )

    plot_left, plot_top, plot_right, plot_bottom = 58.0, 28.0, 542.0, 194.0
    all_numbers = [number for _name, points in series for number in points if number is not None]
    minimum = min(0.0, min(all_numbers))
    maximum = max(0.0, max(all_numbers))
    if math.isclose(minimum, maximum):
        maximum = minimum + 1.0
    span = maximum - minimum

    def y_for(value: float) -> float:
        return plot_bottom - ((value - minimum) / span) * (plot_bottom - plot_top)

    baseline = y_for(0.0)
    category_slot = (plot_right - plot_left) / len(categories)
    group_width = min(category_slot * 0.72, 64.0)
    bar_width = max(3.0, min(30.0, group_width / len(series)))
    parts: list[str] = []
    for fraction in (0.0, 0.5, 1.0):
        y = plot_bottom - fraction * (plot_bottom - plot_top)
        parts.append(
            f'<line class="action-grid" x1="{plot_left:.1f}" y1="{y:.1f}" '
            f'x2="{plot_right:.1f}" y2="{y:.1f}"></line>'
        )
    parts.append(
        f'<line class="action-axis" x1="{plot_left:.1f}" y1="{baseline:.1f}" '
        f'x2="{plot_right:.1f}" y2="{baseline:.1f}"></line>'
    )

    for category_index, label in enumerate(categories):
        center = plot_left + category_slot * (category_index + 0.5)
        start = center - (bar_width * len(series)) / 2
        for series_index, (_series_name, points) in enumerate(series):
            value = points[category_index]
            if value is None:
                continue
            value_y = y_for(value)
            y = min(value_y, baseline)
            height = max(2.0, abs(baseline - value_y))
            x = start + series_index * bar_width
            parts.append(
                f'<rect class="action-bar action-series-{series_index + 1}" x="{x:.1f}" y="{y:.1f}" '
                f'width="{max(2.0, bar_width - 2):.1f}" height="{height:.1f}" rx="2"></rect>'
            )
        parts.append(
            f'<text class="action-axis-label" x="{center:.1f}" y="217" text-anchor="middle">'
            f"{escape(_short_label(label))}</text>"
        )

    legend = "".join(
        f'<span class="action-legend-item"><span class="action-legend-swatch action-series-{index + 1}"></span>'
        f"{escape(_short_label(name, limit=24))}</span>"
        for index, (name, _points) in enumerate(series)
    )
    return (
        '<svg class="reply-graphic action-chart" viewBox="0 0 560 232" role="img" '
        'aria-label="Vertical bar chart preview">'
        + "".join(parts)
        + "</svg>"
        + f'<div class="action-chart-legend">{legend}</div>'
    )


def _chart_data(
    display_values: tuple[tuple[str, ...], ...],
    typed_values: tuple[tuple[Any, ...], ...],
) -> tuple[list[str], list[tuple[str, list[float | None]]]]:
    if len(display_values) < 2 or len(display_values[0]) < 2:
        return [], []
    row_count = min(len(display_values), len(typed_values), 9)
    column_count = min(len(display_values[0]), len(typed_values[0]), 5)
    categories = [display_values[index][0] or f"Row {index}" for index in range(1, row_count)]
    series: list[tuple[str, list[float | None]]] = []
    for column in range(1, column_count):
        points = [
            _numeric_value(typed_values[row][column], display_values[row][column])
            for row in range(1, row_count)
        ]
        if any(point is not None for point in points):
            series.append((display_values[0][column] or f"Series {column}", points))
    return categories, series


def _numeric_value(typed: Any, displayed: str) -> float | None:
    if isinstance(typed, (int, float)) and not isinstance(typed, bool):
        number = float(typed)
        return number if math.isfinite(number) else None
    source = displayed if typed is None or typed == "" else typed
    text = str(source).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    percent = "%" in text
    cleaned = re.sub(r"[^0-9eE+.,-]", "", text).replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if negative:
        number = -abs(number)
    if percent:
        number /= 100.0
    return number if math.isfinite(number) else None


def _short_label(value: str, *, limit: int = 12) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _display(value: str) -> str:
    return value if len(value) <= 60 else f"{value[:57]}…"
