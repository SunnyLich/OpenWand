"""Offline conformance of every configured provider and shared failure boundaries.

Compatible providers use the real OpenAI SDK with an in-memory HTTP transport.
Native Messages, Responses, and Copilot endpoints are scripted; sockets and real
OpenWand tools are forbidden. These tests do not claim live account availability.
"""
from __future__ import annotations

import json
import socket
from copy import deepcopy
from types import SimpleNamespace as NS

import httpx
import pytest
from openai import OpenAI

from core.llm_clients import client as llm
from core.llm_clients.adapter_protocol import AdapterProtocolError, ToolContinuationError
from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
from core.llm_clients.chat_tool_loop import (
    ChatModelTurn,
    ChatToolLoop,
    ChatToolLoopConfig,
    ChatToolRequest,
    OpenWandToolCall,
    OpenWandToolResult,
)
from core.llm_clients.provider_adapters import COMPATIBLE_PROVIDERS, PROVIDER_ADAPTERS, Protocol, adapter_for
from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

TOOLS = [{"type": "function", "function": {
    "name": "fixture", "description": "Read a synthetic fixture",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                   "required": ["path"], "additionalProperties": False},
}}]
_REAL_EXECUTE_MODEL_TOOL = llm._execute_model_tool


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_a, **_kw):
        raise AssertionError("Adapter conformance must not use sockets or real tools")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(llm, "_execute_model_tool", forbidden)
    monkeypatch.setattr(llm, "_route_capabilities", {})
    monkeypatch.setattr(llm, "_custom_connection_settings", lambda _provider: ("https://adapter.invalid/v1", "synthetic"))
    monkeypatch.setattr(llm, "_get_openai_tool_schemas", lambda *_a, **_kw: deepcopy(TOOLS))
    monkeypatch.setattr(llm, "_log_offered_model_tools", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm, "_emit_live_progress", lambda *_a: None)
    monkeypatch.setattr(llm, "_use_macos_openai_compat_non_streaming", lambda *_a: False)
    monkeypatch.setattr(llm.macos_safety, "openai_compat_tools_enabled", lambda: True)
    monkeypatch.setattr(llm.config, "CHAT_REASONING_EFFORT", "")
    monkeypatch.setattr(llm, "_tool_turn_budget", lambda: NS(max_calls=6, max_result_chars=5000, max_total_chars=20000))


def call(identifier="one", path="café.txt", arguments=None):
    return {"id": identifier, "type": "function", "function": {
        "name": "fixture", "arguments": json.dumps({"path": path}, ensure_ascii=False) if arguments is None else arguments,
    }}


def completion(calls=(), text="", finish=None, **extra):
    return {"id": "test-completion", "object": "chat.completion", "created": 0, "model": "adapter-test",
            "choices": [{"index": 0, "finish_reason": finish or ("tool_calls" if calls else "stop"),
                         "message": {"role": "assistant", "content": text or None, "tool_calls": list(calls), **extra}}]}


def stream_response(reply):
    message = reply["choices"][0]["message"]
    events = []
    def event(delta, finish=None):
        payload = {"id": "stream", "object": "chat.completion.chunk", "created": 0, "model": "adapter-test",
                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        events.append("data: " + json.dumps(payload) + "\n\n")

    if message.get("content"):
        event({"content": message["content"]})
    if message.get("images"):
        event({"images": message["images"]})
    if message.get("reasoning_content"):
        event({"reasoning_content": message["reasoning_content"]})
    calls = message.get("tool_calls", [])
    for index, item in enumerate(calls):
        encoded = item["function"]["arguments"]
        fragment = deepcopy(item)
        fragment["index"] = index
        fragment["function"]["arguments"] = encoded[:6]
        event({"tool_calls": [fragment]})
    for index in reversed(range(len(calls))):
        event({"tool_calls": [{"index": index, "function": {"arguments": calls[index]["function"]["arguments"][6:]}}]})
    event({}, reply["choices"][0]["finish_reason"])
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="".join(events) + "data: [DONE]\n\n")


def run_compatible(monkeypatch, provider, replies, *, use_tools=True):
    requests, executed = [], []
    scripted = iter(replies)
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        reply = next(scripted)
        if isinstance(reply, httpx.Response):
            return reply
        return stream_response(reply) if payload.get("stream") else httpx.Response(200, json=reply)

    def execute(name, arguments, **_kwargs):
        executed.append((name, deepcopy(arguments)))
        return "fixture result: " + arguments["path"]

    monkeypatch.setattr(llm, "_execute_model_tool", execute)
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport, OpenAI(
        api_key="synthetic-not-a-credential", base_url="https://adapter.invalid/v1", http_client=transport, max_retries=0,  # secret-scan: allow (synthetic test credential)
    ) as client:
        chunks = list(llm._stream_openai_compat(
            "Process the fixture plan.", None, "adapter-test", client, provider=provider,
            use_tools=use_tools, allowed_tools=["fixture"], system_prompt="Synthetic conformance.",
            history=[{"role": "user", "content": "Earlier user context"}, {"role": "assistant", "content": "Acknowledged"}],
        ))
    return chunks, requests, executed


@pytest.mark.parametrize("provider", sorted(COMPATIBLE_PROVIDERS | {"custom@synthetic"}))
@pytest.mark.parametrize("scenario", ["plain", "no_call", "one_call", "parallel", "dependent", "stop_with_calls"])
def test_all_compatible_provider_wire_round_trips(monkeypatch, provider, scenario):
    replies = []
    expected = []
    if scenario not in {"plain", "no_call"}:
        calls = [call()]
        expected.append(("fixture", {"path": "café.txt"}))
        if scenario == "parallel":
            calls.append(call("two", "b.txt"))
            expected.append(("fixture", {"path": "b.txt"}))
        replies.append(completion(calls, "Checking fixtures.", finish="stop" if scenario == "stop_with_calls" else None))
        if scenario in {"dependent", "stop_with_calls"}:
            replies.append(completion([call("next", "next.txt")], finish="stop"))
            expected.append(("fixture", {"path": "next.txt"}))
    replies.append(completion(text="Complete."))
    chunks, requests, executed = run_compatible(monkeypatch, provider, replies, use_tools=scenario != "plain")
    assert executed == expected
    assert chunks[-1] == "Complete."
    assert requests[0]["messages"][1:3] == [
        {"role": "user", "content": "Earlier user context"}, {"role": "assistant", "content": "Acknowledged"},
    ]
    if expected:
        results = [m for m in requests[-1]["messages"] if m["role"] == "tool"]
        assert len(results) == len(expected)
        assert len({m["tool_call_id"] for m in results}) == len(expected)
        assert all(m["content"].startswith("fixture result:") for m in results)


def test_provider_registry_covers_every_settings_provider():
    from ui.settings_panel.dialog import _PROVIDER_MODELS

    assert set(PROVIDER_ADAPTERS) == set(_PROVIDER_MODELS)
    assert adapter_for("openai", "gpt-6.1-sol").protocol == Protocol.RESPONSES
    assert adapter_for("custom@synthetic", "gpt-6.1-sol").protocol == Protocol.CHAT_COMPLETIONS
    for provider in ("unknown-provider", "github_models"):
        with pytest.raises(ValueError):
            adapter_for(provider)


@pytest.mark.parametrize("arguments", ['{"path":', '[]', 'null', '{"path":"a","path":"b"}', '{"path":NaN}'])
def test_invalid_arguments_are_reported_without_executing_them(monkeypatch, arguments):
    _, requests, executed = run_compatible(monkeypatch, "google", [
        completion([call("bad", arguments=arguments), call("good", "good.txt")]), completion(text="Complete."),
    ])
    assert executed == [("fixture", {"path": "good.txt"})]
    results = {m["tool_call_id"]: m["content"] for m in requests[-1]["messages"] if m["role"] == "tool"}
    assert "JSON object" in results["bad"]
    assert results["good"] == "fixture result: good.txt"


@pytest.mark.parametrize("finish", ["length", "content_filter"])
def test_truncated_or_filtered_calls_do_not_execute(monkeypatch, finish):
    with pytest.raises(AdapterProtocolError):
        run_compatible(monkeypatch, "mistral", [completion([call()], finish=finish)])


def test_reasoning_and_signatures_are_replayed_without_becoming_answer_text(monkeypatch):
    signed = call()
    signed["extra_content"] = {"google": {"thought_signature": "opaque-signature"}}
    chunks, requests, _ = run_compatible(monkeypatch, "deepseek", [
        completion([signed], reasoning_content="private reasoning"), completion(text="Complete."),
    ])
    assistant = requests[1]["messages"][-2]
    assert assistant["reasoning_content"] == "private reasoning"
    assert assistant["tool_calls"][0]["extra_content"] == signed["extra_content"]
    assert all("private reasoning" not in str(chunk) for chunk in chunks)


def test_followup_parameter_rejection_is_recovered_on_that_same_turn(monkeypatch):
    rejected = httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'temperature'", "param": "temperature"}})
    _, requests, executed = run_compatible(monkeypatch, "cohere", [completion([call()]), rejected, completion(text="Complete.")])
    assert len(executed) == 1
    assert "temperature" in requests[1] and "temperature" not in requests[2]
    assert requests[1]["messages"] == requests[2]["messages"]


def request(tools=None):
    return ChatToolRequest(messages=[{"role": "user", "content": "Fixture plan"}], system_prompt="test",
                           model_route={}, tools=deepcopy(TOOLS if tools is None else tools), allowed_tools=["fixture"],
                           pinned_tools=None, permissions={}, budgets={})


def test_tool_execution_prevents_cross_provider_replay(monkeypatch):
    class Model:
        def next_turn(self, *_args):
            if executions:
                raise RuntimeError("temporary provider failure")
            return ChatModelTurn(tool_calls=[OpenWandToolCall("one", "fixture", {"path": "test"})])
    executions, routes = [], []
    class Executor:
        def execute(self, item):
            executions.append(item)
            return OpenWandToolResult(item.id, item.name, True, "Done")
    def factory(provider, _model):
        routes.append(provider)
        yield ChatToolLoop().run(request(), Model(), Executor()).text
    monkeypatch.setattr(llm, "_route_cooldowns", {})
    with pytest.raises(RuntimeError) as failure:
        list(llm._stream_with_fallbacks("test", [("first", "test"), ("second", "test")], factory))
    assert failure.value.tools_executed is True
    assert routes == ["first"] and len(executions) == 1


@pytest.mark.parametrize("family", ["anthropic", "responses"])
def test_native_adapters_reject_truncation_before_calls(family):
    if family == "anthropic":
        endpoint = NS(create=lambda **_kw: NS(stop_reason="max_tokens", content=[
            NS(type="tool_use", id="one", name="fixture", input={"path": "test"}),
        ]))
        model = AnthropicChatLoopModel(NS(messages=endpoint), model="test", system="test", messages=[], tools=[], max_tokens=256)
    else:
        endpoint = NS(create=lambda **_kw: {"status": "incomplete", "output": [{
            "type": "function_call", "call_id": "one", "name": "fixture", "arguments": '{"path":"test"}',
        }]})
        model = ResponsesChatLoopModel(NS(responses=endpoint), model="test", instructions="test", tools=[])
    with pytest.raises(AdapterProtocolError):
        model.next_turn(request(), [], [])


def test_budget_and_schema_rules_are_identical_for_every_executor():
    executions = []
    class Model:
        def next_turn(self, _request, observations, _calls):
            if observations:
                assert [result.ok for result in observations[0].tool_results] == [False, True, False]
                return ChatModelTurn(final_text="Complete.", status="final")
            return ChatModelTurn(tool_calls=[OpenWandToolCall("bad", "fixture", {"path": 3}),
                                            OpenWandToolCall("one", "fixture", {"path": "ok"}),
                                            OpenWandToolCall("two", "fixture", {"path": "over budget"})])
    class Executor:
        def execute(self, item):
            executions.append(item.id)
            return OpenWandToolResult(item.id, item.name, True, "fixture result")
    final = ChatToolLoop(ChatToolLoopConfig(max_tool_calls=1)).run(request(), Model(), Executor())
    assert final.text == "Complete." and executions == ["one"]


def test_copilot_uses_only_guarded_openwand_tools_with_current_sdk(monkeypatch):
    import copilot

    from core.auth import copilot_auth, copilot_client

    sessions, executions = [], []
    class Session:
        async def send_and_wait(self, prompt):
            assert prompt == "Fixture plan"
            options = sessions[-1]
            assert options["available_tools"] == ["fixture"]
            assert options["on_permission_request"]({}, {})["kind"] == "denied-by-rules"
            tool = options["tools"][0]
            # Schema failures and exhausted budgets are returned without execution.
            invalid = tool.handler(NS(tool_call_id="bad", arguments={"path": 5}))
            assert invalid.result_type == "failure"
            result = tool.handler(NS(tool_call_id="one", arguments={"path": "ok"}))
            assert result.result_type == "success"
            rejected = tool.handler(NS(tool_call_id="two", arguments={"path": "later"}))
            assert rejected.result_type == "failure"
            return NS(data=NS(content="Complete."))
    class Client:
        def __init__(self, *, github_token, env, use_logged_in_user):
            assert github_token == "github_pat_synthetic" and not use_logged_in_user
        async def start(self):
            pass
        async def create_session(self, **options):
            sessions.append(options)
            return Session()
        async def stop(self):
            pass
    class Executor:
        def execute(self, item):
            executions.append(item.id)
            return OpenWandToolResult(item.id, item.name, True, "Fixture result")

    monkeypatch.setattr(copilot, "CopilotClient", Client)
    monkeypatch.setattr(copilot_auth, "get_effective_token", lambda: "github_pat_synthetic")
    monkeypatch.setattr(copilot_client, "_client_options", lambda token: {
        "github_token": token, "env": {}, "use_logged_in_user": False,
    })
    # All fake SDK coroutines complete immediately. Drive them without an OS
    # event loop: Windows creates a TCP wakeup pair even for an offline loop.
    async def immediate(awaitable, *, timeout):
        assert timeout == 120
        return await awaitable
    monkeypatch.setattr(copilot_client.asyncio, "wait_for", immediate)
    pending = copilot_client._ask_async("Fixture plan", "test", tool_request=request(), tool_executor=Executor(), max_tool_calls=1)
    with pytest.raises(StopIteration) as finished:
        pending.send(None)
    answer = finished.value.value
    assert answer == "Complete." and executions == ["one"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_errors_do_not_trigger_format_retries_or_tool_execution(monkeypatch, status):
    response = httpx.Response(status, json={"error": {"message": "Synthetic provider rejection"}})
    with pytest.raises(Exception) as caught:
        run_compatible(monkeypatch, "together", [response])
    assert getattr(caught.value, "status_code", None) == status


def test_reused_call_id_after_execution_stops_without_repeating_the_tool(monkeypatch):
    with pytest.raises(ToolContinuationError):
        run_compatible(monkeypatch, "groq", [completion([call()]), completion([call()])])


def test_missing_provider_call_id_is_not_fabricated(monkeypatch):
    malformed = call()
    malformed["id"] = ""
    with pytest.raises(AdapterProtocolError, match="stable call ID"):
        run_compatible(monkeypatch, "nvidia", [completion([malformed])])


def test_activity_text_does_not_prevent_a_safe_route_fallback(monkeypatch):
    tried = []
    def factory(provider, _model):
        tried.append(provider)
        if provider == "first":
            yield llm._progress_chunk("Connecting...")
            raise RuntimeError("Provider unavailable before any tool execution")
        yield "Complete."
    monkeypatch.setattr(llm, "_route_cooldowns", {})
    output = list(llm._stream_with_fallbacks("test", [("first", "model"), ("next", "model")], factory))
    assert output[-1] == "Complete." and tried == ["first", "next"]


@pytest.mark.parametrize("empty", [False, True])
def test_legacy_executor_dispatch_prevents_route_replay(monkeypatch, empty):
    tried, executed = [], []
    monkeypatch.setattr(llm, "_route_cooldowns", {})
    monkeypatch.setattr(llm._LIVE_TOOL_CONTEXT, "tool_execution_serial", 0, raising=False)
    monkeypatch.setattr(llm._TOOL_REGISTRY, "execute", lambda name, inputs: executed.append(name) or "Done")
    monkeypatch.setattr(llm, "_scrub_live_tool_result", lambda _name, result: result)
    monkeypatch.setattr(llm, "_consume_model_tool_ui_request", lambda _name, result: result)

    def factory(provider, _model):
        tried.append(provider)
        _REAL_EXECUTE_MODEL_TOOL("fixture", {"path": "synthetic"}, allowed_tools=["fixture"])
        if not empty:
            raise RuntimeError("Transport failed after execution")
        yield from ()

    with pytest.raises(RuntimeError) as failure:
        list(llm._stream_with_fallbacks("test", [("first", "model"), ("next", "model")], factory))
    assert failure.value.tools_executed is True
    assert executed == ["fixture"] and tried == ["first"]


def test_external_schema_references_cannot_fetch_remote_content():
    from core.llm_clients.adapter_protocol import argument_error

    assert argument_error({"path": "test"}, {"$ref": "https://adapter.invalid/schema.json"})


def test_gpt6_structured_requests_use_responses_and_validate_arguments(monkeypatch):
    from core.llm_clients.provider_requests import required_tool_call

    sent = []
    def create(**options):
        sent.append(options)
        return {"status": "completed", "output": [{
            "type": "function_call", "call_id": "one", "name": "fixture",
            "arguments": '{"path":"synthetic"}',
        }]}

    monkeypatch.setattr(llm, "_dynamic_openai_client", lambda provider: NS(responses=NS(create=create)))
    result = required_tool_call("openai", "gpt-6-astra", system="Fixture system", prompt="Fixture prompt",
                                tool=TOOLS[0], max_tokens=1200)
    assert result.arguments == {"path": "synthetic"}
    assert sent[0]["store"] is False and sent[0]["max_output_tokens"] == 1200
    assert sent[0]["tool_choice"] == {"type": "function", "name": "fixture"}


@pytest.mark.parametrize("with_credentials", [False, True])
def test_missing_route_configuration_keeps_its_clear_error(with_credentials):
    check = llm._check_route_config_with_credentials if with_credentials else llm._check_route_config
    with pytest.raises(ValueError, match="route is missing provider or model"):
        check("", "", "Fixture")


@pytest.mark.parametrize("provider", sorted(COMPATIBLE_PROVIDERS | {"custom@synthetic"}))
@pytest.mark.parametrize("use_tools", [False, True])
@pytest.mark.parametrize("with_text", [False, True])
def test_multiple_image_replies_survive_every_compatible_provider(monkeypatch, provider, use_tools, with_text):

    urls = ["data:image/png;base64,aW1hZ2Ux", "data:image/jpeg;base64,aW1hZ2Uy"]
    images = [{"type": "image_url", "image_url": {"url": url}} for url in urls]
    chunks, _, executed = run_compatible(monkeypatch, provider, [
        completion(text="Two images." if with_text else "", images=images),
    ], use_tools=use_tools)
    attachments = [image for chunk in chunks if getattr(chunk, "kind", "") == "attachments"
                   for image in json.loads(chunk)]
    assert [image["data_url"] for image in attachments] == urls
    assert "".join(str(chunk) for chunk in chunks if getattr(chunk, "kind", "answer") == "answer") == ("Two images." if with_text else "")
    assert not executed


@pytest.mark.parametrize("shape", ["inline_data", "inlineData", "anthropic", "responses", "content"])
def test_image_output_normalizes_native_payloads_without_reading_tool_arguments(shape):
    from core.llm_clients.image_output import extract_images

    native = {
        "inline_data": {"inline_data": {"mime_type": "image/jpeg", "data": "YWJj"}},
        "inlineData": {"inlineData": {"mimeType": "image/jpeg", "data": "YWJj"}},
        "anthropic": {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "YWJj"}},
        "responses": {"type": "image_generation_call", "result": "YWJj", "media_type": "image/jpeg"},
        "content": {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,YWJj"}},
    }[shape]
    assert [item["data_url"] for item in extract_images({"content": [native, native]})] == ["data:image/jpeg;base64,YWJj"]
    assert extract_images({"type": "tool_use", "input": {"content": [native]}}) == []


def test_remote_image_output_is_downloaded_before_ui_persistence(monkeypatch):
    from core.llm_clients.image_output import ImageOutputChunk

    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"image bytes")
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        monkeypatch.setattr(httpx, "stream", transport.stream)
        chunk = ImageOutputChunk([{"kind": "image", "url": "https://images.invalid/result.png"}])
    assert json.loads(chunk)[0]["data_url"].startswith("data:image/png;base64,")
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize("family", ["anthropic", "responses"])
def test_native_image_only_turn_finishes_and_preserves_multiple_images(family):
    if family == "anthropic":
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
                  for data in ["b25l", "dHdv"]]
        endpoint = NS(create=lambda **_kw: NS(stop_reason="end_turn", content=blocks))
        model = AnthropicChatLoopModel(NS(messages=endpoint), model="test", system="test", messages=[], tools=[], max_tokens=256)
    else:
        blocks = [{"type": "image_generation_call", "id": f"image-{i}", "status": "completed", "result": data}
                  for i, data in enumerate(["b25l", "dHdv"])]
        endpoint = NS(create=lambda **_kw: {"status": "completed", "output": blocks})
        model = ResponsesChatLoopModel(NS(responses=endpoint), model="test", instructions="test", tools=[])
    final = ChatToolLoop().run(request(), model, NS(execute=lambda _call: pytest.fail("No tools expected")))
    assert final.status == "final"
    assert final.text == ""
    assert [item["data_url"] for item in final.metadata["attachments"]] == [
        "data:image/png;base64,b25l", "data:image/png;base64,dHdv",
    ]


def test_generated_images_replay_on_followup_for_both_input_protocols():
    messages = [{"role": "assistant", "content": "", "images_base64": ["b25l", "dHdv"]},
                {"role": "user", "content": "Edit the second image"}]
    assert llm._history_user_has_image(messages)
    openai = llm._openai_history_payload(messages)
    assert [part["image_url"]["url"] for part in openai[0]["content"] if part["type"] == "image_url"] == [
        "data:image/png;base64,b25l", "data:image/png;base64,dHdv",
    ]
    _, anthropic = llm._anthropic_history_payload(messages)
    assert [part["source"]["data"] for part in anthropic[0]["content"] if part["type"] == "image"] == ["b25l", "dHdv"]
    from core.llm_clients.provider_requests import responses_kwargs
    converted = responses_kwargs({"model": "test", "messages": openai})
    assert len([part for part in converted["input"][0]["content"] if part["type"] == "input_image"]) == 2


def test_nonstream_image_only_completion_and_copilot_shim_preserve_images(monkeypatch):
    from core.auth import copilot_client
    from core.llm_clients.image_output import ImageReplyText

    images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,b25l"}},
              {"type": "image_url", "image_url": {"url": "data:image/png;base64,dHdv"}}]
    endpoint = NS(create=lambda **_kw: completion(images=images))
    chunks = list(llm._run_unified_compatible_tool_loop(NS(chat=NS(completions=endpoint)), {
        "messages": [{"role": "user", "content": "Draw two"}], "stream": False,
    }, provider="openai", model="test"))
    assert len(json.loads(next(chunk for chunk in chunks if getattr(chunk, "kind", "") == "attachments"))) == 2
    text = copilot_client._extract_content({"data": {"content": images}})
    assert isinstance(text, ImageReplyText) and not text and len(text.images) == 2
    monkeypatch.setattr(copilot_client, "ask", lambda *_a, **_kw: text)
    assert len(json.loads(list(copilot_client.stream("Draw", "test"))[0])) == 2


def test_responses_completed_events_keep_images_without_duplicating_them(monkeypatch):
    from contextlib import contextmanager

    output = [{"type": "image_generation_call", "result": data} for data in ["b25l", "dHdv"]]
    @contextmanager
    def stream(**_kwargs):
        yield iter([NS(type="response.output_item.done", item=item) for item in output] + [
            NS(type="response.completed", response={"output": output}),
        ])
    chunks = list(llm._response_stream_text(NS(responses=NS(stream=stream)), {}, provider="openai", model="test"))
    assert len([image for chunk in chunks for image in json.loads(chunk)]) == 2


def test_markdown_image_replies_resolve_local_files_but_ignore_code_examples(tmp_path):
    from core.llm_clients.image_output import extract_images, markdown_images

    path = tmp_path / "image with spaces.png"
    path.write_bytes(b"image")
    reply = f"![first](<{path}>)\n![second](relative.png)"
    (tmp_path / "relative.png").write_bytes(b"image")
    assert [item["path"] for item in markdown_images(reply, cwd=tmp_path)] == [str(path), str(tmp_path / "relative.png")]
    assert extract_images({"content": "`![example](https://example.invalid/x.png)`"}) == []
    assert extract_images({"content": reply})[0]["path"] == str(path)
