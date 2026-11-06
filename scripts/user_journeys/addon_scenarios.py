"""Install and use a disposable addon through the complete running application."""

from __future__ import annotations

import json
import os
import re
import zipfile

from scripts.user_journeys.basic_scenarios import new, no_network, requests, test_basic_01_reopen
from scripts.user_journeys.extended_scenarios import completed_dialogs, dialogs, tool_outcomes
from scripts.user_journeys.scenarios import journey as register_journey

ADDON_PHASE = "addons"
NAME = "Journey acceptance addon"
ID = "journey-acceptance"

MANIFEST = '''[addon]
id = "journey-acceptance"
name = "Journey acceptance addon"
version = "1.0.0"
author = "OpenWand acceptance fixture"
entry = "__init__.py"

[permissions]
query = "modify"
response = "modify"
tools = true
ui = ["settings", "tray"]
'''

SOURCE = '''import os
import sys
from core.addon_manager import addon_setting

def before_query(prompt, context):
    greeting = addon_setting("journey-acceptance", "greeting", "hello")
    print("E2E_ADDON_PID:" + str(os.getpid()), file=sys.stderr, flush=True)
    return prompt + "\\n[E2E_ADDON_CONTEXT:" + str(greeting) + "]", context

def transform_response_text(payload):
    return {"text": payload["text"] + "\\n```text\\nE2E_ADDON_RESPONSE\\n```"}

def get_tools():
    print("E2E_ADDON_PID:" + str(os.getpid()), file=sys.stderr, flush=True)
    def execute(inputs):
        return {"reply": "E2E_ADDON_TOOL_RESULT", "greeting": addon_setting("journey-acceptance", "greeting", "hello"), "pid": os.getpid(), "text": inputs["text"]}
    return [{"name": "journey_addon_echo", "description": "Return a controlled acceptance reply", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "executor": execute}]

def get_settings():
    return [
        {"key": "greeting", "label": "Greeting", "type": "text", "default": "hello"},
        {"key": "flag", "label": "Flag", "type": "bool", "default": "false"},
        {"key": "limit", "label": "Limit", "type": "number", "default": "2"},
        {"key": "mode", "label": "Mode", "type": "choice", "options": ["quiet", "verbose"], "default": "quiet"},
    ]

def get_tray_actions():
    return [{"label": "E2E addon action", "callback": lambda: {"message": "E2E_ADDON_TRAY_RESULT"}}]
'''


def journey(title, *, features=(), requires=()):
    """Only genuinely dependent addon stories block after an earlier failure."""
    def register(function):
        dependencies = [] if function.__name__ == "test_addon_01_open" else ["test_addon_01_open", *requires]
        return register_journey(title, features=features, phase=ADDON_PHASE, independent=True, requires=dependencies)(function)
    return register


def manager(app):
    app.ui("tray", label="Addon Manager")
    app.wait(lambda s: "addons" in s["extended"], "the real Addon Manager")


def card(app):
    return next(row for row in app.ui()["extended"]["addons"] if NAME in row["labels"])


def close(app):
    app.ui("extended.addon_button", text="Close")
    app.wait(lambda s: "addons" not in s["extended"], "Addon Manager to close")


def enabled(app, value):
    """Wait for the refreshed public tool listing, not just checkbox paint."""
    app.ui("extended.addon_enabled", name=NAME, value=value)
    app.wait(lambda s: any(NAME in row["labels"] and row["enabled"] is value
                          and any("journey_addon_echo" in label for label in row["labels"]) is value
                          for row in s["extended"].get("addons", [])), "the addon's refreshed enabled state")


def package(app):
    """Create only the external package a user will choose in the installer."""
    path = app.state / "journey-addon.openwand"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("addon.toml", MANIFEST)
        archive.writestr("__init__.py", SOURCE)
    return path


@journey("Open Addon Manager from the running app's tray", features=("F358",))
def test_addon_01_open(app):
    # Reconnect a copied debug profile through Settings, then open the actual
    # runtime-owned manager. The addon's own files are not seeded as installed.
    test_basic_01_reopen(app)
    manager(app)
    assert not any(NAME in row["labels"] for row in app.ui()["extended"]["addons"])
    close(app)


@journey("Cancel choosing an addon archive without installing anything", features=("F360",))
def test_addon_02_cancel_install(app):
    # The actual chooser's Cancel button must leave both the list and disk alone.
    manager(app)
    before = app.ui()["extended"]["addons"]
    dialogs(app, {"kind": "button", "title": "Install Addon Archive", "button": "Cancel"})
    app.ui("extended.addon_button", text="Install archive")
    completed_dialogs(app)
    assert app.ui()["extended"]["addons"] == before
    assert not (app.state / "addons" / ID).exists()
    close(app)


@journey("Install a chosen addon archive and show its pending access review", features=("F360", "F368"))
def test_addon_03_install_archive(app):
    # Choose the archive in a real file dialog; the real installer, brain and UI
    # must copy/discover the package and expose its Review access control.
    archive = package(app)
    manager(app)
    dialogs(app, {"kind": "file", "title": "Install Addon Archive", "value": str(archive)})
    app.ui("extended.addon_button", text="Install archive")
    completed_dialogs(app)
    app.wait(lambda s: any(NAME in row["labels"] for row in s["extended"].get("addons", [])), "the installed addon card")
    assert (app.state / "addons" / ID / "addon.toml").read_text(encoding="utf-8") == MANIFEST
    assert "Review access" in card(app)["buttons"]
    close(app)


@journey("Decline addon access and verify its hooks and tools do not run", features=("F368",), requires=("test_addon_03_install_archive",))
def test_addon_04_decline_access(app):
    # Choosing No must leave the package installed but its executable hooks and
    # model tool inactive on the next actual user prompt.
    manager(app)
    dialogs(app, {"kind": "button", "title": "Review Addon Access", "button": "No"})
    app.ui("extended.addon_button", name=NAME, text="Review access")
    completed_dialogs(app)
    assert "Review access" in card(app)["buttons"]
    close(app)
    new(app)
    app.send("E2E_ADDON_NOT_APPROVED")
    app.reply("E2E_ADDON_NOT_APPROVED")
    payload = json.dumps(app.request("E2E_ADDON_NOT_APPROVED"))
    assert "E2E_ADDON_CONTEXT" not in payload and "journey_addon_echo" not in payload


@journey("Approve an addon and use its response hook and model tool listing", features=("F367", "F368", "F370", "F371"), requires=("test_addon_03_install_archive",))
def test_addon_05_approve_access(app):
    # Approval must start the real addon host. A normal Chat request must include
    # its tool, and the displayed answer its response hook. The separate query-
    # hook journey must still fail if that integration is broken.
    manager(app)
    dialogs(app, {"kind": "button", "title": "Review Addon Access", "button": "Yes"})
    app.ui("extended.addon_button", name=NAME, text="Review access")
    completed_dialogs(app)
    app.wait(lambda s: any(NAME in row["labels"] and "Review access" not in row["buttons"] for row in s["extended"].get("addons", [])), "the approved loaded addon")
    close(app)
    new(app)
    app.send("E2E_ADDON_APPROVED")
    app.reply("E2E_ADDON_APPROVED")
    payload = json.dumps(app.request("E2E_ADDON_APPROVED"))
    assert "journey_addon_echo" in payload
    assert any("E2E_ADDON_RESPONSE" in text for text in app.ui()["chat"]["messages"])


@journey("Edit addon text, checkbox, number and choice settings and reopen them", features=("F363", "F364", "F375"), requires=("test_addon_05_approve_access",))
def test_addon_06_edit_settings(app):
    # Every field uses its actual edit/selection event. Reopening and a later
    # prompt must read the persisted values through the real addon host.
    manager(app)
    app.ui("extended.addon_button", name=NAME, text="Settings")
    app.wait(lambda s: ID in s["extended"]["addon_settings"], "the addon settings window")
    expected = {"Greeting": "E2E_SAVED_ADDON_GREETING", "Flag": True, "Limit": "7", "Mode": "verbose"}
    for label, value in expected.items():
        app.ui("extended.addon_setting", id=ID, label=label, value=value)
    app.ui("extended.addon_child_close", id=ID)
    app.ui("extended.addon_button", name=NAME, text="Settings")
    app.wait(lambda s: s["extended"]["addon_settings"].get(ID) == expected, "the persisted addon setting values")
    saved = app.state / "data" / "addon_data" / ID / "settings.json"
    app.wait(lambda _s: saved.exists() and json.loads(saved.read_text(encoding="utf-8")).get("settings") == {
        "greeting": "E2E_SAVED_ADDON_GREETING", "flag": "true", "limit": "7", "mode": "verbose",
    }, "all four addon settings persisted independently of the displayed controls")
    app.ui("extended.addon_child_close", id=ID)
    close(app)
    new(app)
    app.send("E2E_ADDON_TOOL_SAVED_SETTINGS")
    app.reply("E2E_ADDON_TOOL_SAVED_SETTINGS")
    assert "E2E_SAVED_ADDON_GREETING" in "\n".join(tool_outcomes(app, "E2E_ADDON_TOOL_SAVED_SETTINGS"))


@journey("Apply an approved addon's before-query hook to a Chat prompt", features=("F369",), requires=("test_addon_05_approve_access",))
def test_addon_06b_chat_query_hook(app):
    # Approval and a loaded host alone do not prove that Chat actually invokes
    # the query hook. Require its text in the independent outgoing request.
    new(app)
    app.send("E2E_ADDON_BEFORE_QUERY")
    app.reply("E2E_ADDON_BEFORE_QUERY")
    assert "E2E_ADDON_CONTEXT:" in json.dumps(app.request("E2E_ADDON_BEFORE_QUERY")), "The approved before_query hook did not contribute to the Chat request"


@journey("Call an installed addon's tool through a real model tool loop", features=("F370", "F367"), requires=("test_addon_05_approve_access",))
def test_addon_07_call_tool(app):
    # The HTTP model fixture asks for the tool, but only the production gateway
    # and separate addon process can execute it and supply the next tool result.
    new(app)
    app.send("E2E_ADDON_TOOL")
    app.reply("E2E_ADDON_TOOL")
    result = "\n".join(tool_outcomes(app, "E2E_ADDON_TOOL"))
    assert "E2E_ADDON_TOOL_RESULT" in result and "controlled payload" in result


@journey("Disable an addon and remove its effects from the next prompt", features=("F362", "F370"), requires=("test_addon_05_approve_access",))
def test_addon_08_disable(app):
    # A checkbox change must stop actual hooks/tools, not merely look unchecked.
    manager(app)
    enabled(app, False)
    close(app)
    new(app)
    app.send("E2E_ADDON_DISABLED")
    app.reply("E2E_ADDON_DISABLED")
    payload = json.dumps(app.request("E2E_ADDON_DISABLED"))
    assert "E2E_ADDON_CONTEXT" not in payload and "journey_addon_echo" not in payload
    assert not any("E2E_ADDON_RESPONSE" in text for text in app.ui()["chat"]["messages"])
    manager(app)
    assert card(app)["enabled"] is False
    close(app)


@journey("Re-enable an installed addon without losing its saved settings", features=("F362",), requires=("test_addon_08_disable",))
def test_addon_09_enable(app):
    # Reloading the host must preserve its configured greeting and tool listing.
    manager(app)
    enabled(app, True)
    app.ui("extended.addon_button", name=NAME, text="Settings")
    result = app.wait(lambda s: ID in s["extended"]["addon_settings"], "the re-enabled addon's settings")
    greeting = result["extended"]["addon_settings"][ID]["Greeting"]
    app.ui("extended.addon_child_close", id=ID)
    close(app)
    new(app)
    app.send("E2E_ADDON_TOOL_ENABLED_AGAIN")
    app.reply("E2E_ADDON_TOOL_ENABLED_AGAIN")
    assert greeting in "\n".join(tool_outcomes(app, "E2E_ADDON_TOOL_ENABLED_AGAIN"))


@journey("Open addon logs and verify its work came from a separate process", features=("F365", "F367"), requires=("test_addon_05_approve_access",))
def test_addon_10_logs(app):
    # Read the visible diagnostic log rather than claiming a host exists from a
    # status label. Its recorded PID must differ from every main app process.
    manager(app)
    enabled(app, True)
    app.ui("extended.addon_button", name=NAME, text="Logs")
    result = app.wait(lambda s: "E2E_ADDON_PID:" in s["extended"]["addon_logs"].get(ID, ""), "the real addon host log")
    ids = {int(value) for value in re.findall(r"E2E_ADDON_PID:(\d+)", result["extended"]["addon_logs"][ID])}
    assert ids and os.getpid() not in ids
    assert not ids.intersection(worker.pid for worker in app.supervisor.workers.values())
    app.ui("extended.addon_child_close", id=ID, kind="logs")
    close(app)


@journey("Run a contributed addon tray action without sending a model request", features=("F374",), requires=("test_addon_09_enable",))
def test_addon_11_tray_action(app):
    # The actual tray QAction must invoke the addon callback and show its result.
    label = next(label for label in app.ui()["extended"]["tray_labels"] if "E2E addon action" in label)
    before = len(requests(app))
    app.ui("tray", label=label)
    app.wait(lambda s: "E2E_ADDON_TRAY_RESULT" in s["extended"].get("bubble", {}).get("text", ""), "the addon tray result")
    no_network(app, before)


@journey("Install an addon from a chosen folder through the real directory picker", features=("F361",))
def test_addon_12_install_folder(app):
    # Directory installation is a separate user path from archive extraction.
    folder = app.state / "folder-addon-source"
    folder.mkdir()
    (folder / "addon.toml").write_text('[addon]\nid="journey-folder"\nname="Journey folder addon"\nentry="__init__.py"\n', encoding="utf-8")
    (folder / "__init__.py").write_text('# A deliberately inert, account-free test addon.\n', encoding="utf-8")
    manager(app)
    dialogs(app, {"kind": "file", "title": "Install Addon Folder", "value": str(folder)})
    app.ui("extended.addon_button", text="Install folder")
    completed_dialogs(app)
    app.wait(lambda s: any("Journey folder addon" in row["labels"] for row in s["extended"].get("addons", [])), "the folder-installed addon")
    assert (app.state / "addons/journey-folder/addon.toml").is_file()
    close(app)


@journey("Reject an addon archive with a path escaping its package", features=("F360", "F368"))
def test_addon_13_unsafe_archive(app):
    # An unsafe ZIP must produce a useful error and must not create a file above
    # its extraction root. The target is still inside disposable test state.
    archive = app.state / "unsafe-addon.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("addon.toml", MANIFEST.replace(ID, "journey-unsafe"))
        stream.writestr("../e2e-escaped-addon.txt", "MUST_NOT_BE_WRITTEN")
    manager(app)
    dialogs(app, {"kind": "file", "title": "Install Addon Archive", "value": str(archive)})
    app.ui("extended.addon_button", text="Install archive")
    completed_dialogs(app)
    try:
        app.wait(lambda s: "unsafe archive path" in s["extended"].get("bubble", {}).get("text", "").lower(), "a useful unsafe-archive error")
    finally:
        assert not (app.state / "addons/journey-unsafe").exists()
        assert not list(app.state.rglob("e2e-escaped-addon.txt"))
    close(app)


@journey("Finish addon journeys with contributed hooks disabled", features=("F362", "F144"), requires=("test_addon_03_install_archive",))
def test_addon_99_complete(app):
    # Return to an ordinary provider-only conversation for the later independent
    # workflows. Disabling through the UI must also stop the actual hooks.
    manager(app)
    enabled(app, False)
    close(app)
    new(app)
    app.send("E2E_ADDON_COMPLETE")
    app.reply("E2E_ADDON_COMPLETE")
    assert "E2E_ADDON_CONTEXT" not in json.dumps(app.request("E2E_ADDON_COMPLETE"))
