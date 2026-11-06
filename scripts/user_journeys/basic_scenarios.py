"""Small, user-facing journeys, before the longer permission/tool workflows.

Every function describes one ordinary action and checks its visible result and,
when a prompt is sent, the request received by the independent HTTP provider.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scripts.user_journeys.extended_scenarios import completed_dialogs, dialogs, menu, open_picker
from scripts.user_journeys.scenarios import journey as register_journey

BASIC_PHASE = "basics"


def journey(title, *, features=(), phase=BASIC_PHASE):
    """Keep unrelated basic stories running; retain real prerequisites."""
    def register(function):
        dependencies = [] if function.__name__ == "test_basic_01_reopen" else ["test_basic_01_reopen"]
        if function.__name__ in {"test_basic_20_cancel_rewind", "test_basic_21_confirm_rewind"}:
            dependencies.append("test_basic_19_branch")
        return register_journey(title, features=features, phase=phase, independent=True, requires=dependencies)(function)
    return register


def requests(app):
    """Read the provider's receipt book, independently of OpenWand's UI."""
    return json.loads((Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json").read_text(encoding="utf-8"))


def active(app):
    """Read the selected conversation's saved identity and message count."""
    state = app.ui()["extended"]
    return state["conversations"][state["active_conversation"]]


def new(app):
    """Click the actual New chat button; this is separate from Ctrl+N."""
    app.chat()
    app.ui("extended.new_chat_button")
    app.wait(lambda s: not s["chat"]["messages"] and not s["chat"]["input"], "an empty new chat")


def no_network(app, before):
    """Give queued UI events time to run before checking a forbidden request."""
    time.sleep(0.25)
    app.ui()
    assert len(requests(app)) == before, "A non-send action unexpectedly contacted the provider"


def model_test(app, section, status_key, *, image=False):
    """Click a Settings test button and require its real authenticated probe."""
    app.settings("Model routing")
    before = len(requests(app))
    app.ui("extended.model_test", section=section)
    app.wait(lambda s: "Primary" in s["extended"]["model_test_status"][status_key]
             and "✓" in s["extended"]["model_test_status"][status_key], "a successful Settings model probe", timeout=75)
    probes = requests(app)[before:]
    assert any(row["authenticated"] and row["payload"].get("model") == "journey-model"
               and "Reply with OK." in json.dumps(row["payload"].get("messages", [])) for row in probes), "No authenticated model-test probe reached the provider"
    if image:
        assert any(part.get("type") == "image_url" for row in probes for message in row["payload"].get("messages", [])
                   if isinstance(message.get("content"), list) for part in message["content"])
    app.close_settings()


@journey("Reopen the saved provider before the basic user journeys", features=("F425", "F144"), phase=BASIC_PHASE)
def test_basic_01_reopen(app):
    # A fresh process must use the provider saved by onboarding/Settings. A
    # marked debug copy reconnects its temporary port through those same widgets.
    if os.environ.get("OPENWAND_E2E_DEBUG_START"):
        app.settings("General")
        app.ui("settings_field", field="PRIVACY_MODE", value="off")
        if app.ui()["settings"]["save_enabled"]:
            app.save_settings()
        app.close_settings()
        app.settings()
        index = next(i for i, row in enumerate(app.ui()["extended"]["connections"]) if row["alias"] == "Journey provider")
        app.ui("connection", index=index, field="custom_address", value=os.environ["OPENWAND_E2E_PROVIDER_URL"])
        app.save_settings()
        app.close_settings()
    new(app)
    app.send("E2E_BASIC_PROCESS_START")
    app.reply("E2E_BASIC_PROCESS_START")


@journey("Press Enter in an empty chat without sending anything", features=("F146",), phase=BASIC_PHASE)
def test_basic_02_empty_prompt(app):
    # An empty message must not create a user turn or an HTTP request.
    new(app)
    before = len(requests(app))
    app.ui("chat_key", key="Return")
    no_network(app, before)
    assert not app.ui()["chat"]["messages"] and active(app)["messages"] == 0


@journey("Submit whitespace without creating a message or network request", features=("F146",), phase=BASIC_PHASE)
def test_basic_03_whitespace_prompt(app):
    # Spaces are not a meaningful prompt, even when the user presses Send.
    new(app)
    before = len(requests(app))
    app.ui("chat_type", text="   ")
    app.ui("chat_send")
    no_network(app, before)
    assert active(app)["messages"] == 0
    app.ui("chat_type", text="")


@journey("Start a new chat with the visible button and retain the old chat", features=("F145", "F150"), phase=BASIC_PHASE)
def test_basic_04_new_chat_button(app):
    # The button must create a new identity while keeping the earlier history.
    app.send("E2E_BUTTON_ORIGINAL")
    app.reply("E2E_BUTTON_ORIGINAL")
    old = active(app)["id"]
    new(app)
    assert active(app)["id"] != old
    assert any(row["id"] == old for row in app.ui()["extended"]["conversations"])


@journey("Type a prompt and send it with Enter", features=("F146", "F144"), phase=BASIC_PHASE)
def test_basic_05_enter_to_send(app):
    # Use the keyboard's Return event instead of the Send button.
    new(app)
    app.ui("chat_type", text="E2E_ENTER_SEND")
    app.ui("chat_key", key="Return")
    app.reply("E2E_ENTER_SEND")
    assert not app.ui()["chat"]["input"]


@journey("Insert a newline with Shift+Enter before sending the full draft", features=("F146",), phase=BASIC_PHASE)
def test_basic_06_shift_enter(app):
    # Shift+Enter must edit the draft without sending its first line early.
    new(app)
    before = len(requests(app))
    app.ui("chat_type", text="E2E_SHIFT_FIRST")
    app.ui("chat_key", key="Return", shift=True)
    assert app.ui()["chat"]["input"] == "E2E_SHIFT_FIRST\n"
    no_network(app, before)
    app.ui("chat_type", text="E2E_SHIFT_FIRST\nE2E_SHIFT_SECOND")
    app.ui("chat_send")
    app.reply("E2E_SHIFT_SECOND")
    assert "E2E_SHIFT_FIRST\\nE2E_SHIFT_SECOND" in json.dumps(app.request("E2E_SHIFT_SECOND"))


@journey("Send Unicode text entered through the user's input method", features=("F144", "F146"), phase=BASIC_PHASE)
def test_basic_07_unicode_prompt(app):
    # An IME commit must preserve accents, CJK characters and emoji end to end.
    new(app)
    text = "E2E_UNICODE café 中文 🦦"
    app.send(text)
    app.reply("E2E_UNICODE")
    assert text in json.dumps(app.request("E2E_UNICODE"), ensure_ascii=False)


@journey("Keep an unsent draft while opening and closing Settings", features=("F144", "F025"), phase=BASIC_PHASE)
def test_basic_08_draft_settings(app):
    # Visiting Settings must neither erase the composer nor submit its draft.
    new(app)
    before = len(requests(app))
    app.ui("chat_type", text="E2E_RETAINED_DRAFT")
    app.settings()
    app.close_settings()
    app.chat()
    assert app.ui()["chat"]["input"] == "E2E_RETAINED_DRAFT"
    no_network(app, before)
    app.ui("chat_send")
    app.reply("E2E_RETAINED_DRAFT")


@journey("Cancel the attachment chooser and keep the draft intact", features=("F161", "F163"), phase=BASIC_PHASE)
def test_basic_09_cancel_attachment(app):
    # Click Cancel in the real chooser; do not supply a fake empty return value.
    new(app)
    before = len(requests(app))
    app.ui("chat_type", text="E2E_CANCELLED_ATTACHMENT")
    dialogs(app, {"kind": "button", "title": "Add files or images", "button": "Cancel"})
    app.ui("extended.choose_attachment")
    completed_dialogs(app)
    assert app.ui()["chat"]["pending_attachments"] == 0
    assert app.ui()["chat"]["input"] == "E2E_CANCELLED_ATTACHMENT"
    no_network(app, before)
    app.ui("chat_send")
    app.reply("E2E_CANCELLED_ATTACHMENT")


@journey("Remove a pending attachment before sending the prompt", features=("F163", "F162"), phase=BASIC_PHASE)
def test_basic_10_remove_attachment(app):
    # Removing a preview must also remove the file's contents from the request.
    new(app)
    file = app.state / "remove-before-send.txt"
    file.write_text("E2E_REMOVED_FILE_MUST_NOT_LEAK", encoding="utf-8")
    app.ui("chat_drop", path=str(file))
    assert app.ui()["chat"]["pending_attachments"] == 1
    assert app.ui()["extended"]["chat_details"]["attachment_preview_visible"]
    app.ui("extended.clear_attachments")
    assert app.ui()["chat"]["pending_attachments"] == 0
    assert not app.ui()["extended"]["chat_details"]["attachment_preview_visible"]
    app.send("E2E_WITHOUT_REMOVED_FILE")
    app.reply("E2E_WITHOUT_REMOVED_FILE")
    assert "E2E_REMOVED_FILE_MUST_NOT_LEAK" not in json.dumps(app.request("E2E_WITHOUT_REMOVED_FILE"))


@journey("Attach two files together and send both contents", features=("F162", "F163"), phase=BASIC_PHASE)
def test_basic_11_multiple_attachments(app):
    # Names in the preview and both independent file contents must survive send.
    new(app)
    files = [app.state / "first-basic.txt", app.state / "second-basic.txt"]
    for index, file in enumerate(files):
        file.write_text(f"E2E_MULTI_FILE_{index}", encoding="utf-8")
    app.ui("chat_drop", paths=[str(file) for file in files])
    assert app.ui()["chat"]["pending_attachments"] == 2
    assert all(file.name in app.ui()["extended"]["chat_details"]["pending_names"] for file in files)
    app.send("E2E_MULTIPLE_FILES")
    app.reply("E2E_MULTIPLE_FILES")
    payload = json.dumps(app.request("E2E_MULTIPLE_FILES"))
    assert all(f"E2E_MULTI_FILE_{index}" in payload for index in range(2))
    assert app.ui()["chat"]["pending_attachments"] == 0


@journey("Drop an image, preview its thumbnail and send it to the image route", features=("F162", "F164"), phase=BASIC_PHASE)
def test_basic_12_image_attachment(app):
    # A tiny synthetic PNG uses the production image attachment and SDK path.
    new(app)
    image = app.state / "basic-pixel.png"
    from PySide6.QtGui import QImage
    pixel = QImage(2, 2, QImage.Format.Format_ARGB32)
    pixel.fill(0xFF336699)
    assert pixel.save(str(image)), "Could not create the synthetic image fixture"
    app.ui("chat_drop", path=str(image))
    details = app.ui()["extended"]["chat_details"]
    assert details["pending_image"] and details["thumbnail_visible"]
    app.send("E2E_IMAGE_ATTACHMENT")
    app.reply("E2E_IMAGE_ATTACHMENT")
    payload = app.request("E2E_IMAGE_ATTACHMENT")
    assert any(part.get("type") == "image_url" and part["image_url"]["url"].startswith("data:image/")
               for message in payload["messages"] if isinstance(message.get("content"), list) for part in message["content"])


@journey("Switch between two saved chats and follow up in the selected one", features=("F150", "F148"), phase=BASIC_PHASE)
def test_basic_13_switch_history(app):
    # The visible history selection must determine context sent to the provider.
    new(app)
    app.send("E2E_HISTORY_CHAT_A")
    app.reply("E2E_HISTORY_CHAT_A")
    index_a = app.ui()["extended"]["active_conversation"]
    new(app)
    app.send("E2E_HISTORY_CHAT_B")
    app.reply("E2E_HISTORY_CHAT_B")
    app.ui("chat_history", index=index_a)
    assert any("E2E_HISTORY_CHAT_A" in text for text in app.ui()["chat"]["messages"])
    app.send("E2E_HISTORY_FOLLOWUP_A")
    app.reply("E2E_HISTORY_FOLLOWUP_A")
    payload = json.dumps(app.request("E2E_HISTORY_FOLLOWUP_A"))
    assert "E2E_HISTORY_CHAT_A" in payload and "E2E_HISTORY_CHAT_B" not in payload


@journey("Test the saved Chat model from Settings", features=("F255",), phase=BASIC_PHASE)
def test_basic_14_test_chat_model(app):
    # The success label requires a real SDK probe, not just configured fields.
    model_test(app, "LLM", "llm")


@journey("Test the saved Image model with an actual image request", features=("F258",), phase=BASIC_PHASE)
def test_basic_15_test_image_model(app):
    # The image test must send an image part to the independent HTTP provider.
    model_test(app, "VISION_LLM", "vision", image=True)


@journey("Test the saved Memory model from Settings", features=("F261",), phase=BASIC_PHASE)
def test_basic_16_test_memory_model(app):
    # The separate Memory test must probe its own configured route.
    model_test(app, "MEMORY_LLM", "memory")


@journey("Show a failing model probe and recover by fixing the draft model", features=("F255", "F227"), phase=BASIC_PHASE)
def test_basic_17_model_probe_failure(app):
    # Exercise the real Settings error label and another successful probe without
    # saving a broken primary model into the user's working configuration.
    app.settings("Model routing")
    app.ui("route", field="model", value="journey-unavailable")
    before = len(requests(app))
    app.ui("extended.model_test", section="LLM")
    app.wait(lambda s: "✗" in s["extended"]["model_test_status"]["llm"], "a visible failed model probe", timeout=75)
    assert any(r["payload"].get("model") == "journey-unavailable" for r in requests(app)[before:])
    app.ui("route", field="model", value="journey-model")
    app.ui("extended.model_test", section="LLM")
    app.wait(lambda s: "✓" in s["extended"]["model_test_status"]["llm"], "recovery after correcting the model", timeout=75)
    app.close_settings()


@journey("Zoom chat text in, out and back to the default size", features=("F179",), phase=BASIC_PHASE)
def test_basic_18_zoom(app):
    # Keyboard shortcuts must change the visible composer style as well as the
    # zoom value, and Ctrl+0 must restore the normal size.
    app.chat()
    app.ui("extended.zoom", key="0")
    before = app.ui()["extended"]["chat_details"]["input_font"]
    app.ui("extended.zoom", key="Equal")
    app.wait(lambda s: s["extended"]["chat_details"]["font_scale"] > 1, "larger chat text")
    assert app.ui()["extended"]["chat_details"]["input_font"] != before
    app.ui("extended.zoom", key="Minus")
    app.wait(lambda s: s["extended"]["chat_details"]["font_scale"] == 1, "smaller chat text")
    app.ui("extended.zoom", key="Equal")
    app.ui("extended.zoom", key="0")
    assert app.ui()["extended"]["chat_details"]["font_scale"] == 1


@journey("Branch an earlier message and preserve the original conversation", features=("F176", "F148"), phase=BASIC_PHASE)
def test_basic_19_branch(app):
    # Branching from the first user message must exclude later turns without deleting
    # them from the source chat. A follow-up must use the branch's own history.
    new(app)
    for text in ("E2E_BRANCH_RETAIN", "E2E_BRANCH_EXCLUDE"):
        app.send(text)
        app.reply(text)
    source = active(app)
    source_index = app.ui()["extended"]["active_conversation"]
    dialogs(app, menu("Branch from here"))
    app.ui("extended.message_menu", index=0)
    completed_dialogs(app)
    assert active(app)["id"] != source["id"] and active(app)["messages"] == 1
    app.send("E2E_BRANCH_FOLLOWUP")
    app.reply("E2E_BRANCH_FOLLOWUP")
    payload = json.dumps(app.request("E2E_BRANCH_FOLLOWUP"))
    assert "E2E_BRANCH_RETAIN" in payload and "E2E_BRANCH_EXCLUDE" not in payload
    app.ui("chat_history", index=source_index)
    assert active(app)["id"] == source["id"] and active(app)["messages"] == 4


@journey("Cancel rewinding a chat and retain every message", features=("F177",), phase=BASIC_PHASE)
def test_basic_20_cancel_rewind(app):
    # A No response in the real confirmation dialog must leave history intact.
    before = active(app)
    dialogs(app, menu("Rewind current chat to here"), {"kind": "button", "title": "Rewind conversation", "button": "No"})
    app.ui("extended.message_menu", index=0)
    completed_dialogs(app)
    assert active(app)["id"] == before["id"] and active(app)["messages"] == before["messages"]


@journey("Confirm rewind and follow up without the removed conversation turns", features=("F177", "F148"), phase=BASIC_PHASE)
def test_basic_21_confirm_rewind(app):
    # A Yes response truncates the same conversation. Removed text must not
    # remain hidden in the context sent with the next prompt.
    original_id = active(app)["id"]
    dialogs(app, menu("Rewind current chat to here"), {"kind": "button", "title": "Rewind conversation", "button": "Yes"})
    app.ui("extended.message_menu", index=0)
    completed_dialogs(app)
    assert active(app)["id"] == original_id and active(app)["messages"] == 1
    app.send("E2E_AFTER_REWIND")
    app.reply("E2E_AFTER_REWIND")
    payload = json.dumps(app.request("E2E_AFTER_REWIND"))
    assert "E2E_BRANCH_RETAIN" in payload and "E2E_BRANCH_EXCLUDE" not in payload


@journey("Cancel creating a project without changing the selected project", features=("F152", "F153"), phase=BASIC_PHASE)
def test_basic_22_cancel_project(app):
    # Cancelling the real name dialog must not leave a project or change scope.
    before = app.ui()["extended"]
    dialogs(app, {"kind": "input", "title": "New project", "button": "Cancel"})
    app.ui("extended.project", new=True)
    completed_dialogs(app)
    after = app.ui()["extended"]
    assert after["projects"] == before["projects"] and after["project"] == before["project"]


@journey("Cancel resetting a Settings page and preserve saved settings", features=("F427", "F425"), phase=BASIC_PHASE)
def test_basic_23_cancel_reset_page(app):
    # Reset is a destructive choice: choosing No must keep the saved appearance.
    app.settings("General")
    before = app.ui()["theme_background"]
    dialogs(app, {"kind": "button", "title": "Reset page?", "button": "No"})
    app.ui("settings_button", text="Reset Page…")
    completed_dialogs(app)
    assert app.ui()["theme_background"] == before
    assert not app.ui()["settings"]["save_enabled"]
    app.close_settings()


@journey("Discard an added connection draft and continue using the saved provider", features=("F215", "F426"), phase=BASIC_PHASE)
def test_basic_24_discard_connection_draft(app):
    # Cancelling Settings must discard a whole unsaved connection, not just its
    # alias. The saved provider must still answer the next prompt.
    app.settings()
    count = len(app.ui()["settings"]["connections"])
    app.ui("settings_button", text="+ Add connection")
    app.ui("connection", field="alias", value="E2E_UNSAVED_CONNECTION")
    assert len(app.ui()["settings"]["connections"]) == count + 1
    app.close_settings()
    app.settings()
    assert len(app.ui()["settings"]["connections"]) == count
    assert all(r["alias"] != "E2E_UNSAVED_CONNECTION" for r in app.ui()["settings"]["connections"])
    app.close_settings()
    new(app)
    app.send("E2E_AFTER_CONNECTION_DISCARD")
    app.reply("E2E_AFTER_CONNECTION_DISCARD")


@journey("Save a Unicode provider alias, reopen it and restore its display name", features=("F216", "F425"), phase=BASIC_PHASE)
def test_basic_25_unicode_provider_alias(app):
    # Alias text must survive the real settings write without changing the
    # connection identity or preventing the next actual SDK request.
    app.settings()
    index = next(i for i, r in enumerate(app.ui()["settings"]["connections"]) if r["alias"] == "Journey provider")
    identity = app.ui()["settings"]["connections"][index]["id"]
    label = "E2E café 提供者"
    app.ui("connection", index=index, field="alias", value=label)
    app.save_settings()
    app.close_settings()
    app.settings()
    index = next(i for i, r in enumerate(app.ui()["settings"]["connections"]) if r["id"] == identity)
    assert app.ui()["settings"]["connections"][index]["alias"] == label
    app.ui("connection", index=index, field="alias", value="Journey provider")
    app.save_settings()
    app.close_settings()
    app.send("E2E_AFTER_ALIAS_RENAME")
    app.reply("E2E_AFTER_ALIAS_RENAME")


@journey("Search shortcuts, show no matches and restore the complete list", features=("F062",), phase=BASIC_PHASE)
def test_basic_26_shortcut_search(app):
    # Search must affect the actual shortcut rows, then clearing it restores them.
    app.settings("Shortcuts")
    before = app.ui()["extended"]["shortcuts"]
    assert len(before) > 3 and any(row["visible"] for row in before)
    app.ui("extended.shortcut_search", value="E2E_NO_SUCH_SHORTCUT")
    assert not any(row["visible"] for row in app.ui()["extended"]["shortcuts"])
    app.ui("extended.shortcut_search", value="General")
    visible = [row for row in app.ui()["extended"]["shortcuts"] if row["visible"]]
    assert visible and all("general" in (row["title"] + row["description"]).lower() for row in visible)
    app.ui("extended.shortcut_search", value="")
    assert sum(row["visible"] for row in app.ui()["extended"]["shortcuts"]) == sum(row["visible"] for row in before)
    app.close_settings()


@journey("Confirm an Advanced page reset without losing the provider or conversation", features=("F427", "F425"), phase=BASIC_PHASE)
def test_basic_27_confirm_reset_page(app):
    # Reset one page through Yes/OK, verify its changed value resets, then restore
    # the prior test preferences through the same visible fields.
    app.settings("Advanced")
    previous = app.ui()["extended"]["field_values"]
    routes = app.ui()["settings"]["routes"]
    app.ui("settings_field", field="BUBBLE_REVEAL_WPM", value="333")
    app.save_settings()
    dialogs(app, {"kind": "button", "title": "Reset page?", "button": "Yes"}, {"kind": "button", "title": "Page reset", "button": "OK"})
    app.ui("settings_button", text="Reset Page…")
    completed_dialogs(app)
    assert app.ui()["extended"]["field_values"]["BUBBLE_REVEAL_WPM"] != "333"
    assert app.ui()["settings"]["routes"] == routes
    for field, value in previous.items():
        app.ui("settings_field", field=field, value=value)
    if app.ui()["settings"]["save_enabled"]:
        app.save_settings()
    app.close_settings()
    app.chat()
    app.send("E2E_AFTER_PAGE_RESET")
    app.reply("E2E_AFTER_PAGE_RESET")


@journey("Save a short intent timeout and let an abandoned picker close", features=("F044",), phase=BASIC_PHASE)
def test_basic_28_picker_timeout(app):
    # An abandoned real picker should close itself without sending a prompt.
    app.settings("Shortcuts")
    previous = app.ui()["extended"]["field_values"]["INTENT_OVERLAY_TIMEOUT_MS"]
    app.ui("settings_field", field="INTENT_OVERLAY_TIMEOUT_MS", value="1000")
    app.save_settings()
    app.close_settings()
    before = len(requests(app))
    try:
        open_picker(app)
        app.wait(lambda s: "intent" not in s["extended"], "the abandoned picker to time out", timeout=8)
        no_network(app, before)
    finally:
        app.settings("Shortcuts")
        app.ui("settings_field", field="INTENT_OVERLAY_TIMEOUT_MS", value=previous)
        app.save_settings()
        app.close_settings()


@journey("Set intent timeout to zero and keep the picker open until Escape", features=("F045", "F043"), phase=BASIC_PHASE)
def test_basic_29_picker_no_timeout(app):
    # Zero disables auto-close; the user still has a working Escape dismissal.
    app.settings("Shortcuts")
    previous = app.ui()["extended"]["field_values"]["INTENT_OVERLAY_TIMEOUT_MS"]
    app.ui("settings_field", field="INTENT_OVERLAY_TIMEOUT_MS", value="0")
    app.save_settings()
    app.close_settings()
    before = len(requests(app))
    try:
        open_picker(app)
        time.sleep(1.3)
        assert app.ui()["extended"]["intent"]["enabled"]
        app.ui("extended.intent_escape")
        app.wait(lambda s: "intent" not in s["extended"], "Escape to close the no-timeout picker")
        no_network(app, before)
    finally:
        app.settings("Shortcuts")
        app.ui("settings_field", field="INTENT_OVERLAY_TIMEOUT_MS", value=previous)
        app.save_settings()
        app.close_settings()


@journey("Turn clipboard context Off and On and verify what reaches the provider", features=("F168", "F093"), phase=BASIC_PHASE)
def test_basic_30_clipboard_context(app):
    # The OS clipboard is a declared synthetic boundary. Its known text must
    # appear only when this conversation grants clipboard access.
    new(app)
    app.ui("chat_context", source="clipboard", value="off")
    app.send("E2E_CLIPBOARD_OFF")
    app.reply("E2E_CLIPBOARD_OFF")
    assert "E2E_CLIPBOARD_TEXT" not in json.dumps(app.request("E2E_CLIPBOARD_OFF"))
    new(app)
    app.ui("chat_context", source="clipboard", value="on")
    app.send("E2E_CLIPBOARD_ON")
    app.reply("E2E_CLIPBOARD_ON")
    assert "E2E_CLIPBOARD_TEXT" in json.dumps(app.request("E2E_CLIPBOARD_ON"))
    app.send("E2E_CLIPBOARD_FOLLOWUP")
    app.reply("E2E_CLIPBOARD_FOLLOWUP")
    assert "E2E_CLIPBOARD_TEXT" in json.dumps(app.request("E2E_CLIPBOARD_FOLLOWUP"))


@journey("Disable selected-text context and compare with a new chat's default", features=("F167", "F094"), phase=BASIC_PHASE)
def test_basic_31_selection_context(app):
    # Turning Selection Off must omit the synthetic selected text. A new chat
    # must retain its own default instead of inheriting the older chat's Off.
    new(app)
    app.ui("chat_context", source="selection", value="off")
    app.send("E2E_SELECTION_OFF")
    app.reply("E2E_SELECTION_OFF")
    assert "E2E_SELECTED_TEXT" not in json.dumps(app.request("E2E_SELECTION_OFF"))
    new(app)
    app.send("E2E_SELECTION_DEFAULT_ON")
    app.reply("E2E_SELECTION_DEFAULT_ON")
    assert "E2E_SELECTED_TEXT" in json.dumps(app.request("E2E_SELECTION_DEFAULT_ON"))


@journey("Change App context per conversation and inspect the actual request", features=("F165", "F091"), phase=BASIC_PHASE)
def test_basic_32_app_context(app):
    # Native desktop input is synthetic, while the app's context policy and
    # prompt builder are real. An App On request must include its window text.
    new(app)
    app.ui("chat_context", source="ambient", value="off")
    app.send("E2E_APP_CONTEXT_OFF")
    app.reply("E2E_APP_CONTEXT_OFF")
    assert "E2E_WINDOW_TEXT" not in json.dumps(app.request("E2E_APP_CONTEXT_OFF"))
    new(app)
    app.ui("chat_context", source="ambient", value="on")
    app.send("E2E_APP_CONTEXT_ON")
    app.reply("E2E_APP_CONTEXT_ON")
    assert "E2E_WINDOW_TEXT" in json.dumps(app.request("E2E_APP_CONTEXT_ON"))


@journey("Reopen guided setup from Settings and cancel without changing the provider", features=("F005",), phase=BASIC_PHASE)
def test_basic_33_reopen_setup(app):
    # This is the normal Run profile setup button after first-run setup already
    # finished. Escape must leave the saved provider and routes usable.
    app.settings("General")
    connections = app.ui()["settings"]["connections"]
    routes = app.ui()["settings"]["routes"]
    app.ui("settings_button", text="Run profile setup")
    app.wait(lambda s: s["extended"]["profile_wizard"]["visible"], "the reopened guided setup wizard")
    app.ui("extended.profile_wizard_escape")
    app.wait(lambda s: not s["extended"]["profile_wizard"]["visible"], "the cancelled setup wizard")
    assert app.ui()["settings"]["connections"] == connections
    assert app.ui()["settings"]["routes"] == routes
    app.close_settings()
    app.chat()
    app.send("E2E_AFTER_SETUP_CANCEL")
    app.reply("E2E_AFTER_SETUP_CANCEL")


@journey("Keep unsaved Settings when guided setup asks to save first", features=("F005", "F426"), phase=BASIC_PHASE)
def test_basic_34_setup_dirty_guard(app):
    # Guided setup must warn about an existing draft rather than replace it.
    app.settings("General")
    previous = app.ui()["extended"]["field_values"]["THEME_MODE"]
    app.ui("settings_field", field="THEME_MODE", value="dark" if previous != "dark" else "light")
    app.wait(lambda s: s["settings"]["save_enabled"], "an unsaved Settings draft")
    dialogs(app, {"kind": "button", "title": "Save settings first", "button": "OK"})
    app.ui("settings_button", text="Run profile setup")
    completed_dialogs(app)
    assert not app.ui()["extended"]["profile_wizard"]["visible"]
    assert app.ui()["settings"]["save_enabled"]
    app.close_settings()
    app.settings("General")
    assert app.ui()["extended"]["field_values"]["THEME_MODE"] == previous
    app.close_settings()


@journey("Test a working primary and a broken fallback without blaming the primary", features=("F255", "F254"), phase=BASIC_PHASE)
def test_basic_35_probe_fallback_warning(app):
    # The model-test button must actually probe both rows and show the fallback
    # failure while preserving the working primary's successful result.
    app.settings("Model routing")
    provider = app.ui()["settings"]["routes"]["LLM"][0]["provider"]
    app.ui("extended.route_button", operation="add")
    app.ui("route", index=1, field="provider", value=provider)
    app.ui("route", index=1, field="model", value="journey-unavailable")
    before = len(requests(app))
    app.ui("extended.model_test", section="LLM")
    result = app.wait(lambda s: "Primary works." in s["extended"]["model_test_status"]["llm"], "a specific fallback warning", timeout=75)
    text = result["extended"]["model_test_status"]["llm"]
    assert "✓ Primary" in text and "✗ Fallback 1" in text
    assert {"journey-model", "journey-unavailable"} <= {r["payload"].get("model") for r in requests(app)[before:]}
    app.close_settings()


@journey("Reject testing an unconfigured model without making a network call", features=("F255",), phase=BASIC_PHASE)
def test_basic_36_empty_model_probe(app):
    # Empty configuration must show a useful failure, never a green test label.
    app.settings("Model routing")
    app.ui("route", field="model", value="")
    before = len(requests(app))
    app.ui("extended.model_test", section="LLM")
    app.wait(lambda s: "No model configured" in s["extended"]["model_test_status"]["llm"], "the missing-model error")
    no_network(app, before)
    app.close_settings()


@journey("Cancel creating a custom profile and retain the saved profile list", features=("F420",), phase=BASIC_PHASE)
def test_basic_37_cancel_profile_creation(app):
    # Clicking Cancel must not leave an empty profile or switch the active one.
    app.settings()
    before = app.ui()["extended"]
    dialogs(app, menu("Create custom profile..."), {"kind": "input", "title": "Create custom profile", "button": "Cancel"})
    app.ui("extended.settings_profile_menu")
    completed_dialogs(app)
    assert app.ui()["extended"]["saved_profiles"] == before["saved_profiles"]
    assert app.ui()["extended"]["profile"] == before["profile"]
    app.close_settings()


@journey("Finish the basic journeys with a saved, usable conversation", features=("F144", "F148"), phase=BASIC_PHASE)
def test_basic_99_complete(app):
    # Leave a real completed turn for the following independently launched phase.
    app.send("E2E_BASIC_COMPLETE")
    app.reply("E2E_BASIC_COMPLETE")
