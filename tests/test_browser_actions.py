"""Tests for preview-first managed-browser actions."""

from __future__ import annotations

import pytest

from core.actions.adapters.browser import (
    BrowserActionAdapter,
    BrowserDevToolsTarget,
    BrowserField,
    BrowserFormSnapshot,
    build_fill_form_plan,
    is_browser_app,
    parse_form_assignments,
)
from core.actions.errors import ActionValidationError
from ui.addon_presentations import sanitize_presentation_html


def snapshot(*, first_name: str = "") -> BrowserFormSnapshot:
    fields = (
        BrowserField("field_1", "#first-name", "First name", "text", first_name, "Jane", True),
        BrowserField("field_2", "#email", "Email", "email", "", "name@example.com", True),
        BrowserField("field_3", "#country", "Country", "select", "ca", options=("ca", "us", "tw")),
    )
    return BrowserFormSnapshot(
        title="OpenWand test form",
        url="https://example.test/form",
        target_id="target-1",
        fields=fields,
        fingerprint=BrowserFormSnapshot.compute_fingerprint("https://example.test/form", fields),
    )


def test_browser_detection_and_model_assignment_parser() -> None:
    assert is_browser_app({"process_name": "chrome.exe", "name": "Form - Google Chrome"})
    assert is_browser_app({"process_name": "msedge.exe", "name": "Form"})
    assert not is_browser_app({"process_name": "notepad.exe", "name": "Form"})
    assert parse_form_assignments(
        '```json\n{"assignments":[{"field_id":"field_1","value":"Sunny"}]}\n```'
    ) == [{"field_id": "field_1", "value": "Sunny"}]


def test_browser_form_plan_and_preview_are_exact_and_sanitized() -> None:
    current = snapshot()
    plan = build_fill_form_plan(
        current,
        [
            {"field_id": "field_1", "value": "Sunny"},
            {"field_id": "field_3", "value": "tw"},
        ],
        summary="Fill the requested contact details.",
    )
    preview = BrowserActionAdapter().render_preview(plan, current)

    assert "action-canvas-preview" in preview.html
    assert "Nothing has changed" not in preview.html
    assert plan.operations[0].args["selector"] == "#first-name"
    assert plan.operations[0].args["expected_value"] == ""
    assert "Sunny" in preview.html
    assert "Will not submit" not in preview.html
    assert "3 fields" not in preview.html
    assert "Google Chrome" in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_browser_plan_rejects_unknown_duplicate_and_invalid_select_values() -> None:
    current = snapshot()
    with pytest.raises(ValueError, match="invalid or duplicated"):
        build_fill_form_plan(current, [{"field_id": "missing", "value": "x"}])
    with pytest.raises(ValueError, match="invalid or duplicated"):
        build_fill_form_plan(
            current,
            [
                {"field_id": "field_1", "value": "A"},
                {"field_id": "field_1", "value": "B"},
            ],
        )
    with pytest.raises(ValueError, match="available options"):
        build_fill_form_plan(current, [{"field_id": "field_3", "value": "uk"}])


def test_browser_apply_rechecks_snapshot_and_reports_verified_result(monkeypatch) -> None:
    current = snapshot()
    plan = build_fill_form_plan(current, [{"field_id": "field_1", "value": "Sunny"}])
    adapter = BrowserActionAdapter(session_token="a" * 32)
    target = BrowserDevToolsTarget(9222, "target-1", current.title, current.url, "ws://127.0.0.1/devtools/page/1")
    monkeypatch.setattr(adapter, "discover", lambda **_kwargs: target)
    monkeypatch.setattr(adapter, "_inspect_target", lambda _target: current)
    monkeypatch.setattr(adapter, "_apply", lambda _target, _assignments: {"ok": True, "verified": 1})

    with pytest.raises(ActionValidationError, match="Review and Apply"):
        adapter.execute(plan, confirmed=False, idempotency_key="fill-1")
    result = adapter.execute(plan, confirmed=True, idempotency_key="fill-1")

    assert result.status == "applied"
    assert "without submitting" in result.message
    assert result.verification[-1] == "No submit button, physical keyboard, or physical mouse was used."


def test_browser_apply_refuses_stale_page(monkeypatch) -> None:
    current = snapshot()
    stale = snapshot(first_name="Changed by user")
    plan = build_fill_form_plan(current, [{"field_id": "field_1", "value": "Sunny"}])
    adapter = BrowserActionAdapter(session_token="a" * 32)
    target = BrowserDevToolsTarget(9222, "target-1", current.title, current.url, "ws://127.0.0.1/devtools/page/1")
    monkeypatch.setattr(adapter, "discover", lambda **_kwargs: target)
    monkeypatch.setattr(adapter, "_inspect_target", lambda _target: stale)

    with pytest.raises(ActionValidationError, match="changed after the preview"):
        adapter.execute(plan, confirmed=True, idempotency_key="fill-stale")
