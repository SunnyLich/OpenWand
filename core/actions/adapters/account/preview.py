"""Escaped HTML previews for account-backed actions."""

from __future__ import annotations

from html import escape
from typing import Any

from core.actions.adapters.account.capabilities import (
    APPLY_CATEGORY,
    CREATE_DISABLED_RULE,
    CREATE_DRAFT,
    CREATE_EVENT,
    RESCHEDULE_EVENT,
    UPDATE_DRAFT,
)
from core.actions.adapters.account.snapshots import CalendarSnapshot, EmailSnapshot
from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import canvas_preview, chips, focus_field, focus_preview


def _value(value: Any) -> str:
    return escape(str(value or ""), quote=True)


def render_email_preview(plan: ActionPlan, snapshot: EmailSnapshot) -> ActionPreview:
    operation = plan.operations[0]
    args = operation.args
    title = "Review email account action"
    if operation.type in {CREATE_DRAFT, UPDATE_DRAFT}:
        verb = "Create" if operation.type == CREATE_DRAFT else "Update"
        title = f"{verb} email draft"
        hero = (
            '<div class="action-mail-card">'
            + _mail_row("To", ", ".join(args["to"]) or "—")
            + _mail_row("Cc", ", ".join(args["cc"]) or "—")
            + _mail_row("Bcc", ", ".join(args["bcc"]) or "—")
            + _mail_row("Subject", args["subject"] or "(no subject)")
            + f'<div class="action-mail-body">{_lines(args["body_text"])}</div>'
            + "</div>"
        )
        properties = ("Draft only", "Not sent", f"{len(args['to'])} recipients")
    elif operation.type == APPLY_CATEGORY:
        title = "Change email labels or categories"
        hero = (
            '<div class="action-mail-card">'
            + _mail_row("Add", ", ".join(args["add"]) or "—")
            + _mail_row("Remove", ", ".join(args["remove"]) or "—")
            + "</div>"
        )
        properties = (f"{len(args['add'])} added", f"{len(args['remove'])} removed")
    elif operation.type == CREATE_DISABLED_RULE:
        title = "Create disabled Outlook rule"
        hero = (
            '<div class="action-mail-card">'
            + _mail_row("Name", args["name"])
            + _mail_row("Status", "Disabled")
            + _mail_row("Conditions", args["conditions"])
            + _mail_row("Actions", args["actions"])
            + "</div>"
        )
        properties = ("Disabled", "Processes no messages")
    else:
        raise ValueError("This email operation has no preview renderer.")
    html = canvas_preview(
        app="Gmail" if snapshot.provider == "gmail" else "Microsoft Outlook",
        target=snapshot.account_display,
        title=plan.summary or title,
        hero_html=hero,
        chips_html=chips(properties),
        badge="GM" if snapshot.provider == "gmail" else "OL",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title=title,
        summary=plan.summary,
        html=html,
        details=({"operation": operation.type, "arguments": dict(args)},),
        warnings=(),
    )


def render_calendar_preview(plan: ActionPlan, snapshot: CalendarSnapshot) -> ActionPreview:
    operation = plan.operations[0]
    args = operation.args
    title = "Create calendar event" if operation.type == CREATE_EVENT else "Reschedule calendar event"
    if operation.type == RESCHEDULE_EVENT:
        title_value = snapshot.title or "Calendar event"
        change = (
            '<div class="action-focus-grid">'
            + focus_field("Current start", snapshot.start)
            + focus_field("New start", args["start"], accent=True)
            + focus_field("Current end", snapshot.end)
            + focus_field("New end", args["end"], accent=True)
            + "</div>"
        )
    else:
        title_value = str(args["title"])
        change = f"""
<div class="action-event-card">
  <div class="action-event-date">{_value(_event_time(args['start']))}</div>
  <div class="action-event-copy">
    <div class="action-event-title">{_value(args['title'])}</div>
    <div class="action-event-meta">{_value(args['start'])}<br>{_value(args['location'] or 'No location')}</div>
  </div>
</div>""".strip()
    details = (
        '<div class="action-focus-grid">'
        + focus_field("Start", args["start"], accent=True)
        + focus_field("End", args["end"])
        + focus_field("Time zone", args["time_zone"])
        + focus_field("Attendees", ", ".join(args.get("attendees") or ()) or "None")
        + focus_field("Attendee notifications", "Off")
        + "</div>"
    )
    html = focus_preview(
        app="Google Calendar" if snapshot.provider == "google" else "Outlook Calendar",
        target=snapshot.calendar_name,
        title=plan.summary or title_value,
        change_html=change,
        details_html=details,
        badge="GC" if snapshot.provider == "google" else "OC",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title=title,
        summary=plan.summary,
        html=html,
        details=({"operation": operation.type, "arguments": dict(args)},),
        warnings=(),
    )


def _mail_row(label: str, value: Any) -> str:
    return (
        '<div class="action-mail-row">'
        f'<span class="action-mail-label">{_value(label)}</span>'
        f"<strong>{_value(value)}</strong>"
        "</div>"
    )


def _lines(value: Any) -> str:
    return "<br>".join(_value(line) for line in str(value or "").splitlines())


def _event_time(value: Any) -> str:
    text = str(value or "")
    if "T" in text:
        return text.split("T", 1)[1][:5]
    return text[:16]
