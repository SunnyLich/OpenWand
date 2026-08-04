"""Deterministic plan builders for account-backed email and calendar actions."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
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
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk, ActionTarget

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_ACTIONS = {CREATE_DRAFT, UPDATE_DRAFT, APPLY_CATEGORY, CREATE_DISABLED_RULE}
_CALENDAR_ACTIONS = {CREATE_EVENT, RESCHEDULE_EVENT}


def _clean_addresses(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError(f"{field} must be a list of at most 50 addresses.")
    result = [str(item).strip() for item in value]
    if any(not _EMAIL.fullmatch(item) or len(item) > 320 for item in result):
        raise ValueError(f"{field} contains an invalid email address.")
    if len(set(item.casefold() for item in result)) != len(result):
        raise ValueError(f"{field} contains a duplicate address.")
    return result


def _draft_args(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"to", "cc", "bcc", "subject", "body_text"}
    if set(value) - allowed:
        raise ValueError("The draft contains unsupported fields.")
    to = _clean_addresses(value.get("to"), "to")
    cc = _clean_addresses(value.get("cc", []), "cc")
    bcc = _clean_addresses(value.get("bcc", []), "bcc")
    if not to and not cc and not bcc:
        raise ValueError("A draft requires at least one recipient.")
    subject = " ".join(str(value.get("subject") or "").split())
    body = str(value.get("body_text") or "")
    if len(subject) > 998 or len(body) > 50_000:
        raise ValueError("The draft subject or body exceeds the bounded action limit.")
    return {"to": to, "cc": cc, "bcc": bcc, "subject": subject, "body_text": body}


def build_email_plan(
    snapshot: EmailSnapshot,
    capability_type: str,
    arguments: dict[str, Any],
    *,
    summary: str = "",
) -> ActionPlan:
    if capability_type not in _EMAIL_ACTIONS:
        raise ValueError("Unsupported email capability.")
    args: dict[str, Any]
    risk = ActionRisk.MEDIUM
    if capability_type in {CREATE_DRAFT, UPDATE_DRAFT}:
        expected_kind = "mailbox" if capability_type == CREATE_DRAFT else "draft"
        if snapshot.object_kind != expected_kind:
            raise ValueError(f"{capability_type} requires an exact {expected_kind} snapshot.")
        args = _draft_args(arguments)
    elif capability_type == APPLY_CATEGORY:
        if snapshot.object_kind not in {"message", "thread"}:
            raise ValueError("Labels and categories require one message or thread snapshot.")
        if set(arguments) != {"add", "remove"}:
            raise ValueError("Category changes require exact add and remove lists.")
        add = [str(item).strip() for item in arguments.get("add") or []]
        remove = [str(item).strip() for item in arguments.get("remove") or []]
        if len(add) > 20 or len(remove) > 20 or not (add or remove):
            raise ValueError("Choose between 1 and 20 category changes.")
        if set(add) & set(remove) or len(set(add)) != len(add) or len(set(remove)) != len(remove):
            raise ValueError("Category changes cannot conflict or repeat.")
        available = set(snapshot.available_categories)
        if any(item not in available for item in add + remove):
            raise ValueError("Only categories or labels returned by the account API may be used.")
        if any(item in snapshot.categories for item in add) or any(item not in snapshot.categories for item in remove):
            raise ValueError("The requested category change does not match the current message state.")
        args = {"add": add, "remove": remove}
        risk = ActionRisk.LOW
    else:
        if snapshot.object_kind != "mailbox":
            raise ValueError("Rule creation requires an exact mailbox snapshot.")
        if snapshot.provider != "outlook" or not snapshot.supports_disabled_rules:
            raise ValueError("Gmail filters cannot be created disabled; Wisp refused this action.")
        if arguments.get("enabled") is not False:
            raise ValueError("Wisp only creates email rules in the disabled state.")
        if set(arguments) != {"name", "enabled", "conditions", "actions"}:
            raise ValueError("The disabled rule contains unsupported fields.")
        name = " ".join(str(arguments.get("name") or "").split())[:120]
        conditions = arguments.get("conditions")
        actions = arguments.get("actions")
        if not name or not isinstance(conditions, dict) or not isinstance(actions, dict):
            raise ValueError("A disabled rule requires a name, conditions, and actions.")
        allowed_conditions = {"from_contains", "subject_contains", "sent_to", "has_attachment"}
        allowed_actions = {"add_category", "move_to_folder", "mark_as_read"}
        if set(conditions) - allowed_conditions:
            raise ValueError("The disabled rule contains unsupported conditions.")
        if set(actions) - allowed_actions:
            raise ValueError("The disabled rule contains unsupported actions.")
        clean_conditions = {key: value for key, value in conditions.items() if value is not None and value != ""}
        clean_actions = {key: value for key, value in actions.items() if value is not None and value != ""}
        if not clean_conditions or not clean_actions:
            raise ValueError("A disabled rule requires at least one condition and one action.")
        if any(len(str(item)) > 500 for item in (*clean_conditions.values(), *clean_actions.values())):
            raise ValueError("A disabled rule value is too long.")
        args = {"name": name, "enabled": False, "conditions": clean_conditions, "actions": clean_actions}
    clean_summary = " ".join(str(summary or "").split())[:180] or {
        CREATE_DRAFT: "Create an email draft without sending",
        UPDATE_DRAFT: "Update an email draft without sending",
        APPLY_CATEGORY: "Apply reviewed labels or categories",
        CREATE_DISABLED_RULE: "Create a disabled Outlook rule",
    }[capability_type]
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="email",
        target=snapshot.target,
        summary=clean_summary,
        operations=(ActionOperation(id="email_action", type=capability_type, args=args),),
        risk=risk,
        requires_confirmation=True,
    )


def _parse_time(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 date/time.") from exc


def _event_times(arguments: dict[str, Any]) -> tuple[str, str, str]:
    start = str(arguments.get("start") or "").strip()
    end = str(arguments.get("end") or "").strip()
    zone = str(arguments.get("time_zone") or "").strip()
    start_dt = _parse_time(start, "start")
    end_dt = _parse_time(end, "end")
    try:
        ordered = end_dt > start_dt
    except TypeError as exc:
        raise ValueError("start and end must use compatible timezone offsets.") from exc
    if not ordered or not zone or len(zone) > 100:
        raise ValueError("The event must end after it starts and name one time zone.")
    return start, end, zone


def build_calendar_plan(
    snapshot: CalendarSnapshot,
    capability_type: str,
    arguments: dict[str, Any],
    *,
    summary: str = "",
) -> ActionPlan:
    if capability_type not in _CALENDAR_ACTIONS:
        raise ValueError("Unsupported calendar capability.")
    start, end, zone = _event_times(arguments)
    if arguments.get("notify_attendees", False) is not False:
        raise ValueError("The first calendar actions never request attendee notifications.")
    if capability_type == CREATE_EVENT:
        if snapshot.object_kind != "calendar":
            raise ValueError("Event creation requires an exact calendar snapshot.")
        allowed = {"title", "start", "end", "time_zone", "location", "description", "attendees", "notify_attendees"}
        if set(arguments) - allowed:
            raise ValueError("The event contains unsupported fields.")
        title = " ".join(str(arguments.get("title") or "").split())
        if not title or len(title) > 300:
            raise ValueError("The event requires a bounded title.")
        args = {
            "title": title,
            "start": start,
            "end": end,
            "time_zone": zone,
            "location": str(arguments.get("location") or "")[:500],
            "description": str(arguments.get("description") or "")[:10_000],
            "attendees": _clean_addresses(arguments.get("attendees", []), "attendees"),
            "notify_attendees": False,
        }
    else:
        if snapshot.object_kind != "event":
            raise ValueError("Rescheduling requires an exact event snapshot.")
        if set(arguments) != {"start", "end", "time_zone", "notify_attendees"}:
            raise ValueError("Rescheduling may change only start, end, and time zone.")
        if (start, end, zone) == (snapshot.start, snapshot.end, snapshot.time_zone):
            raise ValueError("The proposed event time is unchanged.")
        args = {"start": start, "end": end, "time_zone": zone, "notify_attendees": False}
    clean_summary = " ".join(str(summary or "").split())[:180] or (
        "Create a reviewed calendar event" if capability_type == CREATE_EVENT else "Reschedule the reviewed event"
    )
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="calendar",
        target=snapshot.target,
        summary=clean_summary,
        operations=(ActionOperation(id="calendar_action", type=capability_type, args=args),),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def action_plan_from_dict(value: dict[str, Any]) -> ActionPlan:
    target = value.get("target") if isinstance(value.get("target"), dict) else {}
    return ActionPlan(
        plan_id=str(value.get("plan_id") or ""),
        app=str(value.get("app") or ""),
        target=ActionTarget(
            app=str(target.get("app") or ""),
            display_name=str(target.get("display_name") or ""),
            locator={str(key): str(item) for key, item in dict(target.get("locator") or {}).items()},
            version=str(target.get("version") or ""),
        ),
        summary=str(value.get("summary") or ""),
        operations=tuple(
            ActionOperation(
                id=str(item.get("id") or ""),
                type=str(item.get("type") or ""),
                args=dict(item.get("args") or {}),
                depends_on=tuple(item.get("depends_on") or ()),
            )
            for item in (value.get("operations") or ())
            if isinstance(item, dict)
        ),
        risk=ActionRisk(str(value.get("risk") or ActionRisk.MEDIUM.value)),
        requires_confirmation=bool(value.get("requires_confirmation", True)),
    )
