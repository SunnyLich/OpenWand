"""Offline wire-protocol regressions for the three production chat adapters.

These tests preserve the real adapter and transcript-building code. Only the
provider endpoints and tool execution are scripted; no SDK client, credential,
network service, or user's filesystem is needed. Captured requests are deep
copies so later transcript mutations cannot make an earlier request look right.
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from core.llm_clients import client as llm
from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
from core.llm_clients.chat_tool_loop import (
    ChatToolRequest,
    OpenWandObservation,
    OpenWandToolResult,
)
from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

_MODEL = "offline-protocol-model"
_HISTORY = [
    {"role": "user", "content": "Remember that the project is called Orchid."},
    {"role": "assistant", "content": "The project is Orchid."},
]
_PROMPT = "Compare the three requested files."
_TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a test fixture.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}]


class _Stream:
    """Minimal SDK stream with observable context-manager cleanup."""

    def __init__(self, events):
        self.events = events
        self.closed = False

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *_args):
        self.closed = True
        return False


class _Endpoint:
    """Snapshot each request before returning a predetermined provider reply."""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture(autouse=True)
def _offline_adapter_state(monkeypatch):
    """Block external effects and isolate machine/profile-dependent settings."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline provider protocol tests must not access the network or real tools")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(llm, "_execute_model_tool", forbidden)
    monkeypatch.setattr(llm, "_route_capabilities", {})
    monkeypatch.setattr(llm.macos_safety, "openai_compat_tools_enabled", lambda: True)
    monkeypatch.setattr(llm, "_use_macos_openai_compat_non_streaming", lambda _provider: False)
    monkeypatch.setattr(llm, "_get_openai_tool_schemas", lambda *_a, **_kw: deepcopy(_TOOLS))
    monkeypatch.setattr(llm, "_log_offered_model_tools", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm, "_tool_turn_budget", lambda: SimpleNamespace(
        max_calls=8, max_result_chars=50000, max_total_chars=90000,
    ))
    monkeypatch.setattr(llm.config, "CHAT_REASONING_EFFORT", "")
    for key in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setattr(llm.config, key, "offline-test-key-not-real", raising=False)


def _request(provider):
    return ChatToolRequest(
        messages=[*_HISTORY, {"role": "user", "content": _PROMPT}],
        system_prompt="Offline protocol test.",
        model_route={"provider": provider, "model": _MODEL},
        tools=_TOOLS,
        allowed_tools=["read_file"],
        pinned_tools=["read_file"],
        permissions={},
        budgets={},
    )


def _observation(*pairs):
    return OpenWandObservation(
        tool_results=[
            OpenWandToolResult(call_id=call_id, name="read_file", ok=True, content=content)
            for call_id, content in pairs
        ],
        summary="Fixture results are available.",
    )


def _delta(index, *, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(*deltas, text=None, finish_reason=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason,
        delta=SimpleNamespace(content=text, tool_calls=list(deltas)),
    )])


def _completion(*calls, text=None, finish_reason="tool_calls"):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=text, tool_calls=[
            SimpleNamespace(id=call_id, function=SimpleNamespace(name="read_file", arguments=arguments))
            for call_id, arguments in calls
        ]),
    )])


def _run_openai(endpoint, provider):
    return list(llm._stream_openai_compat(
        _PROMPT, None, _MODEL,
        SimpleNamespace(chat=SimpleNamespace(completions=endpoint)),
        use_tools=True, allowed_tools=["read_file"], pinned_tools=["read_file"],
        provider=provider, history=deepcopy(_HISTORY), system_prompt="Offline protocol test.",
    ))


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize("finish_reason", ["tool_calls", "stop"])
def test_openai_interleaved_calls_preserve_ids_arguments_and_three_turn_history(
    monkeypatch, provider, finish_reason,
):
    """Multiple fragmented calls must stay distinct across stream and follow-ups."""
    alpha_args = '{"path":"caf\\u00e9.txt"}'
    beta_args = '{"path":"b\\\\eta.txt"}'
    stream = _Stream([
        SimpleNamespace(choices=[]),  # Usage-only chunks have no choice.
        _chunk(text="Reading both files."),
        _chunk(_delta(0, call_id="call-alpha", name="read_", arguments='{"path":"caf\\u')),
        _chunk(_delta(1, call_id="call-beta", name="read_file", arguments='{"path":')),
        _chunk(_delta(1, arguments='"b\\\\eta.txt"}'), _delta(0, name="file", arguments='00e9.txt"}')),
        _chunk(finish_reason=finish_reason),
    ])
    endpoint = _Endpoint([
        stream,
        _completion(("call-gamma", '{"path":"third.txt"}'), text="One more file."),
        _completion(text="All three compared.", finish_reason="stop"),
    ])
    execute = Mock(side_effect=lambda _name, args, **_kwargs: f"contents:{args['path']}")
    monkeypatch.setattr(llm, "_execute_model_tool", execute)

    chunks = _run_openai(endpoint, provider)

    assert chunks == ["Reading both files.", "One more file.", "All three compared."]
    assert [getattr(chunk, "kind", "answer") for chunk in chunks] == ["progress", "progress", "answer"]
    assert stream.closed
    assert execute.call_args_list == [
        call("read_file", {"path": "café.txt"}, allowed_tools=["read_file"]),
        call("read_file", {"path": "b\\eta.txt"}, allowed_tools=["read_file"]),
        call("read_file", {"path": "third.txt"}, allowed_tools=["read_file"]),
    ]
    assert len(endpoint.calls) == 3
    first, second, third = endpoint.calls
    assert [request["stream"] for request in endpoint.calls] == [True, False, False]
    assert first["messages"][1:] == [*_HISTORY, {"role": "user", "content": _PROMPT}]
    assert second["messages"][:len(first["messages"])] == first["messages"]
    assert third["messages"][:len(second["messages"])] == second["messages"]
    assert len(first["messages"]) == 4  # The snapshots must not alias mutable history.
    assistant = second["messages"][-3]
    assert [(item["id"], item["function"]["arguments"]) for item in assistant["tool_calls"]] == [
        ("call-alpha", alpha_args), ("call-beta", beta_args),
    ]
    assert [(item["tool_call_id"], item["content"]) for item in third["messages"] if item["role"] == "tool"] == [
        ("call-alpha", "contents:café.txt"),
        ("call-beta", "contents:b\\eta.txt"),
        ("call-gamma", "contents:third.txt"),
    ]


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.parametrize("bad_arguments", ['{"path":', '["not", "an object"]', '"scalar"', "null"])
def test_openai_malformed_stream_call_does_not_discard_valid_sibling(monkeypatch, provider, bad_arguments):
    """A malformed call must not execute or poison a separate complete call."""
    stream = _Stream([
        _chunk(_delta(0, call_id="bad-call", name="read_file", arguments=bad_arguments)),
        _chunk(_delta(1, call_id="good-call", name="read_file", arguments='{"path":"good.txt"}')),
        _chunk(finish_reason="stop"),
    ])
    endpoint = _Endpoint([stream, _completion(text="Read the valid file.", finish_reason="stop")])
    execute = Mock(return_value="good contents")
    monkeypatch.setattr(llm, "_execute_model_tool", execute)

    assert _run_openai(endpoint, provider) == ["Read the valid file."]

    execute.assert_called_once_with("read_file", {"path": "good.txt"}, allowed_tools=["read_file"])
    assert len(endpoint.calls) == 2
    assistant, result = endpoint.calls[1]["messages"][-2:]
    assert [item["id"] for item in assistant["tool_calls"]] == ["good-call"]
    assert result == {"role": "tool", "tool_call_id": "good-call", "content": "good contents"}


def test_anthropic_multiple_results_keep_call_ids_and_three_turn_history():
    """Reordered results for same-name tools must match by id, never position."""
    first_content = [
        SimpleNamespace(type="text", text="Reading two fixtures."),
        SimpleNamespace(type="tool_use", id="tool-alpha", name="read_file", input={"path": "alpha.txt"}),
        SimpleNamespace(type="tool_use", id="tool-beta", name="read_file", input={"path": "beta.txt"}),
    ]
    second_content = [
        SimpleNamespace(type="tool_use", id="tool-gamma", name="read_file", input={"path": "gamma.txt"}),
    ]
    endpoint = _Endpoint([
        SimpleNamespace(content=first_content),
        SimpleNamespace(content=second_content),
        SimpleNamespace(content=[SimpleNamespace(type="text", text="All three compared.")]),
    ])
    request = _request("anthropic")
    tools = [{"name": "read_file", "input_schema": _TOOLS[0]["function"]["parameters"]}]
    model = AnthropicChatLoopModel(
        SimpleNamespace(messages=endpoint), model=_MODEL, system=request.system_prompt,
        messages=deepcopy(request.messages), tools=tools, max_tokens=256,
    )

    first = model.next_turn(request, [], [])
    observations = [_observation(("tool-beta", "beta result"), ("tool-alpha", "alpha result"))]
    second = model.next_turn(request, observations, first.tool_calls)
    observations.append(_observation(("tool-gamma", "gamma result")))
    final = model.next_turn(request, observations, first.tool_calls + second.tool_calls)

    assert [(item.id, item.arguments) for item in first.tool_calls] == [
        ("tool-alpha", {"path": "alpha.txt"}), ("tool-beta", {"path": "beta.txt"}),
    ]
    assert first.progress == "Reading two fixtures."
    assert [(item.id, item.arguments) for item in second.tool_calls] == [("tool-gamma", {"path": "gamma.txt"})]
    assert final.final_text == "All three compared."
    assert len(endpoint.calls) == 3
    assert endpoint.calls[0]["messages"] == request.messages
    assert endpoint.calls[1]["messages"] == [
        *request.messages,
        {"role": "assistant", "content": first_content},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tool-beta", "content": "beta result"},
            {"type": "tool_result", "tool_use_id": "tool-alpha", "content": "alpha result"},
        ]},
    ]
    assert endpoint.calls[2]["messages"] == [
        *endpoint.calls[1]["messages"],
        {"role": "assistant", "content": second_content},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tool-gamma", "content": "gamma result"},
        ]},
    ]
    assert all(item["system"] == request.system_prompt and item["tools"] == tools for item in endpoint.calls)


def _response_call(call_id, path):
    return {
        "type": "function_call", "id": f"provider-item-{call_id}", "call_id": call_id,
        "name": "read_file", "arguments": json.dumps({"path": path}, ensure_ascii=False),
    }


def _responses_model(endpoint, *, initial_input=None):
    return ResponsesChatLoopModel(
        SimpleNamespace(responses=endpoint), model=_MODEL,
        instructions="Offline protocol test.", tools=[{"type": "function", "name": "read_file"}],
        initial_input=initial_input,
    )


@pytest.mark.parametrize("sdk_objects", [False, True], ids=["dict", "sdk-object"])
def test_responses_multiple_results_keep_call_ids_and_full_stateless_history(sdk_objects):
    """Replay all prior calls/results once without confusing item ids and call ids."""
    reasoning = {"type": "reasoning", "id": "rs-private", "summary": [{"type": "summary_text", "text": "Read fixtures."}]}
    first_items = [reasoning, _response_call("call-alpha", "alpha.txt"), _response_call("call-beta", "beta.txt")]
    second_items = [_response_call("call-gamma", "gamma.txt")]
    replies = [
        {"id": "response-1", "output_text": "Reading two fixtures.", "output": first_items},
        {"id": "response-2", "output_text": "", "output": second_items},
        {"id": "response-3", "output_text": "All three compared.", "output": []},
    ]
    if sdk_objects:
        replies = [SimpleNamespace(**{**reply, "output": [SimpleNamespace(**item) for item in reply["output"]]}) for reply in replies]
    endpoint = _Endpoint(replies)
    initial = [{"type": "message", **message} for message in _request("chatgpt").messages]
    initial_snapshot = deepcopy(initial)
    model = _responses_model(endpoint, initial_input=initial)
    request = _request("chatgpt")

    first = model.next_turn(request, [], [])
    observations = [_observation(("call-beta", "beta result"), ("call-alpha", "alpha result"))]
    second = model.next_turn(request, observations, first.tool_calls)
    observations.append(_observation(("call-gamma", "gamma result")))
    final = model.next_turn(request, observations, first.tool_calls + second.tool_calls)

    assert [(item.id, item.arguments) for item in first.tool_calls] == [
        ("call-alpha", {"path": "alpha.txt"}), ("call-beta", {"path": "beta.txt"}),
    ]
    assert first.progress == "Reading two fixtures."
    assert [(item.id, item.arguments) for item in second.tool_calls] == [("call-gamma", {"path": "gamma.txt"})]
    assert final.final_text == "All three compared."
    assert len(endpoint.calls) == 3
    assert initial == initial_snapshot
    expected_second = [
        *initial_snapshot,
        *[{key: value for key, value in item.items() if key != "id"} for item in first_items],
        {"type": "function_call_output", "call_id": "call-beta", "output": "beta result"},
        {"type": "function_call_output", "call_id": "call-alpha", "output": "alpha result"},
    ]
    assert endpoint.calls[0]["input"] == initial_snapshot
    assert endpoint.calls[1]["input"] == expected_second
    assert endpoint.calls[2]["input"] == [
        *expected_second,
        {key: value for key, value in second_items[0].items() if key != "id"},
        {"type": "function_call_output", "call_id": "call-gamma", "output": "gamma result"},
    ]
    for kwargs in endpoint.calls:
        assert kwargs["store"] is False
        assert "previous_response_id" not in kwargs
        assert kwargs["instructions"] == "Offline protocol test."
        assert kwargs["tools"] == [{"type": "function", "name": "read_file"}]


@pytest.mark.parametrize("sdk_events", [False, True], ids=["dict", "sdk-object"])
@pytest.mark.parametrize("send_done", [False, True], ids=["delta-only", "with-done"])
def test_responses_stream_required_reassembles_interleaved_arguments(sdk_events, send_done):
    """The stream-required fallback must reconstruct distinct complete calls."""
    calls = [_response_call("call-alpha", "café.txt"), _response_call("call-beta", "beta.txt")]
    events = [{"type": "response.created", "response": {"id": "response-stream"}}]
    for index, item in enumerate(calls):
        events.append({"type": "response.output_item.added", "output_index": index, "item": {**item, "arguments": ""}})
    # Interleave both calls, splitting inside their JSON argument strings.
    for index, fragment in [(0, calls[0]["arguments"][:8]), (1, calls[1]["arguments"][:8]),
                            (1, calls[1]["arguments"][8:]), (0, calls[0]["arguments"][8:])]:
        events.append({
            "type": "response.function_call_arguments.delta", "output_index": index,
            "item_id": calls[index]["id"], "delta": fragment,
        })
    if send_done:
        for index, item in enumerate(calls):
            events.extend([
                {"type": "response.function_call_arguments.done", "output_index": index,
                 "item_id": item["id"], "arguments": item["arguments"]},
                {"type": "response.output_item.done", "output_index": index, "item": item},
            ])
    # Some compatibility streams end without an authoritative completed output.
    events.append({"type": "response.completed", "response": {"id": "response-stream", "output": []}})
    if sdk_events:
        events = [SimpleNamespace(**event) for event in events]
    stream = _Stream(events)
    endpoint = _Endpoint([
        RuntimeError("stream must be true"),
        {"id": "response-final", "output_text": "Both files read.", "output": []},
    ])
    endpoint.stream = Mock(return_value=stream)
    model = _responses_model(endpoint)
    request = _request("chatgpt")

    turn = model.next_turn(request, [], [])
    final = model.next_turn(request, [_observation(("call-beta", "beta result"), ("call-alpha", "alpha result"))], turn.tool_calls)

    assert [(item.id, item.name, item.arguments) for item in turn.tool_calls] == [
        ("call-alpha", "read_file", {"path": "café.txt"}),
        ("call-beta", "read_file", {"path": "beta.txt"}),
    ]
    assert final.final_text == "Both files read."
    assert stream.closed
    endpoint.stream.assert_called_once()
    assert endpoint.stream.call_args.kwargs["extra_body"]["stream"] is True
    assert endpoint.stream.call_args.kwargs["store"] is False
    replay = endpoint.calls[1]["input"]
    assert [(item["call_id"], item["arguments"]) for item in replay if item["type"] == "function_call"] == [
        (item["call_id"], item["arguments"]) for item in calls
    ]
    assert [(item["call_id"], item["output"]) for item in replay if item["type"] == "function_call_output"] == [
        ("call-beta", "beta result"), ("call-alpha", "alpha result"),
    ]


@pytest.mark.parametrize("arguments", ['{"path":', '["not", "an object"]', '"scalar"', "null"])
def test_responses_malformed_arguments_normalize_without_losing_identity(arguments):
    """Defensive parsing retains call identity and the exact provider transcript."""
    bad_call = {**_response_call("call-malformed", "unused"), "arguments": arguments}
    endpoint = _Endpoint([
        {"id": "response-bad", "output": [bad_call]},
        {"id": "response-final", "output_text": "Please provide a path.", "output": []},
    ])
    model = _responses_model(endpoint)
    request = _request("chatgpt")

    turn = model.next_turn(request, [], [])
    assert len(turn.tool_calls) == 1
    parsed = turn.tool_calls[0]
    assert parsed.id == "call-malformed"
    assert parsed.arguments == {}
    assert parsed.provider_payload["arguments"] == arguments
    final = model.next_turn(request, [_observation((parsed.id, "read_file requires a path"))], turn.tool_calls)

    assert final.final_text == "Please provide a path."
    assert endpoint.calls[1]["input"][-2:] == [
        {key: value for key, value in bad_call.items() if key != "id"},
        {"type": "function_call_output", "call_id": "call-malformed", "output": "read_file requires a path"},
    ]


@pytest.mark.parametrize("provider", ["google", "openai"])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "client._stream_openai_compat accepts initial stop-ended tool calls but "
        "discards complete follow-up calls unless finish_reason is tool_calls"
    ),
)
def test_openai_followup_stop_ended_complete_call_is_not_lost(monkeypatch, provider):
    """The accepted initial stop-ended call contract must also hold on follow-up."""
    endpoint = _Endpoint([
        _Stream([_chunk(_delta(0, call_id="call-first", name="read_file", arguments='{"path":"first.txt"}'), finish_reason="stop")]),
        _completion(("call-second", '{"path":"second.txt"}'), finish_reason="stop"),
        _completion(text="Both files read.", finish_reason="stop"),
    ])
    execute = Mock(side_effect=["first contents", "second contents"])
    monkeypatch.setattr(llm, "_execute_model_tool", execute)

    output = _run_openai(endpoint, provider)

    assert execute.call_args_list == [
        call("read_file", {"path": "first.txt"}, allowed_tools=["read_file"]),
        call("read_file", {"path": "second.txt"}, allowed_tools=["read_file"]),
    ]
    assert output == ["Both files read."]
    assert endpoint.calls[2]["messages"][-1] == {
        "role": "tool", "tool_call_id": "call-second", "content": "second contents",
    }
