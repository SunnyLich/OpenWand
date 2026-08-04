"""Escaped HTML/CSS preview generated from the exact presentation plan."""

from __future__ import annotations

from html import escape
from typing import Any

from core.actions.adapters.presentation.capabilities import (
    CREATE_SLIDE,
    RESTYLE_SLIDE,
)
from core.actions.adapters.presentation.snapshot import PresentationSnapshot
from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import focus_field, focus_preview


def render_presentation_preview(plan: ActionPlan, snapshot: PresentationSnapshot) -> ActionPreview:
    """Render only allow-listed markup with every plan value HTML-escaped."""
    operation = plan.operations[0]
    details: list[dict[str, Any]] = [{
        "operation_id": operation.id,
        "type": operation.type,
        "backend": snapshot.backend,
    }]
    if operation.type == CREATE_SLIDE:
        title = str(operation.args["title"])
        body = str(operation.args["body"])
        position = str(operation.args["position"]).replace("_", " ")
        change = f"""
<div class="action-slide-card">
  <div class="action-slide-title">{escape(title or 'Untitled slide')}</div>
  <div class="action-slide-rule"></div>
  <div class="action-slide-copy">{_lines(body)}</div>
</div>""".strip()
        content = (
            '<div class="action-focus-grid">'
            + focus_field("Layout", str(operation.args["layout"]).replace("_", " ").title(), accent=True)
            + focus_field("Position", position.title())
            + "</div>"
        )
        details[0].update({"title": title, "body": body, "position": position})
        preview_title = "Create presentation slide"
    elif operation.type == RESTYLE_SLIDE:
        slide = snapshot.slide(str(operation.args["slide_id"]))
        before = slide.style_preset if slide is not None else ""
        after = str(operation.args["preset"])
        change = (
            '<div class="action-focus-grid">'
            + focus_field("Current style", before or "Presentation default")
            + focus_field("New style", after.replace("_", " ").title(), accent=True)
            + focus_field("Text", "Unchanged")
            + focus_field("Speaker notes", "Unchanged")
            + "</div>"
        )
        content = ""
        details[0].update({"slide_id": operation.args["slide_id"], "before": before, "after": after})
        preview_title = "Restyle selected slide"
    else:
        slide = snapshot.slide(str(operation.args["slide_id"]))
        previous = slide.speaker_notes if slide is not None else ""
        notes = str(operation.args["notes"])
        change = (
            '<div class="action-focus-grid">'
            + focus_field("Current notes", previous or "(none)")
            + focus_field("New notes", notes or "(empty)", accent=True)
            + "</div>"
        )
        content = ""
        details[0].update({"slide_id": operation.args["slide_id"], "previous": previous, "notes": notes})
        preview_title = "Update speaker notes"

    html = focus_preview(
        app=_presentation_app_name(snapshot),
        target=plan.target.display_name,
        title=plan.summary,
        change_html=change,
        details_html=content,
        badge=_presentation_badge(snapshot),
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title=preview_title,
        summary=plan.summary,
        html=html,
        details=tuple(details),
        warnings=(),
    )


def _lines(value: str) -> str:
    return "<br>".join(escape(line) for line in str(value or "").splitlines())


def _presentation_app_name(snapshot: PresentationSnapshot) -> str:
    backend = str(snapshot.backend or "").lower()
    if "powerpoint" in backend or "com" in backend or "office" in backend:
        return "Microsoft PowerPoint"
    if "google" in backend or "slides" in backend:
        return "Google Slides"
    return "Presentation"


def _presentation_badge(snapshot: PresentationSnapshot) -> str:
    return "PP" if _presentation_app_name(snapshot) == "Microsoft PowerPoint" else "GS"
