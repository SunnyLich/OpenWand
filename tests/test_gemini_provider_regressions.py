"""Recovered Gemini metadata and indexless parallel-call regressions."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.llm_clients import client as llm


@pytest.fixture(autouse=True)
def offline_provider_state(monkeypatch):
    import socket

    def blocked(*_args, **_kwargs):
        raise AssertionError("Offline Gemini regression attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(llm, "_route_capabilities", {})
    monkeypatch.setattr(llm, "_log_context", lambda *_a, **_kw: None)

@pytest.mark.parametrize("stream_first", [True, False], ids=["streamed", "nonstream-fallback"])
@pytest.mark.parametrize("signed", [
    pytest.param(True, id="google-metadata", marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="dev drops Gemini extra_content signatures during normalization/replay; recovered product fix is absent",
    )),
    pytest.param(False, id="ordinary-openai"),
])
def test_openai_tool_metadata_survives_parallel_and_later_rounds(stream_first, signed):
    """Preserve opaque tool metadata across all replay paths without inventing it."""
    from openai.types.chat import ChatCompletion, ChatCompletionChunk

    first_extra = {"google": {"trace": "keep", "thought_signature": "signature-A"}, "other": {"flag": True}}
    second_extra = {"google": {"thought_signature": "signature-B"}}
    next_extra = {"google": {"thought_signature": "signature-C"}, "vertex": {"trace": "also-keep"}}

    def call(name, call_id, extra):
        """Build a complete function call with optional provider extensions."""
        payload = {"id": call_id, "type": "function", "function": {"name": name, "arguments": '{"value":1}'}}
        if signed:
            payload["extra_content"] = deepcopy(extra)
        return payload

    first_calls = [call("qa_lookup", "call-a", first_extra), call("qa_other", "call-b", second_extra)]
    later_calls = [call("qa_next", "call-c", next_extra)]

    def response(calls):
        """Use real SDK models for completed nonstreaming tool turns."""
        return ChatCompletion(
            id="synthetic", created=1, model="test-model", object="chat.completion",
            choices=[{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                      "message": {"role": "assistant", "content": None if calls else "done", "tool_calls": calls}}],
        )

    def chunk(calls, finish=None):
        """Use real SDK models, including metadata-only streamed deltas."""
        return ChatCompletionChunk(
            id="synthetic", created=1, model="test-model", object="chat.completion.chunk",
            choices=[{"index": 0, "finish_reason": finish, "delta": {"tool_calls": calls}}],
        )

    initial = {"index": 0, "id": "call-a", "type": "function", "function": {"name": "qa_", "arguments": '{"value":'}}
    metadata_only = {"index": 0}
    rest = {"index": 0, "function": {"name": "lookup", "arguments": "1}"}}
    if signed:
        initial["extra_content"] = {"google": {"trace": "keep"}, "other": {"flag": True}}
        metadata_only["extra_content"] = {"google": {"thought_signature": "signature-A"}}
        # Repeated opaque metadata must not be concatenated like text deltas.
        rest["extra_content"] = {"google": {"thought_signature": "signature-A"}}
    empty_metadata = {"index": 0, "extra_content": {"google": {"thought_signature": None, "trace": None}, "other": None}} if signed else {"index": 0}
    chunks = [chunk([initial]), chunk([metadata_only]), chunk([empty_metadata]), chunk([rest, {"index": 1, **first_calls[1]}], "tool_calls")]

    class FakeStream:
        """Stream fragmented tool calls without making network requests."""

        def __enter__(self):
            """Yield the synthetic stream."""
            return iter(chunks)

        def __exit__(self, *_args):
            """Leave the in-memory stream."""
            return False

    class StreamModeError(RuntimeError):
        """Exercise the existing nonstreaming fallback without live retries."""

        status_code = 400

    requests = []
    completed_turns = iter([response(later_calls), response([])])

    def create(**kwargs):
        """Return first streamed/fallback turn, a later tool turn, then text."""
        requests.append(deepcopy(kwargs))
        if len(requests) == 1:
            if not stream_first:
                raise StreamModeError("stream is not supported for this model")
            return FakeStream()
        if not stream_first and len(requests) == 2:
            return response(first_calls)
        return next(completed_turns)

    schemas = [{"type": "function", "function": {"name": name, "description": "Synthetic fixture", "parameters": {"type": "object", "properties": {"value": {"type": "integer"}}}}} for name in ["qa_lookup", "qa_other", "qa_next"]]
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm._route_capabilities.clear()
    with patch.object(llm, "_get_openai_tool_schemas", return_value=schemas), \
         patch.object(llm, "_execute_model_tool", return_value="synthetic result") as execute, \
         patch.object(llm.macos_safety, "openai_compat_tools_enabled", return_value=True), \
         patch.object(llm, "_use_macos_openai_compat_non_streaming", return_value=False):
        result = list(llm._stream_openai_compat(
            "Use the synthetic tools.", None, "test-model", sdk,
            use_tools=True, allowed_tools=["qa_lookup", "qa_other", "qa_next"],
            provider="google" if signed else "openai", system_prompt="Synthetic test.",
        ))

    assert result == ["done"]
    assert execute.call_count == 3
    assistant_turns = [message for message in requests[-1]["messages"] if message["role"] == "assistant"]
    assert assistant_turns[0]["tool_calls"] == first_calls
    assert assistant_turns[1]["tool_calls"] == later_calls
    assert [message["tool_call_id"] for message in requests[-1]["messages"] if message["role"] == "tool"] == ["call-a", "call-b", "call-c"]


@pytest.mark.xfail(strict=True, raises=KeyError, reason="dev drops extra_content instead of copying provider metadata")
def test_openai_tool_metadata_is_copied_at_normalization_and_replay():
    """History, normalized calls, and SDK responses must not alias metadata."""
    extra = {"google": {"thought_signature": "synthetic-signature"}, "other": {"items": [1, 2]}}
    source = SimpleNamespace(id="call-a", function=SimpleNamespace(name="qa_lookup", arguments="{}"), extra_content=extra)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[source]))])
    normalized = llm._openai_compat_message_tool_calls(response)[0]
    assert normalized["extra_content"] == extra
    payload = llm._tool_call_payload(normalized)
    payload["extra_content"]["other"]["items"].append(3)
    assert normalized["extra_content"]["other"]["items"] == [1, 2]
    normalized["extra_content"]["google"]["thought_signature"] = "changed"
    assert extra["google"]["thought_signature"] == "synthetic-signature"


@pytest.mark.parametrize("ambiguous", [False, True], ids=["distinct-calls", "unidentified-fragment"])
@pytest.mark.xfail(
    strict=True, raises=(AssertionError, pytest.fail.Exception),
    reason="dev merges indexless parallel calls and does not reject unidentified fragments; recovered fix is absent",
)
def test_openai_parallel_stream_without_indices_executes_both_calls(ambiguous):
    """Reproduce the exact Gemini shape: distinct IDs, empty args, no indices."""
    from openai._models import construct_type
    from openai.types.chat import ChatCompletionChunk

    calls = [
        {"id": "call-alpha", "type": "function", "function": {"name": "qa_alpha", "arguments": "{}"}, "extra_content": {"google": {"thought_signature": "synthetic-signature"}}},
        {"id": "call-beta", "type": "function", "function": {"name": "qa_beta", "arguments": "{}"}},
    ]
    chunks = [construct_type(type_=ChatCompletionChunk, value={
        "id": "synthetic", "created": 1, "model": "test-model", "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"tool_calls": [call] if call else []}, "finish_reason": None if call else "stop"}],
    }) for call in [*calls, None]]
    if ambiguous:
        chunks.insert(1, construct_type(type_=ChatCompletionChunk, value={
            "id": "synthetic", "created": 1, "model": "test-model", "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"tool_calls": [{"function": {"arguments": "{}"}}]}}],
        }))

    class Stream:
        """Return the provider-shaped chunks without network."""

        def __enter__(self):
            """Enter the synthetic stream."""
            return iter(chunks)

        def __exit__(self, *_args):
            """Exit the synthetic stream."""
            return False

    requests = []

    def create(**kwargs):
        """Capture replay and return a deterministic final answer."""
        requests.append(deepcopy(kwargs))
        if len(requests) == 1:
            return Stream()
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="17,29", tool_calls=[]))])

    schemas = [{"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {}}}} for name in ["qa_alpha", "qa_beta"]]
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm._route_capabilities.clear()
    with patch.object(llm, "_get_openai_tool_schemas", return_value=schemas), \
         patch.object(llm, "_execute_model_tool", side_effect=["17", "29"]) as execute, \
         patch.object(llm.macos_safety, "openai_compat_tools_enabled", return_value=True), \
         patch.object(llm, "_use_macos_openai_compat_non_streaming", return_value=False):
        output = llm._stream_openai_compat(
            "Call both tools.", None, "test-model", sdk, use_tools=True,
            allowed_tools=["qa_alpha", "qa_beta"], provider="google", system_prompt="Synthetic test.",
        )
        if ambiguous:
            with pytest.raises(ValueError, match="no index or ID"):
                list(output)
            execute.assert_not_called()
            assert len(requests) == 1  # Identity errors must not trigger a fallback request.
            return
        result = list(output)
    assert result == ["17,29"]
    assert [call.args[:2] for call in execute.call_args_list] == [("qa_alpha", {}), ("qa_beta", {})]
    replay = next(message for message in requests[1]["messages"] if message["role"] == "assistant")
    assert replay["tool_calls"] == calls
    assert [message["tool_call_id"] for message in requests[1]["messages"] if message["role"] == "tool"] == ["call-alpha", "call-beta"]


@pytest.mark.parametrize("identity", ["index", "id", "mixed"])
@pytest.mark.xfail(
    strict=True, raises=ModuleNotFoundError,
    reason="recovered tests require the missing product helper core.llm_clients.tool_call_metadata",
)
def test_openai_stream_interleaved_fragments_keep_call_identity(identity):
    """Join each call's text and late metadata through either stable identity."""
    from core.llm_clients.tool_call_metadata import StreamToolCallAccumulator

    accumulator = StreamToolCallAccumulator()

    def add(index, call_id, name="", arguments="", extra=None):
        accumulator.add(SimpleNamespace(index=index, id=call_id,
                        function=SimpleNamespace(name=name, arguments=arguments), extra_content=extra))

    # A deliberately nonzero, out-of-order index proves index 0 is not assumed.
    add(7 if identity != "id" else None, "a" if identity != "mixed" else None, "qa_", '{"value":')
    add(2 if identity == "index" else None, "b", "qa_", '{"value":')
    if identity == "mixed":
        add(7, "a")  # Bind the previously index-only call to its ID.
        add(2, "b")  # Bind the previously ID-only call to its index.
    add(None if identity == "id" else 2, "b" if identity == "id" else None, "beta", "2}")
    add(7 if identity == "index" else None, None if identity == "index" else "a", "alpha", "1}")
    metadata = {"google": {"thought_signature": "opaque-a"}, "sibling": {"flag": True}}
    add(None, "a", extra=metadata)
    add(2 if identity != "id" else None, "b", extra={"google": {"thought_signature": "opaque-b"}})
    add(None, "a", extra={"google": {"thought_signature": None}})
    add(None, "a", extra=metadata)  # Repeated signatures are not text fragments.
    metadata["sibling"]["flag"] = False
    accumulator.add(SimpleNamespace())  # Empty delta carries no call data.
    assert list(accumulator.calls.values()) == [
        {"id": "a", "name": "qa_alpha", "arguments": '{"value":1}', "extra_content": {"google": {"thought_signature": "opaque-a"}, "sibling": {"flag": True}}},
        {"id": "b", "name": "qa_beta", "arguments": '{"value":2}', "extra_content": {"google": {"thought_signature": "opaque-b"}}},
    ]


@pytest.mark.parametrize("fragment, message", [
    ({"index": 0, "id": "b"}, "different calls"),
    ({"index": 0, "id": "new-id"}, "changes an existing call ID"),
    ({"index": 2, "id": "a"}, "changes an existing call index"),
    ({"function": SimpleNamespace(arguments="}")}, "no index or ID"),
    ({"extra_content": {"google": {"thought_signature": "unassigned"}}}, "no index or ID"),
    ({"index": -1, "id": "c"}, "invalid index"),
    ({"index": True, "id": "c"}, "invalid index"),
    ({"id": " "}, "invalid ID"),
])
@pytest.mark.xfail(
    strict=True, raises=ModuleNotFoundError,
    reason="recovered tests require the missing product helper core.llm_clients.tool_call_metadata",
)
def test_openai_stream_rejects_ambiguous_identity_without_mutating_calls(fragment, message):
    """Never join unrelated calls or attach opaque metadata by last-seen order."""
    from core.llm_clients.tool_call_metadata import StreamToolCallAccumulator

    accumulator = StreamToolCallAccumulator()
    accumulator.add(SimpleNamespace(index=0, id="a", function=SimpleNamespace(name="qa_alpha", arguments="{}")))
    accumulator.add(SimpleNamespace(index=1, id="b", function=SimpleNamespace(name="qa_beta", arguments="{}")))
    before = deepcopy(accumulator.calls)
    with pytest.raises(ValueError, match=message):
        accumulator.add(SimpleNamespace(**fragment))
    assert accumulator.calls == before
