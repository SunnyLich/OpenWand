"""Public search works independently of AI-provider credentials."""

from types import SimpleNamespace

import pytest

from core.web_search import WebSearchError, search_web


@pytest.fixture(autouse=True)
def public_search_environment(monkeypatch):
    monkeypatch.setattr("core.privacy_gateway.scrub_cloud_fields", lambda fields, **kwargs: (None, fields, {}))
    monkeypatch.setattr("core.web_search.getproxies", lambda: {})
    for key in ("DDGS_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)


def _install_engine(monkeypatch, rows=None, error=None):
    import ddgs

    calls = []

    class Engine:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def text(self, query, **kwargs):
            calls.append({"query": query, **kwargs})
            if error:
                raise error
            return rows

    monkeypatch.setattr(ddgs, "DDGS", Engine)
    return calls


def test_public_search_normalizes_sources_without_provider_keys(monkeypatch):
    import config

    monkeypatch.setattr(config, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    calls = _install_engine(monkeypatch, [
        {"title": "Official forecast", "href": "https://weather.gc.ca/forecast", "body": "Current conditions"},
        {"title": "Duplicate", "href": "https://weather.gc.ca/forecast"},
        {"title": "Unsafe", "href": "javascript:alert(1)"},
        {"title": "Credentials", "href": "https://user:password@example.com"},
        {"href": "https://example.com", "body": "More information"},
    ])
    assert search_web("weather", 2) == [
        {"title": "Official forecast", "url": "https://weather.gc.ca/forecast", "snippet": "Current conditions"},
        {"title": "example.com", "url": "https://example.com", "snippet": "More information"},
    ]
    assert calls[0] == {"proxy": None, "timeout": 8, "verify": True}
    # Leave engine selection to DDGS's automatic cross-engine search.
    assert calls[1] == {"query": "weather", "safesearch": "moderate", "max_results": 2}


@pytest.mark.parametrize("limit,expected", [(99, 10), (-1, 1), ("invalid", 5)])
def test_public_search_caps_request_size(monkeypatch, limit, expected):
    calls = _install_engine(monkeypatch, [{"href": "https://example.com"}])
    search_web("example", limit)
    assert calls[1]["max_results"] == expected


def test_public_search_scrubs_query_and_respects_network_configuration(monkeypatch):
    monkeypatch.setattr("core.web_search.getproxies", lambda: {"https": "http://configured-proxy:8080"})
    monkeypatch.setenv("SSL_CERT_FILE", "configured-ca.pem")
    monkeypatch.setattr(
        "core.privacy_gateway.scrub_cloud_fields",
        lambda fields, **kwargs: (None, {"search_query": "masked query"}, {}),
    )
    calls = _install_engine(monkeypatch, [{"href": "https://example.com"}])
    search_web("private query")
    assert calls[0]["proxy"] == "http://configured-proxy:8080"
    assert calls[0]["verify"] == "configured-ca.pem"
    assert calls[1]["query"] == "masked query"


@pytest.mark.parametrize("rows", [[], [{"href": "file:///private/file"}], [None]])
def test_empty_or_unusable_results_are_an_explicit_failure(monkeypatch, rows):
    _install_engine(monkeypatch, rows)
    with pytest.raises(WebSearchError, match="No current information was retrieved"):
        search_web("weather")


def test_service_error_keeps_actual_reason_and_never_claims_success(monkeypatch):
    _install_engine(monkeypatch, error=RuntimeError("HTTP 429: temporarily blocked"))
    with pytest.raises(WebSearchError, match="HTTP 429: temporarily blocked"):
        search_web("weather")


def test_blank_query_never_contacts_an_engine(monkeypatch):
    calls = _install_engine(monkeypatch)
    assert search_web("   ") == [] and not calls


def test_ddgs_continues_when_one_engine_is_blocked(monkeypatch):
    from ddgs.ddgs import DDGS
    from ddgs.results import TextResult

    calls = []

    def blocked(*args, **kwargs):
        calls.append("blocked")
        raise RuntimeError("HTTP 202: bot check")

    def working(*args, **kwargs):
        calls.append("working")
        return [TextResult(title="Forecast", href="https://weather.gc.ca/forecast", body="Current weather")]

    engine = DDGS(timeout=1)
    monkeypatch.setattr(engine, "_get_engines", lambda *a: [
        SimpleNamespace(name="blocked", provider="blocked", search=blocked),
        SimpleNamespace(name="working", provider="working", search=working),
    ])
    monkeypatch.setattr("ddgs.DDGS", lambda **kwargs: engine)
    assert search_web("weather", 1)[0]["url"] == "https://weather.gc.ca/forecast"
    assert set(calls) == {"blocked", "working"}


def test_live_search_does_not_finish_with_an_invented_source():
    from core.llm_clients.chat_tool_loop import (
        ChatToolLoop,
        ChatToolRequest,
        OpenWandObservation,
        OpenWandToolCall,
        OpenWandToolResult,
        _explicit_web_search,
    )

    assert not _explicit_web_search("Why does web search need an API key?")
    assert not _explicit_web_search("Don't search the web.")
    request = ChatToolRequest(
        messages=[{"role": "user", "content": "Search the web for the forecast page and give its URL."}],
        system_prompt="", model_route={}, tools=[{"name": "web_search"}],
        allowed_tools=["web_search"], pinned_tools=[], permissions={}, budgets={},
    )
    loop = ChatToolLoop()
    assert "Call it" in loop._completion_gate_message(request, [], [], "I can't search")
    call = OpenWandToolCall(id="search1", name="web_search", arguments={"query": "weather"})
    result = OpenWandToolResult(
        call_id="search1", name="web_search", ok=True,
        content='Raw JSON:\n[{"url": "[URL_1]", "title": "Official forecast"}]',
    )
    observations = [OpenWandObservation(tool_results=[result], summary="web search succeeded")]
    assert "exact URL" in loop._completion_gate_message(request, [call], observations, "https://invented.example/weather")
    assert not loop._completion_gate_message(request, [call], observations, "Official forecast: [URL_1]")


def test_only_public_search_sources_are_readable_to_the_model(monkeypatch):
    import json

    import config
    from core.llm_clients import client
    from core.privacy_gateway import PrivacySession

    for setting in ("PRIVACY_HIDE_URLS", "PRIVACY_HIDE_CONTACT_DETAILS", "PRIVACY_HIDE_SECRETS"):
        monkeypatch.setattr(config, setting, True)
    source = "https://weather.gc.ca/en/location/index.html?coords=42.982,-81.249"
    personal = "https://example.com/private-document"
    result = f"URL: {source}\nOwner: alex@example.com\nOther: {personal}\nRaw JSON:\n" + json.dumps([{"url": source}])
    session = PrivacySession("readable-search")
    client.set_live_privacy_context(session)
    try:
        scrubbed = client._scrub_live_tool_result("web_search", result)
        assert source in scrubbed
        assert "alex@example.com" not in scrubbed
        assert personal not in scrubbed
        assert source not in client._scrub_live_tool_result("read_file", result)
        assert source not in session.scrub_fields({"prompt": source})[0]["prompt"]
    finally:
        client.set_live_privacy_context(None)


@pytest.mark.parametrize("source", [
    "https://example.com/?api_key=private-secret-value",
    "https://user:password@example.com/private",
    "https://example.com/?email=alex%40example.com",
    "https://example.com/?email=alex%2540example.com",
    "https://example.com/?email=alex%25252540example.com",
    "https://example.com/?sessionid=private-session-value",
    "https://example.com/?X-Amz-Signature=private-signature-value",
    "https://example.com/private/123-45-6789",
    "http://localhost/private",
    "http://127.0.0.1/private",
    "http://192.168.1.2/private",
    "http://[::1]/private",
    "http://127.1/private",
])
def test_sensitive_search_source_urls_still_get_masked(monkeypatch, source):
    import config
    from core.privacy_gateway import PrivacySession

    for setting in ("PRIVACY_HIDE_URLS", "PRIVACY_HIDE_CONTACT_DETAILS", "PRIVACY_HIDE_SECRETS", "PRIVACY_HIDE_ID_NUMBERS"):
        monkeypatch.setattr(config, setting, True, raising=False)
    session = PrivacySession("private-source")
    scrubbed, report = session.scrub_fields({"tool:web_search": source}, public_source_urls=[source])
    assert scrubbed["tool:web_search"] == "[URL_1]"
    assert report["count"] == 1
    assert session.restore("[URL_1]") == source


def test_public_source_exception_keeps_advanced_privacy_detection(monkeypatch):
    from core.privacy_gateway import PrivacySession
    from core.privacy_redaction import SensitiveEntity

    source = "https://example.com/private-person"
    def detect(text, **kwargs):
        if source not in text:
            return []
        return [SensitiveEntity("secret", 0, len(source), source, "[SECRET]", kwargs.get("source", ""))]
    monkeypatch.setattr("core.privacy_model.detect_with_model", detect)
    scrubbed, _ = PrivacySession("advanced-search").scrub_fields(
        {"tool:web_search": source}, public_source_urls=[source], ai_enabled=True,
    )
    assert scrubbed["tool:web_search"] == "[SECRET_1]"


def test_anthropic_native_search_is_not_replayed_as_a_client_tool(monkeypatch):
    from unittest.mock import Mock

    from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
    from core.llm_clients.chat_tool_loop import ChatToolLoop, ChatToolRequest

    monkeypatch.setattr("core.llm_clients.client._update_route_capabilities", lambda *a, **kw: None)
    source = "https://weather.gc.ca/forecast"
    endpoint = Mock(return_value=SimpleNamespace(stop_reason="end_turn", content=[
        {"type": "server_tool_use", "id": "search1", "name": "web_search", "input": {"query": "weather"}},
        {"type": "web_search_tool_result", "tool_use_id": "search1", "content": [
            {"type": "web_search_result", "url": source, "title": "Official forecast"},
        ]},
        {"type": "text", "text": f"Official forecast: {source}"},
    ]))
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}]
    request = ChatToolRequest(
        messages=[{"role": "user", "content": "Search the web for the forecast and give its URL."}],
        system_prompt="", model_route={"provider": "anthropic"}, tools=tools,
        allowed_tools=["web_search"], pinned_tools=[], permissions={}, budgets={},
    )
    model = AnthropicChatLoopModel(
        SimpleNamespace(messages=SimpleNamespace(create=endpoint)), model="test",
        system="", messages=request.messages, tools=tools, max_tokens=256,
    )
    executor = SimpleNamespace(execute=Mock(side_effect=AssertionError("Server search must not be locally dispatched")))
    result = ChatToolLoop().run(request, model, executor)
    assert result.text == f"Official forecast: {source}"
    assert not result.metadata["completion_gate_missed"]
    endpoint.assert_called_once()
    executor.execute.assert_not_called()
