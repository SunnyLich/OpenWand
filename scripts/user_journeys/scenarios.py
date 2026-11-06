"""Numbered user journeys executed against the complete running application.

Read each function as a user story: comments describe the action, followed by
checks of the visible result. The report links to these exact function ranges.
Hosted runs simulate the external provider, credential vault and desktop input.
OpenWand's UI, controller, model and persistence handlers are not replaced.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

CASES = []
PHASES = ("onboarding", "initial", "basics", "addons", "agents", "workspace", "extended", "restart")


def journey(title, *, features=(), phase="initial", independent=False, requires=()):
    """Register a readable source section without declaring it passed."""
    def register(function):
        CASES.append({"id": function.__name__, "title": title, "features": list(features), "phase": phase, "function": function,
                      "independent": independent, "requires": list(requires),
                      "source_path": function.__module__.replace(".", "/") + ".py"})
        return function
    return register


class App:
    """Send user input to the real UI worker and observe its visible state."""

    def __init__(self, supervisor):
        self.supervisor = supervisor
        self.steps = []
        self.state = Path(os.environ["OPENWAND_E2E_STATE"])

    def ui(self, action="snapshot", **params):
        result = self.supervisor.call("ui", "ui.debug.user_journey", {"action": action, **params}, timeout=30)
        # Retain actions and observations, never typed credentials.
        safe = dict(params)
        if safe.get("field") in {"key", "provider_key"}:
            safe["value"] = "[test credential omitted]"
        self.steps.append({"action": action, "parameters": safe, "observation": result})
        if not params.get("capture"):
            assert not result.get("extended", {}).get("dialog_errors"), result.get("extended", {}).get("dialog_errors")
        return result

    def wait(self, predicate, description, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.ui()
            if predicate(result):
                return result
            time.sleep(0.15)
        raise AssertionError(f"Timed out waiting for {description}; last observation: {result}")

    def settings(self, page="Connections"):
        self.ui("tray", label="Settings")
        self.wait(lambda s: "settings" in s, "Settings to open")
        self.ui("settings_page", page=page)

    def close_settings(self):
        self.ui("settings_button", text="Cancel")
        self.wait(lambda s: "settings" not in s, "Settings to close")

    def save_settings(self):
        # Dirty-state calculation is asynchronous. Wait until the user can
        # actually press Save; never force a disabled control or call _do_save.
        self.wait(lambda s: s.get("settings", {}).get("save_enabled") is True, "Save changes to become available")
        self.ui("settings_button", text="Save changes")
        self.wait(lambda s: s.get("settings", {}).get("save_enabled") is False, "the settings write and runtime reload")

    def chat(self):
        self.ui("tray", label="Last chat")
        return self.wait(lambda s: "chat" in s, "Chat to open")

    def send(self, text):
        self.ui("chat_type", text=text)
        self.ui("chat_send")

    def reply(self, marker):
        result = self.wait(
            lambda s: "chat" in s and not s["chat"]["streaming"] and s["chat"]["send_enabled"]
            and any("Journey response:" in m and marker in m for m in s["chat"]["messages"]),
            f"a visible completed provider response containing {marker!r}",
            timeout=60,
        )
        # A visible answer alone is insufficient: the independent HTTP service
        # must also have received this marker through the production client.
        rows = json.loads((Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json").read_text(encoding="utf-8"))
        assert any(row.get("authenticated") and marker in json.dumps(row["payload"].get("messages", [])) for row in rows), f"No authenticated provider request for visible answer {marker!r}"
        return result

    def request(self, marker):
        """Read the independent HTTP service's evidence, not the app's belief."""
        # The runner sets this environment variable to this run's report folder.
        # Read the provider's list of received requests from its JSON log file.
        path = Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "provider-requests.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        # Keep requests whose latest message contains this test's unique text.
        matches = [row for row in rows if marker in json.dumps(row["payload"].get("messages", [])[-1])]
        # Each assert stops the test if its condition is false. The [-1] means
        # the last matching request; payload is the body sent to the provider.
        assert matches, f"No real HTTP request arrived for {marker}"
        assert matches[-1]["path"] == "/v1/chat/completions"
        assert matches[-1]["authenticated"], "The configured fake credential did not reach the provider"
        assert matches[-1]["payload"]["model"] == "journey-model"
        return matches[-1]["payload"]


@journey("Fresh first launch opens the setup wizard", features=("F004",), phase="onboarding")
def test_setup_01_first_launch(app):
    # An empty user profile must reach the real first-start screen automatically.
    result = app.wait(lambda s: "wizard" in s, "the first-run wizard")
    assert result["wizard"]["page"] == 0


@journey("Choose language, theme and advanced setup", features=("F006", "F007", "F008", "F009"), phase="onboarding")
def test_setup_02_preferences(app):
    # Use the first screen's real controls, including Back navigation.
    app.ui("wizard_field", field="app_language", value="en")
    app.ui("wizard_field", field="assistant_language", value="English")
    app.ui("wizard_field", field="theme_mode", value="dark")
    app.ui("wizard_button", button="next")
    app.ui("wizard_button", button="back")
    assert app.ui()["wizard"]["page"] == 0
    app.ui("wizard_button", button="next")
    app.ui("wizard_field", field="advanced_mode", value=True)
    app.ui("wizard_button", button="next")
    # A blank name must prevent continuing; typing a valid name enables it.
    assert not app.ui()["wizard"]["next_enabled"]
    app.ui("wizard_field", field="name", value="Acceptance user")
    app.ui("wizard_button", button="next")
    assert app.ui()["wizard"]["page"] == 3


@journey("Configure a provider and finish first-run setup", features=("F010", "F012", "F013", "F014"), phase="onboarding")
def test_setup_03_provider_and_finish(app):
    # The wizard stores the key through its normal keyring API and applies the
    # saved profile through the normal Settings-to-supervisor reload callback.
    app.ui("wizard_field", field="provider", value="custom")
    app.ui("wizard_field", field="provider_model", value="journey-model", typed=True)
    app.ui("wizard_field", field="custom_base_url", value=os.environ["OPENWAND_E2E_PROVIDER_URL"])
    app.ui("wizard_field", field="provider_key", value="e2e-wizard-credential")
    app.ui("wizard_button", button="next")
    # Skip optional ChatGPT OAuth explicitly. This test never claims a live login.
    app.ui("wizard_button", button="next")
    app.ui("wizard_field", field="tts", value="none")
    app.ui("wizard_field", field="stt", value="none")
    app.ui("wizard_button", button="next")
    app.ui("wizard_field", field="open_chat", value=True)
    app.ui("wizard_button", button="next")
    app.wait(lambda s: "wizard" not in s, "setup completion")
    app.wait(lambda s: "chat" in s, "the automatic first chat after setup")


@journey("Send the first prompt with the provider chosen during setup", features=("F010", "F144"), phase="onboarding")
def test_setup_04_first_prompt(app):
    # Completing setup is insufficient: its saved credentials must actually
    # reach the SDK in a different worker and produce a visible response.
    app.chat()
    app.send("E2E_ONBOARDING_PROMPT")
    app.reply("E2E_ONBOARDING_PROMPT")


@journey("Launch the app and open Settings from its tray", features=("F002", "F025"))
def test_01_launch_and_open_settings(app):
    # The parent launcher has already required four distinct real worker PIDs.
    # Use the actual tray action, then verify a window the user can interact with.
    app.settings()
    snapshot = app.ui()
    assert "SettingsDialog" in snapshot["windows"]
    assert snapshot["settings"]["page"] == "Connections"


@journey("Add a custom provider with alias, endpoint and credential", features=("F215", "F216", "F223"))
def test_02_add_provider(app):
    # Add and fill the production connection row; no configuration file is edited.
    app.ui("settings_button", text="+ Add connection")
    app.ui("connection", field="provider", value="custom")
    app.ui("connection", field="alias", value="Journey provider")
    app.ui("connection", field="endpoint_combo", value="")
    app.ui("connection", field="custom_address", value=os.environ["OPENWAND_E2E_PROVIDER_URL"])
    app.ui("connection", field="key", value="e2e-disposable-credential")
    row = app.ui()["settings"]["connections"][-1]
    assert row["alias"] == "Journey provider" and row["provider"] == "custom"
    assert row["id"], "A real connection identity must be assigned"


@journey("Select the new provider for Chat, Image and Memory routes", features=("F253", "F256", "F259"))
def test_03_select_model_routes(app):
    # Choose the user-created connection and an exact model through visible controls.
    connection = app.ui()["settings"]["connections"][-1]
    app.ui("settings_page", page="Model routing")
    for section in ("LLM", "VISION_LLM", "MEMORY_LLM"):
        app.ui("route", section=section, field="provider", value="custom@" + connection["id"])
        app.ui("route", section=section, field="model", value="journey-model")
    routes = app.ui()["settings"]["routes"]
    assert all(rows[0]["model"] == "journey-model" for rows in routes.values())


@journey("Save provider settings, close and reopen Settings", features=("F425",))
def test_04_save_and_reopen_provider(app):
    # Click Save and wait for the real write, config reload and dirty-state reset.
    app.save_settings()
    app.wait(lambda s: not s["settings"]["save_enabled"], "saved Settings")
    app.close_settings()
    app.settings()
    connections = app.ui()["settings"]["connections"]
    assert any(row["alias"] == "Journey provider" for row in connections)
    app.close_settings()


@journey("Prompt using the provider added in Settings", features=("F144", "F146"))
def test_05_prompt(app):
    # Type into the real composer. The production brain/SDK must contact HTTP.
    app.chat()
    app.ui("chat_type", text="E2E_FIRST_PROMPT: explain the number seven")
    app.ui("chat_key", key="Return")
    app.reply("E2E_FIRST_PROMPT")
    app.request("E2E_FIRST_PROMPT")
    # The final text must replace loading state, and Send must work again.
    visible = app.ui()["chat"]
    assert not any(message == "Preparing response..." for message in visible["messages"])
    assert visible["input"] == ""


@journey("Follow up with prior conversation context", features=("F148",))
def test_06_follow_up(app):
    # The provider echoes the received history, making lost context observable.
    app.send("E2E_FOLLOW_UP: what did I ask before?")
    result = app.reply("E2E_FOLLOW_UP")["chat"]
    assert "E2E_FIRST_PROMPT" in result["messages"][-1]


@journey("Close Chat and reopen the retained conversation", features=("F144", "F148"))
def test_07_reopen_chat(app):
    # Closing a window must not discard the completed conversation.
    app.ui("chat_close")
    result = app.chat()["chat"]
    assert any("E2E_FOLLOW_UP" in message for message in result["messages"])


@journey("Start a new conversation with the platform's New shortcut", features=("F145",))
def test_08_new_conversation(app):
    # Exercise the actual keyboard shortcut and prove old history is not sent.
    previous = app.ui()["extended"]
    previous_id = previous["conversations"][previous["active_conversation"]]["id"]
    app.ui("chat_new")
    current = app.ui()["extended"]
    assert current["conversations"][current["active_conversation"]]["id"] != previous_id
    assert app.ui()["chat"]["messages"] == []
    app.send("E2E_NEW_CONVERSATION")
    result = app.reply("E2E_NEW_CONVERSATION")["chat"]
    assert "E2E_FIRST_PROMPT" not in result["messages"][-1]


@journey("Drop a text file, prompt about it and receive its content", features=("F162", "F163"))
def test_09_file_attachment(app):
    # Prepare a user document, then deliver a file-drop event to the real window.
    document = app.state / "journey-attachment.txt"
    document.write_text("E2E_ATTACHMENT_CONTENT: the project colour is violet.", encoding="utf-8")
    app.ui("chat_drop", path=str(document))
    assert any(document.name in label for label in app.ui()["chat"]["labels"]), "Pending file name is not visible"
    app.send("E2E_FILE_QUESTION: describe the attached document")
    result = app.reply("E2E_FILE_QUESTION")["chat"]
    assert "E2E_ATTACHMENT_CONTENT" in result["messages"][-1]


@journey("Show a provider error and return to usable controls", features=("F051",))
def test_10_provider_error(app):
    # The HTTP service returns a genuine failing response; no UI error is injected.
    app.ui("chat_new")
    app.send("E2E_FORCE_ERROR")
    result = app.wait(
        lambda s: "chat" in s and not s["chat"]["streaming"]
        and any("Journey provider temporarily unavailable" in m for m in s["chat"]["messages"]),
        "the provider error to be visible", timeout=75,
    )["chat"]
    assert result["send_enabled"]


@journey("Send successfully after a failed provider request", features=("F051", "F148"))
def test_11_error_recovery(app):
    # Continue the failed conversation. Error text must not poison the next request.
    app.send("E2E_RECOVERED_PROMPT")
    app.reply("E2E_RECOVERED_PROMPT")


@journey("Cancel streaming and send another prompt", features=("F052",))
def test_12_cancel_and_send_again(app):
    # Stop a reply while bytes are arriving, then verify a new turn can finish.
    app.ui("chat_new")
    app.send("E2E_SLOW: " + "long answer please " * 30)
    app.wait(lambda s: s.get("chat", {}).get("streaming") is True, "streaming to begin")
    app.ui("bubble_stop")
    app.wait(lambda s: not s["chat"]["streaming"], "cancellation to finish")
    app.ui("chat_new")
    app.send("E2E_AFTER_CANCEL")
    app.reply("E2E_AFTER_CANCEL")


@journey("Visit all Settings pages and return to Chat", features=("F417",))
def test_13_settings_navigation(app):
    # Each page must remain accessible in the running app after actual requests.
    app.settings()
    pages = app.ui()["settings"]["pages"]
    assert len(pages) == 8
    for page in pages:
        result = app.ui("settings_page", page=page)
        assert result["settings"]["page"] == page
    app.close_settings()


@journey("Change appearance, save it and continue prompting", features=("F429", "F425"))
def test_14_appearance_and_prompt(app):
    # Save through production Settings; workers must still handle the next turn.
    previous_colour = app.ui()["theme_background"]
    app.settings("General")
    app.ui("settings_field", field="THEME_MODE", value="light")
    app.save_settings()
    app.wait(lambda s: not s["settings"]["save_enabled"], "appearance settings to save")
    app.close_settings()
    assert app.ui()["theme_background"] != previous_colour, "Saved theme never reached the running application"
    app.send("E2E_AFTER_APPEARANCE_SAVE")
    app.reply("E2E_AFTER_APPEARANCE_SAVE")


@journey("Discard an unsaved provider alias change", features=("F426", "F216"))
def test_15_discard_settings(app):
    # Cancel must preserve the saved connection, not merely close the dialog.
    app.settings()
    app.ui("connection", field="alias", value="Discard this alias")
    app.close_settings()
    app.settings()
    aliases = [r["alias"] for r in app.ui()["settings"]["connections"]]
    assert "Journey provider" in aliases and "Discard this alias" not in aliases
    app.close_settings()


@journey("Open Memory and Addon Manager from the running app", features=("F023", "F024", "F315", "F358"))
def test_16_auxiliary_windows(app):
    # These are the actual tray destinations, not separately constructed widgets.
    for label, window in (("Memory", "MemoryViewer"), ("Addon Manager", "Addon Manager")):
        app.ui("tray", label=label)
        result = app.wait(lambda s, expected=window: any(expected in name for name in (*s["windows"], *s["titles"])), label)
        assert result["titles"]
        app.ui("close_auxiliary")
    app.chat()


@journey("Add a memory fact and reopen the actual Memory viewer", features=("F315", "F317", "F321"))
def test_16b_memory_persistence(app):
    # Adding a fact crosses UI -> supervisor -> brain -> durable memory store.
    app.ui("tray", label="Memory")
    app.wait(lambda s: "memory" in s and not s["memory"]["loading"], "Memory to load")
    app.ui("memory_add", text="E2E memory fact: the project code is violet.")
    app.wait(lambda s: any("E2E memory fact" in fact for fact in s["memory"]["facts"]), "saved memory fact")
    app.ui("memory_refresh")
    app.wait(lambda s: not s["memory"]["loading"] and any("E2E memory fact" in fact for fact in s["memory"]["facts"]), "the saved fact after Refresh")
    app.ui("close_auxiliary")
    app.ui("tray", label="Memory")
    app.wait(lambda s: "memory" in s and any("E2E memory fact" in fact for fact in s["memory"]["facts"]), "the retained fact after reopening")
    app.ui("close_auxiliary")
    app.chat()


@journey("Switch Enter behaviour and send a multiline prompt", features=("F146",))
def test_16c_multiline_input(app):
    # The composer option changes actual key handling, not just its checkbox.
    app.ui("chat_new")
    app.ui("chat_menu", text="Enter sends message")

    app.ui("chat_type", text="E2E_MULTILINE")
    app.ui("chat_key", key="Return")
    result = app.ui()["chat"]
    assert not result["streaming"] and result["input"].endswith("\n")
    app.ui("chat_key", key="Return", control=True)
    app.reply("E2E_MULTILINE")
    app.ui("chat_menu", text="Enter sends message")

    # With Enter-to-send restored, Shift+Enter must insert a newline instead.
    app.ui("chat_new")
    app.ui("chat_type", text="E2E_SHIFT_NEWLINE")
    app.ui("chat_key", key="Return", shift=True)
    result = app.ui()["chat"]
    assert not result["streaming"] and result["input"].endswith("\n")
    app.ui("chat_send")
    app.reply("E2E_SHIFT_NEWLINE")


@journey("Search conversation history without discarding it", features=("F150",))
def test_16d_history_search(app):
    # A search with no matches hides rows, and clearing it restores them.
    before = app.ui()["chat"]["history_visible"]
    assert before
    app.ui("chat_search", text="NO_SUCH_CONVERSATION_E2E")
    app.wait(lambda s: not s["chat"]["history_visible"], "empty history search")
    app.ui("chat_search", text="")
    app.wait(lambda s: len(s["chat"]["history_visible"]) == len(before), "restored history")
    indices = app.ui()["chat"]["history_indices"]
    app.ui("chat_history", index=min(indices))
    assert any("E2E_FIRST_PROMPT" in text for text in app.ui()["chat"]["messages"])
    app.ui("chat_history", index=max(indices))
    assert any("E2E_SHIFT_NEWLINE" in text for text in app.ui()["chat"]["messages"])


@journey("Enable privacy filtering and verify the actual outgoing request", features=("F323", "F329"))
def test_16e_privacy_before_network(app):
    # Configure built-in privacy through Settings, then send a synthetic email.
    # Inspect the independent HTTP server's payload so a visual-only redaction
    # cannot pass while the private value is still transmitted.
    app.settings("General")
    app.ui("settings_field", field="PRIVACY_MODE", value="builtin")
    app.ui("settings_field", field="PRIVACY_REVIEW_BEFORE_SEND", value=False)
    app.save_settings()
    app.wait(lambda s: not s["settings"]["save_enabled"], "privacy settings to save")
    app.close_settings()
    app.ui("chat_new")
    app.send("E2E_PRIVACY: Contact alex@example.com about the project")
    app.reply("E2E_PRIVACY")
    sent = json.dumps(app.request("E2E_PRIVACY"))
    assert "alex@example.com" not in sent, "The provider received the private value"
    assert "[EMAIL_" in sent, "No privacy replacement reached the provider"
    # Restore the baseline by the same visible settings flow.
    app.settings("General")
    app.ui("settings_field", field="PRIVACY_MODE", value="off")
    app.save_settings()
    app.wait(lambda s: not s["settings"]["save_enabled"], "baseline privacy mode to save")
    app.close_settings()


@journey("Change browser context access and verify the actual model request", features=("F166",))
def test_16f_context_controls_reach_provider(app):
    # The same conversation changes its Browser/Web chip from Off to model
    # control. Check the received tool definitions, not only the chip label.
    app.ui("chat_new")
    app.ui("chat_context", source="browser", value="off")
    app.send("E2E_CONTEXT_OFF")
    app.reply("E2E_CONTEXT_OFF")
    off_tools = json.dumps(app.request("E2E_CONTEXT_OFF").get("tools", []))
    assert "get_context" not in off_tools
    app.ui("chat_context", source="browser", value="auto")
    app.send("E2E_CONTEXT_AUTO")
    app.reply("E2E_CONTEXT_AUTO")
    on_tools = json.dumps(app.request("E2E_CONTEXT_AUTO").get("tools", []))
    assert "get_context" in on_tools
    app.send("E2E_CONTEXT_AUTO_FOLLOWUP")
    app.reply("E2E_CONTEXT_AUTO_FOLLOWUP")
    assert "get_context" in json.dumps(app.request("E2E_CONTEXT_AUTO_FOLLOWUP").get("tools", []))


@journey("After a full app restart, reopen saved provider and conversation", features=("F425", "F144", "F148"), phase="restart")
def test_17_restart_and_prompt(app):
    # The outer runner starts a new supervisor and all four new worker processes.
    # Nothing here seeds settings or conversation state for that second launch.
    app.settings()
    assert any(r["alias"] == "Journey provider" for r in app.ui()["settings"]["connections"])
    app.close_settings()
    result = app.chat()["chat"]
    assert any("E2E_EXTENDED_COMPLETE" in m for m in result["messages"])
    app.send("E2E_AFTER_PROCESS_RESTART")
    app.reply("E2E_AFTER_PROCESS_RESTART")


@journey("Verify answer text was visible before the floating request finished", features=("F049",), phase="restart")
def test_18_audit_visible_streaming(app):
    # Run this audit last so a buffering failure does not prevent unrelated
    # journeys from running. Inspect the earlier real UI observations, not a
    # model callback or a final answer that merely looks like streamed text.
    app.ui()
    output = Path(os.environ["OPENWAND_E2E_OUTPUT"])
    results = json.loads((output / "extended-results.json").read_text(encoding="utf-8"))
    case = next(row for row in results if row["id"] == "test_ext_29_floating_prompt")
    final_id = case["evidence"]["extended"]["bubble"]["response_id"]
    requests = json.loads((output / "provider-requests.json").read_text(encoding="utf-8"))
    request = next(row for row in requests if row.get("authenticated") and "E2E_SLOW_ICON_PROMPT" in json.dumps(row["payload"].get("messages", [])))
    finished = request["response_finished_monotonic_ns"]
    observations = [step.get("observation", {}) for step in case["steps"]]
    assert any((b := s.get("extended", {}).get("bubble", {})).get("response_id") == final_id
               and b.get("phase") == "streaming" and "Journey response:" in b.get("text", "")
               and request["received_monotonic_ns"] < s["observed_monotonic_ns"] < finished for s in observations), (
        "No partial answer was visible before the provider response finished. "
        "The current response pipeline buffers the complete answer before displaying it."
    )


def run_journeys(supervisor):
    """Run the registered stories, writing a result even when a story fails."""
    desktop = supervisor.call("native", "native.context.snapshot", {}, timeout=10)
    assert desktop.get("debug", {}).get("external_boundary") == "synthetic desktop input", "Refusing to run user journeys with personal desktop context"
    app = App(supervisor)
    phase = os.environ.get("OPENWAND_E2E_PHASE", "initial")
    output = Path(os.environ["OPENWAND_E2E_OUTPUT"])
    results = []
    statuses = {}
    failed = False
    debug_start = os.environ.get("OPENWAND_E2E_DEBUG_START", "")
    eligible = [case["id"] for case in CASES if case["phase"] == phase]
    if debug_start:
        assert phase in {"basics", "addons", "agents", "workspace", "extended"} and debug_start in eligible, "Invalid partial debug journey"
    for case in CASES:
        if case["phase"] != phase:
            continue
        if debug_start and case["id"] != eligible[0] and eligible.index(case["id"]) < eligible.index(debug_start):
            continue
        result = {key: value for key, value in case.items() if key != "function"}
        missing = [name for name in case["requires"] if statuses.get(name) != "passed"]
        blocked = bool(missing) if case["independent"] else failed
        result["status"] = "blocked" if blocked else "running"
        app.steps = []
        started = time.monotonic()
        if not blocked:
            try:
                if failed and case["independent"]:
                    # Preserve the earlier failure first, then use only normal
                    # Cancel/Escape/Stop controls to reach the next independent
                    # story. Recovery never turns the earlier failure green.
                    app.ui("extended.recover_ui")
                case["function"](app)
                result["status"] = "passed"
            except Exception:
                result["status"] = "failed"
                result["error"] = traceback.format_exc()
                failed = True
            try:
                result["evidence"] = app.ui(capture=case["id"])
            except Exception as error:
                result["capture_error"] = str(error)
                result["status"] = "failed"
                failed = True
        else:
            result["error"] = ("Required journeys did not pass: " + ", ".join(missing)) if missing else "An earlier prerequisite journey failed; this journey was not executed."
        result["seconds"] = round(time.monotonic() - started, 3)
        result["steps"] = app.steps
        results.append(result)
        statuses[case["id"]] = result["status"]
        destination = output / f"{phase}-results.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(results, indent=2), encoding="utf-8")
        temporary.replace(destination)
        print(f"[user-journey] {case['id']}: {result['status']}", flush=True)
    if failed and phase in {"onboarding", "initial"}:
        raise RuntimeError(f"User journeys failed in phase {phase}; inspect {output / (phase + '-results.json')}")
    return results


# Importing registers additional source-linked cases without replacing the
# existing core stories or running any application code at import time.
from scripts.user_journeys.addon_scenarios import ADDON_PHASE  # noqa: E402
from scripts.user_journeys.agent_scenarios import AGENT_PHASE  # noqa: E402
from scripts.user_journeys.basic_scenarios import BASIC_PHASE  # noqa: E402
from scripts.user_journeys.extended_scenarios import EXTENDED_PHASE  # noqa: E402
from scripts.user_journeys.workspace_scenarios import WORKSPACE_PHASE  # noqa: E402

assert EXTENDED_PHASE in PHASES
assert BASIC_PHASE in PHASES
assert ADDON_PHASE in PHASES
assert AGENT_PHASE in PHASES
assert WORKSPACE_PHASE in PHASES
CASES.sort(key=lambda case: PHASES.index(case["phase"]))
