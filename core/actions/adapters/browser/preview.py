"""Sanitized HTML preview for browser form filling."""

from __future__ import annotations

from html import escape

from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import canvas_preview, chips


def render_browser_form_preview(plan: ActionPlan) -> ActionPreview:
    rows = []
    details = []
    for operation in plan.operations:
        label = str(operation.args.get("label") or operation.args.get("field_id") or "Field")
        old = str(operation.args.get("expected_value") or "")
        new = str(operation.args.get("value") or "")
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{escape(label)}</th>"
            f"<td>{escape(old) if old else '<span class=\"muted\">Empty</span>'}</td>"
            f"<td class=\"action-new-value\">{escape(new) if new else '<span class=\"muted\">Empty</span>'}</td>"
            "</tr>"
        )
        details.append({"operation_id": operation.id, "type": operation.type, "label": f"Fill {label}"})
    hero = f"""
<div class="table-wrap">
  <table>
    <thead><tr><th>Field</th><th>Current</th><th class="action-new-value">New value</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>""".strip()
    fragment = canvas_preview(
        app="Google Chrome",
        target=plan.target.display_name,
        title=plan.summary,
        hero_html=hero,
        chips_html=chips((f"{len(plan.operations)} fields", "Will not submit")),
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Fill web form",
        summary=plan.summary,
        html=fragment,
        details=tuple(details),
        warnings=(),
    )
