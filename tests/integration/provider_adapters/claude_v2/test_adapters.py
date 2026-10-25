"""Fresh contract tests of the actual checkout adapters with scripted transports."""

import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest
from anthropic.types import Message

from core.llm_clients import client as llm
from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
from core.llm_clients.chat_tool_loop import (
    ChatToolLoop,
    ChatToolLoopConfig,
    ChatToolRequest,
    OpenWandToolResult,
)
from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

from .scenarios import SCENARIOS, SYSTEM, execute, grade, schemas


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    llm._route_capabilities.clear()
    monkeypatch.setattr(llm, "_log_context", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_log_offered_model_tools", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_use_macos_openai_compat_non_streaming", lambda *a: False)
    monkeypatch.setattr(llm.macos_safety, "openai_compat_tools_enabled", lambda: True)
    yield
    llm._route_capabilities.clear()


def request(scenario, family):
    return ChatToolRequest(
        messages=[{"role": "user", "content": scenario.prompt}],
        system_prompt=SYSTEM,
        model_route={"provider": family, "model": "qa-model"},
        tools=schemas(scenario, family),
        allowed_tools=list(scenario.offered),
        pinned_tools=None,
        permissions={},
        budgets={},
    )


class Executor:
    def __init__(self):
        self.calls = []

    def execute(self, call):
        self.calls.append((call.name, call.arguments))
        result = execute(call.name, call.arguments)
        return OpenWandToolResult(call.id, call.name, "failed" not in result, result)


def anthropic_response(calls=(), text="", stop=None):
    content = [{"type": "tool_use", "id": f"call_{i}", "name": n, "input": a} for i, (n, a) in enumerate(calls)]
    if text:
        content.insert(0, {"type": "text", "text": text})
    return Message(
        id="msg_qa",
        type="message",
        role="assistant",
        model="qa-model",
        content=content,
        stop_reason=stop or ("tool_use" if calls else "end_turn"),
        usage={"input_tokens": 10, "output_tokens": 10},
    )


def responses_response(calls=(), text=""):
    output = [
        {
            "type": "function_call",
            "id": f"fc_{i}",
            "call_id": f"call_{i}",
            "name": n,
            "arguments": json.dumps(a),
        }
        for i, (n, a) in enumerate(calls)
    ]
    if text:
        output.append(
            {
                "id": "message_id",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        )
    return {"id": "response_id", "output_text": text, "output": output}


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.parametrize("family", ["anthropic", "responses"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_actual_neutral_adapters(scenario, family):
    factory = anthropic_response if family == "anthropic" else responses_response
    wire = Scripted([factory(calls=r) for r in scenario.rounds] + [factory(text=scenario.expected_text)])
    req = request(scenario, family)
    if family == "anthropic":
        adapter = AnthropicChatLoopModel(
            NS(messages=wire),
            model="qa-model",
            system=SYSTEM,
            messages=req.messages,
            tools=req.tools,
            max_tokens=256,
        )
    else:
        adapter = ResponsesChatLoopModel(NS(responses=wire), model="qa-model", instructions=SYSTEM, tools=req.tools)
    executor = Executor()
    result = ChatToolLoop(ChatToolLoopConfig(max_rounds=4, max_tool_calls=4)).run(req, adapter, executor)
    assert not grade(scenario, executor.calls, result.text)
    assert result.status == "final"
    assert len(wire.requests) == len(scenario.rounds) + 1
    for i, calls in enumerate(scenario.rounds):
        followup = wire.requests[i + 1]
        if family == "anthropic":
            assert followup["system"] == SYSTEM and followup["tools"] == req.tools
            blocks = followup["messages"][-1]["content"]
            assert [(b["tool_use_id"], b["content"]) for b in blocks] == [
                (f"call_{n}", execute(name, args)) for n, (name, args) in enumerate(calls)
            ]
            assert followup["messages"][0] == req.messages[0]
        else:
            assert followup["store"] is False and "previous_response_id" not in followup
            outs = [x for x in followup["input"] if x.get("type") == "function_call_output"][-len(calls) :]
            assert [(b["call_id"], b["output"]) for b in outs] == [
                (f"call_{n}", execute(name, args)) for n, (name, args) in enumerate(calls)
            ]
            assert all("id" not in x for x in followup["input"])
            assert followup["input"][0]["content"][0]["text"] == scenario.prompt


@pytest.mark.parametrize("family", ["anthropic", "responses"])
@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_propagate_without_tool_execution(family, status):
    err = RuntimeError(f"synthetic HTTP {status}")
    wire = Scripted([err])
    req = request(SCENARIOS[0], family)
    adapter = (
        AnthropicChatLoopModel(
            NS(messages=wire),
            model="qa-model",
            system=SYSTEM,
            messages=req.messages,
            tools=[],
            max_tokens=256,
        )
        if family == "anthropic"
        else ResponsesChatLoopModel(NS(responses=wire), model="qa-model", instructions=SYSTEM, tools=[])
    )
    with pytest.raises(RuntimeError, match="synthetic HTTP"):
        adapter.next_turn(req, [], [])
    assert len(wire.requests) == 1


@pytest.mark.parametrize("stop", ["tool_use", "end_turn", "max_tokens"])
def test_anthropic_complete_call_normalized_from_content(stop):
    wire = Scripted([anthropic_response(calls=(("qa_add", {"a": 2, "b": 3}),), stop=stop)])
    req = request(SCENARIOS[1], "anthropic")
    model = AnthropicChatLoopModel(
        NS(messages=wire),
        model="qa-model",
        system=SYSTEM,
        messages=req.messages,
        tools=req.tools,
        max_tokens=256,
    )
    turn = model.next_turn(req, [], [])
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [("qa_add", {"a": 2, "b": 3})]


@pytest.mark.xfail(
    strict=True,
    reason="Anthropic adapter labels max_tokens truncation final and drops stop metadata",
)
def test_anthropic_truncation_not_reported_as_success():
    wire = Scripted([anthropic_response(text="unfinished", stop="max_tokens")])
    req = request(SCENARIOS[0], "anthropic")
    model = AnthropicChatLoopModel(
        NS(messages=wire),
        model="qa-model",
        system=SYSTEM,
        messages=req.messages,
        tools=[],
        max_tokens=256,
    )
    turn = model.next_turn(req, [], [])
    assert turn.status != "final" or turn.metadata.get("stop_reason") == "max_tokens"


def chunk(content=None, calls=(), finish=None):
    return NS(choices=[NS(finish_reason=finish, delta=NS(content=content, tool_calls=list(calls)))])


@contextmanager
def stream(items):
    yield iter(items)


def completion(calls=(), text=None, finish="tool_calls"):
    return NS(
        choices=[
            NS(
                finish_reason=finish,
                message=NS(
                    content=text,
                    tool_calls=[
                        NS(
                            id=f"later_{i}",
                            function=NS(name=n, arguments=json.dumps(a)),
                        )
                        for i, (n, a) in enumerate(calls)
                    ],
                ),
            )
        ]
    )


@pytest.mark.parametrize("provider", ["openai", "google", "groq", "mistral", "deepseek"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_openai_compatible_real_entrypoint(provider, scenario, monkeypatch):
    first_calls = scenario.rounds[0] if scenario.rounds else ()
    events = []
    for i, (name, args) in enumerate(first_calls):
        encoded = json.dumps(args, ensure_ascii=False)
        cut = len(encoded) // 2
        for part, start in [(encoded[:cut], True), (encoded[cut:], False)]:
            events.append(
                chunk(
                    calls=[
                        NS(
                            index=i,
                            id=f"call_{i}" if start else None,
                            function=NS(name=name if start else None, arguments=part),
                        )
                    ]
                )
            )
    events.append(
        chunk(
            content=None if first_calls else scenario.expected_text,
            finish="tool_calls" if first_calls else "stop",
        )
    )
    replies = [stream(events)]
    replies.extend(completion(calls=calls) for calls in scenario.rounds[1:])
    if first_calls:
        replies.append(completion(text=scenario.expected_text, finish="stop"))
    wire = Scripted(replies)
    executed = []

    def synthetic(name, arguments, **kwargs):
        executed.append((name, arguments))
        return execute(name, arguments)

    monkeypatch.setattr(llm, "_get_openai_tool_schemas", lambda *a, **k: schemas(scenario, "openai"))
    monkeypatch.setattr(llm, "_execute_model_tool", synthetic)
    result = "".join(
        llm._stream_openai_compat(
            scenario.prompt,
            None,
            "qa-model",
            NS(chat=NS(completions=wire)),
            provider=provider,
            system_prompt=SYSTEM,
            use_tools=bool(scenario.offered),
            allowed_tools=list(scenario.offered),
            max_tokens=256,
        )
    )
    assert not grade(scenario, executed, result)
    assert wire.requests[0]["stream"] is True
    assert all(r["stream"] is False for r in wire.requests[1:])
    for r in wire.requests[1:]:
        results = [m for m in r["messages"] if m["role"] == "tool"]
        assert results and all(m["tool_call_id"] for m in results)


@pytest.mark.parametrize(
    "finish,arguments,expected",
    [
        ("stop", '{"a":2,"b":3}', True),
        ("tool_calls", '{"a":2,"b":3}', True),
        ("length", '{"a":2,"b":3}', False),
        ("stop", '{"a":', False),
        ("stop", "[2,3]", False),
    ],
)
def test_compatible_stream_finish_and_json_validation(finish, arguments, expected, monkeypatch):
    scenario = SCENARIOS[1]
    event = chunk(
        calls=[NS(index=0, id="c1", function=NS(name="qa_add", arguments=arguments))],
        finish=finish,
    )
    wire = Scripted([stream([event]), completion(text="5", finish="stop")])
    called = []
    monkeypatch.setattr(llm, "_get_openai_tool_schemas", lambda *a, **k: schemas(scenario, "openai"))
    monkeypatch.setattr(llm, "_execute_model_tool", lambda *a, **k: called.append(a) or "5")
    list(
        llm._stream_openai_compat(
            scenario.prompt,
            None,
            "qa-model",
            NS(chat=NS(completions=wire)),
            provider="openai",
            use_tools=True,
            allowed_tools=["qa_add"],
            max_tokens=256,
        )
    )
    assert bool(called) is expected


@pytest.mark.xfail(
    strict=True,
    reason="Later nonstreaming complete tool call with finish_reason=stop is discarded at client.py:5202",
)
@pytest.mark.parametrize("provider", ["openai", "google"])
def test_compatible_later_stop_tool_call(provider, monkeypatch):
    scenario = SCENARIOS[6]
    event = chunk(
        calls=[
            NS(
                index=0,
                id="first",
                function=NS(name="qa_lookup", arguments='{"code":"beta"}'),
            )
        ],
        finish="tool_calls",
    )
    wire = Scripted(
        [
            stream([event]),
            completion(calls=scenario.rounds[1], finish="stop"),
            completion(text="9", finish="stop"),
        ]
    )
    called = []
    monkeypatch.setattr(llm, "_get_openai_tool_schemas", lambda *a, **k: schemas(scenario, "openai"))
    monkeypatch.setattr(
        llm,
        "_execute_model_tool",
        lambda n, a, **k: called.append((n, a)) or execute(n, a),
    )
    list(
        llm._stream_openai_compat(
            scenario.prompt,
            None,
            "qa-model",
            NS(chat=NS(completions=wire)),
            provider=provider,
            use_tools=True,
            allowed_tools=list(scenario.offered),
            max_tokens=256,
        )
    )
    assert [n for n, _ in called] == ["qa_lookup", "qa_add"]


@pytest.mark.parametrize("with_tool", [False, True])
def test_responses_stream_reconstruction(with_tool):
    events = [
        {"type": "response.output_text.delta", "delta": "QA_"},
        {"type": "response.output_text.delta", "delta": "OK"},
    ]
    if with_tool:
        events += [
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc",
                    "call_id": "c1",
                    "name": "qa_add",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "delta": '{"a":2,',
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "delta": '"b":3}',
            },
        ]
    wire = NS(stream=lambda **k: stream(events))
    response = llm._responses_stream_to_response(
        NS(responses=wire),
        {"model": "qa-model", "input": "synthetic"},
        provider="chatgpt",
        model="qa-model",
    )
    assert llm._response_output_text(response) == "QA_OK"
    calls = llm._response_function_calls(response)
    assert len(calls) == int(with_tool)
    if with_tool:
        assert json.loads(calls[0]["arguments"]) == {"a": 2, "b": 3}


def test_anthropic_no_tool_stream_uses_production_path():
    recorded = []

    @contextmanager
    def text_stream(**kwargs):
        recorded.append(copy.deepcopy(kwargs))
        yield NS(text_stream=iter(["QA_", "OK"]))

    text = "".join(
        llm._stream_anthropic(
            "Reply QA_OK",
            None,
            "qa-model",
            NS(messages=NS(stream=text_stream)),
            max_tokens=256,
            system_prompt=SYSTEM,
            use_tools=False,
        )
    )
    assert text == "QA_OK"
    assert recorded[0]["messages"] == [{"role": "user", "content": "Reply QA_OK"}]
    assert recorded[0]["max_tokens"] == 256
    assert "tools" not in recorded[0]


def test_live_grading_excludes_progress_channel():
    assert llm._collect_answer_text(iter([llm._progress_chunk("Calling a tool"), "QA_OK"])) == "QA_OK"


@pytest.mark.parametrize(
    "arguments",
    ['{"n":1}', '{"payload":{"arr":[true,null,"x"]}}', "malformed", "[1,2]", "null"],
)
def test_responses_json_argument_normalization(arguments):
    resp = responses_response(calls=(("qa_record", {}),))
    resp["output"][0]["arguments"] = arguments
    wire = Scripted([resp])
    req = request(SCENARIOS[3], "responses")
    model = ResponsesChatLoopModel(NS(responses=wire), model="qa-model", instructions=SYSTEM, tools=req.tools)
    result = model.next_turn(req, [], [])
    expected = json.loads(arguments) if arguments.startswith("{") else {}
    assert result.tool_calls[0].arguments == expected
