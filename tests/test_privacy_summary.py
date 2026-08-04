from __future__ import annotations

from core.privacy_summary import summarize_privacy_report


def test_summary_has_safe_categories_fields_reasons_and_counts() -> None:
    report = {
        "count": 3,
        "items": [
            {
                "source": "clipboard",
                "category": "api_key",
                "replacement": "[SECRET_1]",
                "preview": "sk-...7890",
            },
            {
                "source": "active_document",
                "category": "credential",
                "replacement": "[SECRET_2]",
                "preview": "pas...cret",
            },
            {
                "source": "selection",
                "category": "email",
                "replacement": "[EMAIL_1]",
                "preview": "p...@...com",
            },
        ],
        "categories": {"api_key": 1, "credential": 1, "email": 1},
        "sources": {"clipboard": 1, "active_document": 1, "selection": 1},
        "ai_enabled": True,
    }

    summary = summarize_privacy_report(report)

    assert summary["count"] == 3
    assert summary["redacted"] is True
    assert summary["disposition"] == "redacted"
    assert summary["detector"] == "advanced_local"
    assert summary["summary"] == "Privacy filter hid 3 private items from the model."
    assert summary["categories"] == [
        {
            "key": "api_key",
            "label": "API key",
            "count": 1,
            "reason": "Hidden because it looks like an API key.",
        },
        {
            "key": "email",
            "label": "Email address",
            "count": 1,
            "reason": "Hidden because it looks like an email address.",
        },
        {
            "key": "credential",
            "label": "Password or credential",
            "count": 1,
            "reason": "Hidden because it looks like a password or credential.",
        },
    ]
    assert summary["fields"] == [
        {"key": "active_document", "label": "Active document", "count": 1},
        {"key": "clipboard", "label": "Clipboard", "count": 1},
        {"key": "selection", "label": "Selected text", "count": 1},
    ]
    assert summary["items"][0] == {
        "id": "private-item-1",
        "category": "api_key",
        "label": "API key",
        "field": "clipboard",
        "field_label": "Clipboard",
        "reason": "Hidden because it looks like an API key.",
    }


def test_summary_wraps_real_redaction_report_without_its_preview() -> None:
    from core.privacy_redaction import redact_with_report

    raw_value = "password=supersecret"
    _redacted, report = redact_with_report(raw_value, source="prompt")

    assert report["items"][0]["preview"]
    summary = summarize_privacy_report(report)

    assert summary["count"] == 1
    assert summary["items"][0]["label"] == "Password or credential"
    assert raw_value not in repr(summary)
    assert report["items"][0]["preview"] not in repr(summary)


def test_summary_never_reflects_secret_values_or_user_controlled_names() -> None:
    canaries = (
        "raw-secret-value",
        "filename-contains-secret",
        "unknown-category-secret",
        "replacement-secret",
        "session-secret",
        "scrubbed-secret",
    )
    report = {
        "count": 1,
        "items": [
            {
                "source": "document:filename-contains-secret.txt",
                "category": "unknown-category-secret",
                "preview": "raw-secret-value",
                "replacement": "replacement-secret",
                "reason": "raw-secret-value",
                "original": "raw-secret-value",
            }
        ],
        "session_id": "session-secret",
        "scrubbed_preview": "scrubbed-secret",
    }

    summary = summarize_privacy_report(report)
    rendered = repr(summary)

    assert summary["items"][0]["category"] == "sensitive"
    assert summary["items"][0]["field"] == "document"
    assert summary["items"][0]["field_label"] == "Attached document"
    assert all(canary not in rendered for canary in canaries)


def test_summary_normalizes_aggregate_only_report_without_echoing_keys() -> None:
    report = {
        "count": 7,
        "categories": {"email": 2, "api_key": "3", "my-private-category-name": 2},
        "sources": {"clipboard": 3, "document:private-name.txt": 2, "private-field-name": 2},
    }

    summary = summarize_privacy_report(report)
    rendered = repr(summary)

    assert summary["count"] == 7
    assert summary["categories"] == [
        {
            "key": "api_key",
            "label": "API key",
            "count": 3,
            "reason": "Hidden because it looks like an API key.",
        },
        {
            "key": "email",
            "label": "Email address",
            "count": 2,
            "reason": "Hidden because it looks like an email address.",
        },
        {
            "key": "sensitive",
            "label": "Sensitive data",
            "count": 2,
            "reason": "Hidden because it may contain private information.",
        },
    ]
    assert "private-name" not in rendered
    assert "private-field-name" not in rendered
    assert "my-private-category-name" not in rendered


def test_summary_reports_review_decisions_without_claiming_redaction() -> None:
    full = summarize_privacy_report({"count": 2, "decision": "full", "reviewed": True})
    cancelled = summarize_privacy_report({"count": 1, "decision": "cancel", "reviewed": True})
    detected = summarize_privacy_report({"count": 1, "redacted": False})

    assert full["disposition"] == "sent_full"
    assert full["redacted"] is False
    assert full["summary"] == "Privacy filter detected 2 private items; full content was sent by user choice."
    assert full["reviewed"] is True
    assert cancelled["disposition"] == "cancelled"
    assert cancelled["redacted"] is False
    assert cancelled["summary"] == "Privacy filter detected 1 private item; the request was cancelled."
    assert detected["disposition"] == "detected"
    assert detected["redacted"] is False


def test_empty_and_malformed_reports_fail_closed_to_constant_output() -> None:
    empty = summarize_privacy_report(None)
    malformed = summarize_privacy_report(
        {
            "count": object(),
            "items": "secret text is not an item sequence",
            "categories": {"secret-key-name": object()},
            "sources": ["private source"],
            "decision": "secret decision",
            "privacy_mode": "secret mode",
        }
    )

    assert empty == malformed
    assert empty == {
        "schema_version": 1,
        "count": 0,
        "redacted": False,
        "disposition": "none",
        "summary": "Privacy filter did not detect private information.",
        "detector": "built_in",
        "reviewed": False,
        "categories": [],
        "fields": [],
        "items": [],
    }


def test_report_size_and_counts_are_bounded() -> None:
    items = [{"category": "email", "source": "clipboard"} for _ in range(700)]
    summary = summarize_privacy_report({"count": 99_999_999, "items": items})

    assert len(summary["items"]) == 500
    assert summary["count"] == 1_000_000
    assert summary["categories"][0]["count"] == 500
