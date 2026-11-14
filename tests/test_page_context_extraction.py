from types import SimpleNamespace

from core import context_fetcher, context_hotkey


def test_tool_page_fetch_keeps_full_text_before_model_excerpt(monkeypatch):
    import requests

    content = b"x" * 150_000
    calls, closed = [], []

    def get(url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            encoding="utf-8", raise_for_status=lambda: None,
            iter_content=lambda **kwargs: iter([content[:80_000], content[80_000:]]),
            close=lambda: closed.append(True),
        )

    def extract(**kwargs):
        assert kwargs["max_chars"] == 0
        return kwargs["html"]

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(context_fetcher, "extract_useful_page_context", extract)
    monkeypatch.setattr(context_fetcher.config, "CONTEXT_BROWSER_MAX_CHARS", 12_000)
    result = context_fetcher.fetch_browser_content_for_tool("https://example.com/large")
    assert len(result) == 150_000
    assert calls[0]["stream"] is True and closed == [True]


def test_tool_page_download_limit_stops_stream_and_closes_response(monkeypatch):
    import pytest
    import requests

    closed, consumed = [], []

    def chunks(**kwargs):
        consumed.append(1)
        yield b"x" * context_fetcher.PAGE_DOWNLOAD_BYTES
        consumed.append(2)
        yield b"x"
        pytest.fail("Download must stop as soon as the decompressed limit is exceeded")

    response = SimpleNamespace(
        encoding="utf-8", raise_for_status=lambda: None, iter_content=chunks,
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(requests, "get", lambda *a, **kwargs: response)
    with pytest.raises(context_fetcher.PageDownloadLimitError, match="10 MiB"):
        context_fetcher.fetch_browser_content_for_tool("https://example.com/huge")
    assert consumed == [1, 2] and closed == [True]


def test_tool_page_download_accepts_exact_limit(monkeypatch):
    import requests

    closed = []
    response = SimpleNamespace(
        encoding="utf-8", raise_for_status=lambda: None,
        iter_content=lambda **kwargs: iter([b"x" * context_fetcher.PAGE_DOWNLOAD_BYTES]),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(requests, "get", lambda *a, **kwargs: response)
    monkeypatch.setattr(context_fetcher, "extract_useful_page_context", lambda **kwargs: "Parsed full page")
    assert context_fetcher.fetch_browser_content_for_tool("https://example.com/exact") == "Parsed full page"
    assert closed == [True]


def test_unlimited_page_extraction_preserves_large_readable_body(monkeypatch):
    monkeypatch.setattr(context_fetcher.config, "CONTEXT_BROWSER_MAX_CHARS", 12_000)
    body = "Readable article content. " * 5000
    result = context_fetcher.extract_useful_page_context(html=f"<article><p>{body}</p></article>", max_chars=0)
    assert body.strip() in result
    assert len(result) > 100_000 and "[truncated]" not in result


def test_extract_useful_page_context_orders_structured_html():
    html = """
    <html>
      <head>
        <title>OpenWand Browser Context</title>
        <meta name="description" content="How OpenWand reads useful browser context.">
      </head>
      <body>
        <nav>Home Pricing Login</nav>
        <div class="cookie-banner">Accept all cookies</div>
        <main>
          <h1>Browser context design</h1>
          <h2>Capture model</h2>
          <p>OpenWand captures the active browser page and turns it into ordered context.</p>
          <p>The model should see headline content before secondary page details.</p>
          <a href="/docs/context">Context docs</a>
        </main>
        <footer>Legal links and footer text</footer>
      </body>
    </html>
    """

    text = context_fetcher.extract_useful_page_context(
        url="https://example.test/product",
        html=html,
        max_chars=2000,
    )

    assert "Title:\nOpenWand Browser Context" in text
    assert "Page description:\nHow OpenWand reads useful browser context." in text
    assert "Headings:\n- Browser context design\n- Capture model" in text
    assert "Main content:\nBrowser context design" in text
    assert "OpenWand captures the active browser page" in text
    assert "Links:\n- Context docs: https://example.test/docs/context" in text
    assert "Accept all cookies" not in text
    assert "Legal links" not in text
    assert "Home Pricing Login" not in text
    assert "Most relevant" not in text
    assert "Additional page text" not in text


def test_extract_useful_page_context_formats_rendered_text_without_relevance_labels():
    rendered = """
    Example Docs

    Overview
    OpenWand can read rendered browser text when the browser exposes it.

    Setup
    Enable the browser context mode for the caller.
    Overview
    """

    text = context_fetcher.extract_useful_page_context(
        rendered_text=rendered,
        max_chars=2000,
    )

    assert "Title:\nExample Docs" in text
    assert "Headings:" in text
    assert "- Overview" in text
    assert "- Setup" in text
    assert text.count("- Overview") == 1
    assert "Visible page content:" in text
    assert "Most relevant" not in text
    assert "Additional page text" not in text


def test_extract_useful_page_context_clips_and_redacts_final_output():
    html = """
    <html>
      <head><title>Secrets page</title></head>
      <body>
        <main>
          <h1>Token notes</h1>
          <p>api_key = sk-proj-abcdefghijklmnopqrstuvwxyz1234567890</p>  <!-- secret-scan: allow -->
          <p>This long paragraph should force clipping when the context budget is small.</p>
        </main>
      </body>
    </html>
    """

    text = context_fetcher.extract_useful_page_context(
        url="https://example.test/secrets",
        html=html,
        max_chars=140,
    )

    assert "[API_KEY]" in text
    assert "sk-proj-" not in text
    assert len(text) <= 140


def test_browser_context_text_includes_source_priority(monkeypatch):
    monkeypatch.setattr(
        context_hotkey.context_fetcher,
        "fetch_browser_content_for_window",
        lambda url, hwnd: "Title:\nExample",
    )
    snapshot = SimpleNamespace(
        active_window=SimpleNamespace(
            url="https://example.test/page",
            hwnd=777,
            process_name="chrome.exe",
        ),
        browser_content="",
    )

    text = context_hotkey.browser_context_text(snapshot)

    assert "[Browser/Web]" in text
    assert "Source priority: primary" in text
    assert "URL: https://example.test/page" in text
    assert "Title:\nExample" in text


def test_browser_context_text_omits_empty_browser_block():
    snapshot = SimpleNamespace(
        active_window=SimpleNamespace(url="", hwnd=0, process_name="notepad.exe"),
        browser_content="",
    )

    assert context_hotkey.browser_context_text(snapshot) == ""
