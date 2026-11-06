"""Scoped Agent Team tasks through the tray, real runner, SDK and saved results."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.user_journeys.basic_scenarios import new, no_network, requests, test_basic_01_reopen
from scripts.user_journeys.extended_scenarios import completed_dialogs, dialogs
from scripts.user_journeys.scenarios import journey as register_journey

AGENT_PHASE = "agents"


def journey(title, *, features=(), requires=()):
    def register(function):
        dependencies = [] if function.__name__ == "test_agent_01_open_cancel" else ["test_agent_01_open_cancel", *requires]
        return register_journey(title, features=features, phase=AGENT_PHASE, independent=True, requires=dependencies)(function)
    return register


def designer(app):
    app.ui("extended.agent_close_all")
    app.ui("tray", label="Start Agent Team...")
    app.wait(lambda s: "agent_task" in s["extended"], "the real Agent Team task designer")


def configure(app, title, marker, *, create=False):
    """Type a task scoped only to a disposable folder, with shell/network denied."""
    scope = app.state / ("agent-scope-" + marker.lower())
    scope.mkdir(exist_ok=True)
    for field, value in (("title_edit", title), ("objective_edit", marker), ("scope_edit", str(scope)),
                         ("provider_combo", "same as app"), ("parallel_briefing", False), ("parallel_execution", False),
                         ("max_turns", 8), ("runtime_minutes", 2), ("allow_shell", "never permit"),
                         ("allow_network", "never permit"), ("allow_git", "never permit"),
                         ("allow_create", "auto" if create else "never permit"), ("allow_edit", "never permit"), ("allow_delete", "never permit")):
        app.ui("extended.agent_field", field=field, value=value)
    return scope


def finished(app, marker="E2E_AGENT_SUCCESS"):
    """Require the displayed final report, finished controls and independent HTTP."""
    result = app.wait(lambda s: marker in s["extended"].get("agent_run", {}).get("final", "")
                      and not s["extended"]["agent_run"]["cancel_enabled"], "the completed visible Agent Team report", timeout=90)
    folder = Path(result["extended"]["agent_run"]["run_dir"]).resolve()
    assert folder.is_relative_to(app.state.resolve()), "Agent artifacts escaped disposable state"
    assert marker in (folder / "final.md").read_text(encoding="utf-8")
    return folder


@journey("Open the agent task designer from the tray and cancel it", features=("F379",))
def test_agent_01_open_cancel(app):
    # Opening and cancelling the real designer must not start a model request.
    test_basic_01_reopen(app)
    before = len(requests(app))
    designer(app)
    assert app.ui()["extended"]["agent_task"]["agents"] >= 1
    app.ui("extended.agent_button", text="Cancel")
    app.wait(lambda s: "agent_task" not in s["extended"], "the cancelled task designer")
    no_network(app, before)


@journey("Reject starting an agent task without a title", features=("F381",))
def test_agent_02_missing_title(app):
    # Real form validation must keep the designer open and make no model call.
    designer(app)
    app.ui("extended.agent_field", field="title_edit", value="")
    before = len(requests(app))
    dialogs(app, {"kind": "button", "title": "Invalid Agent Team", "button": "OK"})
    app.ui("extended.agent_button", text="Start Task")
    events = completed_dialogs(app)
    assert any("title" in " ".join(event.get("labels", [])).lower() for event in events)
    no_network(app, before)
    app.ui("extended.agent_button", text="Cancel")


@journey("Reject starting an agent task without an objective", features=("F381",))
def test_agent_03_missing_objective(app):
    # Validation must distinguish the missing objective from the title check.
    designer(app)
    app.ui("extended.agent_field", field="title_edit", value="Journey invalid objective")
    app.ui("extended.agent_field", field="objective_edit", value="")
    before = len(requests(app))
    dialogs(app, {"kind": "button", "title": "Invalid Agent Team", "button": "OK"})
    app.ui("extended.agent_button", text="Start Task")
    events = completed_dialogs(app)
    assert any("objective" in " ".join(event.get("labels", [])).lower() for event in events)
    no_network(app, before)
    app.ui("extended.agent_button", text="Cancel")


@journey("Preview a scoped task specification before starting work", features=("F381", "F385", "F398"))
def test_agent_04_preview_spec(app):
    # Preview must show the actual collected spec but start no worker/model turn.
    designer(app)
    scope = configure(app, "Journey preview agent", "E2E_AGENT_PREVIEW")
    before = len(requests(app))
    dialogs(app, {"kind": "button", "title": "Agent Team Spec", "button": "Close"})
    app.ui("extended.agent_button", text="Preview Spec")
    events = completed_dialogs(app)
    text = "\n".join(value for event in events for value in event.get("text", []))
    assert "Journey preview agent" in text and "E2E_AGENT_PREVIEW" in text and str(scope) in text
    assert "never permit" in text
    no_network(app, before)
    app.ui("extended.agent_button", text="Cancel")


@journey("Start an agent task and receive its saved final report", features=("F379", "F381", "F399", "F403"))
def test_agent_05_complete_task(app):
    # Start Task must run the production agent JSON loop and real SDK, then show
    # and persist its final report. No model callback or runner is substituted.
    designer(app)
    configure(app, "Journey smoke agent", "E2E_AGENT_SMOKE")
    app.ui("extended.agent_button", text="Start Task")
    folder = finished(app)
    spec = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    assert spec["title"] == "Journey smoke agent"
    assert any(row["authenticated"] and "E2E_AGENT_SMOKE" in json.dumps(row["payload"]) for row in requests(app))
    assert (folder / "turns.json").is_file() and (folder / "run.log").is_file()
    app.ui("extended.agent_close_all")


@journey("Copy the last started agent task into a new task designer", features=("F380",), requires=("test_agent_05_complete_task",))
def test_agent_06_copy_last_task(app):
    # Copy from Last Task must read the real earlier submission, not test seed data.
    designer(app)
    dialogs(app, {"kind": "button", "title": "Copied", "button": "OK"})
    app.ui("extended.agent_button", text="Copy from Last Task")
    completed_dialogs(app)
    result = app.ui()["extended"]["agent_task"]
    assert result["title"] == "Journey smoke agent" and result["objective"] == "E2E_AGENT_SMOKE"
    assert Path(result["scope"]).is_relative_to(app.state)
    assert result["max_turns"] == 8 and result["parallel_briefing"] is False
    app.ui("extended.agent_button", text="Cancel")


@journey("Run an agent team that creates a scoped file and hands work between roles", features=("F385", "F387", "F399"))
def test_agent_07_scoped_team_write(app):
    # The model fixture requests a create_file call and handoffs; the real agent
    # runner must enforce scope, write the file and persist the executed turns.
    designer(app)
    scope = configure(app, "Journey writing team", "E2E_AGENT_TEAM_WRITE", create=True)
    app.ui("extended.agent_button", text="Start Task")
    folder = finished(app)
    assert (scope / "e2e-agent-output.txt").read_text(encoding="utf-8") == "E2E_AGENT_CREATED_FILE\n"
    turns = json.loads((folder / "turns.json").read_text(encoding="utf-8"))
    assert len(turns) >= 3 and "create_file" in json.dumps(turns)
    assert "Builder" in json.dumps(turns) and "Reviewer" in json.dumps(turns)
    app.ui("extended.agent_close_all")


@journey("Cancel a running agent task and return to usable controls", features=("F413",))
def test_agent_08_cancel_task(app):
    # Cancel only after an authenticated request actually reaches the provider,
    # before its deliberately slow response finishes.
    designer(app)
    configure(app, "Journey cancelled agent", "E2E_SLOW_AGENT_CANCEL")
    app.ui("extended.agent_button", text="Start Task")
    app.wait(lambda s: s["extended"].get("agent_run", {}).get("cancel_enabled") is True
             and any("E2E_SLOW_AGENT_CANCEL" in json.dumps(row["payload"]) for row in requests(app)), "the running authenticated agent task")
    app.ui("extended.agent_button", kind="run", text="Cancel")
    result = app.wait(lambda s: "cancel" in s["extended"].get("agent_run", {}).get("final", "").lower()
                      and not s["extended"]["agent_run"]["cancel_enabled"], "the cancelled task's final state", timeout=45)
    assert "E2E_AGENT_SUCCESS" not in result["extended"]["agent_run"]["final"]
    app.ui("extended.agent_close_all")


@journey("Reopen a finished agent run from history and inspect its report and logs", features=("F414", "F415"), requires=("test_agent_05_complete_task",))
def test_agent_09_history(app):
    # The history window must load saved artifacts after the activity window closes.
    app.ui("tray", label="Agent Team Activity...")
    app.wait(lambda s: "agent_history" in s["extended"], "Agent Team history")
    app.ui("extended.agent_history_select", title="Journey smoke agent")
    app.wait(lambda s: "E2E_AGENT_SUCCESS" in s["extended"]["agent_history"]["text"], "the retained final report")
    for tab, marker in (("Run Log", "agent run finished"), ("Model Trace", "E2E_AGENT_SMOKE")):
        app.ui("extended.agent_history_tab", text=tab)
        app.wait(lambda s, marker=marker: marker in s["extended"]["agent_history"]["text"], "the retained " + tab)
    app.ui("extended.agent_close_all")


@journey("Approve a scoped agent file write after inspecting the pending request", features=("F400", "F385"))
def test_agent_10_approve_file(app):
    # Ask permission must pause before writing. Capture the actual request and
    # absent file, then click Approve and independently verify the created file.
    designer(app)
    scope = configure(app, "Journey approved agent", "E2E_AGENT_ASK_APPROVE", create=True)
    app.ui("extended.agent_field", field="allow_create", value="ask permission")
    target = scope / "approved-agent.txt"
    dialogs(app, {"kind": "agent_approval", "button": "Approve", "absent_path": str(target), "capture": "test_agent_10_approval"})
    app.ui("extended.agent_button", text="Start Task")
    events = completed_dialogs(app)
    assert any("approved-agent.txt" in " ".join(event.get("labels", [])) and event.get("target_existed_before_choice") is False for event in events)
    finished(app)
    assert target.read_text(encoding="utf-8") == "E2E_AGENT_CREATED_FILE\n"
    app.ui("extended.agent_close_all")


@journey("Decline an agent file write and verify that the file is not created", features=("F401", "F385"))
def test_agent_11_decline_file(app):
    # A declined approval must reach the real permission gateway. The recorded
    # tool result must describe the denial, and the filesystem must stay intact.
    designer(app)
    scope = configure(app, "Journey declined agent", "E2E_AGENT_ASK_DECLINE", create=True)
    app.ui("extended.agent_field", field="allow_create", value="ask permission")
    target = scope / "declined-agent.txt"
    dialogs(app, {"kind": "agent_approval", "button": "Decline", "absent_path": str(target), "capture": "test_agent_11_approval"})
    app.ui("extended.agent_button", text="Start Task")
    events = completed_dialogs(app)
    assert events and all(event.get("target_existed_before_choice") is False for event in events)
    folder = finished(app, "E2E_AGENT_DECLINED_FILE")
    assert not target.exists()
    turns = (folder / "turns.json").read_text(encoding="utf-8").lower()
    assert "denied" in turns or "declined" in turns
    app.ui("extended.agent_close_all")


@journey("Continue ordinary Chat after completing and cancelling agent tasks", features=("F144", "F379"))
def test_agent_99_complete(app):
    # Background-task windows and cancellation must not break the app's main prompt path.
    app.ui("extended.agent_close_all")
    new(app)
    app.send("E2E_AGENT_STAGE_COMPLETE")
    app.reply("E2E_AGENT_STAGE_COMPLETE")
