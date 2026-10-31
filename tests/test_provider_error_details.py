"""Provider messages retain their origin and fields without leaking credentials."""

import json
from types import SimpleNamespace

import pytest

from core.llm_clients.error_details import from_exception, normalize
from core.llm_clients.routing import _route_failure_summary
from runtime.supervisor.ipc import WorkerError


@pytest.mark.parametrize(
    "provider,body,code",
    [
        (
            "google",
            [
                {
                    "error": {
                        "message": "Original quota message.",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"retryDelay": "57.2s"}],
                    }
                }
            ],
            "RESOURCE_EXHAUSTED",
        ),
        ("openai", {"message": "Original quota message.", "code": "insufficient_quota"}, "insufficient_quota"),
        (
            "anthropic",
            {"error": {"type": "rate_limit_error", "message": "Original quota message."}},
            "rate_limit_error",
        ),
        (
            "groq",
            {"error": {"message": "Original quota message.", "code": "rate_limit_exceeded"}},
            "rate_limit_exceeded",
        ),
    ],
)
def test_original_structured_provider_message_survives_wrapping_and_workers(provider, body, code):
    error = RuntimeError("SDK wrapper, not the provider message")
    error.status_code = 429
    error.body = body
    error.provider_error = from_exception(error, provider=provider, model="model")
    wrapped = _route_failure_summary("chat", [(provider, "model", error)], error)
    wire = json.loads(json.dumps(wrapped.provider_error))
    remote = WorkerError("Remote exception wrapper", provider_error=wire)
    result = from_exception(remote)
    assert result["message"] == "Original quota message."
    assert result["provider"] == provider and result["http_status"] == 429 and result["code"] == code
    assert result["source"] == "provider"
    if provider == "google":
        assert result["retry_after_seconds"] == 57.2


def test_credentials_and_request_payloads_are_not_in_displayable_details():
    secret = "arbitrary-provider-credential-12345"  # secret-scan: allow (synthetic test credential)
    error = RuntimeError("SDK wrapper")
    error.status_code = 401
    error.body = {
        "error": {
            "message": f"Invalid credential: {secret}",
            "api_key": secret,
            "request": {"prompt": "private request body"},
            "headers": {"Authorization": "Bearer " + secret},
        }
    }
    result = from_exception(error, provider="google", secrets=(secret,))
    serialized = json.dumps(result)
    assert secret not in serialized and "private request body" not in serialized
    assert "Invalid credential: [REDACTED]" in result["message"]
    assert "headers" not in serialized


@pytest.mark.parametrize(
    "message",
    [
        "Connection failed.",
        "Local file could not be read.",
        "Provider stream ended without a completion marker.",
        "Local parser could not decode the text HTTP 429.",
    ],
)
def test_local_and_network_failures_do_not_claim_the_provider_reported_them(message):
    result = from_exception(RuntimeError(message), provider="google")
    assert result["source"] == "openwand"
    assert result["http_status"] is None
    assert result["message"] == message
    assert "retry_after_seconds" not in result


def test_retry_header_is_preserved_without_inventing_a_default():
    error = RuntimeError("Try later")
    error.status_code = 429
    error.response = SimpleNamespace(headers={"retry-after": "12.5"}, json=lambda: {"error": {"message": "Try later"}})
    assert from_exception(error)["retry_after_seconds"] == 12.5
    error.response = None
    assert "retry_after_seconds" not in from_exception(error)


def test_normalizing_details_preserves_non_english_original_message():
    original = "Limite atteinte. Réessayez demain. <think>literal</think>"
    info = {
        "message": original,
        "provider": "google",
        "source": "provider",
        "http_status": 429,
        "code": "RESOURCE_EXHAUSTED",
    }
    assert normalize(info)["message"] == original


def test_response_failure_event_keeps_original_provider_error(monkeypatch):
    from core.llm_clients import client as llm
    from core.llm_clients.adapter_protocol import AdapterProtocolError
    from core.llm_clients.chat_tool_loop import ChatToolRequest
    from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

    response = {
        "status": "failed",
        "error": {"code": "insufficient_quota", "message": "Original event error, unchanged."},
    }
    monkeypatch.setattr(llm, "_responses_create_with_retries", lambda *a, **k: response)
    request = ChatToolRequest(
        messages=[{"role": "user", "content": "Hi"}],
        system_prompt="",
        model_route={},
        tools=[],
        allowed_tools=[],
        pinned_tools=[],
        permissions={},
        budgets={},
    )
    model = ResponsesChatLoopModel(None, model="model", instructions="", tools=[], initial_input=[], provider="chatgpt")
    with pytest.raises(AdapterProtocolError) as caught:
        model.next_turn(request, [], [])
    info = from_exception(caught.value)
    assert info["message"] == "Original event error, unchanged."
    assert info["source"] == "provider" and info["code"] == "insufficient_quota"
    assert info["http_status"] is None
    assert llm._is_quota_error(caught.value)
