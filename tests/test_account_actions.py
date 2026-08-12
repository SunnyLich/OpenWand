"""Account-action contract tests using fake normalized API clients only."""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.actions.adapters.account import (
    APPLY_CATEGORY,
    CREATE_DISABLED_RULE,
    CREATE_DRAFT,
    CREATE_EVENT,
    RESCHEDULE_EVENT,
    CalendarAccountActionAdapter,
    EmailAccountActionAdapter,
    build_calendar_plan,
    build_email_plan,
    detect_calendar_provider,
    detect_email_provider,
    email_capabilities,
    email_suggestion_metadata,
)
from core.actions.adapters.account.capabilities import calendar_capabilities
from core.actions.errors import ActionValidationError
from core.actions.providers import detected_picker_context
from core.llm_clients.client import _validated_action_planning_spec
from ui.addon_presentations import sanitize_presentation_html


class FakeMailClient:
    def __init__(self, provider: str = "gmail") -> None:
        self.provider = provider
        self.supports_disabled_rules = provider == "outlook"
        self.revision = 1
        self.drafts: dict[str, dict] = {}
        self.messages = {
            "m1": {"id": "m1", "object_kind": "message", "revision": "m1-r1", "subject": "Hello",
                   "categories": ["Inbox"], "available_categories": ["Inbox", "Follow up"]}
        }
        self.rules: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.sabotage_draft_readback = False
        self.sabotage_after_update = False

    def get_mailbox(self, account_id: str) -> dict:
        return {"id": "", "revision": "mailbox-r1", "account_display": account_id,
                "available_categories": ["Inbox", "Follow up"]}

    def get_draft(self, account_id: str, draft_id: str) -> dict:
        value = deepcopy(self.drafts[draft_id])
        if self.sabotage_draft_readback:
            value["subject"] = "unexpected"
            self.sabotage_draft_readback = False
        return value

    def get_message(self, account_id: str, object_id: str, object_kind: str) -> dict:
        return deepcopy(self.messages[object_id])

    def create_draft(self, account_id: str, payload: dict, *, idempotency_key: str) -> dict:
        self.calls.append(("create_draft", idempotency_key))
        value = {"id": "d1", "object_kind": "draft", "revision": "d1-r1", **deepcopy(payload)}
        self.drafts["d1"] = value
        return {"id": "d1", "revision": "d1-r1"}

    def update_draft(self, account_id: str, draft_id: str, payload: dict, *, if_revision: str) -> dict:
        self.calls.append(("update_draft", if_revision))
        self.revision += 1
        self.drafts[draft_id] = {"id": draft_id, "object_kind": "draft",
                                 "revision": f"d1-r{self.revision}", **deepcopy(payload)}
        if self.sabotage_after_update:
            self.sabotage_draft_readback = True
            self.sabotage_after_update = False
        return {"id": draft_id, "revision": f"d1-r{self.revision}"}

    def delete_draft(self, account_id: str, draft_id: str, *, if_revision: str) -> None:
        self.calls.append(("delete_draft", if_revision))
        self.drafts.pop(draft_id, None)

    def set_categories(self, account_id: str, object_id: str, object_kind: str,
                       categories: tuple[str, ...], *, if_revision: str) -> dict:
        self.calls.append(("set_categories", if_revision))
        self.revision += 1
        self.messages[object_id]["categories"] = list(categories)
        self.messages[object_id]["revision"] = f"m1-r{self.revision}"
        return {"id": object_id, "revision": f"m1-r{self.revision}"}

    def create_disabled_rule(self, account_id: str, payload: dict, *, idempotency_key: str) -> dict:
        self.calls.append(("create_disabled_rule", payload["enabled"]))
        self.rules["rule1"] = {"id": "rule1", **deepcopy(payload)}
        return {"id": "rule1"}

    def get_rule(self, account_id: str, rule_id: str) -> dict:
        return deepcopy(self.rules[rule_id])

    def delete_rule(self, account_id: str, rule_id: str) -> None:
        self.rules.pop(rule_id, None)


class FakeCalendarClient:
    provider = "google"

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.revision = 1

    def get_calendar(self, account_id: str, calendar_id: str) -> dict:
        return {"calendar_name": "Work", "revision": "cal-r1"}

    def get_event(self, account_id: str, calendar_id: str, event_id: str) -> dict:
        return deepcopy(self.events[event_id])

    def create_event(self, account_id: str, calendar_id: str, payload: dict, *,
                     idempotency_key: str, client_event_id: str) -> dict:
        self.calls.append(("create_event", client_event_id))
        self.events[client_event_id] = {"id": client_event_id, "revision": "ev-r1", **deepcopy(payload)}
        return {"id": client_event_id, "revision": "ev-r1"}

    def update_event(self, account_id: str, calendar_id: str, event_id: str, payload: dict, *,
                     if_revision: str, notify_attendees: bool) -> dict:
        self.calls.append(("update_event", if_revision, notify_attendees))
        self.revision += 1
        self.events[event_id].update(deepcopy(payload))
        self.events[event_id]["revision"] = f"ev-r{self.revision}"
        return {"id": event_id, "revision": f"ev-r{self.revision}"}

    def delete_event(self, account_id: str, calendar_id: str, event_id: str, *,
                     if_revision: str, notify_attendees: bool) -> None:
        self.calls.append(("delete_event", if_revision, notify_attendees))
        self.events.pop(event_id, None)


def _draft_args(subject: str = "Hello <team>") -> dict:
    return {"to": ["person@example.com"], "cc": [], "bcc": [], "subject": subject, "body_text": "Body & details"}


def test_context_detection_and_answer_only_summary_metadata() -> None:
    assert detect_email_provider({"active_app": {"process_name": "chrome.exe"}, "browser_url": "https://mail.google.com/mail/u/0"}) == "gmail"
    assert detect_email_provider({"active_app": {"process_name": "OUTLOOK.EXE"}}) == "outlook"
    assert detect_calendar_provider({"active_app": {"process_name": "chrome.exe", "title": "Google Calendar"}}) == "google"
    assert detect_calendar_provider({"active_app": {"process_name": "outlook.exe", "title": "Calendar"}}) == "outlook"
    assert detect_email_provider({
        "active_app": {"process_name": "msedge.exe", "title": "Mail - Outlook"},
        "browser_url": "https://outlook.cloud.microsoft/mail/",
    }) == "outlook"
    assert detect_calendar_provider({
        "active_app": {"process_name": "chrome.exe", "title": "Calendar - Outlook"},
        "browser_url": "https://outlook.office365.com/calendar/view/week",
    }) == "outlook"
    assert email_suggestion_metadata("gmail")[0]["mode"] == "answer"


def test_disabled_rule_schema_is_closed_and_gmail_refuses_it() -> None:
    capability = next(item for item in email_capabilities() if item.type == CREATE_DISABLED_RULE)
    assert capability.input_schema["properties"]["conditions"]["additionalProperties"] is False
    client = FakeMailClient("gmail")
    snapshot = EmailAccountActionAdapter(client).snapshot_mailbox("me@example.com")
    with pytest.raises(ValueError, match="cannot be created disabled"):
        build_email_plan(snapshot, CREATE_DISABLED_RULE, {
            "name": "Invoices", "enabled": False, "conditions": {"subject_contains": "invoice"},
            "actions": {"add_category": "Follow up"},
        })
    assert not client.calls


def test_all_account_capabilities_are_valid_for_forced_planning() -> None:
    for capability in (*email_capabilities(), *calendar_capabilities()):
        _validated_action_planning_spec(
            capability.type.replace(".", "_").replace("@", "_"),
            capability.description,
            capability.input_schema,
        )


def test_create_draft_escapes_preview_never_sends_and_is_idempotent() -> None:
    client = FakeMailClient()
    adapter = EmailAccountActionAdapter(client)
    snapshot = adapter.snapshot_mailbox("me@example.com")
    plan = build_email_plan(snapshot, CREATE_DRAFT, _draft_args())
    preview = adapter.render_preview(plan, snapshot)
    assert "action-canvas-preview" in preview.html
    assert "Not sent" not in preview.html
    assert preview.warnings == ()
    assert "Hello &lt;team&gt;" in preview.html and "Body &amp; details" in preview.html
    first = adapter.execute(plan, confirmed=True, idempotency_key="draft-1")
    second = adapter.execute(plan, confirmed=True, idempotency_key="draft-1")
    assert first == second
    assert [call[0] for call in client.calls].count("create_draft") == 1
    assert client.drafts["d1"]["subject"] == "Hello <team>"


def test_stale_draft_is_rejected_before_api_mutation() -> None:
    client = FakeMailClient()
    client.create_draft("me@example.com", _draft_args("Old"), idempotency_key="setup")
    adapter = EmailAccountActionAdapter(client)
    snapshot = adapter.snapshot_draft("me@example.com", "d1")
    plan = build_email_plan(snapshot, "email.update_draft@1", _draft_args("New"))
    client.drafts["d1"]["revision"] = "changed"
    before = len(client.calls)
    with pytest.raises(ActionValidationError, match="revision changed"):
        adapter.execute(plan, confirmed=True, idempotency_key="update-1")
    assert len(client.calls) == before


def test_failed_draft_verification_rolls_back_original() -> None:
    client = FakeMailClient()
    client.create_draft("me@example.com", _draft_args("Old"), idempotency_key="setup")
    adapter = EmailAccountActionAdapter(client)
    snapshot = adapter.snapshot_draft("me@example.com", "d1")
    plan = build_email_plan(snapshot, "email.update_draft@1", _draft_args("New"))
    client.sabotage_after_update = True
    with pytest.raises(RuntimeError, match="rolled back"):
        adapter.execute(plan, confirmed=True, idempotency_key="update-2")
    assert client.drafts["d1"]["subject"] == "Old"


def test_outlook_rule_is_created_disabled_and_verified() -> None:
    client = FakeMailClient("outlook")
    adapter = EmailAccountActionAdapter(client)
    snapshot = adapter.snapshot_mailbox("me@example.com")
    plan = build_email_plan(snapshot, CREATE_DISABLED_RULE, {
        "name": "Invoices", "enabled": False, "conditions": {"subject_contains": "invoice"},
        "actions": {"add_category": "Follow up"},
    })
    assert "Disabled" in adapter.render_preview(plan, snapshot).html
    adapter.execute(plan, confirmed=True, idempotency_key="rule-1")
    assert client.rules["rule1"]["enabled"] is False


def test_category_change_uses_revision_and_verifies_exact_state() -> None:
    client = FakeMailClient()
    adapter = EmailAccountActionAdapter(client)
    snapshot = adapter.snapshot_message("me@example.com", "m1")
    plan = build_email_plan(snapshot, APPLY_CATEGORY, {"add": ["Follow up"], "remove": ["Inbox"]})
    adapter.execute(plan, confirmed=True, idempotency_key="label-1")
    assert client.messages["m1"]["categories"] == ["Follow up"]
    assert ("set_categories", "m1-r1") in client.calls


def test_calendar_create_and_reschedule_use_api_etags_without_notifications() -> None:
    client = FakeCalendarClient()
    adapter = CalendarAccountActionAdapter(client)
    calendar = adapter.snapshot_calendar("me@example.com", "primary")
    create = build_calendar_plan(calendar, CREATE_EVENT, {
        "title": "Planning", "start": "2026-08-04T09:00:00-06:00", "end": "2026-08-04T10:00:00-06:00",
        "time_zone": "America/Edmonton", "attendees": [], "notify_attendees": False,
    })
    preview = adapter.render_preview(create, calendar)
    assert "action-focus-preview" in preview.html
    assert "Attendee notifications" in preview.html
    assert all(text not in preview.html for text in ("Ready to review", "Nothing has changed", "Apply rechecks", "OpenWand will"))
    assert sanitize_presentation_html(preview.html) == preview.html
    created = adapter.execute(create, confirmed=True, idempotency_key="event-1")
    event_id = created.created[0]["name"]
    event = adapter.snapshot_event("me@example.com", "primary", event_id)
    reschedule = build_calendar_plan(event, RESCHEDULE_EVENT, {
        "start": "2026-08-04T11:00:00-06:00", "end": "2026-08-04T12:00:00-06:00",
        "time_zone": "America/Edmonton", "notify_attendees": False,
    })
    adapter.execute(reschedule, confirmed=True, idempotency_key="event-2")
    assert ("update_event", "ev-r1", False) in client.calls
    assert client.events[event_id]["start"] == "2026-08-04T11:00:00-06:00"


def test_gmail_and_calendar_picker_options_are_detected_but_truthfully_gated() -> None:
    gmail = detected_picker_context({
        "active_app": {"name": "Inbox - Gmail", "process_name": "chrome.exe"},
        "browser_url": "https://mail.google.com/mail/u/0/#inbox",
    })
    calendar = detected_picker_context({
        "active_app": {"name": "Google Calendar", "process_name": "msedge.exe"},
        "browser_url": "https://calendar.google.com/calendar/u/0/r",
    })

    assert gmail["display_name"] == "Gmail"
    assert [item["label"] for item in gmail["suggested_intents"]] == [
        "Create email draft",
        "Label this email",
    ]
    assert all(item["available"] is False for item in gmail["suggested_intents"])
    assert calendar["display_name"] == "Google Calendar"
    assert [item["label"] for item in calendar["suggested_intents"]] == [
        "Create calendar event",
        "Reschedule this event",
    ]
    assert all(item["available"] is False for item in calendar["suggested_intents"])
