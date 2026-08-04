"""Typed, versioned account-API capabilities."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk

CREATE_DRAFT = "email.create_draft@1"
UPDATE_DRAFT = "email.update_draft@1"
APPLY_CATEGORY = "email.apply_category@1"
CREATE_DISABLED_RULE = "email.create_disabled_rule@1"
CREATE_EVENT = "calendar.create_event@1"
RESCHEDULE_EVENT = "calendar.reschedule_event@1"

_ADDRESS_LIST = {"type": "array", "items": {"type": "string"}, "maxItems": 50}


def email_capabilities() -> tuple[ActionCapability, ...]:
    return (
        ActionCapability(
            type=CREATE_DRAFT,
            app="email",
            title="Create email draft",
            description="Create a reviewed draft through Gmail or Microsoft Graph without sending it.",
            input_schema={
                "type": "object",
                "required": ["to", "cc", "bcc", "subject", "body_text"],
                "properties": {
                    "to": _ADDRESS_LIST,
                    "cc": _ADDRESS_LIST,
                    "bcc": _ADDRESS_LIST,
                    "subject": {"type": "string", "maxLength": 998},
                    "body_text": {"type": "string", "maxLength": 50000},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=UPDATE_DRAFT,
            app="email",
            title="Update email draft",
            description="Replace a reviewed draft only if its revision still matches; never send it.",
            input_schema={
                "type": "object",
                "required": ["to", "cc", "bcc", "subject", "body_text"],
                "properties": {
                    "to": _ADDRESS_LIST,
                    "cc": _ADDRESS_LIST,
                    "bcc": _ADDRESS_LIST,
                    "subject": {"type": "string", "maxLength": 998},
                    "body_text": {"type": "string", "maxLength": 50000},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=APPLY_CATEGORY,
            app="email",
            title="Apply label or category",
            description="Add or remove existing Gmail labels or Outlook categories from one reviewed target.",
            input_schema={
                "type": "object",
                "required": ["add", "remove"],
                "properties": {
                    "add": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "remove": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.LOW,
            reversible=True,
        ),
        ActionCapability(
            type=CREATE_DISABLED_RULE,
            app="email",
            title="Create disabled email rule",
            description="Create an Outlook Inbox rule with isEnabled=false. Gmail is refused because its API has no disabled filter state.",
            input_schema={
                "type": "object",
                "required": ["name", "enabled", "conditions", "actions"],
                "properties": {
                    "name": {"type": "string", "maxLength": 120},
                    "enabled": {"const": False},
                    "conditions": {
                        "type": "object",
                        "properties": {
                            "from_contains": {"type": ["string", "null"], "maxLength": 500},
                            "subject_contains": {"type": ["string", "null"], "maxLength": 500},
                            "sent_to": {"type": ["string", "null"], "maxLength": 320},
                            "has_attachment": {"type": ["boolean", "null"]},
                        },
                        "required": ["from_contains", "subject_contains", "sent_to", "has_attachment"],
                        "additionalProperties": False,
                    },
                    "actions": {
                        "type": "object",
                        "properties": {
                            "add_category": {"type": ["string", "null"], "maxLength": 500},
                            "move_to_folder": {"type": ["string", "null"], "maxLength": 500},
                            "mark_as_read": {"type": ["boolean", "null"]},
                        },
                        "required": ["add_category", "move_to_folder", "mark_as_read"],
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )


def calendar_capabilities() -> tuple[ActionCapability, ...]:
    return (
        ActionCapability(
            type=CREATE_EVENT,
            app="calendar",
            title="Create calendar event",
            description="Create one reviewed event through Google Calendar or Microsoft Graph.",
            input_schema={
                "type": "object",
                "required": [
                    "title", "start", "end", "time_zone", "location", "description", "attendees",
                    "notify_attendees",
                ],
                "properties": {
                    "title": {"type": "string", "maxLength": 300},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "time_zone": {"type": "string"},
                    "location": {"type": ["string", "null"], "maxLength": 500},
                    "description": {"type": ["string", "null"], "maxLength": 10000},
                    "attendees": _ADDRESS_LIST,
                    "notify_attendees": {"const": False},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=RESCHEDULE_EVENT,
            app="calendar",
            title="Reschedule calendar event",
            description="Change only start/end/time zone after etag or changeKey revalidation.",
            input_schema={
                "type": "object",
                "required": ["start", "end", "time_zone", "notify_attendees"],
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "time_zone": {"type": "string"},
                    "notify_attendees": {"const": False},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )
