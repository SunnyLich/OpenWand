"""Offline checks for the test-only harness and real OpenWand adapter."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from . import gemini_adapter_qa as qa


def tool_call(name, args, index):
    """Build one SDK function-call fixture."""
    return {"id": f"call_{name}_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def completion(calls=(), final="", stream=False):
    """Build real SDK response objects without connecting to a provider."""
    data = {"id": "synthetic-response", "created": 1, "model": qa.MODEL, "object": "chat.completion.chunk" if stream else "chat.completion", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
    message = {"role": "assistant", "content": final or None}
    if calls:
        message["tool_calls"] = [tool_call(name, args, i) for i, (name, args) in enumerate(calls)]
        if stream:
            for i, tc in enumerate(message["tool_calls"]):
                tc["index"] = i
    data["choices"] = [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "delta" if stream else "message": message}]
    return ChatCompletionChunk(**data) if stream else ChatCompletion(**data)


class Stream:
    """Minimal context-managed synthetic SDK stream."""

    def __init__(self, chunk):
        """Retain the single fixture chunk."""
        self.chunk = chunk

    def __enter__(self):
        """Return the stream."""
        return self

    def __exit__(self, *args):
        """No connection needs closing."""
        return False

    def __iter__(self):
        """Yield one synthetic fixture."""
        yield self.chunk


class ScriptedSDK:
    """Emit prescribed turns and retain request protocol for assertions."""

    def __init__(self, case):
        """Prepare expected tool rounds and a final answer."""
        self.case = case
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        """Supply the next turn without any transport."""
        self.requests.append(copy.deepcopy(kwargs))
        round_index = len(self.requests) - 1
        expected = self.case["expected"]
        if self.case["name"] == "multiround_tools":
            calls = expected[round_index:round_index + 1]
        else:
            calls = expected if round_index == 0 else []
        final = "" if calls else self.case["final"]
        result = completion(calls, final, kwargs["stream"])
        return Stream(result) if kwargs["stream"] else result


@pytest.mark.parametrize("case", qa.scenarios(), ids=lambda c: c["name"])
def test_nine_scenarios_through_actual_adapter(case):
    """Validate schemas, loop execution, correlation, grading, and usage capture."""
    sdk = ScriptedSDK(case)
    result = qa.run_case(case, sdk, qa.Gate())
    assert result["error"] is None
    assert result["tool_contract"] == "pass"
    assert result["content"] == "pass"
    assert all(record["responses"][-1]["usage"]["total_tokens"] == 13 for record in result["records"])
    for request in sdk.requests:
        assert request["model"] == qa.MODEL
        assert request["max_tokens"] == 256
        for message in request["messages"]:
            if message["role"] == "tool":
                assert any(message["tool_call_id"] == tc["id"] for prior in request["messages"] if prior["role"] == "assistant" for tc in prior.get("tool_calls", []))
    if case["expected"]:
        assert sdk.requests[0]["stream"] is True
        assert sdk.requests[1]["stream"] is False
        assert any(m["role"] == "tool" for m in sdk.requests[1]["messages"])


def test_quota_error_stops_without_adapter_retry():
    """An HTTP 429 cannot enter the product's retry recovery path."""
    calls = []

    def fail(**kwargs):
        """Raise a real SDK rate-limit exception without network."""
        calls.append(kwargs)
        response = httpx.Response(429, request=httpx.Request("POST", qa.ENDPOINT))
        raise RateLimitError("synthetic quota exhausted", response=response, body={"error": "RESOURCE_EXHAUSTED"})

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    gate = qa.Gate()
    result = qa.run_case(qa.scenarios()[0], sdk, gate)
    assert result["error"]["status_code"] == 429
    assert len(calls) == gate.count == 1
    assert gate.stopped
    assert result["tool_contract"] == "unresolved"


@pytest.mark.parametrize("change", [{"model": "other-model"}, {"max_tokens": 257}, {"n": 2}, {"service_tier": "priority"}])
def test_request_guard_rejects_unapproved_work(change):
    """Reject changes to model, cap, candidate count, and paid feature knobs."""
    kwargs = {"model": qa.MODEL, "max_tokens": 256, "messages": []}
    kwargs.update(change)
    gate = qa.Gate()
    with pytest.raises(qa.StopRun):
        gate.allow(kwargs)
    assert gate.count == 0


def test_total_cap_is_exactly_twenty():
    """The twenty-first generation is rejected before transport."""
    gate = qa.Gate()
    kwargs = {"model": qa.MODEL, "max_tokens": 256, "messages": []}
    for _ in range(20):
        gate.allow(kwargs)
    with pytest.raises(qa.StopRun):
        gate.allow(kwargs)
    assert gate.count == 20


def test_bad_arguments_and_output_are_separate():
    """Wrong final prose does not erase an otherwise correct tool contract."""
    case = qa.scenarios()[1]
    calls = [{"name": "qa_lookup", "arguments": {"code": "A"}, "schema_valid": True}]
    grade = qa.grade(case, calls, "The answer is ALPHA_41.", [], None)
    assert grade["tool_contract"] == "pass"
    assert grade["content"] == "fail"
    assert not qa.validate(qa.SPECS["qa_record"][1], {"profile": {"name": "Nia", "active": "true"}, "items": [], "priority": "high"})


def test_secret_redaction(monkeypatch):
    """Even exceptions containing the current credential are redacted."""
    monkeypatch.setattr(qa, "KEY", "synthetic-sensitive-value")
    assert "synthetic-sensitive-value" not in json.dumps(qa.sanitized({"message": "key=synthetic-sensitive-value"}))


def test_signature_survives_after_fix():
    """Ensure the live harness observes preserved metadata in replayed calls."""
    class SignatureSDK(ScriptedSDK):
        """Add representative Google extension metadata to a tool-call chunk."""

        def create(self, **kwargs):
            """Supply signed synthetic tool metadata on the first response."""
            result = super().create(**kwargs)
            if kwargs["stream"]:
                raw = result.chunk.model_dump(exclude_none=True)
                raw["choices"][0]["delta"]["tool_calls"][0]["extra_content"] = {"google": {"thought_signature": "synthetic-signature-not-a-credential"}}
                result.chunk = ChatCompletionChunk(**raw)
            return result

    sdk = SignatureSDK(qa.scenarios()[1])
    result = qa.run_case(qa.scenarios()[1], sdk, qa.Gate())
    assert result["records"][0]["responses"][0]["thought_signature_present"]
    assistant = next(m for m in sdk.requests[1]["messages"] if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "synthetic-signature-not-a-credential"
    recorded = result["records"][1]["request"]
    assert "synthetic-signature-not-a-credential" not in json.dumps(recorded)
    assert "[PRESENT; REDACTED]" in json.dumps(recorded)


def test_original_requests_count_toward_twenty():
    """Only seventeen additional calls fit after the original three requests."""
    gate = qa.Gate(prior_requests=3)
    kwargs = {"model": qa.MODEL, "max_tokens": 256, "messages": []}
    for _ in range(17):
        gate.allow(kwargs)
    with pytest.raises(qa.StopRun):
        gate.allow(kwargs)
    assert gate.count == 20


def test_only_parallel_verification_with_two_remaining_requests():
    """Permit exactly two requests after the eighteen already consumed."""
    cases = qa.verification_cases()
    assert len(cases) == 1
    assert cases[0]["name"] == "multiple_tools"
    assert cases[0]["budget"] == 2
    gate = qa.Gate(prior_requests=18)
    kwargs = {"model": qa.MODEL, "max_tokens": 256, "messages": []}
    gate.allow(kwargs)
    gate.allow(kwargs)
    with pytest.raises(qa.StopRun):
        gate.allow(kwargs)
    assert gate.count == 20
