"""Recreated OpenAI supplement; synthetic HTTP, real SDK and production adapters.

The lost October 12 source was unavailable. These are new contract tests, not a
claim to have recovered its exact contents or reproduced its live model output.
"""

from __future__ import annotations

import json
import socket
from copy import deepcopy

import httpx
import pytest
from openai import OpenAI
from support.provider_adapter_matrix import SCENARIOS, grade, run_case

from core.llm_clients import client as llm
from core.llm_clients.chat_tool_loop import ChatToolRequest, OpenWandObservation, OpenWandToolResult
from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

MODEL = "offline-openai-contract-model"


@pytest.fixture(autouse=True)
def offline_state(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("OpenAI supplement attempted a real network connection or tool")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(llm, "_execute_model_tool", blocked)
    monkeypatch.setattr(llm, "_route_capabilities", {})
    monkeypatch.setattr(llm, "_log_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm, "_log_offered_model_tools", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm.config, "CHAT_REASONING_EFFORT", "")


def sdk(handler):
    return OpenAI(
        api_key="synthetic-offline-key",  # secret-scan: allow -- deliberate fake for MockTransport
        base_url="https://openai.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )


def responses_body(calls=(), text="", extra=()):
    output = [*deepcopy(extra), *[
        {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id,
         "name": name, "arguments": json.dumps(args, ensure_ascii=False), "status": "completed"}
        for call_id, name, args in calls
    ]]
    if text:
        output.append({
            "type": "message", "id": "msg_final", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
        })
    return {"id": "resp_synthetic", "object": "response", "created_at": 1, "model": MODEL,
            "status": "completed", "output": output, "parallel_tool_calls": True,
            "tools": [], "tool_choice": "auto"}


def chat_body(calls=(), text="", *, stream=False):
    tool_calls = [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        for call_id, name, args in calls
    ]
    message = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = [
            {"index": index, **call} if stream else call for index, call in enumerate(tool_calls)
        ]
    return {"id": "chat_synthetic", "object": "chat.completion.chunk" if stream else "chat.completion",
            "created": 1, "model": MODEL, "choices": [{"index": 0,
            "finish_reason": "tool_calls" if calls else "stop", "delta" if stream else "message": message}]}


@pytest.mark.parametrize("route", ["openai", "openai_responses"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.id)
def test_nine_scenarios_through_real_openai_sdk(route, scenario, tmp_path):
    """SDK serialization, schema conversion, JSON types, and tool links agree."""
    requests = []
    pending = list(scenario.expected_calls)

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == ("/v1/responses" if route == "openai_responses" else "/v1/chat/completions")
        assert body["model"] == MODEL
        # Independent calls share a turn; dependent/recovery scenarios need two.
        batch_size = len(pending) if scenario.id == "two_tools" else min(1, len(pending))
        batch = [pending.pop(0) for _ in range(batch_size)]
        calls = [(f"call_{len(requests)}_{i}", name, args) for i, (name, args) in enumerate(batch)]
        text = "" if calls else scenario.answer_exact or " ".join(scenario.answer_contains)
        if route == "openai_responses":
            assert body["store"] is False and "previous_response_id" not in body
            assert body["max_output_tokens"] == 768
            response = responses_body(calls, text)
            if body.get("stream"):
                events = [
                    {"type": "response.created", "response": responses_body()},
                    {"type": "response.output_item.added", "output_index": 0,
                     "item": {**response["output"][0], "content": []}},
                    {"type": "response.content_part.added", "output_index": 0, "content_index": 0,
                     "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []}},
                    {"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                     "item_id": "msg_final", "delta": text, "logprobs": []},
                    {"type": "response.completed", "response": response},
                ]
                data = "".join(f"data: {json.dumps({**event, 'sequence_number': index})}\n\n"
                               for index, event in enumerate(events))
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)
            return httpx.Response(200, json=response)
        result = chat_body(calls, text, stream=body.get("stream", False))
        if body.get("stream"):
            events = "data: " + json.dumps(result) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=events)
        return httpx.Response(200, json=result)

    with sdk(handle) as client:
        trace = run_case(route, MODEL, scenario, client, tmp_path)
    assert grade(trace, scenario) == [], trace.to_dict()
    assert not pending
    expected_requests = 3 if scenario.id in {"dependent_rounds", "tool_error_recovery"} else 2 if scenario.expected_calls else 1
    assert len(requests) == expected_requests
    if scenario.tools_enabled:
        assert requests[0]["tools"]
    else:
        assert not requests[0].get("tools")


@pytest.mark.parametrize("route", ["openai", "openai_responses"])
@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "authentication"),
                                            (429, "rate_limit_or_quota"), (500, "provider_api")])
def test_real_sdk_http_errors_are_classified_without_retry_or_tool_use(route, status, category, tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "synthetic error", "type": "api_error"}})

    with sdk(handle) as client:
        trace = run_case(route, MODEL, SCENARIOS[0], client, tmp_path)
    assert trace.error_category == category
    assert len(requests) == 1
    assert trace.executions == []
    assert grade(trace, SCENARIOS[0])[0]["category"] == category


def test_responses_sdk_replays_reasoning_parallel_results_and_full_initial_context():
    """Stateless follow-ups retain opaque reasoning and correlate by call_id."""
    reasoning = {"type": "reasoning", "id": "rs_one", "summary": [], "encrypted_content": "opaque-synthetic-reasoning"}
    replies = iter([
        responses_body([("alpha", "qa_lookup", {"text": "café 雪"}), ("beta", "qa_lookup", {"text": "B"})], extra=[reasoning]),
        responses_body([("gamma", "qa_lookup", {"text": "C"})]),
        responses_body(text="done"),
    ])
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))

    initial = [
        {"role": "user", "content": [{"type": "input_text", "text": "Earlier context"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Acknowledged"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Compare"},
         {"type": "input_image", "image_url": "data:image/png;base64,c3ludGhldGlj"}]},
    ]
    original = deepcopy(initial)
    tools = [{"type": "function", "name": "qa_lookup", "parameters": {"type": "object"}}]
    request = ChatToolRequest(messages=[], system_prompt="Synthetic contract", model_route={}, tools=tools,
                              allowed_tools=["qa_lookup"], pinned_tools=None, permissions={}, budgets={})
    first_results = OpenWandObservation(tool_results=[
        OpenWandToolResult("beta", "qa_lookup", True, {"value": 2}),
        OpenWandToolResult("alpha", "qa_lookup", False, "synthetic failure; use C"),
    ], summary="Results")
    second_results = OpenWandObservation(tool_results=[OpenWandToolResult("gamma", "qa_lookup", True, "3")], summary="Done")
    with sdk(handle) as client:
        model = ResponsesChatLoopModel(client, model=MODEL, instructions="Synthetic contract", tools=tools, initial_input=initial)
        first = model.next_turn(request, [], [])
        assert [(call.id, call.arguments) for call in first.tool_calls] == [("alpha", {"text": "café 雪"}), ("beta", {"text": "B"})]
        second = model.next_turn(request, [first_results], first.tool_calls)
        assert [call.id for call in second.tool_calls] == ["gamma"]
        final = model.next_turn(request, [first_results, second_results], second.tool_calls)
    assert final.status == "final" and final.final_text == "done"
    assert initial == original
    for body in requests:
        assert body["store"] is False and "previous_response_id" not in body
        assert body["instructions"] == "Synthetic contract" and body["tools"] == tools
        assert body["input"][:3] == original
    transcript = requests[-1]["input"][3:]
    assert [item["type"] for item in transcript] == ["reasoning", "function_call", "function_call",
                                                    "function_call_output", "function_call_output", "function_call", "function_call_output"]
    assert transcript[0] == {key: value for key, value in reasoning.items() if key != "id"}
    assert [(item["call_id"], item["output"]) for item in transcript if item["type"] == "function_call_output"] == [
        ("beta", '{"value": 2}'), ("alpha", "synthetic failure; use C"), ("gamma", "3"),
    ]
    assert all("id" not in item for item in transcript)
