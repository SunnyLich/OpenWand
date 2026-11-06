"""Connected user stories beyond the initial prompting and setup slice.

Each test uses the running app. Dialogs are entered and confirmed with actual
Qt input; no API, model, store or approval handler inside OpenWand is replaced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.user_journeys.scenarios import journey

EXTENDED_PHASE = "extended"


def dialogs(app, *plans):
    app.ui("extended.dialogs", plans=list(plans))


def completed_dialogs(app):
    return app.wait(lambda s: s["extended"]["dialog_pending"] == 0 and all(event.get("completed") for event in s["extended"]["dialog_events"]), "the user's dialog choices")["extended"]["dialog_events"]


def conversation_action(app, *plans):
    dialogs(app, *plans)
    index = app.ui()["extended"]["active_conversation"]
    app.ui("extended.conversation_menu", index=index)
    return completed_dialogs(app)


def menu(value):
    return {"kind": "menu", "value": value}


def primary_provider(app):
    return app.ui()["settings"]["routes"]["LLM"][0]["provider"]


def provider_requests(app, marker):
    rows = json.loads((Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json").read_text(encoding="utf-8"))
    return [row["payload"] for row in rows if marker in json.dumps([m for m in row["payload"].get("messages", []) if m.get("role") == "user"][-1:])]


def tool_outcomes(app, marker):
    """Require actual worker tool results, not merely an absent side effect."""
    results = []
    for payload in provider_requests(app, marker):
        messages = payload.get("messages", [])
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        results.extend(str(m.get("content", "")) for m in messages[last_user + 1:] if m.get("role") == "tool")
    return results


@journey("Use the retained provider after another full application launch", features=("F222", "F425"), phase=EXTENDED_PHASE)
def test_ext_01_retained_provider(app):
    # On a normal run the endpoint is retained. A debug copy has a new local
    # provider port, which is updated through the same visible connection row.
    if os.environ.get("OPENWAND_E2E_DEBUG_START"):
        # A failed debug copy may have stopped with mandatory privacy review
        # enabled. Reset through Settings so reconnecting cannot strand it.
        app.settings("General")
        app.ui("settings_field", field="PRIVACY_MODE", value="off")
        if app.ui()["settings"]["save_enabled"]:
            app.save_settings()
        app.close_settings()
    app.settings()
    rows = app.ui()["extended"]["connections"]
    index = next(i for i, row in enumerate(rows) if row["alias"] == "Journey provider")
    if rows[index]["address"] != os.environ["OPENWAND_E2E_PROVIDER_URL"]:
        app.ui("connection", index=index, field="custom_address", value=os.environ["OPENWAND_E2E_PROVIDER_URL"])
        app.save_settings()
    app.close_settings()
    app.chat()
    app.ui("chat_new")
    app.send("E2E_EXTENDED_START")
    app.reply("E2E_EXTENDED_START")


@journey("Add, search and filter a second provider connection", features=("F215", "F219", "F220"), phase=EXTENDED_PHASE)
def test_ext_02_connection_search_and_filter(app):
    # A second real connection must participate in search/filter controls and
    # survive Save/reopen; the first provider remains usable for conversations.
    app.settings()
    app.ui("settings_button", text="+ Add connection")
    for field, value in (("provider", "custom"), ("alias", "Secondary journey provider"), ("endpoint_combo", ""), ("custom_address", os.environ["OPENWAND_E2E_PROVIDER_URL"]), ("key", "e2e-secondary-key")):
        app.ui("connection", field=field, value=value)
    app.ui("extended.connection_search", value="Secondary journey")
    assert [r["alias"] for r in app.ui()["settings"]["connections"] if r["visible"]] == ["Secondary journey provider"]
    app.ui("extended.connection_filter", value="cloud")
    assert not any(r["visible"] for r in app.ui()["settings"]["connections"])
    app.ui("extended.connection_filter", value="local")
    assert any(r["visible"] for r in app.ui()["settings"]["connections"])
    app.ui("extended.connection_filter", value="all")
    app.ui("extended.connection_search", value="")
    app.save_settings()
    app.close_settings()
    app.settings()
    assert any(r["alias"] == "Secondary journey provider" for r in app.ui()["settings"]["connections"])
    app.close_settings()


@journey("Cancel provider removal, then save removal without breaking its sibling", features=("F218", "F426"), phase=EXTENDED_PHASE)
def test_ext_03_connection_removal(app):
    # Cancelling a removal must retain the saved connection. Saving a later
    # removal must remove only that connection, not its same-provider sibling.
    app.settings()
    rows = app.ui()["settings"]["connections"]
    index = next(i for i, row in enumerate(rows) if row["alias"] == "Secondary journey provider")
    app.ui("extended.connection_remove", index=index)
    app.close_settings()
    app.settings()
    rows = app.ui()["settings"]["connections"]
    index = next(i for i, row in enumerate(rows) if row["alias"] == "Secondary journey provider")
    app.ui("extended.connection_remove", index=index)
    app.save_settings()
    app.close_settings()
    app.settings()
    assert "Secondary journey provider" not in [r["alias"] for r in app.ui()["settings"]["connections"]]
    app.close_settings()
    app.send("E2E_AFTER_SIBLING_REMOVAL")
    app.reply("E2E_AFTER_SIBLING_REMOVAL")


@journey("Refresh provider model names through the live Settings control", features=("F226", "F264"), phase=EXTENDED_PHASE)
def test_ext_04_refresh_models(app):
    # The refresh control must make the production client fetch models over HTTP
    # and display the returned model, rather than depend on a curated list.
    app.settings("Model routing")
    app.ui("extended.route_button", operation="refresh")
    app.wait(lambda s: not s["extended"]["route_details"]["LLM"][0]["refresh_busy"] and "journey-discovered-model" in s["extended"]["route_details"]["LLM"][0]["models"], "the fetched model in Settings")
    app.close_settings()


@journey("Add model fallbacks, copy routes and remove the extra row", features=("F254", "F257", "F260", "F262"), phase=EXTENDED_PHASE)
def test_ext_05_route_editing(app):
    # Ordered route edits must survive actual save/reopen on all three routes.
    app.settings("Model routing")
    provider = primary_provider(app)
    app.ui("extended.route_button", operation="add")
    app.ui("route", index=1, field="provider", value=provider)
    app.ui("route", index=1, field="model", value="journey-fallback")
    app.ui("extended.route_button", operation="apply_all")
    app.save_settings()
    app.close_settings()
    app.settings("Model routing")
    assert all(len(rows) == 2 and rows[1]["model"] == "journey-fallback" for rows in app.ui()["settings"]["routes"].values())
    for section in ("LLM", "VISION_LLM", "MEMORY_LLM"):
        app.ui("extended.route_button", section=section, operation="remove", index=1)
    app.save_settings()
    app.close_settings()


@journey("Recover through a fallback and cool down the failing primary", features=("F265", "F266"), phase=EXTENDED_PHASE)
def test_ext_06_runtime_fallback(app):
    # The HTTP fixture rejects one model. The actual runtime must try the saved
    # fallback; evidence must show both network requests and a visible answer.
    app.settings("Model routing")
    provider = primary_provider(app)
    app.ui("extended.route_button", operation="add")
    app.ui("route", index=1, field="provider", value=provider)
    app.ui("route", index=1, field="model", value="journey-model")
    app.ui("route", field="model", value="journey-unavailable")
    app.save_settings()
    app.close_settings()
    app.ui("chat_new")
    app.send("E2E_FALLBACK_ROUTE")
    app.reply("E2E_FALLBACK_ROUTE")
    models = [p["model"] for p in provider_requests(app, "E2E_FALLBACK_ROUTE")]
    assert "journey-unavailable" in models and "journey-model" in models
    app.send("E2E_FALLBACK_COOLDOWN")
    app.reply("E2E_FALLBACK_COOLDOWN")
    assert {p["model"] for p in provider_requests(app, "E2E_FALLBACK_COOLDOWN")} == {"journey-model"}
    app.settings("Model routing")
    app.ui("route", field="model", value="journey-model")
    app.ui("extended.route_button", operation="remove", index=1)
    app.save_settings()
    app.close_settings()


@journey("Rename, pin and unpin a conversation through its history menu", features=("F156", "F157"), phase=EXTENDED_PHASE)
def test_ext_07_conversation_identity(app):
    # Menus open real input dialogs. The selected name and pin state must be
    # retained after the chat closes and reopens, not merely in a temporary row.
    conversation_action(app, menu("Rename"), {"kind": "input", "title": "Rename conversation", "value": "Journey conversation"})
    conversation_action(app, menu("Pin"))
    current = app.ui()["extended"]
    assert current["conversations"][current["active_conversation"]]["pinned"]
    app.ui("chat_close")
    app.chat()
    assert any(c["title"] == "Journey conversation" and c["pinned"] for c in app.ui()["extended"]["conversations"])
    conversation_action(app, menu("Unpin"))
    current = app.ui()["extended"]
    assert not current["conversations"][current["active_conversation"]]["pinned"]


@journey("Create a project, move a conversation and start a scoped chat", features=("F152", "F153", "F155"), phase=EXTENDED_PHASE)
def test_ext_08_project_conversation(app):
    # Choose New project and enter its name in the actual dialog. Moving the
    # existing chat and creating a new one must use that saved project identity.
    dialogs(app, {"kind": "input", "title": "New project", "value": "Journey project"})
    app.ui("extended.project", new=True)
    completed_dialogs(app)
    project = next(p for p in app.ui()["extended"]["projects"] if p["name"] == "Journey project")
    conversation_action(app, menu("Add to project"), menu("Journey project"))
    snapshot = app.ui()["extended"]
    assert snapshot["conversations"][snapshot["active_conversation"]]["project_id"] == project["id"]
    app.ui("chat_new")
    app.send("E2E_PROJECT_PROMPT")
    app.reply("E2E_PROJECT_PROMPT")
    snapshot = app.ui()["extended"]
    assert snapshot["conversations"][snapshot["active_conversation"]]["project_id"] == project["id"]


@journey("Decline conversation deletion, then confirm deletion", features=("F158",), phase=EXTENDED_PHASE)
def test_ext_09_delete_confirmation(app):
    # The first confirmation is No: the exact conversation must remain. The
    # second is Yes: only that conversation disappears from durable history.
    before = app.ui()["extended"]
    removed_id = before["conversations"][before["active_conversation"]]["id"]
    conversation_action(app, menu("Delete"), {"kind": "button", "title": "Delete conversation", "button": "No"})
    assert any(c["id"] == removed_id for c in app.ui()["extended"]["conversations"])
    conversation_action(app, menu("Delete"), {"kind": "button", "title": "Delete conversation", "button": "Yes"})
    app.wait(lambda s: not any(c["id"] == removed_id for c in s["extended"]["conversations"]), "confirmed conversation deletion")
    app.ui("chat_close")
    app.chat()
    assert not any(c["id"] == removed_id for c in app.ui()["extended"]["conversations"])


@journey("Edit a memory fact, move it between scopes and refresh", features=("F318", "F319", "F316", "F314"), phase=EXTENDED_PHASE)
def test_ext_10_memory_edit_and_scope(app):
    # The existing fact crosses the real worker boundary on edit and move; a
    # viewer refresh must read the new text and project from persistent storage.
    app.ui("tray", label="Memory")
    app.wait(lambda s: "memory" in s and not s["memory"]["loading"], "Memory viewer")
    app.ui("extended.memory_edit", match="E2E memory fact", value="E2E edited memory fact: the project colour is indigo.")
    project = next(p for p in app.ui()["extended"]["projects"] if p["name"] == "Journey project")
    app.ui("extended.memory_scope", match="E2E edited memory fact", value=project["id"])
    app.ui("memory_refresh")
    app.wait(lambda s: any(r["text"].startswith("E2E edited memory fact") and r["project"] == project["id"] for r in s["extended"].get("memory_rows", [])), "the edited project memory")


@journey("Cancel memory deletion, then delete and reopen the viewer", features=("F320", "F321"), phase=EXTENDED_PHASE)
def test_ext_11_memory_delete(app):
    # A cancelled delete must keep the fact, while a confirmed delete must
    # survive refreshing and reopening the actual viewer.
    for choice in ("No", "Yes"):
        dialogs(app, {"kind": "button", "title": "Delete fact", "button": choice})
        app.ui("extended.memory_delete", match="E2E edited memory fact")
        completed_dialogs(app)
        if choice == "No":
            assert any("E2E edited memory fact" in text for text in app.ui()["memory"]["facts"])
    app.wait(lambda s: not any("E2E edited memory fact" in text for text in s["memory"]["facts"]), "memory deletion")
    app.ui("close_auxiliary")
    app.ui("tray", label="Memory")
    app.wait(lambda s: "memory" in s and not s["memory"]["loading"], "Memory reload")
    assert not any("E2E edited memory fact" in text for text in app.ui()["memory"]["facts"])
    app.ui("close_auxiliary")
    app.chat()


@journey("Review privacy redaction before permitting a network request", features=("F327", "F323"), phase=EXTENDED_PHASE)
def test_ext_12_privacy_review(app):
    # Enable review, enter synthetic private data, inspect the real review text,
    # choose Send redacted and independently inspect the resulting HTTP payload.
    app.settings("General")
    app.ui("settings_field", field="PRIVACY_MODE", value="builtin")
    app.ui("settings_field", field="PRIVACY_REVIEW_BEFORE_SEND", value=True)
    app.save_settings()
    app.close_settings()
    app.ui("chat_new")
    dialogs(app, {"kind": "button", "button": "Send redacted"})
    app.send("E2E_REVIEW_REDACTED: Email jordan@example.com")
    events = completed_dialogs(app)
    assert "jordan@example.com" not in json.dumps(events)
    assert "[EMAIL_" in json.dumps(events)
    app.reply("E2E_REVIEW_REDACTED")
    assert "jordan@example.com" not in json.dumps(provider_requests(app, "E2E_REVIEW_REDACTED"))


@journey("Cancel a privacy review and send a later clean prompt", features=("F328",), phase=EXTENDED_PHASE)
def test_ext_13_privacy_cancel(app):
    # Cancelling must prevent the model request entirely and leave Chat usable.
    app.settings("General")
    app.ui("settings_field", field="PRIVACY_MODE", value="builtin")
    app.ui("settings_field", field="PRIVACY_REVIEW_BEFORE_SEND", value=True)
    if app.ui()["settings"]["save_enabled"]:
        app.save_settings()
    app.close_settings()
    app.ui("chat_new")
    dialogs(app, {"kind": "button", "button": "Cancel send"})
    app.send("E2E_REVIEW_CANCELLED: Email taylor@example.com")
    completed_dialogs(app)
    app.wait(lambda s: not s["chat"]["streaming"], "the cancelled privacy request")
    assert provider_requests(app, "E2E_REVIEW_CANCELLED") == []
    app.ui("chat_new")
    # A fresh clean conversation needs no redaction review. In particular, the
    # cancelled conversation's sensitive input must not follow it into this one.
    app.send("E2E_AFTER_PRIVACY_CANCEL")
    app.reply("E2E_AFTER_PRIVACY_CANCEL")
    app.settings("General")
    app.ui("settings_field", field="PRIVACY_MODE", value="off")
    app.save_settings()
    app.close_settings()


@journey("Search Settings and restore navigation after no matches", features=("F418",), phase=EXTENDED_PHASE)
def test_ext_14_settings_search(app):
    # Search must control actual navigation destinations; clearing it restores
    # every page without applying or saving unrelated changes.
    app.settings()
    app.ui("settings_search", text="NO_MATCHING_SETTING_E2E")
    app.wait(lambda s: not s["extended"]["visible_pages"], "no-match Settings search")
    app.ui("settings_search", text="")
    app.wait(lambda s: len(s["extended"]["visible_pages"]) == 8, "restored Settings pages")
    app.close_settings()


@journey("Create and rename a custom profile through real dialogs", features=("F420", "F421"), phase=EXTENDED_PHASE)
def test_ext_15_custom_profile(app):
    # A custom profile must save the current working provider and be selectable
    # after reopening Settings. Name dialogs are entered through real controls.
    app.settings()
    dialogs(app, menu("Create custom profile..."), {"kind": "input", "title": "Create custom profile", "value": "Journey saved profile"})
    app.ui("extended.settings_profile_menu")
    completed_dialogs(app)
    app.save_settings()
    app.close_settings()
    app.settings()
    assert "Journey saved profile" in app.ui()["extended"]["profile"]
    plans = [menu("Rename profile...")]
    if len(app.ui()["extended"]["saved_profiles"]) > 1:
        plans.append({"kind": "input", "title": "Rename profile", "value": "Journey saved profile"})
    plans.append({"kind": "input", "title": "Rename profile", "value": "Journey renamed profile"})
    dialogs(app, *plans)
    app.ui("extended.settings_profile_menu")
    completed_dialogs(app)
    app.close_settings()
    app.settings()
    assert "Journey renamed profile" in app.ui()["extended"]["profile"]
    app.close_settings()
    app.send("E2E_RENAMED_PROFILE")
    app.reply("E2E_RENAMED_PROFILE")


@journey("Choose a file with the real file picker and ask about it", features=("F161",), phase=EXTENDED_PHASE)
def test_ext_16_file_picker(app):
    # Qt's actual file dialog is driven with keyboard/mouse events. A file
    # chooser result is never substituted into the attachment handler.
    document = app.state / "chosen-document.txt"
    document.write_text("E2E_CHOSEN_DOCUMENT_CONTENT", encoding="utf-8")
    app.ui("chat_new")
    dialogs(app, {"kind": "file", "value": str(document)})
    app.ui("extended.choose_attachment")
    completed_dialogs(app)
    app.send("E2E_CHOSEN_DOCUMENT_QUESTION")
    response = app.reply("E2E_CHOSEN_DOCUMENT_QUESTION")
    assert "E2E_CHOSEN_DOCUMENT_CONTENT" in response["chat"]["messages"][-1]


@journey("Add an allowed file root through the real folder chooser", features=("F113",), phase=EXTENDED_PHASE)
def test_ext_17_file_root(app):
    # Prepare harmless documents as fixture data, then explicitly grant access
    # through Settings. Tools receive no access by editing configuration files.
    scope = app.state / "file-scope"
    scope.mkdir(exist_ok=True)
    (scope / "readme.txt").write_text("E2E_FILE_SOURCE: the stored colour is cerulean.\n", encoding="utf-8")
    (scope / "private.secret").write_text("E2E_PRIVATE_FILE_MUST_NOT_LEAVE_DISK", encoding="utf-8")
    app.settings("Advanced")
    if app.ui()["extended"]["file_roots"]:
        app.ui("extended.settings_folder_remove_all")
    dialogs(app, {"kind": "file", "value": str(scope)})
    app.ui("extended.settings_folder_add")
    completed_dialogs(app)
    assert [Path(p).resolve() for p in app.ui()["extended"]["file_roots"]] == [scope.resolve()]
    app.ui("settings_field", field="TOOL_FILE_BLOCKED_GLOBS", value="*.secret")
    app.save_settings()
    app.close_settings()


@journey("Files Off withholds local file tools from the actual provider", features=("F109", "F172"), phase=EXTENDED_PHASE)
def test_ext_18_files_off(app):
    # A normal prompt must not acquire local-file capabilities while Files is Off.
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="off")
    app.send("E2E_FILES_DISABLED")
    app.reply("E2E_FILES_DISABLED")
    requests = provider_requests(app, "E2E_FILES_DISABLED")
    names = [tool["function"]["name"] for tool in requests[-1].get("tools", [])]
    assert not {"read_file", "create_file", "edit_file", "write_file", "list_files"}.intersection(names)


@journey("Read-only Files reads a document and withholds writing tools", features=("F110", "F342"), phase=EXTENDED_PHASE)
def test_ext_19_read_only_files(app):
    # The model asks for a file through the real tool loop. Its response must
    # contain data read by OpenWand, and the HTTP schema must exclude writes.
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="read")
    app.send("E2E_TOOL_READ: read the permitted readme")
    response = app.reply("E2E_TOOL_READ")
    assert "E2E_FILE_SOURCE" in response["chat"]["messages"][-1]
    requests = provider_requests(app, "E2E_TOOL_READ")
    names = [tool["function"]["name"] for tool in requests[0].get("tools", [])]
    assert "read_file" in names and not {"create_file", "edit_file", "write_file"}.intersection(names)


@journey("Preview a file change, approve it and verify the actual file", features=("F111", "F343", "F352", "F353"), phase=EXTENDED_PHASE)
def test_ext_20_approve_file(app):
    # The pending preview must exist before any write. Only clicking the real
    # Approve control allows the production tool to create the scoped file.
    target = app.state / "file-scope" / "approved.txt"
    assert not target.exists()
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="ask")
    dialogs(app, {"kind": "approval", "button": "Approve", "absent_path": str(target), "capture": "test_ext_20_approve_file"})
    app.send("E2E_TOOL_CREATE_APPROVE")
    events = completed_dialogs(app)
    assert events[0]["target_existed_before_choice"] is False
    assert "approved.txt" in json.dumps(events[0]["labels"])
    app.reply("E2E_TOOL_CREATE_APPROVE")
    assert target.read_text(encoding="utf-8") == "E2E_APPROVED_FILE_CONTENT\n"


@journey("Decline a file change and verify that no file is written", features=("F355",), phase=EXTENDED_PHASE)
def test_ext_21_decline_file(app):
    # Decline must resolve the in-flight tool request and leave the disk intact.
    target = app.state / "file-scope" / "declined.txt"
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="ask")
    dialogs(app, {"kind": "approval", "button": "Decline", "absent_path": str(target), "capture": "test_ext_21_decline_file"})
    app.send("E2E_TOOL_CREATE_DECLINE")
    completed_dialogs(app)
    app.reply("E2E_TOOL_CREATE_DECLINE")
    assert not target.exists()


@journey("Create and overwrite scoped files with automatic permission", features=("F112", "F343", "F345"), phase=EXTENDED_PHASE)
def test_ext_22_automatic_files(app):
    # Writes are performed by OpenWand's actual worker/tool path, not by this
    # fixture. Verify both create and overwrite by reading the resulting file.
    target = app.state / "file-scope" / "automatic.txt"
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="auto")
    app.send("E2E_TOOL_CREATE_AUTO")
    app.reply("E2E_TOOL_CREATE_AUTO")
    assert target.read_text(encoding="utf-8") == "E2E_AUTOMATIC_FILE_CONTENT\n"
    app.send("E2E_TOOL_WRITE")
    app.reply("E2E_TOOL_WRITE")
    assert target.read_text(encoding="utf-8") == "E2E_REPLACED_FILE_CONTENT\n"


@journey("Reject file access outside the allowed root and to blocked files", features=("F113", "F114"), phase=EXTENDED_PHASE)
def test_ext_23_file_boundaries(app):
    # The provider proposes an escaping path and a blocked filename. The real
    # gateway must preserve the outside path and withhold private file content.
    app.ui("chat_new")
    app.ui("chat_context", source="files", value="auto")
    app.send("E2E_TOOL_ESCAPE")
    app.reply("E2E_TOOL_ESCAPE")
    assert any("Path escapes scope" in text for text in tool_outcomes(app, "E2E_TOOL_ESCAPE"))
    assert not (app.state / "outside-root.txt").exists()
    app.send("E2E_TOOL_BLOCKED")
    result = app.reply("E2E_TOOL_BLOCKED")
    assert any("Path is blocked" in text for text in tool_outcomes(app, "E2E_TOOL_BLOCKED"))
    assert "E2E_PRIVATE_FILE_MUST_NOT_LEAVE_DISK" not in result["chat"]["messages"][-1]
    assert "E2E_PRIVATE_FILE_MUST_NOT_LEAVE_DISK" not in json.dumps(provider_requests(app, "E2E_TOOL_BLOCKED"))


@journey("Save a memory through a model tool and find it in the viewer", features=("F309", "F308"), phase=EXTENDED_PHASE)
def test_ext_24_model_memory(app):
    # Tool invocations go from the real provider stream through the brain to
    # persistent memory. Reopen the viewer to verify the durable saved fact.
    app.ui("chat_new")
    app.ui("chat_context", source="memory", value="auto")
    app.send("E2E_MEMORY_SAVE")
    app.reply("E2E_MEMORY_SAVE")
    app.send("E2E_MEMORY_SEARCH")
    response = app.reply("E2E_MEMORY_SEARCH")
    assert "otter" in response["chat"]["messages"][-1]
    app.ui("tray", label="Memory")
    app.wait(lambda s: "memory" in s and any("E2E model memory" in fact for fact in s["memory"]["facts"]), "the model-saved memory fact")
    app.ui("close_auxiliary")
    app.chat()


@journey("Enter an exact model name and send a prompt through that route", features=("F227", "F253"), phase=EXTENDED_PHASE)
def test_ext_25_exact_model(app):
    # A manual model value must reach the actual outgoing request, not just a
    # Settings text field. Restore the normal route after checking the answer.
    app.settings("Model routing")
    app.ui("route", field="model", value="journey-exact-2026")
    app.save_settings()
    app.close_settings()
    app.ui("chat_new")
    app.send("E2E_EXACT_MODEL")
    app.reply("E2E_EXACT_MODEL")
    assert {p["model"] for p in provider_requests(app, "E2E_EXACT_MODEL")} == {"journey-exact-2026"}
    app.settings("Model routing")
    app.ui("route", field="model", value="journey-model")
    app.save_settings()
    app.close_settings()


@journey("Expand and collapse a large provider list without saving drafts", features=("F221", "F426"), phase=EXTENDED_PHASE)
def test_ext_26_large_provider_list(app):
    # Add enough actual connection rows to exercise the collapsed view. These
    # drafts are discarded; reopening must retain only the saved provider.
    app.settings()
    original = app.ui()["extended"]["connections"]
    for i in range(7):
        app.ui("settings_button", text="+ Add connection")
        app.ui("connection", field="provider", value="custom")
        app.ui("connection", field="alias", value=f"E2E draft provider {i}")
    app.ui("extended.connections_toggle")
    assert sum(r["visible"] for r in app.ui()["extended"]["connections"]) == 6
    app.ui("extended.connections_toggle")
    assert sum(r["visible"] for r in app.ui()["extended"]["connections"]) == len(original) + 7
    app.close_settings()
    app.settings()
    assert app.ui()["extended"]["connections"] == original
    app.close_settings()


@journey("Delete an inactive custom profile with Cancel and confirmation", features=("F422",), phase=EXTENDED_PHASE)
def test_ext_27_delete_profile(app):
    # Create a throwaway profile using the real name dialog, then return to the
    # working profile. Cancel must preserve it; confirmation must remove it.
    app.settings()
    dialogs(app, menu("Create custom profile..."), {"kind": "input", "title": "Create custom profile", "value": "E2E disposable profile"})
    app.ui("extended.settings_profile_menu")
    completed_dialogs(app)
    app.save_settings()
    dialogs(app, menu("Journey renamed profile"))
    app.ui("extended.settings_profile_menu")
    completed_dialogs(app)
    app.save_settings()
    for button in ("No", "Yes"):
        dialogs(app, menu("Delete profile..."), {"kind": "input", "title": "Delete profile", "value": "E2E disposable profile"}, {"kind": "button", "title": "Delete profile", "button": button})
        app.ui("extended.settings_profile_menu")
        completed_dialogs(app)
        assert ("E2E disposable profile" in app.ui()["extended"]["saved_profiles"]) == (button == "No")
    app.close_settings()
    app.settings()
    assert "E2E disposable profile" not in app.ui()["extended"]["saved_profiles"]
    app.close_settings()
    app.send("E2E_PROFILE_DELETE_SURVIVOR")
    app.reply("E2E_PROFILE_DELETE_SURVIVOR")


@journey("Click ChatGPT sign-in and recover from declined, invalid and incomplete callbacks", features=("F206", "F207"), phase=EXTENDED_PHASE)
def test_ext_28_chatgpt_sign_in_failures(app):
    # The external browser is a declared fixture, not a real signed-in account.
    # OpenWand's actual button, PKCE, loopback server and status handling run.
    output = Path(os.environ["OPENWAND_E2E_OUTPUT"])
    app.settings()
    for mode, message in (("declined", "E2E sign-in declined"), ("mismatched_state", "Sign-in state did not match"), ("missing_code", "Sign-in did not return an authorization code")):
        (output / "browser-mode.txt").write_text(mode, encoding="utf-8")
        app.ui("extended.chatgpt_sign_in")
        app.wait(lambda s, message=message: s["extended"]["chatgpt_oauth"]["login_enabled"] and message in s["extended"]["chatgpt_oauth"]["detail"], "the sign-in failure and usable retry button")
    events = json.loads((output / "browser-events.json").read_text(encoding="utf-8"))
    assert [event["mode"] for event in events] == ["declined", "mismatched_state", "missing_code"]
    assert all(event["pkce"] and event["state_present"] for event in events)
    vault = json.loads((app.state / "credentials.json").read_text(encoding="utf-8"))
    assert not any(key.startswith("chatgpt-oauth") for key in vault.get("python-ai-overlay", {}))
    app.close_settings()
    app.send("E2E_AFTER_DECLINED_SIGNIN")
    app.reply("E2E_AFTER_DECLINED_SIGNIN")


def open_picker(app):
    """Wait for real context capture to enable the icon's loading picker."""
    app.ui("extended.floating_icon")
    app.wait(lambda s: s["extended"].get("intent", {}).get("enabled") is True, "the floating-icon picker to become interactive")
    app.ui("extended.intent_new")
    app.wait(lambda s: s["extended"].get("intent", {}).get("conversation_choice", {}).get("mode") == "new", "the picker to select a new conversation")


def bubble_reply(app, previous_id, marker=None):
    """Require a new completed response actually visible in the bubble."""
    return app.wait(lambda s: (b := s["extended"].get("bubble", {})).get("response_id") != previous_id
                    and b.get("phase") == "completed" and "Journey response:" in b.get("text", "")
                    and (marker is None or marker in b["text"]), "the completed visible floating reply", timeout=90)


@journey("Click the floating icon, type a custom prompt and receive its answer", features=("F017", "F032", "F040", "F047"), phase=EXTENDED_PHASE)
def test_ext_29_floating_prompt(app):
    # Start from the actual icon, rather than the Chat window or a debug submit
    # handler. The separate final streaming audit checks these live observations
    # after the other journeys, so buffering cannot hide their results.
    app.ui("chat_close")
    open_picker(app)
    app.ui("extended.intent_choice", custom=True)
    app.wait(lambda s: s["extended"]["intent"]["input_visible"], "custom prompt input")
    app.ui(capture="test_ext_29_floating_picker")
    app.ui("extended.intent_type", text="E2E_SLOW_ICON_PROMPT")
    app.ui("extended.intent_enter")
    result = bubble_reply(app, "", "E2E_SLOW_ICON_PROMPT")
    assert result["extended"]["bubble"]["response_id"]
    assert provider_requests(app, "E2E_SLOW_ICON_PROMPT")


@journey("Cancel the floating intent picker with Escape without sending a request", features=("F043",), phase=EXTENDED_PHASE)
def test_ext_30_cancel_picker(app):
    # Cancel must close the real picker and leave the external provider untouched.
    path = Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json"
    before = len(json.loads(path.read_text(encoding="utf-8")))
    open_picker(app)
    app.ui("extended.intent_escape")
    app.wait(lambda s: "intent" not in s["extended"], "the cancelled picker to close")
    assert len(json.loads(path.read_text(encoding="utf-8"))) == before


@journey("Click the built-in What is this action and receive its actual prompt", features=("F033", "F042"), phase=EXTENDED_PHASE)
def test_ext_31_click_builtin_intent(app):
    # Distinguish this action from custom prompting: the selected built-in
    # instruction must reach the external service and produce a new response.
    previous = app.ui()["extended"].get("bubble", {}).get("response_id", "")
    open_picker(app)
    row = next(r for r in app.ui()["extended"]["intent"]["rows"] if r["label"] == "What is this?")
    app.ui("extended.intent_choice", label=row["label"])
    bubble_reply(app, previous)
    assert any(row["prompt"] in str(message.get("content", "")) for payload in provider_requests(app, row["prompt"]) for message in payload["messages"])


@journey("Choose Explain simply using its single-key intent shortcut", features=("F034", "F041"), phase=EXTENDED_PHASE)
def test_ext_32_keyboard_builtin_intent(app):
    # A different built-in action uses the real picker shortcut, not a direct
    # signal or business-method call. Its own instruction must reach the model.
    previous = app.ui()["extended"].get("bubble", {}).get("response_id", "")
    open_picker(app)
    row = next(r for r in app.ui()["extended"]["intent"]["rows"] if r["label"] == "Explain simply")
    app.ui("extended.intent_choice", label=row["label"], keyboard=True)
    bubble_reply(app, previous)
    assert any(row["prompt"] in str(message.get("content", "")) for payload in provider_requests(app, row["prompt"]) for message in payload["messages"])


@journey("Click the floating answer to open its conversation and follow up", features=("F134", "F148"), phase=EXTENDED_PHASE)
def test_ext_33_bubble_to_chat(app):
    # The compact answer must lead into the same durable conversation. A new
    # Chat prompt must include the earlier built-in request in its history.
    app.ui("extended.bubble_open_chat")
    app.wait(lambda s: "chat" in s, "Chat opened by clicking the bubble")
    assert any("Journey response:" in text for text in app.ui()["chat"]["messages"])
    app.send("E2E_FROM_FLOATING_FOLLOWUP")
    app.reply("E2E_FROM_FLOATING_FOLLOWUP")
    assert "Explain this as simply as possible." in json.dumps(provider_requests(app, "E2E_FROM_FLOATING_FOLLOWUP"))


@journey("Replace a connection key, show authentication failure and recover", features=("F222", "F051"), phase=EXTENDED_PHASE)
def test_ext_34_credential_change(app):
    # The HTTP service rejects the wrong key. Saving a replacement must reload
    # the existing connection, rather than silently keeping its cached client.
    app.settings()
    index = next(i for i, row in enumerate(app.ui()["extended"]["connections"]) if row["alias"] == "Journey provider")
    app.ui("connection", index=index, field="key", value="e2e-invalid-for-test")
    app.save_settings()
    app.close_settings()
    app.ui("chat_new")
    app.send("E2E_BAD_CREDENTIAL")
    app.wait(lambda s: "chat" in s and not s["chat"]["streaming"] and s["chat"]["send_enabled"]
             and any("Journey credential rejected" in m for m in s["chat"]["messages"]), "the real authentication error and usable controls")
    rows = json.loads((Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json").read_text(encoding="utf-8"))
    assert any(not row["authenticated"] and "E2E_BAD_CREDENTIAL" in json.dumps(row["payload"]) for row in rows)
    app.settings()
    app.ui("connection", index=index, field="key", value="e2e-disposable-credential")
    app.save_settings()
    app.close_settings()
    app.send("E2E_CREDENTIAL_RECOVERED")
    app.reply("E2E_CREDENTIAL_RECOVERED")


@journey("Complete the extended stories and retain their last conversation", features=("F144", "F148"), phase=EXTENDED_PHASE)
def test_ext_99_complete(app):
    # Leave a distinctive completed turn for the next independent app launch to
    # reopen. The restart test cannot seed or invent this persisted response.
    app.chat()
    app.ui("chat_new")
    app.send("E2E_EXTENDED_COMPLETE")
    app.reply("E2E_EXTENDED_COMPLETE")
