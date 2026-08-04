"""Context-only detection for account-backed mail and calendar providers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_BROWSER_PROCESSES = {
    "chrome.exe", "chrome", "msedge.exe", "msedge", "firefox.exe", "firefox",
    "brave.exe", "brave", "safari", "safari.app",
}
_OUTLOOK_PROCESSES = {
    "outlook.exe", "outlook", "olk.exe", "olk", "newoutlook.exe", "ms-outlook",
}
_OUTLOOK_WEB_HOSTS = {
    "outlook.cloud.microsoft",
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.live.com",
}


def _identity(context: dict[str, Any] | None) -> tuple[str, str, str, str]:
    value = context if isinstance(context, dict) else {}
    active = value.get("active_app") if isinstance(value.get("active_app"), dict) else value
    process = str(active.get("process_name") or "").strip().casefold()
    title = str(active.get("name") or active.get("title") or "").strip().casefold()
    bundle = str(active.get("bundle_id") or "").strip().casefold()
    url = str(value.get("browser_url") or active.get("browser_url") or active.get("url") or "").strip()
    host = (urlparse(url).hostname or "").casefold()
    return process, title, bundle, host


def detect_email_provider(context: dict[str, Any] | None) -> str:
    """Return gmail/outlook only when captured context identifies that service."""
    process, title, bundle, host = _identity(context)
    if process in _OUTLOOK_PROCESSES or bundle == "com.microsoft.outlook":
        return "outlook"
    if host == "mail.google.com" or (process in _BROWSER_PROCESSES and "gmail" in title):
        return "gmail"
    if host in _OUTLOOK_WEB_HOSTS or (
        process in _BROWSER_PROCESSES and ("outlook" in title or "microsoft 365 mail" in title)
    ):
        return "outlook"
    return ""


def detect_calendar_provider(context: dict[str, Any] | None) -> str:
    """Return google/outlook for captured calendar surfaces; never drive the UI."""
    process, title, bundle, host = _identity(context)
    if host == "calendar.google.com" or (process in _BROWSER_PROCESSES and "google calendar" in title):
        return "google"
    if process in _OUTLOOK_PROCESSES or bundle == "com.microsoft.outlook":
        return "outlook" if "calendar" in title else ""
    if host in _OUTLOOK_WEB_HOSTS and "calendar" in title:
        return "outlook"
    if process in _BROWSER_PROCESSES and "outlook" in title and "calendar" in title:
        return "outlook"
    return ""


def email_suggestion_metadata(provider: str) -> tuple[dict[str, str], ...]:
    """Return integration-ready mail suggestions, including answer-only summary."""
    label = "Gmail" if provider == "gmail" else "Outlook"
    return (
        {
            "id": "email.summarize_thread",
            "mode": "answer",
            "label": "Summarize this thread",
            "hint": f"Read a bounded {label} thread snapshot without changing mail",
            "prompt": "Summarize this email thread and identify decisions and follow-ups.",
        },
    )
