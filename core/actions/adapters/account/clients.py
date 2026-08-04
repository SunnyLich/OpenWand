"""Injected normalized account-API client protocols; implementations must not click UIs."""

from __future__ import annotations

from typing import Any, Protocol


class MailApiClient(Protocol):
    provider: str
    supports_disabled_rules: bool

    def get_mailbox(self, account_id: str) -> dict[str, Any]: ...
    def get_draft(self, account_id: str, draft_id: str) -> dict[str, Any]: ...
    def get_message(self, account_id: str, object_id: str, object_kind: str) -> dict[str, Any]: ...
    def create_draft(self, account_id: str, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]: ...
    def update_draft(self, account_id: str, draft_id: str, payload: dict[str, Any], *, if_revision: str) -> dict[str, Any]: ...
    def delete_draft(self, account_id: str, draft_id: str, *, if_revision: str) -> None: ...
    def set_categories(
        self,
        account_id: str,
        object_id: str,
        object_kind: str,
        categories: tuple[str, ...],
        *,
        if_revision: str,
    ) -> dict[str, Any]: ...
    def create_disabled_rule(
        self,
        account_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def get_rule(self, account_id: str, rule_id: str) -> dict[str, Any]: ...
    def delete_rule(self, account_id: str, rule_id: str) -> None: ...


class CalendarApiClient(Protocol):
    provider: str

    def get_calendar(self, account_id: str, calendar_id: str) -> dict[str, Any]: ...
    def get_event(self, account_id: str, calendar_id: str, event_id: str) -> dict[str, Any]: ...
    def create_event(
        self,
        account_id: str,
        calendar_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        client_event_id: str,
    ) -> dict[str, Any]: ...
    def update_event(
        self,
        account_id: str,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        *,
        if_revision: str,
        notify_attendees: bool,
    ) -> dict[str, Any]: ...
    def delete_event(
        self,
        account_id: str,
        calendar_id: str,
        event_id: str,
        *,
        if_revision: str,
        notify_attendees: bool,
    ) -> None: ...
