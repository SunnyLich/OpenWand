"""Shared Workspace journeys using its shipped addon and production HTTP backend.

The workspace backend is not replaced by a fixture. Only the external model's
tool decisions are controlled. Files, permissions, UI, sockets and storage are real.
"""

from __future__ import annotations

from pathlib import Path

from scripts.user_journeys.addon_scenarios import close, manager
from scripts.user_journeys.basic_scenarios import new, no_network, requests, test_basic_01_reopen
from scripts.user_journeys.extended_scenarios import completed_dialogs, dialogs, menu, tool_outcomes
from scripts.user_journeys.scenarios import journey as register_journey

WORKSPACE_PHASE = "workspace"
NAME = "Virtual Workspace (Experimental)"


def journey(title, *, features=(), requires=()):
    def register(function):
        dependencies = [] if function.__name__ == "test_workspace_01_install" else ["test_workspace_01_install", *requires]
        return register_journey(title, features=features, phase=WORKSPACE_PHASE, independent=True, requires=dependencies)(function)
    return register


def scope(app):
    path = Path(app.ui()["extended"]["workspace"]["scope"]).resolve()
    assert path.is_relative_to(app.state.resolve()), "Shared Workspace escaped disposable state"
    return path


@journey("Install and approve the shipped Shared Workspace addon", features=("F361", "F368"))
def test_workspace_01_install(app):
    # Choose the real repository addon in the folder picker. Its production
    # controller and authenticated local server will run in the addon host.
    test_basic_01_reopen(app)
    folder = Path(__file__).resolve().parents[2] / "addons/virtual_workspace"
    manager(app)
    dialogs(app, {"kind": "file", "title": "Install Addon Folder", "value": str(folder)})
    app.ui("extended.addon_button", text="Install folder")
    completed_dialogs(app)
    app.wait(lambda s: any(NAME in row["labels"] for row in s["extended"].get("addons", [])), "the installed Shared Workspace addon")
    dialogs(app, {"kind": "button", "title": "Review Addon Access", "button": "Yes"})
    app.ui("extended.addon_button", name=NAME, text="Review access")
    completed_dialogs(app)
    app.wait(lambda s: any(NAME in row["labels"] and "Review access" not in row["buttons"] for row in s["extended"].get("addons", [])), "the approved workspace addon")
    close(app)


@journey("Ask to open Shared Workspace and connect its real local viewer", features=("F370",))
def test_workspace_02_open(app):
    # A model tool request must start the real workspace server and cause the
    # app's normal UI-request handler to show its connected native window.
    new(app)
    app.send("E2E_WORKSPACE_START")
    app.reply("E2E_WORKSPACE_START")
    app.wait(lambda s: bool(s["extended"].get("workspace", {}).get("scope"))
             and s["extended"]["workspace"]["start_enabled"] and s["extended"]["workspace"]["tree_ready"], "the connected Shared Workspace")
    assert scope(app).is_dir()
    assert any("virtual_workspace" in str(item) for item in app.request("E2E_WORKSPACE_START").get("tools", []))


@journey("Deny model file creation while the workspace addon setting is Off", features=("F368", "F370"), requires=("test_workspace_02_open",))
def test_workspace_03_blocked_model_write(app):
    # A running workspace must not imply permission for the model to write.
    new(app)
    app.send("E2E_WORKSPACE_DISABLED_WRITE")
    app.reply("E2E_WORKSPACE_DISABLED_WRITE")
    assert "Model file changes are disabled" in "\n".join(tool_outcomes(app, "E2E_WORKSPACE_DISABLED_WRITE"))
    assert not (scope(app) / "must-not-exist.txt").exists()


@journey("Create a workspace folder and text document from its file explorer", requires=("test_workspace_02_open",))
def test_workspace_04_create_entries(app):
    # Use the actual explorer context menu and name dialogs; the production
    # server must create the files and refresh the visible tree.
    dialogs(app, menu("New folder"), {"kind": "input", "title": "Create folder", "value": "journey-notes"})
    app.ui("extended.workspace_menu", path="")
    completed_dialogs(app)
    app.wait(lambda s: "journey-notes" in s["extended"]["workspace"]["entries"], "the created workspace folder")
    dialogs(app, menu("New text document"), {"kind": "input", "title": "Create text document", "value": "first.txt"})
    app.ui("extended.workspace_menu", path="journey-notes")
    completed_dialogs(app)
    app.wait(lambda s: "journey-notes/first.txt" in s["extended"]["workspace"]["entries"], "the created workspace file")
    assert (scope(app) / "journey-notes/first.txt").is_file()


@journey("Open, edit and save a document inside Shared Workspace", requires=("test_workspace_04_create_entries",))
def test_workspace_05_edit_document(app):
    # Saving uses the real authenticated workspace endpoint, then reads the
    # resulting file independently from disk and reopens it in the editor.
    app.ui("extended.workspace_open", path="journey-notes/first.txt")
    app.wait(lambda s: s["extended"]["workspace"]["selected"] == "journey-notes/first.txt"
             and s["extended"]["workspace"]["editor_visible"] and "first.txt" in s["extended"]["workspace"]["editor_title"], "the opened text document")
    app.ui("extended.workspace_edit", text="E2E_USER_WORKSPACE_EDIT\nsecond line")
    app.wait(lambda s: s["extended"]["workspace"]["save_enabled"], "workspace Save to become enabled")
    app.ui("extended.workspace_save")
    app.wait(lambda s: not s["extended"]["workspace"]["save_enabled"], "the document save to finish")
    assert (scope(app) / "journey-notes/first.txt").read_text(encoding="utf-8") == "E2E_USER_WORKSPACE_EDIT\nsecond line"


@journey("Rename a workspace file with F2 and retain its saved contents", requires=("test_workspace_05_edit_document",))
def test_workspace_06_rename(app):
    # The real F2 shortcut must rename the actual file, not just the tree label.
    dialogs(app, {"kind": "input", "title": "Rename", "value": "renamed.txt"})
    app.ui("extended.workspace_key", path="journey-notes/first.txt", key="F2")
    completed_dialogs(app)
    app.wait(lambda s: "journey-notes/renamed.txt" in s["extended"]["workspace"]["entries"], "the renamed workspace file")
    assert not (scope(app) / "journey-notes/first.txt").exists()
    assert "E2E_USER_WORKSPACE_EDIT" in (scope(app) / "journey-notes/renamed.txt").read_text(encoding="utf-8")


@journey("Cancel deleting a workspace file and preserve it", requires=("test_workspace_06_rename",))
def test_workspace_07_cancel_delete(app):
    # No in the actual trash confirmation must leave the user's file intact.
    dialogs(app, {"kind": "button", "title": "Move to workspace trash?", "button": "No"})
    app.ui("extended.workspace_key", path="journey-notes/renamed.txt", key="Delete")
    completed_dialogs(app)
    assert (scope(app) / "journey-notes/renamed.txt").is_file()


@journey("Confirm workspace deletion and retain a recoverable trash copy", requires=("test_workspace_07_cancel_delete",))
def test_workspace_08_confirm_delete(app):
    # Yes must remove the live file but preserve its content in workspace trash.
    root = scope(app)
    dialogs(app, {"kind": "button", "title": "Move to workspace trash?", "button": "Yes"})
    app.ui("extended.workspace_key", path="journey-notes/renamed.txt", key="Delete")
    completed_dialogs(app)
    app.wait(lambda s: "journey-notes/renamed.txt" not in s["extended"]["workspace"]["entries"], "the deleted file to leave the tree")
    assert not (root / "journey-notes/renamed.txt").exists()
    copies = list((root.parent / "user-trash").glob("*-renamed.txt"))
    assert copies and "E2E_USER_WORKSPACE_EDIT" in copies[-1].read_text(encoding="utf-8")


@journey("Reject an empty Shared Workspace task without starting a model request", requires=("test_workspace_02_open",))
def test_workspace_09_empty_task(app):
    # Start task with an empty composer must explain what is missing, not launch
    # an empty background agent task or contact the provider.
    before = len(requests(app))
    app.ui("extended.workspace_start_task")
    assert "Describe what OpenWand should do first" in app.ui()["extended"]["workspace"]["notice"]
    no_network(app, before)


@journey("Close and reopen the Shared Workspace viewer without losing the session", requires=("test_workspace_04_create_entries",))
def test_workspace_10_reopen(app):
    # Reopening through a real model tool must reconnect to the same production
    # session and retain the folder created by the user.
    root = scope(app)
    app.ui("extended.workspace_close")
    new(app)
    app.send("E2E_WORKSPACE_START_REOPEN")
    app.reply("E2E_WORKSPACE_START_REOPEN")
    app.wait(lambda s: bool(s["extended"].get("workspace", {}).get("scope")), "the reopened workspace viewer")
    assert scope(app) == root
    assert "journey-notes" in app.ui()["extended"]["workspace"]["entries"]


@journey("Stop the workspace service, disable its addon and return to Chat", features=("F362", "F144"), requires=("test_workspace_02_open",))
def test_workspace_99_complete(app):
    # Stop through a real tool call, then disable the installed addon with its
    # checkbox so later application journeys cannot depend on a live session.
    new(app)
    app.send("E2E_WORKSPACE_STOP")
    app.reply("E2E_WORKSPACE_STOP")
    assert tool_outcomes(app, "E2E_WORKSPACE_STOP")
    if "workspace" in app.ui()["extended"]:
        app.ui("extended.workspace_close")
    manager(app)
    app.ui("extended.addon_enabled", name=NAME, value=False)
    app.wait(lambda s: any(NAME in row["labels"] and row["enabled"] is False
                          and not any("virtual_workspace_start" in label for label in row["labels"])
                          for row in s["extended"].get("addons", [])), "the disabled workspace addon")
    close(app)
    new(app)
    app.send("E2E_WORKSPACE_STAGE_COMPLETE")
    app.reply("E2E_WORKSPACE_STAGE_COMPLETE")
