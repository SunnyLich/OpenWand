from __future__ import annotations

import pytest

from core.rewrite_browser import BrowserRewriteSnapshot, build_browser_rewrite_plan
from runtime.supervisor.flows import FlowController


def _snapshot_value() -> dict:
    draft = BrowserRewriteSnapshot(
        title="Editor",
        url="https://example.test/editor",
        target_id="tab-1",
        kind="contenteditable",
        element_path=(1, 0),
        start=2,
        end=7,
        selected_text="rough",
        container_text="A rough sentence.",
        fingerprint="",
    )
    return {**draft.to_dict(), "fingerprint": draft.compute_fingerprint()}


def test_browser_rewrite_snapshot_is_fingerprint_bound() -> None:
    snapshot = BrowserRewriteSnapshot.from_dict(_snapshot_value())
    assert snapshot.selected_text == "rough"
    changed = _snapshot_value()
    changed["container_text"] = "A moved sentence."
    with pytest.raises(ValueError, match="invalid exact"):
        BrowserRewriteSnapshot.from_dict(changed)


def test_browser_rewrite_plan_serializes_exact_target() -> None:
    snapshot = BrowserRewriteSnapshot.from_dict(_snapshot_value())
    plan = build_browser_rewrite_plan(snapshot, "clear")
    assert plan.to_dict()["snapshot"]["target_id"] == "tab-1"
    assert plan.replacement_text == "clear"


def test_flow_builds_browser_exact_rewrite_plan() -> None:
    snapshot = BrowserRewriteSnapshot.from_dict(_snapshot_value())
    plan = FlowController._build_structured_rewrite_plan(
        {"kind": "browser_text_range", "snapshot": snapshot},
        "clear",
    )
    assert plan.snapshot is snapshot
    assert plan.replacement_text == "clear"
