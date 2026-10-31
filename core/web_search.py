"""Key-free public web search using the same DDGS library as Open WebUI."""

from __future__ import annotations

import os
from urllib.parse import urlsplit
from urllib.request import getproxies


class WebSearchError(RuntimeError):
    """Search failed; the caller must not invent live information."""


def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search public engines automatically, retaining source URLs and snippets."""
    query = str(query or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(int(max_results or 5), 10))
    except (TypeError, ValueError, OverflowError):
        limit = 5

    from core.privacy_gateway import scrub_cloud_fields
    from core.privacy_redaction import redact_text

    _session, fields, _report = scrub_cloud_fields(
        {"search_query": query}, session_id="context:online-search",
    )
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise WebSearchError("The DDGS search component is missing. Update OpenWand's runtime dependencies.") from exc

    proxies = getproxies()
    proxy = os.environ.get("DDGS_PROXY") or proxies.get("https") or proxies.get("http")
    verify = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or True
    try:
        with DDGS(proxy=proxy, timeout=8, verify=verify) as engine:
            rows = engine.text(fields["search_query"], safesearch="moderate", max_results=limit)
    except Exception as exc:
        raise WebSearchError(f"DDGS public web search failed: {redact_text(str(exc))}") from exc

    results = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("href") or row.get("url") or "").strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({
            "title": redact_text(str(row.get("title") or parsed.hostname).strip()),
            "url": url,
            "snippet": redact_text(str(row.get("body") or row.get("snippet") or "").strip()),
        })
        if len(results) >= limit:
            break
    if not results:
        raise WebSearchError("DDGS returned no usable web results. No current information was retrieved.")
    return results
