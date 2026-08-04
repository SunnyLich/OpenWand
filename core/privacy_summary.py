"""Secret-free, structured summaries of existing privacy reports.

The privacy engine's reports contain useful structured metadata, but their
``preview`` values intentionally retain small pieces of the detected value and
some ``source`` strings contain user-controlled filenames.  Those fields must
not be copied into persistent agent logs or Workspace Activity.

This module only emits fixed labels and reasons selected from allowlists.  It
never includes previews, replacements, session identifiers, scrubbed request
text, filenames, or unknown report values in its output.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_CATEGORY_DETAILS: dict[str, tuple[str, str]] = {
    "person": ("Personal name", "Hidden because it may identify a person."),
    "email": ("Email address", "Hidden because it looks like an email address."),
    "phone": ("Phone number", "Hidden because it looks like a phone number."),
    "url": ("Web address", "Hidden because it may contain private browsing information."),
    "address": ("Street address", "Hidden because it may identify a physical location."),
    "date": ("Private date", "Hidden because it may be personally identifying."),
    "account_number": ("Account identifier", "Hidden because it looks like an account number."),
    "passport": ("Passport number", "Hidden because it looks like a passport number."),
    "drivers_license": (
        "Driver's license number",
        "Hidden because it looks like a driver's license number.",
    ),
    "card_number": ("Payment card number", "Hidden because it looks like a payment card number."),
    "ssn": ("Social security number", "Hidden because it looks like a social security number."),
    "iban": ("Bank account identifier", "Hidden because it looks like a bank account identifier."),
    "api_key": ("API key", "Hidden because it looks like an API key."),
    "bearer_token": ("Access token", "Hidden because it looks like a sign-in or access token."),
    "credential": ("Password or credential", "Hidden because it looks like a password or credential."),
    "private_key": ("Private cryptographic key", "Hidden because it looks like a private key."),
    "url_credential": (
        "Credential in a web address",
        "Hidden because a web address contains a credential.",
    ),
    "secret": ("Secret", "Hidden because it was identified as secret information."),
    "custom": ("Custom private pattern", "Hidden because it matched a private pattern you configured."),
    "sensitive": ("Sensitive data", "Hidden because it may contain private information."),
}

_SOURCE_LABELS: dict[str, str] = {
    "prompt": "Task instructions",
    "agent_prompt": "Agent request",
    "addon_prompt": "Addon request",
    "selection": "Selected text",
    "clipboard": "Clipboard",
    "active_document": "Active document",
    "ambient": "Screen or app context",
    "buffered_context": "Saved context",
    "preview": "Local preview",
    "context": "Additional context",
}

_DECISIONS = {"redacted", "full", "cancel"}
_MAX_ITEMS = 500
_MAX_COUNT = 1_000_000


def _category_key(value: object) -> str:
    if not isinstance(value, str):
        return "sensitive"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in _CATEGORY_DETAILS else "sensitive"


def _source_key(value: object) -> str:
    if not isinstance(value, str):
        return "context"
    normalized = value.strip().lower()
    if normalized in _SOURCE_LABELS:
        return normalized
    # Query reports use document:<filename> and dropped:<filename>.  Keep the
    # source type but never retain the user-controlled filename.
    if normalized.startswith("document:"):
        return "document"
    if normalized.startswith("dropped:"):
        return "dropped"
    if normalized in {"document", "dropped"}:
        return normalized
    return "context"


def _source_label(key: str) -> str:
    if key == "document":
        return "Attached document"
    if key == "dropped":
        return "Dropped context"
    return _SOURCE_LABELS.get(key, _SOURCE_LABELS["context"])


def _safe_count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return min(_MAX_COUNT, max(0, value))
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 7:
        return min(_MAX_COUNT, int(value))
    return 0


def _safe_items(report: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_items = report.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
        return []
    items: list[dict[str, str]] = []
    for raw in raw_items[:_MAX_ITEMS]:
        if not isinstance(raw, Mapping):
            continue
        category = _category_key(raw.get("category"))
        source = _source_key(raw.get("source"))
        label, reason = _CATEGORY_DETAILS[category]
        items.append(
            {
                "id": f"private-item-{len(items) + 1}",
                "category": category,
                "label": label,
                "field": source,
                "field_label": _source_label(source),
                "reason": reason,
            }
        )
    return items


def _counts_from_items(items: Sequence[Mapping[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item[key]
        counts[value] = counts.get(value, 0) + 1
    return counts


def _safe_aggregate_counts(raw: object, *, kind: str) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    counts: dict[str, int] = {}
    for untrusted_key, untrusted_count in list(raw.items())[:_MAX_ITEMS]:
        key = _category_key(untrusted_key) if kind == "category" else _source_key(untrusted_key)
        count = _safe_count(untrusted_count)
        if count:
            counts[key] = min(_MAX_COUNT, counts.get(key, 0) + count)
    return counts


def _category_rows(counts: Mapping[str, int]) -> list[dict[str, object]]:
    rows = []
    for key in sorted(counts, key=lambda value: (_CATEGORY_DETAILS[value][0], value)):
        label, reason = _CATEGORY_DETAILS[key]
        rows.append({"key": key, "label": label, "count": counts[key], "reason": reason})
    return rows


def _field_rows(counts: Mapping[str, int]) -> list[dict[str, object]]:
    return [
        {"key": key, "label": _source_label(key), "count": counts[key]}
        for key in sorted(counts, key=lambda value: (_source_label(value), value))
    ]


def _disposition(report: Mapping[str, Any], count: int) -> tuple[str, bool]:
    raw_decision = report.get("decision")
    decision = raw_decision.strip().lower() if isinstance(raw_decision, str) else ""
    decision = decision if decision in _DECISIONS else ""
    if decision == "full":
        return "sent_full", False
    if decision == "cancel":
        return "cancelled", False
    if decision == "redacted":
        return "redacted", bool(count)
    if report.get("redacted") is False:
        return "detected", False
    return ("redacted", True) if count else ("none", False)


def _summary_text(count: int, disposition: str) -> str:
    noun = "private item" if count == 1 else "private items"
    if disposition == "redacted":
        return f"Privacy filter hid {count} {noun} from the model."
    if disposition == "sent_full":
        return f"Privacy filter detected {count} {noun}; full content was sent by user choice."
    if disposition == "cancelled":
        return f"Privacy filter detected {count} {noun}; the request was cancelled."
    if disposition == "detected":
        return f"Privacy filter detected {count} {noun}."
    return "Privacy filter did not detect private information."


def summarize_privacy_report(report: object) -> dict[str, object]:
    """Return a JSON-safe summary that cannot contain detected secret values.

    The output is suitable for persistent logs and Workspace Activity.  Its
    strings are all module-owned constants or count-only sentences; no unknown
    input string is reflected into the result.
    """
    source_report: Mapping[str, Any] = report if isinstance(report, Mapping) else {}
    items = _safe_items(source_report)
    if items:
        category_counts = _counts_from_items(items, "category")
        field_counts = _counts_from_items(items, "field")
    else:
        category_counts = _safe_aggregate_counts(source_report.get("categories"), kind="category")
        field_counts = _safe_aggregate_counts(source_report.get("sources"), kind="source")

    aggregate_count = max(
        len(items),
        sum(category_counts.values()),
        sum(field_counts.values()),
        _safe_count(source_report.get("count")),
    )
    count = min(_MAX_COUNT, aggregate_count)
    disposition, redacted = _disposition(source_report, count)
    advanced = source_report.get("ai_enabled") is True or source_report.get("privacy_mode") == "advanced"
    return {
        "schema_version": 1,
        "count": count,
        "redacted": redacted,
        "disposition": disposition,
        "summary": _summary_text(count, disposition),
        "detector": "advanced_local" if advanced else "built_in",
        "reviewed": source_report.get("reviewed") is True,
        "categories": _category_rows(category_counts),
        "fields": _field_rows(field_counts),
        "items": items,
    }
