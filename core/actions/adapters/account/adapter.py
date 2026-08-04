"""Preview-first email and calendar actions through injected account APIs."""

from __future__ import annotations

import hashlib
from typing import Any

from core.actions.adapters.account.capabilities import (
    APPLY_CATEGORY,
    CREATE_DRAFT,
    CREATE_EVENT,
    UPDATE_DRAFT,
    calendar_capabilities,
    email_capabilities,
)
from core.actions.adapters.account.clients import CalendarApiClient, MailApiClient
from core.actions.adapters.account.plans import build_calendar_plan, build_email_plan
from core.actions.adapters.account.preview import render_calendar_preview, render_email_preview
from core.actions.adapters.account.snapshots import CalendarSnapshot, EmailSnapshot
from core.actions.contracts import ActionCapability, ActionExecutionResult, ActionPlan, ActionPreview, ValidationIssue
from core.actions.errors import ActionValidationError


def _approval(plan: ActionPlan, confirmed: bool, key: str) -> None:
    issues: list[ValidationIssue] = []
    if plan.requires_confirmation and not confirmed:
        issues.append(ValidationIssue("confirmation_required", "Review and approve the preview before applying."))
    if not key:
        issues.append(ValidationIssue("idempotency_required", "An idempotency key is required before applying."))
    if issues:
        raise ActionValidationError(tuple(issues))


class EmailAccountActionAdapter:
    """Execute one reviewed mail mutation without exposing send or browser controls."""

    def __init__(self, client: MailApiClient) -> None:
        self.client = client
        self.provider = str(client.provider).lower()
        if self.provider not in {"gmail", "outlook"}:
            raise ValueError("The email API provider must be gmail or outlook.")
        self._results: dict[str, tuple[str, ActionExecutionResult]] = {}

    def capabilities(self) -> tuple[ActionCapability, ...]:
        return email_capabilities()

    def snapshot_mailbox(self, account_id: str) -> EmailSnapshot:
        value = dict(self.client.get_mailbox(account_id))
        value.update(object_kind="mailbox", supports_disabled_rules=bool(self.client.supports_disabled_rules))
        return EmailSnapshot.from_api(self.provider, account_id, value)

    def snapshot_draft(self, account_id: str, draft_id: str) -> EmailSnapshot:
        value = dict(self.client.get_draft(account_id, draft_id))
        value["object_kind"] = "draft"
        return EmailSnapshot.from_api(self.provider, account_id, value)

    def snapshot_message(self, account_id: str, object_id: str, object_kind: str = "message") -> EmailSnapshot:
        value = dict(self.client.get_message(account_id, object_id, object_kind))
        value["object_kind"] = object_kind
        return EmailSnapshot.from_api(self.provider, account_id, value)

    def validate(self, plan: ActionPlan, snapshot: EmailSnapshot) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if plan.app != "email" or plan.target.app != "email":
            issues.append(ValidationIssue("wrong_adapter", "This adapter can run only email plans."))
        if not plan.plan_id.strip() or not plan.requires_confirmation:
            issues.append(ValidationIssue("confirmation_policy", "Email changes require an identified, approval-gated plan."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(ValidationIssue("target_changed", "The email account target changed after preview."))
        if plan.target.version != snapshot.revision:
            issues.append(ValidationIssue("target_stale", "The email item revision changed after preview."))
        if len(plan.operations) != 1:
            issues.append(ValidationIssue("single_operation_required", "Review one email change at a time."))
            return tuple(issues)
        operation = plan.operations[0]
        try:
            build_email_plan(snapshot, operation.type, operation.args)
        except ValueError as exc:
            issues.append(ValidationIssue("invalid_email_action", str(exc), operation.id))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: EmailSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_email_preview(plan, snapshot)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        key = str(idempotency_key or "").strip()
        _approval(plan, confirmed, key)
        cached = self._results.get(key)
        if cached:
            if cached[0] != plan.plan_id:
                raise ActionValidationError((ValidationIssue("idempotency_conflict", "This key belongs to another plan."),))
            return cached[1]
        before = self._snapshot_target(plan)
        issues = self.validate(plan, before)
        if issues:
            raise ActionValidationError(issues)
        operation = plan.operations[0]
        created: tuple[dict[str, str], ...] = ()
        rollback: tuple[str, Any] | None = None
        receipt: dict[str, Any]
        try:
            if operation.type == CREATE_DRAFT:
                receipt = dict(self.client.create_draft(before.account_id, dict(operation.args), idempotency_key=key))
                object_id = str(receipt.get("id") or "")
                created = ({"kind": "email_draft", "name": object_id},)
                rollback = ("draft", (before.account_id, object_id, str(receipt.get("revision") or receipt.get("etag") or "")))
                after = self.snapshot_draft(before.account_id, object_id)
                self._verify_draft(operation.args, after)
            elif operation.type == UPDATE_DRAFT:
                rollback = ("draft_restore", (before,))
                receipt = dict(self.client.update_draft(before.account_id, before.object_id, dict(operation.args), if_revision=before.revision))
                after = self.snapshot_draft(before.account_id, before.object_id)
                self._verify_draft(operation.args, after)
            elif operation.type == APPLY_CATEGORY:
                final = tuple(item for item in before.categories if item not in operation.args["remove"])
                final += tuple(item for item in operation.args["add"] if item not in final)
                rollback = ("categories", (before,))
                receipt = dict(self.client.set_categories(before.account_id, before.object_id, before.object_kind, final, if_revision=before.revision))
                after = self.snapshot_message(before.account_id, before.object_id, before.object_kind)
                if after.categories != final:
                    raise RuntimeError("The API readback did not retain the reviewed categories.")
            else:
                if self.provider != "outlook" or not self.client.supports_disabled_rules:
                    raise RuntimeError("This provider cannot create a disabled rule.")
                payload = dict(operation.args)
                payload["enabled"] = False
                receipt = dict(self.client.create_disabled_rule(before.account_id, payload, idempotency_key=key))
                rule_id = str(receipt.get("id") or "")
                created = ({"kind": "disabled_email_rule", "name": rule_id},)
                rollback = ("rule", (before.account_id, rule_id))
                rule = self.client.get_rule(before.account_id, rule_id)
                if rule.get("enabled", rule.get("is_enabled")) is not False:
                    raise RuntimeError("The Outlook rule was not disabled during API readback.")
                after = before
        except Exception as exc:
            rollback_ok = self._rollback(rollback, locals().get("receipt", {})) if rollback else False
            state = "rolled back" if rollback_ok else "rollback could not be verified"
            raise RuntimeError(f"Email API verification failed and the change was {state}: {exc}") from exc
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message="Applied and verified the reviewed email account action.",
            created=created,
            journal=({"kind": "email_account_api", "provider": self.provider, "operation": operation.type,
                      "before_revision": before.revision, "after_revision": getattr(after, "revision", "")},),
            verification=("Verified the exact reviewed state through account API readback.",),
        )
        self._results[key] = (plan.plan_id, result)
        return result

    def _snapshot_target(self, plan: ActionPlan) -> EmailSnapshot:
        loc = plan.target.locator
        if loc.get("provider") != self.provider:
            raise ActionValidationError((ValidationIssue("provider_changed", "The email provider changed."),))
        kind, account, object_id = loc.get("object_kind", ""), loc.get("account_id", ""), loc.get("object_id", "")
        if kind == "mailbox":
            return self.snapshot_mailbox(account)
        if kind == "draft":
            return self.snapshot_draft(account, object_id)
        return self.snapshot_message(account, object_id, kind)

    @staticmethod
    def _verify_draft(args: dict[str, Any], after: EmailSnapshot) -> None:
        if (after.to, after.cc, after.bcc, after.subject, after.body_text) != (
            tuple(args["to"]), tuple(args["cc"]), tuple(args["bcc"]), args["subject"], args["body_text"]
        ):
            raise RuntimeError("The draft API readback did not match the approved preview.")

    def _rollback(self, rollback: tuple[str, Any], receipt: dict[str, Any]) -> bool:
        kind, values = rollback
        try:
            if kind == "draft":
                account, draft_id, revision = values
                self.client.delete_draft(account, draft_id, if_revision=revision)
                return True
            if kind == "rule":
                self.client.delete_rule(*values)
                return True
            before = values[0]
            revision = str(receipt.get("revision") or receipt.get("etag") or receipt.get("change_key") or "")
            if kind == "draft_restore":
                payload = {"to": list(before.to), "cc": list(before.cc), "bcc": list(before.bcc),
                           "subject": before.subject, "body_text": before.body_text}
                self.client.update_draft(before.account_id, before.object_id, payload, if_revision=revision)
                restored = self.snapshot_draft(before.account_id, before.object_id)
                self._verify_draft(payload, restored)
                return True
            self.client.set_categories(before.account_id, before.object_id, before.object_kind, before.categories, if_revision=revision)
            return self.snapshot_message(before.account_id, before.object_id, before.object_kind).categories == before.categories
        except Exception:
            return False


class CalendarAccountActionAdapter:
    """Execute reviewed event creation/rescheduling through a calendar API."""

    def __init__(self, client: CalendarApiClient) -> None:
        self.client = client
        self.provider = str(client.provider).lower()
        if self.provider not in {"google", "outlook"}:
            raise ValueError("The calendar API provider must be google or outlook.")
        self._results: dict[str, tuple[str, ActionExecutionResult]] = {}

    def capabilities(self) -> tuple[ActionCapability, ...]:
        return calendar_capabilities()

    def snapshot_calendar(self, account_id: str, calendar_id: str) -> CalendarSnapshot:
        return CalendarSnapshot.from_api(self.provider, account_id, calendar_id, dict(self.client.get_calendar(account_id, calendar_id)))

    def snapshot_event(self, account_id: str, calendar_id: str, event_id: str) -> CalendarSnapshot:
        return CalendarSnapshot.from_api(self.provider, account_id, calendar_id, dict(self.client.get_event(account_id, calendar_id, event_id)))

    def validate(self, plan: ActionPlan, snapshot: CalendarSnapshot) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if plan.app != "calendar" or plan.target.app != "calendar":
            issues.append(ValidationIssue("wrong_adapter", "This adapter can run only calendar plans."))
        if not plan.plan_id.strip() or not plan.requires_confirmation:
            issues.append(ValidationIssue("confirmation_policy", "Calendar changes require an identified, approval-gated plan."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(ValidationIssue("target_changed", "The calendar target changed after preview."))
        if plan.target.version != snapshot.revision:
            issues.append(ValidationIssue("target_stale", "The event or calendar revision changed after preview."))
        if len(plan.operations) != 1:
            issues.append(ValidationIssue("single_operation_required", "Review one calendar change at a time."))
            return tuple(issues)
        try:
            build_calendar_plan(snapshot, plan.operations[0].type, plan.operations[0].args)
        except ValueError as exc:
            issues.append(ValidationIssue("invalid_calendar_action", str(exc), plan.operations[0].id))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: CalendarSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_calendar_preview(plan, snapshot)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        key = str(idempotency_key or "").strip()
        _approval(plan, confirmed, key)
        cached = self._results.get(key)
        if cached:
            if cached[0] != plan.plan_id:
                raise ActionValidationError((ValidationIssue("idempotency_conflict", "This key belongs to another plan."),))
            return cached[1]
        before = self._snapshot_target(plan)
        issues = self.validate(plan, before)
        if issues:
            raise ActionValidationError(issues)
        operation = plan.operations[0]
        receipt: dict[str, Any] = {}
        created: tuple[dict[str, str], ...] = ()
        try:
            if operation.type == CREATE_EVENT:
                client_id = hashlib.sha256(key.encode()).hexdigest()[:26]
                receipt = dict(self.client.create_event(before.account_id, before.calendar_id, dict(operation.args),
                                                        idempotency_key=key, client_event_id=client_id))
                event_id = str(receipt.get("id") or client_id)
                created = ({"kind": "calendar_event", "name": event_id},)
                after = self.snapshot_event(before.account_id, before.calendar_id, event_id)
                self._verify_times(operation.args, after)
            else:
                receipt = dict(self.client.update_event(before.account_id, before.calendar_id, before.event_id,
                                                        dict(operation.args), if_revision=before.revision,
                                                        notify_attendees=False))
                after = self.snapshot_event(before.account_id, before.calendar_id, before.event_id)
                self._verify_times(operation.args, after)
        except Exception as exc:
            rollback_ok = self._rollback(operation.type, before, receipt, locals().get("after"))
            state = "rolled back" if rollback_ok else "rollback could not be verified"
            raise RuntimeError(f"Calendar API verification failed and the change was {state}: {exc}") from exc
        result = ActionExecutionResult(
            plan_id=plan.plan_id, status="applied", message="Applied and verified the reviewed calendar API action.",
            created=created,
            journal=({"kind": "calendar_account_api", "provider": self.provider, "operation": operation.type,
                      "before_revision": before.revision, "after_revision": after.revision},),
            verification=("Verified the reviewed event state through calendar API readback.",),
        )
        self._results[key] = (plan.plan_id, result)
        return result

    def _snapshot_target(self, plan: ActionPlan) -> CalendarSnapshot:
        loc = plan.target.locator
        if loc.get("provider") != self.provider:
            raise ActionValidationError((ValidationIssue("provider_changed", "The calendar provider changed."),))
        account, calendar, event = loc.get("account_id", ""), loc.get("calendar_id", ""), loc.get("event_id", "")
        return self.snapshot_event(account, calendar, event) if event else self.snapshot_calendar(account, calendar)

    @staticmethod
    def _verify_times(args: dict[str, Any], after: CalendarSnapshot) -> None:
        if (after.start, after.end, after.time_zone) != (args["start"], args["end"], args["time_zone"]):
            raise RuntimeError("The calendar API readback did not match the reviewed event time.")
        if "title" in args and after.title != args["title"]:
            raise RuntimeError("The created event title did not match the preview.")

    def _rollback(self, operation_type: str, before: CalendarSnapshot, receipt: dict[str, Any], after: Any) -> bool:
        try:
            revision = str(receipt.get("revision") or receipt.get("etag") or receipt.get("change_key") or "")
            if operation_type == CREATE_EVENT:
                event_id = str(receipt.get("id") or "")
                self.client.delete_event(before.account_id, before.calendar_id, event_id,
                                         if_revision=revision, notify_attendees=False)
                return True
            current_revision = getattr(after, "revision", "") or revision
            payload = {"start": before.start, "end": before.end, "time_zone": before.time_zone,
                       "notify_attendees": False}
            self.client.update_event(before.account_id, before.calendar_id, before.event_id, payload,
                                     if_revision=current_revision, notify_attendees=False)
            restored = self.snapshot_event(before.account_id, before.calendar_id, before.event_id)
            return (restored.start, restored.end, restored.time_zone) == (before.start, before.end, before.time_zone)
        except Exception:
            return False
