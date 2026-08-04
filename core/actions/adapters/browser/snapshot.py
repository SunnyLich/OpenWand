"""Serializable browser form snapshot captured before model planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from core.actions.contracts import ActionTarget


@dataclass(frozen=True)
class BrowserField:
    field_id: str
    selector: str
    label: str
    kind: str
    value: str
    placeholder: str = ""
    required: bool = False
    options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BrowserField:
        return cls(
            field_id=str(value.get("field_id") or ""),
            selector=str(value.get("selector") or ""),
            label=str(value.get("label") or ""),
            kind=str(value.get("kind") or ""),
            value=str(value.get("value") or ""),
            placeholder=str(value.get("placeholder") or ""),
            required=bool(value.get("required")),
            options=tuple(str(item) for item in (value.get("options") or ())),
        )


@dataclass(frozen=True)
class BrowserFormSnapshot:
    title: str
    url: str
    target_id: str
    fields: tuple[BrowserField, ...]
    fingerprint: str

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="browser",
            display_name=self.title or self.url,
            locator={"target_id": self.target_id, "url": self.url},
            version=self.fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "target_id": self.target_id,
            "fields": [field.to_dict() for field in self.fields],
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BrowserFormSnapshot:
        fields = tuple(
            BrowserField.from_dict(item)
            for item in (value.get("fields") or ())
            if isinstance(item, dict)
        )
        fingerprint = str(value.get("fingerprint") or "")
        snapshot = cls(
            title=str(value.get("title") or ""),
            url=str(value.get("url") or ""),
            target_id=str(value.get("target_id") or ""),
            fields=fields,
            fingerprint=fingerprint or cls.compute_fingerprint(str(value.get("url") or ""), fields),
        )
        return snapshot

    def model_context(self) -> dict[str, Any]:
        return {
            "page": {"title": self.title, "url": self.url},
            "fields": [
                {
                    "field_id": field.field_id,
                    "label": field.label,
                    "kind": field.kind,
                    "current_value": field.value,
                    "placeholder": field.placeholder,
                    "required": field.required,
                    "options": list(field.options),
                }
                for field in self.fields
            ],
        }

    @staticmethod
    def compute_fingerprint(url: str, fields: tuple[BrowserField, ...]) -> str:
        payload = {
            "url": url,
            "fields": [
                {
                    "field_id": field.field_id,
                    "selector": field.selector,
                    "kind": field.kind,
                    "value": field.value,
                    "options": list(field.options),
                }
                for field in fields
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
