from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from core.actions.adapters.vscode import (
    VSCodeExtensionAPIAdapter,
    VSCodeExtensionEndpoint,
    VSCodeSnapshot,
    build_format_document_plan,
    build_registered_task_plan,
    build_rename_symbol_plan,
    build_test_file_plan,
    render_vscode_extension_preview,
    validate_vscode_extension_plan,
    vscode_extension_capabilities,
)
from ui.addon_presentations import sanitize_presentation_html


def _snapshot(tmp_path: Path) -> VSCodeSnapshot:
    text = "def old_name():\n    return 1\n"
    path = tmp_path / "module.py"
    path.write_text(text, encoding="utf-8")
    selected = "old_name"
    start = text.index(selected)
    return VSCodeSnapshot(
        file_path=str(path),
        display_name="module.py",
        window_id=7,
        pid=8,
        text=text,
        selected_text=selected,
        selection_start=start,
        selection_end=start + len(selected),
        fingerprint=hashlib.sha256(text.encode()).hexdigest(),
        selection_fingerprint=hashlib.sha256(selected.encode()).hexdigest(),
    )


def test_extension_capabilities_are_separate_and_never_accept_shell_text() -> None:
    capabilities = {item.type: item for item in vscode_extension_capabilities()}
    assert set(capabilities) == {
        "vscode.format_document@1",
        "vscode.upsert_test_file@1",
        "vscode.run_registered_task@1",
        "vscode.rename_symbol@1",
    }
    task_schema = capabilities["vscode.run_registered_task@1"].input_schema
    assert "command" not in task_schema["properties"]


def test_extension_plans_render_exact_safe_previews(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    plans = (
        build_format_document_plan(
            snapshot,
            formatted_text="def old_name():\n    return 1\n\n",
            preview_token="formatter-preview-123",
            document_version=4,
        ),
        build_test_file_plan(
            snapshot,
            relative_path="tests/test_module.py",
            current_text="",
            proposed_text="def test_old_name():\n    assert old_name() == 1\n",
            expected_file_sha256="0" * 64,
            preview_token="test-preview-1234",
        ),
        build_registered_task_plan(snapshot, task_id="python:test", task_label="Python tests"),
        build_rename_symbol_plan(
            snapshot,
            new_name="new_name",
            affected_files=("module.py", "tests/test_module.py"),
            preview_token="rename-preview-123",
            document_version=4,
        ),
    )
    for plan in plans:
        assert not validate_vscode_extension_plan(plan, snapshot)
        preview = render_vscode_extension_preview(plan, snapshot)
        assert "action-canvas-preview" in preview.html
        assert "Nothing has changed" not in preview.html
        assert sanitize_presentation_html(preview.html) == preview.html


def test_extension_plans_refuse_stale_document_and_unsafe_inputs(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    plan = build_registered_task_plan(snapshot, task_id="python:test", task_label="Python tests")
    assert any(
        issue.code == "target_stale"
        for issue in validate_vscode_extension_plan(plan, replace(snapshot, fingerprint="changed"))
    )
    with pytest.raises(ValueError, match="workspace"):
        build_test_file_plan(
            snapshot,
            relative_path="../outside.py",
            current_text="",
            proposed_text="pass\n",
            expected_file_sha256="0" * 64,
            preview_token="test-preview-1234",
        )
    with pytest.raises(ValueError, match="identifier"):
        build_rename_symbol_plan(
            snapshot,
            new_name="bad name; rm",
            affected_files=("module.py",),
            preview_token="rename-preview-123",
            document_version=4,
        )


def test_extension_transport_requires_dry_run_tokens_verification_and_registered_task(monkeypatch) -> None:
    adapter = VSCodeExtensionAPIAdapter(VSCodeExtensionEndpoint(port=12345, token="x" * 32))
    requests = []

    def request(path, *, method="GET", payload=None):
        requests.append((path, method, payload))
        if path.endswith("/preview"):
            return {"ok": True, "previewToken": "preview-12345678", "applied": False}
        if path == "/tasks/run":
            return {"ok": True, "registeredTask": True, "focusUnchanged": True, "exitCode": 0}
        return {"ok": True, "verified": True, "focusUnchanged": True}

    monkeypatch.setattr(adapter, "_request", request)
    assert adapter.preview_format_document()["applied"] is False
    adapter.apply_format_document(
        preview_token="preview-12345678", expected_document_version=4, expected_document_sha256="a" * 64
    )
    adapter.run_registered_task(task_id="python:test")
    assert requests[-1][2] == {"taskId": "python:test"}
    assert all("command" not in (payload or {}) for _path, _method, payload in requests)

    monkeypatch.setattr(
        adapter,
        "_request",
        lambda *_args, **_kwargs: {"ok": False, "verified": False, "focusUnchanged": True, "rolledBack": False},
    )
    with pytest.raises(RuntimeError, match="rollback"):
        adapter.apply_rename_symbol(
            preview_token="preview-12345678",
            new_name="safe",
            expected_document_version=4,
            expected_document_sha256="a" * 64,
        )
