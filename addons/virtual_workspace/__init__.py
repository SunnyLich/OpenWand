"""Wisp Virtual Workspace addon.

This is a clean-room Wisp addon with no external runtime dependencies.  Its
model tools are constrained to an addon-owned directory and its viewer is
local, authenticated, and explicitly opened by the user.
"""
from __future__ import annotations

import json
from typing import Any

from .workspace import WorkspaceController, WorkspaceError

ADDON_ID = "virtual-workspace"
_controller = WorkspaceController()
_TRUE = {"1", "true", "yes", "on"}


def _setting_bool(key: str, default: bool) -> bool:
    try:
        from core.addon_manager import addon_setting

        value = addon_setting(ADDON_ID, key, default)
    except Exception:
        value = default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE


def on_startup(app_context: Any) -> None:
    """Configure private storage; do not start a session or viewer automatically."""
    _controller.configure(app_context.data_dir)


def on_shutdown() -> None:
    """Stop the loopback viewer while preserving session files for audit."""
    _controller.stop()


def _open_viewer() -> dict[str, str]:
    _controller.start()
    return {"virtual_workspace_url": _controller.viewer_url}


def _pause() -> None:
    _controller.pause()


def _resume() -> None:
    _controller.resume()


def _stop() -> None:
    _controller.stop()


def get_tray_actions() -> list[dict[str, Any]]:
    """Expose explicit user actions; only Open reveals the secret viewer URL."""
    status = _controller.status()
    actions: list[dict[str, Any]] = [
        {"label": "Open Virtual Workspace", "callback": _open_viewer},
    ]
    if status["status"] == "running":
        if status["paused"]:
            actions.append({"label": "Resume Virtual Workspace", "callback": _resume})
        else:
            actions.append({"label": "Pause Virtual Workspace", "callback": _pause})
        actions.append({"label": "Stop Virtual Workspace", "callback": _stop})
    return actions


def _json_result(call: Any, *args: Any, **kwargs: Any) -> str:
    try:
        result = call(*args, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except WorkspaceError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _start(_inputs: dict[str, Any]) -> str:
    result = _controller.start()
    safe = {
        **result,
        "message": "The virtual workspace is ready. The user can view it from Wisp's tray menu.",
    }
    return json.dumps(safe, ensure_ascii=False)


def _status(_inputs: dict[str, Any]) -> str:
    return json.dumps(_controller.status(), ensure_ascii=False)


def _list(_inputs: dict[str, Any]) -> str:
    return json.dumps({"ok": True, "entries": _controller.list_entries()}, ensure_ascii=False)


def _create_folder(inputs: dict[str, Any]) -> str:
    if not _setting_bool("allow_model_file_changes", False):
        return json.dumps({
            "ok": False,
            "error": "Model file changes are disabled in the Virtual Workspace addon settings.",
        })
    return _json_result(_controller.create_folder, str(inputs.get("path") or ""))


def _write_text(inputs: dict[str, Any]) -> str:
    if not _setting_bool("allow_model_file_changes", False):
        return json.dumps({
            "ok": False,
            "error": "Model file changes are disabled in the Virtual Workspace addon settings.",
        })
    return _json_result(
        _controller.write_text,
        str(inputs.get("path") or ""),
        str(inputs.get("text") or ""),
    )


def _stop_tool(_inputs: dict[str, Any]) -> str:
    return _json_result(_controller.stop)


def get_tools() -> list[dict[str, Any]]:
    """Return a deliberately narrow workspace tool set with no arbitrary host paths."""
    path_properties: dict[str, Any] = {
        "path": {
            "type": "string",
            "description": "Relative path inside the active virtual workspace.",
        },
    }
    path_schema = {
        "type": "object",
        "properties": path_properties,
        "required": ["path"],
        "additionalProperties": False,
    }
    return [
        {
            "name": "virtual_workspace_start",
            "description": "Start Wisp's isolated addon workspace and its local activity viewer.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "executor": _start,
        },
        {
            "name": "virtual_workspace_status",
            "description": "Check workspace status, control owner, and entry count.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "executor": _status,
        },
        {
            "name": "virtual_workspace_list",
            "description": "List file and folder metadata in the isolated workspace.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "executor": _list,
        },
        {
            "name": "virtual_workspace_create_folder",
            "description": "Create one folder inside the isolated workspace; never touches host paths.",
            "input_schema": path_schema,
            "executor": _create_folder,
        },
        {
            "name": "virtual_workspace_write_text",
            "description": "Create a new UTF-8 text file in the workspace without overwriting files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    **path_properties,
                    "text": {"type": "string", "description": "UTF-8 text content, up to 256 KB."},
                },
                "required": ["path", "text"],
                "additionalProperties": False,
            },
            "executor": _write_text,
        },
        {
            "name": "virtual_workspace_stop",
            "description": "Stop the viewer and freeze the session while preserving its audit files.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "executor": _stop_tool,
        },
    ]
