"""Tests for the preview-first VS Code saved-file action."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.actions.adapters.vscode import (
    VSCodeActionAdapter,
    VSCodeSelectionReader,
    action_plan_from_dict,
    build_replace_file_plan,
    build_replace_selection_plan,
    code_editor_name,
    is_code_editor_app,
    is_vscode_app,
    render_vscode_untitled_preview,
)
from core.actions.errors import ActionValidationError
from runtime.workers import native_host
from ui.addon_presentations import sanitize_presentation_html


def _active_app(path: Path) -> dict:
    return {
        "name": f"{path.name} - demo - Visual Studio Code",
        "process_name": "Code.exe",
        "pid": 42,
        "window_id": 777,
        "document_path": str(path),
    }


def test_vscode_app_recognizes_code_and_supported_forks() -> None:
    assert is_vscode_app({"process_name": "Code.exe", "name": "main.py"})
    assert is_vscode_app({"process_name": "cursor", "name": "main.py - Cursor"})
    assert is_vscode_app({"process_name": "windsurf", "name": "main.py - Windsurf"})
    assert not is_vscode_app({"process_name": "notepad.exe", "name": "main.py"})


@pytest.mark.parametrize(
    ("process_name", "title", "expected_name"),
    [
        ("pycharm64.exe", "main.py – demo – PyCharm", "PyCharm"),
        ("idea64.exe", "Main.java – demo – IntelliJ IDEA", "IntelliJ IDEA"),
        ("devenv.exe", "demo - Microsoft Visual Studio", "Visual Studio"),
        ("eclipse.exe", "main.py - demo - Eclipse IDE", "Eclipse"),
        ("sublime_text.exe", "main.py - Sublime Text", "Sublime Text"),
        ("nvim.exe", "main.py - Neovim", "Neovim"),
    ],
)
def test_saved_file_editor_family_is_recognized(
    process_name: str,
    title: str,
    expected_name: str,
) -> None:
    active = {"process_name": process_name, "name": title}
    assert is_code_editor_app(active)
    assert code_editor_name(active) == expected_name


def test_jetbrains_saved_selection_reuses_exact_verified_writer(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("value = old_value\n", encoding="utf-8")
    active = {
        "name": "main.py – demo – PyCharm",
        "process_name": "pycharm64.exe",
        "pid": 51,
        "window_id": 901,
        "document_path": str(path),
    }

    snapshot = VSCodeSelectionReader().inspect_selection(active, "old_value")
    plan = build_replace_selection_plan(snapshot, "new_value")
    preview = VSCodeActionAdapter().render_preview(plan, snapshot)
    result = VSCodeActionAdapter().execute(plan, confirmed=True, idempotency_key="pycharm-edit")

    assert snapshot.editor_name == "PyCharm"
    assert "PyCharm" in preview.html
    assert path.read_text(encoding="utf-8") == "value = new_value\n"
    assert result.status == "applied"


def test_trailing_jetbrains_dirty_marker_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("value = old_value\n", encoding="utf-8")
    active = {
        "name": "main.py* – demo – PyCharm",
        "process_name": "pycharm64.exe",
        "document_path": str(path),
    }

    with pytest.raises(ValueError, match="Save the active"):
        VSCodeSelectionReader().inspect_selection(active, "old_value")


def test_vscode_reader_requires_one_unique_saved_selection(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    reader = VSCodeSelectionReader()

    snapshot = reader.inspect_selection(_active_app(path), "    return a / b")

    assert snapshot.file_path == str(path.resolve())
    assert snapshot.text[snapshot.selection_start:snapshot.selection_end] == "    return a / b"
    assert snapshot.target.locator["path"] == str(path.resolve())
    assert snapshot.fingerprint

    path.write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more than once"):
        reader.inspect_selection(_active_app(path), "x = 1")

    dirty_app = _active_app(path)
    dirty_app["name"] = f"\u25cf {path.name} - demo - Visual Studio Code"
    with pytest.raises(ValueError, match="Save the active"):
        reader.inspect_selection(dirty_app, "x = 1")


def test_vscode_diff_preview_and_confirmed_apply_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    snapshot = VSCodeSelectionReader().inspect_selection(_active_app(path), "    return a / b")
    replacement = "    if b == 0:\n        raise ValueError(\"b must not be zero\")\n    return a / b"
    plan = build_replace_selection_plan(
        snapshot,
        replacement,
        summary="Avoid division by zero with an explicit error.",
    )
    adapter = VSCodeActionAdapter()
    assert action_plan_from_dict(plan.to_dict()).operations == plan.operations
    preview = adapter.render_preview(plan, snapshot)

    assert "main.py" in preview.html
    assert "+    if b == 0:" in preview.html
    assert "return a / b+    if b == 0:" not in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html

    with pytest.raises(ActionValidationError):
        adapter.execute(plan, confirmed=False, idempotency_key="edit-1")

    first = adapter.execute(plan, confirmed=True, idempotency_key="edit-1")
    second = adapter.execute(plan, confirmed=True, idempotency_key="edit-1")
    assert first == second
    assert replacement in path.read_text(encoding="utf-8")
    assert first.verification[-1] == "No editor focus or keyboard input was used."


def test_vscode_apply_refuses_a_stale_file(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("value = old_value\n", encoding="utf-8")
    snapshot = VSCodeSelectionReader().inspect_selection(_active_app(path), "old_value")
    plan = build_replace_selection_plan(snapshot, "new_value")
    path.write_text("# changed elsewhere\nvalue = old_value\n", encoding="utf-8")

    with pytest.raises(ActionValidationError):
        VSCodeActionAdapter().execute(plan, confirmed=True, idempotency_key="stale")

    assert path.read_text(encoding="utf-8").startswith("# changed elsewhere")


def test_native_vscode_snapshot_uses_the_saved_file_reader(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text("answer = 41\n", encoding="utf-8")
    monkeypatch.setattr(native_host, "_vscode_selection_reader", VSCodeSelectionReader())

    result = native_host.action_vscode_snapshot(
        _active_app(path),
        "answer = 41",
    )

    assert result["ok"] is True
    assert result["snapshot"]["file_path"] == str(path.resolve())
    assert result["snapshot"]["selected_text"] == "answer = 41"


def test_empty_saved_file_uses_a_confirmed_focusless_action(tmp_path: Path) -> None:
    path = tmp_path / "new_file.py"
    path.write_text("", encoding="utf-8")
    snapshot = VSCodeSelectionReader().inspect_empty_file(_active_app(path))
    plan = build_replace_file_plan(snapshot, 'print("Hello from Wisp")')
    adapter = VSCodeActionAdapter()
    preview = adapter.render_preview(plan, snapshot)
    assert '+print("Hello from Wisp")' in preview.html

    with pytest.raises(ActionValidationError):
        adapter.execute(plan, confirmed=False, idempotency_key="buffer")
    result = adapter.execute(plan, confirmed=True, idempotency_key="buffer")

    assert path.read_text(encoding="utf-8") == 'print("Hello from Wisp")'
    assert result.message == "Updated new_file.py; VS Code will reload the saved file change."
    assert result.verification[-1] == "No editor focus or keyboard input was used."


def test_native_vscode_snapshot_refuses_an_unsaved_empty_tab(monkeypatch) -> None:
    reader = VSCodeSelectionReader()
    monkeypatch.setattr(reader, "_resolve_path", lambda _active_app: "")
    monkeypatch.setattr(native_host, "_vscode_selection_reader", reader)

    result = native_host.action_vscode_snapshot(
        {"name": "Untitled-1 - Visual Studio Code", "process_name": "Code.exe"},
        "",
    )

    assert result["ok"] is False
    assert "Save it once" in result["error"]


def test_untitled_preview_is_safe_and_contains_exact_proposed_text() -> None:
    preview = render_vscode_untitled_preview(
        'print("hello")',
        selected_text="",
        display_name="Untitled-1 - Visual Studio Code",
        summary="Create a tiny example.",
    )

    assert preview.title == "Apply code to Untitled tab"
    assert '+print("hello")' in preview.html
    assert "Insertion point" in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html


def test_native_untitled_apply_requires_preview_and_uses_official_api(monkeypatch) -> None:
    class Bridge:
        def apply_text(self, text: str) -> dict:
            return {"ok": True, "method": "vscode-extension-api", "text": text}

    monkeypatch.setattr(native_host, "_vscode_extension_api_adapter", Bridge())

    refused = native_host.action_vscode_live_apply(text="print('no')", confirmed=False)
    applied = native_host.action_vscode_live_apply(text="print('yes')", confirmed=True)

    assert refused["ok"] is False
    assert refused["method"] == "vscode-extension-api"
    assert applied == {
        "ok": True,
        "method": "vscode-extension-api",
        "text": "print('yes')",
    }


def test_reader_resolves_a_new_loose_desktop_file(monkeypatch, tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    path = desktop / "new loose file.txt"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.setattr(
        "core.context_fetcher.get_active_document_path",
        lambda **_kwargs: "new loose file.txt",
    )

    snapshot = VSCodeSelectionReader().inspect_empty_file(
        {
            "name": "new loose file.txt - Visual Studio Code",
            "process_name": "Code.exe",
            "pid": 42,
            "window_id": 777,
        }
    )

    assert snapshot.file_path == str(path.resolve())
