"""Public search works independently of AI-provider credentials."""

from types import SimpleNamespace

import pytest

from core.web_search import WebSearchError, search_web


@pytest.fixture(autouse=True)
def public_search_environment(monkeypatch):
    from core.llm_clients import page_reader

    monkeypatch.setattr(page_reader, "PAGES", page_reader.PageCache())
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


@pytest.fixture
def search_batches(monkeypatch):
    from core.llm_clients import client, web_search_tool

    monkeypatch.setattr(web_search_tool, "SNAPSHOTS", web_search_tool.SearchSnapshots())
    rows = [{"title": f"Page {i}", "url": f"https://example.com/{i}", "snippet": f"Snippet {i}"}
            for i in range(1, 11)]
    searches, reads = [], []

    def search(query, **kwargs):
        searches.append((query, kwargs))
        # A second fresh search deliberately changes the order.
        return rows if len(searches) == 1 else rows[::-1]

    def read(url):
        reads.append(url)
        return f"Full page evidence: {url}"

    monkeypatch.setattr("core.context_fetcher.search_online_for_tool", search)
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool", read)
    return client, web_search_tool, searches, reads


def _search_id(text):
    return next(line.removeprefix("Search ID: ") for line in text.splitlines() if line.startswith("Search ID: "))


def test_search_ranges_reuse_original_order_and_page_contents(search_batches):
    client, _module, searches, reads = search_batches
    first = client._execute_web_search({"query": "topic", "start_result": 1, "end_result": 2})
    search_id = _search_id(first)
    second = client._execute_web_search({
        "query": "topic", "search_id": search_id, "start_result": 3, "end_result": 4,
    })
    repeated = client._execute_web_search({
        "query": "topic", "search_id": search_id, "start_result": 1, "end_result": 2,
    })
    assert searches == [("topic", {"max_results": 10})]
    assert sorted(reads) == [f"https://example.com/{i}" for i in range(1, 5)]
    assert "3. Page 3" in second and "4. Page 4" in second
    assert "1. Page 1" not in second
    assert repeated == first
    fresh = client._execute_web_search({"query": "topic", "end_result": 1})
    assert "1. Page 10" in fresh and _search_id(fresh) != search_id


@pytest.mark.parametrize("arguments", [
    {"start_result": 0}, {"end_result": 11}, {"start_result": 4, "end_result": 2},
    {"start_result": 1, "end_result": 6}, {"start_result": True}, {"end_result": "3"},
    {"search_id": "unknown"},
])
def test_invalid_search_ranges_never_silently_run_another_search(search_batches, arguments):
    client, _module, searches, reads = search_batches
    assert "failed" in client._execute_web_search({"query": "topic", **arguments}).lower()
    assert not searches and not reads


def test_saved_search_rejects_query_changes_and_expired_ids(search_batches, monkeypatch):
    client, module, searches, _reads = search_batches
    first = client._execute_web_search({"query": "topic"})
    search_id = _search_id(first)
    assert "does not match" in client._execute_web_search({"query": "other", "search_id": search_id})
    snapshot = module.SNAPSHOTS.get(search_id, "")
    snapshot.created = 0
    monkeypatch.setattr(module.time, "monotonic", lambda: module.SNAPSHOT_TTL)
    assert "expired" in client._execute_web_search({"query": "topic", "search_id": search_id})
    assert len(searches) == 1


def test_saved_searches_are_scoped_and_bounded(search_batches, monkeypatch):
    _client, module, _searches, _reads = search_batches
    monkeypatch.setattr(module, "SNAPSHOT_LIMIT", 2)
    store = module.SearchSnapshots()
    first, _ = store.add("topic", "chat-a", [])
    second, _ = store.add("topic", "chat-b", [])
    assert store.get(first, "chat-b") is None
    assert store.get(first, "chat-a") is not None
    store.add("new topic", "chat-a", [])
    assert store.get(second, "chat-b") is None  # Least recently used entry was evicted.


def test_search_page_failure_preserves_other_evidence_and_source_json(search_batches, monkeypatch):
    import json

    client, _module, _searches, _reads = search_batches
    from core.llm_clients.page_reader import PAGE_CHARS

    def read(url):
        if url.endswith("/1"):
            raise TimeoutError("unavailable")
        return "x" * (PAGE_CHARS + 100)

    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool", read)
    result = client._execute_web_search({"query": "topic", "end_result": 2})
    assert "TimeoutError" in result
    assert "x" * PAGE_CHARS in result
    assert "x" * (PAGE_CHARS + 1) not in result
    assert "Truncated: 100 more characters available" in result
    assert [row["url"] for row in json.loads(result.rpartition("Raw JSON:\n")[2])] == [
        "https://example.com/1", "https://example.com/2",
    ]


def test_search_and_read_batch_needs_only_two_model_requests(search_batches, monkeypatch):
    import json
    from copy import deepcopy

    client, _module, searches, reads = search_batches
    monkeypatch.setattr(client, "_route_capabilities", {})
    requests = []

    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        calls = [{"id": "search-read", "type": "function", "function": {
            "name": "web_search", "arguments": json.dumps({
                "query": "topic", "start_result": 1, "end_result": 3,
            }),
        }}] if len(requests) == 1 else []
        assert len(requests) <= 2
        return {"choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": {
            "content": None if calls else "An answer based on three pages.", "tool_calls": calls,
        }}]}

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    output = list(client._run_unified_compatible_tool_loop(
        sdk, {"model": "synthetic-gemini", "messages": [{"role": "user", "content": "Research topic."}],
              "tools": client._get_openai_tool_schemas(allowed_tools=["web_search"]), "stream": False},
        provider="google", model="synthetic-gemini", allowed_tools=["web_search"], user_intent="Research topic.",
    ))
    assert output[-1] == "An answer based on three pages."
    assert len(requests) == 2 and len(searches) == 1 and len(reads) == 3
    evidence = next(m["content"] for m in requests[-1]["messages"] if m["role"] == "tool")
    for i in range(1, 4):
        assert f"Full page evidence: https://example.com/{i}" in evidence


@pytest.mark.parametrize("size", [99_999, 100_000, 100_001])
def test_page_character_limit_counts_complete_extracted_text(monkeypatch, size):
    from core.llm_clients import client

    calls = []
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool",
                        lambda url: calls.append(url) or "x" * size)
    result = client._execute_retrieve_website({"url": "https://example.com/large"})
    assert f"Total readable characters: {size}" in result
    assert f"Remaining characters: {max(0, size - 100_000)}" in result
    assert "x" * min(size, 100_000) in result
    if size > 100_000:
        assert "x" * size not in result
        assert "read_full=true" in result and "offset=100000" in result
    else:
        assert "[Complete]" in result and "Truncated" not in result
    assert len(calls) == 1


def test_full_and_continuation_reads_reuse_complete_cached_page(monkeypatch):
    from core.llm_clients import client

    text = "a" * 100_000 + "z" * 50
    calls = []
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool",
                        lambda url: calls.append(url) or text)
    url = "https://example.com/complete-copy"
    first = client._execute_retrieve_website({"url": url})
    full = client._execute_retrieve_website({"url": url, "read_full": True})
    rest = client._execute_retrieve_website({"url": url, "offset": 100_000})
    assert "Remaining characters: 50" in first
    assert text in full and "[Complete]" in full
    assert "Returned characters: 100001-100050" in rest
    assert "z" * 50 in rest and "a" * 1000 not in rest
    assert "earlier text was omitted by offset" in rest
    assert calls == [url]


@pytest.mark.parametrize("arguments", [
    {"read_full": "true"}, {"offset": -1}, {"offset": True},
    {"read_full": True, "offset": 1},
])
def test_invalid_page_read_arguments_do_not_fetch(monkeypatch, arguments):
    from core.llm_clients import client

    def unexpected(url):
        pytest.fail("Invalid page options must not cause a download")

    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool", unexpected)
    assert "requires" in client._execute_retrieve_website({"url": "https://example.com/page", **arguments})


def test_full_read_never_silently_truncates_at_remaining_turn_budget(monkeypatch):
    from core.llm_clients import client
    from core.llm_clients.chat_tool_loop import OpenWandToolCall
    from core.llm_clients.responses_chat_adapter import LiveModelToolExecutor

    monkeypatch.setattr(client, "_tool_turn_budget", lambda: SimpleNamespace(
        max_result_chars=200_000, max_total_chars=120_000,
    ))
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool", lambda url: "x" * 110_000)
    executor = LiveModelToolExecutor(allowed_tools=["retrieve_website"])
    executor._spent_chars = 80_000
    result = executor.execute(OpenWandToolCall("full-read", "retrieve_website", {
        "url": "https://example.com/budget", "read_full": True,
    }))
    assert not result.ok
    assert "Full page not returned" in result.content and "40000" in result.content
    assert "x" * 1000 not in result.content and "[Complete]" not in result.content


def test_full_read_respects_per_result_budget(monkeypatch):
    from core.llm_clients import client

    monkeypatch.setattr(client, "_tool_turn_budget", lambda: SimpleNamespace(max_result_chars=100_000))
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool", lambda url: "x" * 110_000)
    result = client._execute_retrieve_website({"url": "https://example.com/budget", "read_full": True})
    assert "Full page not returned" in result and "offset" in result
    assert "x" * 1000 not in result


def test_page_cache_expiration_and_scope_cause_fresh_downloads(monkeypatch):
    from core.llm_clients import page_reader

    calls = []

    def fetch(url):
        calls.append(url)
        return f"Page version {len(calls)}"

    url = "https://example.com/changing"
    first = page_reader.read_page(url, fetch=fetch, scope="chat-a")
    assert first == page_reader.read_page(url, fetch=fetch, scope="chat-a")
    assert "Page version 2" in page_reader.read_page(url, fetch=fetch, scope="chat-b")
    page_reader.PAGES.get("chat-a", url).created = 0
    monkeypatch.setattr(page_reader.time, "monotonic", lambda: page_reader.CACHE_TTL)
    assert "Page version 3" in page_reader.read_page(url, fetch=fetch, scope="chat-a")
    assert len(calls) == 3


def test_page_cache_evicts_by_byte_budget(monkeypatch):
    from core.llm_clients import page_reader

    monkeypatch.setattr(page_reader, "CACHE_BYTES", 8)
    store = page_reader.PageCache()
    store.put("chat", "first", "aaaa")
    store.put("chat", "second", "bbbb")
    assert store.get("chat", "first") is not None
    store.put("chat", "third", "cccc")
    assert store.get("chat", "second") is None
    assert store.get("chat", "first") is not None


def test_search_workers_and_direct_full_reads_share_conversation_cache(search_batches, monkeypatch):
    client, _module, _searches, _reads = search_batches
    calls = []
    text = "x" * 100_050
    monkeypatch.setattr("core.context_fetcher.fetch_browser_content_for_tool",
                        lambda url: calls.append(url) or text)
    client.set_live_privacy_context(SimpleNamespace(session_id="chat-page-cache"))
    try:
        search = client._execute_web_search({"query": "topic", "end_result": 1})
        assert "Remaining characters: 50" in search
        full = client._execute_retrieve_website({"url": "https://example.com/1", "read_full": True})
        assert text in full and "[Complete]" in full
        assert calls == ["https://example.com/1"]
    finally:
        client.set_live_privacy_context(None)
