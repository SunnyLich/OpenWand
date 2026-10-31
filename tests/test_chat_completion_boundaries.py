"""Regression checks for actual request boundaries and file completion gates."""

import pytest

from core.llm_clients.chat_tool_loop import ChatToolLoop, ChatToolRequest, OpenWandObservation, OpenWandToolResult
from core.llm_clients.messages import build_contextual_user_text


def request(prompt):
    return ChatToolRequest(
        messages=[{"role": "user", "content": prompt}],
        system_prompt="",
        model_route={},
        tools=[],
        allowed_tools=["create_file", "read_file", "list_files", "edit_file"],
        pinned_tools=[],
        permissions={},
        budgets={},
    )


def test_completed_file_mutation_does_not_demand_an_unrequested_read():
    observations = [OpenWandObservation([OpenWandToolResult("create", "create_file", True, "Saved")], "saved")]
    prompt = build_contextual_user_text(
        "Create a file and return its path", "Old tools: read_file, list_files; remember to verify"
    )
    assert ChatToolLoop()._completion_gate_message(request(prompt), [], observations, "Saved notes.md") == ""


def test_context_cannot_make_a_completed_request_demand_memory_or_verification():
    prompt = build_contextual_user_text("Thanks!", "Remember my preferences. Run tests. Read the file.")
    assert ChatToolLoop()._completion_gate_message(request(prompt), [], [], "You're welcome.") == ""


def test_explicit_file_verification_still_requires_evidence():
    observations = [OpenWandObservation([OpenWandToolResult("create", "create_file", True, "Saved")], "saved")]
    assert ChatToolLoop()._completion_gate_message(
        request("Create a file and read it back to verify"), [], observations, "Saved"
    )


def test_disabled_file_permission_is_explicit_even_without_file_schemas():
    from core.llm_clients import client as llm

    try:
        llm.set_live_file_access_mode("off")
        note = llm._with_local_file_tools_note("System", [])
        assert "Local file access is disabled" in note
        assert "earlier conversation" in note
        assert llm._with_local_file_tools_note(note, []) == note
    finally:
        llm.set_live_file_access_mode(None)


@pytest.mark.parametrize("mode", ["off", "read", "ask", "auto"])
def test_append_keeps_existing_file_and_obeys_permissions(tmp_path, monkeypatch, mode):
    import config
    from core.tools.local_files import execute_live_file_tool

    monkeypatch.setattr(config, "TOOL_FILE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(config, "TOOL_FILE_BLOCKED_GLOBS", [])
    target = tmp_path / "checklist.md"
    before = "# Checklist\n- Passport\n- Charger"
    target.write_text(before, encoding="utf-8")
    approvals = []
    result = execute_live_file_tool(
        "edit_file",
        {"path": "checklist.md", "old": "", "new": "- Water bottle"},
        access_mode=mode,
        approval_callback=lambda p: approvals.append(p) or True,
    )
    assert target.read_text(encoding="utf-8") == (before + "\n- Water bottle" if mode in {"ask", "auto"} else before)
    assert bool(approvals) == (mode == "ask")
    if mode in {"off", "read"}:
        assert "disabled" in result


@pytest.mark.parametrize("concurrent", [False, True])
def test_append_respects_declined_approval_and_concurrent_changes(tmp_path, monkeypatch, concurrent):
    import config
    from core.tools.local_files import execute_live_file_tool

    monkeypatch.setattr(config, "TOOL_FILE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(config, "TOOL_FILE_BLOCKED_GLOBS", [])
    target = tmp_path / "checklist.md"
    target.write_text("Original", encoding="utf-8")

    def approval(_payload):
        if concurrent:
            target.write_text("Changed by someone else", encoding="utf-8")
        return concurrent

    execute_live_file_tool(
        "edit_file", {"path": "checklist.md", "old": "", "new": "New"}, access_mode="ask", approval_callback=approval
    )
    assert target.read_text(encoding="utf-8") == ("Changed by someone else" if concurrent else "Original")


def test_disabled_tool_json_never_executes_and_has_a_clear_refusal():
    from core.llm_clients.chat_tool_loop import ChatModelTurn

    r = request("Add a line to that file")
    r.permissions["file_access_mode"] = "off"

    class Model:
        def next_turn(self, *_args):
            return ChatModelTurn(
                final_text='{"name":"edit_file","parameters":{"path":"x","old":"","new":"X"}}', status="final"
            )

    class Executor:
        def execute(self, _call):
            raise AssertionError("Assistant JSON must not execute")

    result = ChatToolLoop().run(r, Model(), Executor())
    assert "File access is disabled" in result.text
    assert result.metadata["disabled_file_call_blocked"] is True


@pytest.mark.parametrize("mode", ["off", "read"])
def test_permission_boundary_overrides_an_accidentally_offered_write_tool(mode):
    from core.llm_clients.chat_tool_loop import OpenWandToolCall, ToolExecutionGuard

    r = request("Change a file")
    r.permissions["file_access_mode"] = mode
    r.tools.append({"name": "edit_file", "parameters": {"type": "object"}})

    class Executor:
        def execute(self, _call):
            raise AssertionError("Disabled write must not execute")

    result = ToolExecutionGuard(r, Executor(), 4).execute(OpenWandToolCall("blocked", "edit_file", {}))
    assert not result.ok
    assert result.metadata["error_type"] == "tool_not_allowed"


def test_empty_reply_after_tool_recovers_once_without_repeating_the_tool():
    from types import SimpleNamespace

    from core.llm_clients.chat_completions_adapter import ChatCompletionsLoopModel
    from core.llm_clients.chat_tool_loop import OpenWandToolResult

    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "edit-once",
                                    "type": "function",
                                    "function": {"name": "edit_file", "arguments": "{}"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": "Saved safely."}, "finish_reason": "stop"}]},
        ]
    )
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return next(responses)

    tools = [{"type": "function", "function": {"name": "edit_file", "parameters": {"type": "object"}}}]
    r = request("Edit the file")
    r.tools.extend(tools)
    executed = []

    class Executor:
        def execute(self, call):
            executed.append(call)
            return OpenWandToolResult(call.id, call.name, True, "Saved")

    model = ChatCompletionsLoopModel(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="openai",
        model="test-empty-recovery",
        kwargs={"messages": r.messages, "tools": tools, "stream": False},
    )
    result = ChatToolLoop().run(r, model, Executor())
    assert result.text == "Saved safely."
    assert len(executed) == 1
    assert len(requests) == 3
    assert "tools" not in requests[-1]


def test_post_tool_quota_blocks_replay_and_remembers_the_retry_window():
    from core.llm_clients import client as llm

    route = ("openai", "post-tool-quota-regression")
    calls = []

    def generate(*_args):
        calls.append(True)
        error = RuntimeError("429 rate limit {'retryDelay': '65s'}")
        error.tools_executed = True
        raise error
        yield

    try:
        with pytest.raises(RuntimeError):
            list(llm._stream_with_fallbacks("chat", [route], generate))
        assert llm._is_route_cooling(*route)
        with pytest.raises(RuntimeError):
            list(llm._stream_with_fallbacks("chat", [route], generate))
        assert len(calls) == 1
    finally:
        llm._clear_route_cooling(*route)
