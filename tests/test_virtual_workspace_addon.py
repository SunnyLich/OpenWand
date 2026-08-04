"""Tests for the optional Virtual Workspace addon."""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import pytest

from addons.virtual_workspace import get_tools
from addons.virtual_workspace.workspace import MAX_PREVIEW_BYTES, WorkspaceController, WorkspaceError


def _authorization(url: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(url)
    token = parse_qs(parsed.query)["token"][0]
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base, {"Authorization": f"Bearer {token}"}


def _json_request(url: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=2.0) as response:  # noqa: S310 - fixed loopback test server
        return json.loads(response.read().decode("utf-8"))


def _activity_summaries(window) -> list[str]:  # noqa: ANN001
    return [
        item.summary
        for activity_id in window._activity.ids
        if (item := window._activity.item(activity_id)) is not None
    ]


@pytest.fixture
def workspace(tmp_path: Path):
    controller = WorkspaceController()
    controller.configure(tmp_path / "addon-data")
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


def test_workspace_creates_only_new_entries_and_records_actions(workspace: WorkspaceController) -> None:
    workspace.create_folder("notes")
    workspace.write_text("notes/plan.txt", "one\ntwo\n")

    entries = workspace.list_entries()
    assert [(item["path"], item["kind"]) for item in entries] == [
        ("notes", "folder"),
        ("notes/plan.txt", "file"),
    ]
    assert entries[1]["bytes"] == len("one\ntwo\n")
    assert workspace.snapshot()["cursor"]["path"] == "notes/plan.txt"
    assert workspace.snapshot()["cursor"]["kind"] == "text"
    assert workspace.snapshot()["operations"][-1]["message"] == "Created file notes/plan.txt"

    with pytest.raises(WorkspaceError, match="overwrite"):
        workspace.write_text("notes/plan.txt", "replacement")


@pytest.mark.parametrize(
    "unsafe_path",
    ["../escape.txt", "/absolute.txt", "C:/host.txt", "notes/../../escape.txt", "a\x00b"],
)
def test_workspace_rejects_paths_outside_its_root(
    workspace: WorkspaceController,
    unsafe_path: str,
) -> None:
    with pytest.raises(WorkspaceError):
        workspace.write_text(unsafe_path, "blocked")


def test_take_control_blocks_model_mutations_until_resume(workspace: WorkspaceController) -> None:
    state = workspace.apply_viewer_control("take_control")
    assert state["paused"] is True
    assert state["control_owner"] == "user"
    with pytest.raises(WorkspaceError, match="you have control"):
        workspace.create_folder("blocked")

    state = workspace.apply_viewer_control("resume")
    assert state["paused"] is False
    workspace.create_folder("allowed")
    assert workspace.list_entries()[0]["path"] == "allowed"


def test_viewer_requires_token_and_exposes_no_remote_input(workspace: WorkspaceController) -> None:
    base, headers = _authorization(workspace.viewer_url)

    with pytest.raises(HTTPError) as denied:
        urlopen(f"{base}/api/state", timeout=2.0)  # noqa: S310 - fixed loopback test server
    assert denied.value.code == 401

    state = _json_request(f"{base}/api/state", headers)
    assert state["capabilities"]["preview_files"] is True
    assert state["capabilities"]["preview_max_bytes"] == MAX_PREVIEW_BYTES
    assert state["capabilities"]["remote_input"] is False
    assert state["capabilities"]["virtual_input"] is True
    assert state["capabilities"]["host_file_access"] is False
    assert "scope_folder" not in state
    assert "token" not in json.dumps(state).lower()

    scope = _json_request(f"{base}/api/task-scope", headers)
    assert Path(scope["scope_folder"]).is_dir()

    paused = _json_request(
        f"{base}/api/control",
        {**headers, "Content-Type": "application/json"},
        {"action": "take_control"},
    )
    assert paused["paused"] is True


def test_authenticated_preview_returns_bounded_image_and_pdf_payloads(
    workspace: WorkspaceController,
) -> None:
    scope = Path(workspace.task_scope()["scope_folder"])
    image = b"\x89PNG\r\n\x1a\n" + b"workspace-image"
    pdf = b"%PDF-1.7\nworkspace-pdf\n%%EOF\n"
    (scope / "result.png").write_bytes(image)
    (scope / "report.pdf").write_bytes(pdf)
    base, headers = _authorization(workspace.viewer_url)

    image_result = _json_request(
        f"{base}/api/preview?{urlencode({'path': 'result.png'})}",
        headers,
    )
    pdf_result = _json_request(
        f"{base}/api/preview?{urlencode({'path': 'report.pdf'})}",
        headers,
    )

    image_modified_ns = image_result.pop("modified_ns")
    assert image_modified_ns > 0
    assert image_result == {
        "ok": True,
        "path": "result.png",
        "name": "result.png",
        "mime_type": "image/png",
        "preview_kind": "image",
        "bytes": len(image),
        "encoding": "base64",
        "data_base64": base64.b64encode(image).decode("ascii"),
    }
    assert pdf_result["mime_type"] == "application/pdf"
    assert pdf_result["preview_kind"] == "pdf"
    assert base64.b64decode(pdf_result["data_base64"], validate=True) == pdf

    entries = {item["path"]: item for item in workspace.list_entries()}
    assert entries["result.png"]["preview_kind"] == "image"
    assert entries["report.pdf"]["preview_kind"] == "pdf"


def test_user_can_edit_shared_text_with_conflict_safe_save(workspace: WorkspaceController) -> None:
    workspace.write_text("shared.txt", "before\n")
    base, headers = _authorization(workspace.viewer_url)
    preview = _json_request(f"{base}/api/preview?path=shared.txt", headers)

    saved = _json_request(
        f"{base}/api/save",
        {**headers, "Content-Type": "application/json"},
        {
            "path": "shared.txt",
            "text": "user edit\n",
            "expected_modified_ns": preview["modified_ns"],
        },
    )

    assert saved["ok"] is True
    assert saved["modified_ns"] != preview["modified_ns"]
    assert Path(workspace.task_scope()["scope_folder"], "shared.txt").read_text(encoding="utf-8") == "user edit\n"
    with pytest.raises(HTTPError) as stale:
        _json_request(
            f"{base}/api/save",
            {**headers, "Content-Type": "application/json"},
            {
                "path": "shared.txt",
                "text": "stale overwrite\n",
                "expected_modified_ns": preview["modified_ns"],
            },
        )
    assert stale.value.code == 400
    assert Path(workspace.task_scope()["scope_folder"], "shared.txt").read_text(encoding="utf-8") == "user edit\n"


def test_authenticated_explorer_operations_are_real_and_delete_is_recoverable(
    workspace: WorkspaceController,
) -> None:
    base, headers = _authorization(workspace.viewer_url)
    request_headers = {**headers, "Content-Type": "application/json"}
    scope = Path(workspace.task_scope()["scope_folder"])

    created_folder = _json_request(
        f"{base}/api/files",
        request_headers,
        {"action": "create", "path": "", "name": "Documents", "kind": "folder"},
    )
    created_file = _json_request(
        f"{base}/api/files",
        request_headers,
        {
            "action": "create",
            "path": "Documents",
            "name": "New Text Document.txt",
            "kind": "file",
        },
    )
    renamed = _json_request(
        f"{base}/api/files",
        request_headers,
        {
            "action": "rename",
            "path": "Documents/New Text Document.txt",
            "name": "notes.txt",
        },
    )
    deleted = _json_request(
        f"{base}/api/files",
        request_headers,
        {"action": "delete", "path": "Documents/notes.txt"},
    )

    assert created_folder["path"] == "Documents"
    assert created_file["path"] == "Documents/New Text Document.txt"
    assert renamed["path"] == "Documents/notes.txt"
    assert deleted["recoverable"] is True
    assert not (scope / "Documents" / "notes.txt").exists()
    recovered = list((scope.parent / "user-trash").glob("*-notes.txt"))
    assert len(recovered) == 1
    assert recovered[0].read_bytes() == b""
    assert any(
        operation.get("message") == "You moved Documents/notes.txt to workspace trash"
        for operation in workspace.snapshot()["operations"]
    )


def test_snapshot_tracks_agent_created_edited_and_deleted_paths(workspace: WorkspaceController) -> None:
    scope = Path(workspace.task_scope()["scope_folder"])
    (scope / "edited.txt").write_text("before", encoding="utf-8")
    workspace.snapshot()
    workspace.apply_viewer_control("task_started")

    (scope / "created.txt").write_text("created", encoding="utf-8")
    (scope / "edited.txt").write_text("after", encoding="utf-8")
    first = workspace.snapshot()
    assert first["changes"]["created.txt"] == "created"
    assert first["changes"]["edited.txt"] == "edited"

    (scope / "edited.txt").unlink()
    second = workspace.snapshot()
    assert second["changes"]["edited.txt"] == "deleted"


def test_preview_endpoint_requires_token_and_rejects_unsafe_or_oversized_files(
    workspace: WorkspaceController,
) -> None:
    scope = Path(workspace.task_scope()["scope_folder"])
    (scope / "too-large.bin").write_bytes(b"")
    with (scope / "too-large.bin").open("r+b") as handle:
        handle.truncate(MAX_PREVIEW_BYTES + 1)
    base, headers = _authorization(workspace.viewer_url)

    with pytest.raises(HTTPError) as denied:
        urlopen(f"{base}/api/preview?path=too-large.bin", timeout=2.0)  # noqa: S310
    assert denied.value.code == 401

    for path in ("../outside.png", "too-large.bin"):
        request = Request(
            f"{base}/api/preview?{urlencode({'path': path})}",
            headers=headers,
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(request, timeout=2.0)  # noqa: S310 - fixed loopback test server
        assert rejected.value.code == 400


def test_preview_rejects_workspace_symlinks(workspace: WorkspaceController) -> None:
    scope = Path(workspace.task_scope()["scope_folder"])
    target = scope / "real.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    link = scope / "linked.png"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable for this test user")

    with pytest.raises(WorkspaceError, match="links"):
        workspace.read_preview("linked.png")


def test_authenticated_background_check_validates_without_running_code(
    workspace: WorkspaceController,
) -> None:
    scope = Path(workspace.task_scope()["scope_folder"])
    marker = scope / "must-not-run.txt"
    (scope / "safe.py").write_text(
        "from pathlib import Path\nPath('must-not-run.txt').write_text('bad')\n",
        encoding="utf-8",
    )
    base, headers = _authorization(workspace.viewer_url)

    result = _json_request(
        f"{base}/api/check",
        {**headers, "Content-Type": "application/json"},
        {"path": "safe.py"},
    )

    assert result["ok"] is True
    assert result["check"] == "python_syntax"
    assert "passed" in result["summary"]
    assert not marker.exists()


def test_activity_is_journaled_to_disk_instead_of_disappearing(
    workspace: WorkspaceController,
) -> None:
    base, headers = _authorization(workspace.viewer_url)
    result = _json_request(
        f"{base}/api/event",
        {**headers, "Content-Type": "application/json"},
        {"id": "ui-visible-progress", "kind": "agent", "message": "Preparing workspace files"},
    )
    workspace.create_folder("kept")

    journal = Path(workspace.task_scope()["scope_folder"]).parent / "activity.jsonl"
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    assert result == {"ok": True, "id": "ui-visible-progress"}
    assert any(item["id"] == "ui-visible-progress" for item in events)
    assert any(item["message"] == "Created folder kept" for item in events)


def test_workspace_renders_in_a_native_wisp_window(workspace: WorkspaceController) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton

    from ui.virtual_workspace_window import VirtualWorkspaceWindow

    workspace.create_folder("notes")
    workspace.write_text("notes/native.txt", "Native Wisp window")
    app = QApplication.instance() or QApplication([])
    started = []
    controls = []
    window = VirtualWorkspaceWindow(
        workspace.viewer_url,
        on_start_task=lambda objective, scope: started.append((objective, scope)),
        on_agent_control=controls.append,
    )
    try:
        window.show()
        deadline = time.monotonic() + 3.0
        while (not window._last_state or not window._scope_folder) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()

        assert window.windowTitle() == "Wisp Shared Workspace"
        assert window._last_state["entry_count"] == 2
        assert len(window._desktop.items_by_path) == 2
        assert window._desktop.items_by_path["notes/native.txt"].text(0) == "native.txt"
        assert not any(frame.objectName() == "header" for frame in window.findChildren(QFrame))
        assert window._activity_panel.isVisible()
        assert window._splitter.widget(1) is window._activity_panel
        assert not any(
            button.text() == "Pause & inspect"
            for button in window.findChildren(QPushButton)
        )
        assert not any(
            button.text() in {"Activity", "Hide activity"}
            for button in window.findChildren(QPushButton)
        )

        window._request_file("notes/native.txt")
        while (
            window._desktop._document.toPlainText() != "Native Wisp window"
            and time.monotonic() < deadline
        ):
            app.processEvents()
            time.sleep(0.01)
        assert window._desktop._document.toPlainText() == "Native Wisp window"
        app.processEvents()
        assert window._desktop.pointer.isVisible()
        assert window._desktop.pointer.mode == "text"

        window._task.setPlainText("Create a visual notes folder")
        window._start.click()
        app.processEvents()
        assert started == [("Create a visual notes folder", window._scope_folder)]
        assert window._task_running is True

        window._control("pause")
        assert controls == ["pause"]
        assert window._task_paused is False
        assert window._pause_requested is True
        assert window._pause.text() == "Pausing…"
        assert "current step will finish" in window._notice.text().lower()

        window.append_agent_event({"line": "agent run paused after turn; waiting for resume"})
        assert window._pause_requested is False
        assert window._task_paused is True
        assert window._pause.text() == "Resume"

        window._control("pause")
        assert controls == ["pause", "resume"]
        assert window._task_paused is False

        window._stop_task()
        assert controls == ["pause", "resume", "cancel"]
        assert window._task_running is False
        assert window._task_stopping is True
        assert window._pause.isHidden()
        assert window._cancel.isHidden()
        assert window._desktop._status.text() == "Task stopped"

        window.finish_agent_task({})
        assert window._task_stopping is False
        assert window._desktop._status.text() == "Task stopped"

        window.set_task_running(True)
        window.finish_agent_task({
            "final": "Agent stopped after reaching configured turn limit.",
            "run_dir": r"C:\Temp\wisp-run",
            "run_log_path": r"C:\Temp\wisp-run\run.log",
            "file_tool_successes": 4,
            "file_tool_failures": 0,
            "file_tool_results": [
                {"tool": "create_file", "ok": True, "message": "preview.md"},
                {"tool": "create_file", "ok": True, "message": "preview.html"},
            ],
        })
        assert window._desktop._status.text() == "Task failed"
        assert "turn limit" in window._notice.text().lower()
        failure_items = [
            item
            for item in window._activity_items.values()
            if item.property("activityStatus") == "failed"
        ]
        assert failure_items
        failure_item = failure_items[-1]
        assert failure_item.expanded is True
        assert "turn limit" in failure_item.summary.lower()
        assert "Successful file operations: 4" in failure_item.detail
        assert "create_file: preview.md" in failure_item.detail
        assert r"Full run log: C:\Temp\wisp-run\run.log" in failure_item.detail

        window.set_task_running(True)
        window.finish_agent_task({
            "final": "Agent stopped after reaching configured turn limit.",
            "model_errors": [
                "All query model routes failed. Tried chatgpt/gpt-5.5: Connection error."
            ],
            "file_tool_successes": 0,
            "run_log_path": r"C:\Temp\provider-failure\run.log",
        })
        provider_failure = list(window._activity_items.values())[-1]
        assert provider_failure.expanded is True
        assert "model connection" in provider_failure.summary.lower()
        assert "Connection error" in provider_failure.detail
        assert "connection error" in window._notice.text().lower()

        window.set_task_running(True)
        window.finish_agent_task({"final": "Looks complete.", "file_tool_successes": 0})
        assert window._desktop._status.text() == "Task failed"
        assert "no workspace files" in window._notice.text().lower()
    finally:
        window.close()
        app.processEvents()


def test_agent_activity_survives_workspace_refresh_and_waits_are_visible(
    workspace: WorkspaceController,
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.virtual_workspace_window import VirtualWorkspaceWindow

    app = QApplication.instance() or QApplication([])
    window = VirtualWorkspaceWindow(
        workspace.viewer_url,
        on_start_task=lambda _objective, _scope: None,
    )
    try:
        window.show()
        deadline = time.monotonic() + 3.0
        while (not window._last_state or not window._scope_folder) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        window.set_task_running(True)
        window._task_started_monotonic = time.monotonic() - 16
        window._last_agent_event_monotonic = window._task_started_monotonic
        window._task_tick()
        assert "task runner" in window._desktop._status.text().lower()

        window.append_agent_event({"line": "[12:00:00] inventory complete: 0 file(s) visible"})
        window._last_agent_event_monotonic = time.monotonic() - 10
        window._task_tick()
        app.processEvents()
        assert not window._desktop.pointer.isVisible()
        stable_pointer_position = window._desktop.pointer.pos()
        window._last_agent_event_monotonic = time.monotonic() - 11
        window._task_tick()
        app.processEvents()
        assert window._desktop.pointer.pos() == stable_pointer_position

        assert window._activity_panel.isVisible()
        assert window._desktop.isVisible()
        assert window._splitter.widget(1) is window._activity_panel
        window.resize(1_200, 800)
        app.processEvents()
        window._splitter.setSizes([650, 430])
        app.processEvents()
        assert window._splitter.sizes()[1] >= 400

        window.append_agent_event({"line": "requesting LLM tool response via configured model"})
        window.append_agent_event({"line": "model call still waiting after 5s via configured model"})
        window.append_agent_event({"line": "model call still waiting after 10s via configured model"})
        wait_rows = [text for text in _activity_summaries(window) if "Waiting for first model response" in text]
        assert len(wait_rows) == 1
        assert "10s" in wait_rows[0]

        window.append_agent_event({
            "line": "model call still waiting after 5s via configured model [agent=Worker 1]"
        })
        window.append_agent_event({
            "line": "model call still waiting after 7s via configured model [agent=Worker 2]"
        })
        worker_wait_rows = [
            text
            for text in _activity_summaries(window)
            if "Worker " in text and "Waiting for first model response" in text
        ]
        assert len(worker_wait_rows) == 2

        partial_reply_text = '{"thought":"Creating the requested preview'
        partial_reply = json.dumps({
            "workspace_progress": {
                "kind": "model_response",
                "agent": "Worker 1",
                "response_id": "turn-1-worker-1",
                "content": partial_reply_text,
                "chars": len(partial_reply_text),
                "complete": False,
            }
        })
        assert window.append_agent_trace({"entry": partial_reply})
        reply_item = next(
            item
            for item in window._activity_items.values()
            if item.property("activityKind") == "model reply"
        )
        assert reply_item.expanded is False
        assert reply_item.detail == partial_reply_text
        assert "reply streaming" in reply_item.summary.lower()
        reply_item.toggle_expanded()

        complete_reply_text = json.dumps({
            "thought": "Creating the requested preview files.",
            "tool_calls": [],
            "final": "Created all seven requested files.",
        })
        complete_reply = json.dumps({
            "workspace_progress": {
                "kind": "model_response",
                "agent": "Worker 1",
                "response_id": "turn-1-worker-1",
                "content": complete_reply_text,
                "chars": len(complete_reply_text),
                "complete": True,
            }
        })
        assert window.append_agent_trace({"entry": complete_reply})
        assert reply_item.expanded is True
        assert reply_item.detail == complete_reply_text
        assert "Created all seven requested files" in reply_item.summary
        assert reply_item.property("activityStatus") == "complete"

        privacy_event = json.dumps({
            "workspace_progress": {
                "kind": "privacy_redaction",
                "agent": "Worker 1",
                "summary": {
                    "count": 2,
                    "redacted": True,
                    "detector": "built_in",
                    "summary": "Privacy filter hid 2 private items from the model.",
                    "categories": [{
                        "label": "API key",
                        "count": 2,
                        "reason": "Hidden because it looks like an API key.",
                    }],
                    "fields": [{"label": "Agent request", "count": 2}],
                },
            }
        })
        assert window.append_agent_trace({"entry": privacy_event})
        privacy_item = next(
            item
            for item in window._activity_items.values()
            if item.property("activityKind") == "privacy"
        )
        assert privacy_item.expanded is False
        assert privacy_item.detail_label.isHidden()
        privacy_item.toggle_expanded()
        assert not privacy_item.detail_label.isHidden()
        assert "API key × 2" in privacy_item.detail
        assert "Agent request × 2" in privacy_item.detail

        first_draft = json.dumps({
            "workspace_progress": {
                "kind": "workspace_draft",
                "path": "live.md",
                "content": "# Live\n\nDraft",
                "chars": 13,
                "agent": "Worker 1",
            }
        })
        assert window.append_agent_trace({"entry": first_draft})
        assert "live draft" in window._desktop._editor_title.text()
        assert "Live" in window._desktop._document.toPlainText()
        second_draft = json.dumps({
            "workspace_progress": {
                "kind": "workspace_draft",
                "path": "live.md",
                "content": "# Live\n\nDraft growing",
                "chars": 21,
                "agent": "Worker 1",
            }
        })
        assert window.append_agent_trace({"entry": second_draft})
        draft_rows = [text for text in _activity_summaries(window) if "Drafting live.md" in text]
        assert len(draft_rows) == 1
        assert "21 characters" in draft_rows[0]

        second_worker_draft = json.dumps({
            "workspace_progress": {
                "kind": "workspace_draft",
                "path": "other.md",
                "content": "# Other worker",
                "chars": 14,
                "agent": "Worker 2",
            }
        })
        assert window.append_agent_trace({"entry": second_worker_draft})
        assert window._desktop._editor_title.text().startswith("live.md")
        worker_draft_rows = [
            text for text in _activity_summaries(window) if "Worker " in text and "Drafting" in text
        ]
        assert len(worker_draft_rows) == 2

        workspace.create_folder("visible")
        window.refresh()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            app.processEvents()
            texts = _activity_summaries(window)
            if any("Created folder visible" in text for text in texts):
                break
            time.sleep(0.01)

        texts = _activity_summaries(window)
        assert "drafting live.md" in window._desktop._status.text().lower()
        assert any("inventory complete" in text for text in texts)
        assert any("Created folder visible" in text for text in texts)
    finally:
        window.close()
        app.processEvents()


def test_native_workspace_is_editable_and_marks_agent_file_changes(
    workspace: WorkspaceController,
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.virtual_workspace_window import VirtualWorkspaceWindow
    from ui.workspace_file_tree import AGENT_CREATED_COLOR, AGENT_EDITED_COLOR

    scope = Path(workspace.task_scope()["scope_folder"])
    (scope / "existing.txt").write_text("before\n", encoding="utf-8")
    workspace.snapshot()
    workspace.apply_viewer_control("task_started")
    (scope / "folder").mkdir()
    (scope / "folder" / "created.txt").write_text("agent line\n", encoding="utf-8")
    (scope / "existing.txt").write_text("after\n", encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    window = VirtualWorkspaceWindow(workspace.viewer_url)
    try:
        window.show()
        deadline = time.monotonic() + 4.0
        while not window._last_state and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        created_item = window._desktop._icons.item_for_path("folder/created.txt")
        edited_item = window._desktop._icons.item_for_path("existing.txt")
        folder_item = window._desktop._icons.item_for_path("folder")
        assert created_item is not None and created_item.foreground(0).color() == AGENT_CREATED_COLOR
        assert edited_item is not None and edited_item.foreground(0).color() == AGENT_EDITED_COLOR
        assert folder_item is not None and folder_item.childCount() == 1

        window._request_file("existing.txt")
        deadline = time.monotonic() + 4.0
        while window._desktop._active_path != "existing.txt" and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert window._desktop._document.isReadOnly() is False
        assert window._desktop._document.extraSelections()

        window._desktop._document.setPlainText("user and agent cowork\n")
        assert window._desktop._save.isEnabled()
        window._desktop.save_user_changes()
        deadline = time.monotonic() + 4.0
        while window._desktop._save.isEnabled() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not window._desktop._save.isEnabled()
        assert (scope / "existing.txt").read_text(encoding="utf-8") == "user and agent cowork\n"

        window._desktop._document.setPlainText("my unsaved follow-up\n")
        (scope / "existing.txt").write_text("newer Wisp version\n", encoding="utf-8")
        window._request_file("existing.txt")
        deadline = time.monotonic() + 4.0
        while window._pending_file is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert window._desktop._document.toPlainText() == "my unsaved follow-up\n"
        assert window._desktop._save.isEnabled()
        assert "preserved" in window._desktop._status.text().lower()
    finally:
        window.close()
        app.processEvents()


def test_native_tree_operations_update_the_real_workspace_and_visible_tree(
    workspace: WorkspaceController,
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.virtual_workspace_window import VirtualWorkspaceWindow

    scope = Path(workspace.task_scope()["scope_folder"])
    app = QApplication.instance() or QApplication([])
    window = VirtualWorkspaceWindow(workspace.viewer_url)
    try:
        window.show()
        deadline = time.monotonic() + 4.0
        while not window._scope_folder and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        tree = window._desktop._icons
        tree.file_operation_requested.emit("create", "", "ui-created.txt", "file")
        deadline = time.monotonic() + 4.0
        while tree.item_for_path("ui-created.txt") is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert (scope / "ui-created.txt").is_file()
        assert tree.item_for_path("ui-created.txt") is not None

        tree.file_operation_requested.emit("rename", "ui-created.txt", "ui-renamed.txt", "")
        deadline = time.monotonic() + 4.0
        while tree.item_for_path("ui-renamed.txt") is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not (scope / "ui-created.txt").exists()
        assert (scope / "ui-renamed.txt").is_file()
        assert tree.item_for_path("ui-renamed.txt") is not None

        tree.file_operation_requested.emit("delete", "ui-renamed.txt", "", "")
        deadline = time.monotonic() + 4.0
        while tree.item_for_path("ui-renamed.txt") is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not (scope / "ui-renamed.txt").exists()
        assert tree.item_for_path("ui-renamed.txt") is None
        assert list((scope.parent / "user-trash").glob("*-ui-renamed.txt"))
    finally:
        window.close()
        app.processEvents()


def test_native_window_renders_rich_files_and_reports_background_checks(
    workspace: WorkspaceController,
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage, QPainter, QPdfWriter
    from PySide6.QtWidgets import QApplication

    from ui.virtual_workspace_window import VirtualWorkspaceWindow

    scope = Path(workspace.task_scope()["scope_folder"])
    (scope / "notes.md").write_text("# Visible heading\n\nRendered markdown", encoding="utf-8")
    (scope / "page.html").write_text("<h1>Embedded HTML</h1>", encoding="utf-8")
    (scope / "table.csv").write_text("name,value\nAda,10\n", encoding="utf-8")
    (scope / "valid.py").write_text("answer = 42\n", encoding="utf-8")
    image = QImage(24, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor("#7651c9"))
    assert image.save(str(scope / "image.png"))
    writer = QPdfWriter(str(scope / "report.pdf"))
    painter = QPainter(writer)
    painter.drawText(100, 100, "Wisp PDF")
    painter.end()

    app = QApplication.instance() or QApplication([])
    window = VirtualWorkspaceWindow(workspace.viewer_url)
    try:
        window.show()
        deadline = time.monotonic() + 4.0
        while not window._last_state and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        for path, expected in (
            ("notes.md", "markdown"),
            ("page.html", "html"),
            ("table.csv", "csv"),
            ("image.png", "image"),
            ("report.pdf", "pdf"),
        ):
            window._request_file(path)
            deadline = time.monotonic() + 4.0
            text_rich_kind = expected in {"markdown", "html", "csv"}
            while (
                (
                    window._desktop._preview.active_path != path
                    or window._desktop._preview.active_kind != ("text" if text_rich_kind else expected)
                )
                and time.monotonic() < deadline
            ):
                app.processEvents()
                time.sleep(0.01)
            if text_rich_kind:
                window._desktop._show_preview_mode()
                app.processEvents()
            assert window._desktop._preview.active_kind == expected

        window._request_file("valid.py")
        deadline = time.monotonic() + 5.0
        while (
            not any("python_syntax check passed" in text for text in _activity_summaries(window))
            and time.monotonic() < deadline
        ):
            app.processEvents()
            time.sleep(0.01)
        assert any("python_syntax check passed" in text for text in _activity_summaries(window))
    finally:
        window.close()
        app.processEvents()


def test_scoped_agent_file_changes_drive_collaborative_caret_and_typing(workspace: WorkspaceController) -> None:
    workspace.apply_viewer_control("task_started")
    scope = Path(workspace.task_scope()["scope_folder"])
    (scope / "agent-note.txt").write_text("Wisp typed this in its isolated editor.", encoding="utf-8")

    state = workspace.snapshot()

    assert state["cursor"]["path"] == "agent-note.txt"
    assert state["cursor"]["label"] == "Wisp agent"
    assert state["cursor"]["kind"] == "text"
    assert state["operations"][-1]["message"] == "Wisp created file agent-note.txt"
    assert workspace.read_text("agent-note.txt")["text"].startswith("Wisp typed")


def test_addon_tools_have_a_narrow_surface() -> None:
    tools = {item["name"]: item for item in get_tools()}
    assert set(tools) == {
        "virtual_workspace_start",
        "virtual_workspace_status",
        "virtual_workspace_list",
        "virtual_workspace_create_folder",
        "virtual_workspace_write_text",
        "virtual_workspace_stop",
    }
    all_names = " ".join(tools).lower()
    assert "delete" not in all_names
    assert "shell" not in all_names
    assert "keyboard" not in all_names
    assert "mouse" not in all_names
    assert tools["virtual_workspace_write_text"]["input_schema"]["additionalProperties"] is False
