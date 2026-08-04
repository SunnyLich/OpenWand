"""Bounded normalized snapshots for mail and calendar account APIs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from core.actions.contracts import ActionTarget

_MAX_BODY = 50_000
_MAX_PREVIEW = 4_000
_MAX_RECIPIENTS = 50
_MAX_CATEGORIES = 100
_MAX_THREAD_MESSAGES = 20


def _tuple_text(value: Any, limit: int) -> tuple[str, ...]:
    rows = value if isinstance(value, (list, tuple)) else ()
    return tuple(str(item).strip()[:500] for item in rows[:limit] if str(item).strip())


@dataclass(frozen=True)
class EmailSnapshot:
    provider: str
    account_id: str
    account_display: str
    object_kind: str
    object_id: str
    revision: str
    subject: str = ""
    sender: str = ""
    to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    body_text: str = ""
    categories: tuple[str, ...] = ()
    available_categories: tuple[str, ...] = ()
    thread_messages: tuple[dict[str, str], ...] = ()
    supports_disabled_rules: bool = False

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="email",
            display_name=self.subject or self.account_display or self.account_id,
            locator={
                "provider": self.provider,
                "account_id": self.account_id,
                "object_kind": self.object_kind,
                "object_id": self.object_id,
            },
            version=self.revision,
        )

    @classmethod
    def from_api(cls, provider: str, account_id: str, value: dict[str, Any]) -> EmailSnapshot:
        kind = str(value.get("object_kind") or "mailbox").strip().lower()
        if kind not in {"mailbox", "draft", "message", "thread"}:
            raise ValueError("Unsupported email snapshot kind.")
        messages: list[dict[str, str]] = []
        for item in (value.get("thread_messages") or ())[:_MAX_THREAD_MESSAGES]:
            if not isinstance(item, dict):
                continue
            messages.append({
                "sender": str(item.get("sender") or "")[:500],
                "sent_at": str(item.get("sent_at") or "")[:100],
                "body_preview": str(item.get("body_preview") or "")[:_MAX_PREVIEW],
            })
        revision = str(value.get("revision") or value.get("etag") or value.get("change_key") or "").strip()
        if not revision:
            revision = cls.compute_revision(value)
        return cls(
            provider=str(provider).strip().lower(),
            account_id=str(account_id).strip(),
            account_display=str(value.get("account_display") or account_id)[:500],
            object_kind=kind,
            object_id=str(value.get("id") or "")[:500],
            revision=revision,
            subject=str(value.get("subject") or "")[:998],
            sender=str(value.get("sender") or "")[:500],
            to=_tuple_text(value.get("to"), _MAX_RECIPIENTS),
            cc=_tuple_text(value.get("cc"), _MAX_RECIPIENTS),
            bcc=_tuple_text(value.get("bcc"), _MAX_RECIPIENTS),
            body_text=str(value.get("body_text") or "")[:_MAX_BODY],
            categories=_tuple_text(value.get("categories"), _MAX_CATEGORIES),
            available_categories=_tuple_text(value.get("available_categories"), _MAX_CATEGORIES),
            thread_messages=tuple(messages),
            supports_disabled_rules=bool(value.get("supports_disabled_rules")),
        )

    def model_context(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "account": self.account_display,
            "kind": self.object_kind,
            "subject": self.subject,
            "sender": self.sender,
            "to": list(self.to),
            "body_preview": self.body_text[:_MAX_PREVIEW],
            "categories": list(self.categories),
            "available_categories": list(self.available_categories),
            "thread_messages": list(self.thread_messages),
            "supports_disabled_rules": self.supports_disabled_rules,
        }

    @staticmethod
    def compute_revision(value: dict[str, Any]) -> str:
        bounded = {
            key: value.get(key)
            for key in ("id", "object_kind", "subject", "sender", "to", "cc", "bcc", "body_text", "categories")
        }
        return hashlib.sha256(
            json.dumps(bounded, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class CalendarSnapshot:
    provider: str
    account_id: str
    calendar_id: str
    calendar_name: str
    event_id: str
    revision: str
    title: str = ""
    start: str = ""
    end: str = ""
    time_zone: str = ""
    location: str = ""
    description: str = ""
    attendees: tuple[str, ...] = ()
    organizer: str = ""

    @property
    def object_kind(self) -> str:
        return "event" if self.event_id else "calendar"

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="calendar",
            display_name=self.title or self.calendar_name or self.calendar_id,
            locator={
                "provider": self.provider,
                "account_id": self.account_id,
                "calendar_id": self.calendar_id,
                "event_id": self.event_id,
            },
            version=self.revision,
        )

    @classmethod
    def from_api(
        cls,
        provider: str,
        account_id: str,
        calendar_id: str,
        value: dict[str, Any],
    ) -> CalendarSnapshot:
        revision = str(value.get("revision") or value.get("etag") or value.get("change_key") or "").strip()
        if not revision:
            revision = hashlib.sha256(
                json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        return cls(
            provider=str(provider).strip().lower(),
            account_id=str(account_id).strip(),
            calendar_id=str(calendar_id).strip(),
            calendar_name=str(value.get("calendar_name") or calendar_id)[:500],
            event_id=str(value.get("id") or "")[:500],
            revision=revision,
            title=str(value.get("title") or value.get("subject") or "")[:300],
            start=str(value.get("start") or "")[:100],
            end=str(value.get("end") or "")[:100],
            time_zone=str(value.get("time_zone") or "")[:100],
            location=str(value.get("location") or "")[:500],
            description=str(value.get("description") or "")[:10_000],
            attendees=_tuple_text(value.get("attendees"), _MAX_RECIPIENTS),
            organizer=str(value.get("organizer") or "")[:500],
        )

    def model_context(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "calendar": self.calendar_name,
            "event_id": self.event_id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "time_zone": self.time_zone,
            "location": self.location,
            "attendees": list(self.attendees),
        }
