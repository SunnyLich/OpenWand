"""Conservative presentation-app detection without controlling any UI."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "brave.exe", "chromium.exe", "firefox.exe"}


def is_powerpoint_desktop_app(active_app: dict[str, Any] | None) -> bool:
    """Recognize Microsoft PowerPoint desktop on Windows or macOS."""
    app = active_app if isinstance(active_app, dict) else {}
    process = str(app.get("process_name") or "").strip().casefold()
    bundle = str(app.get("bundle_id") or "").strip().casefold()
    title = str(app.get("name") or app.get("title") or "").strip().casefold()
    return (
        process in {"powerpnt.exe", "microsoft powerpoint", "powerpoint"}
        or bundle == "com.microsoft.powerpoint"
        or ("powerpoint" in title and process not in _BROWSER_PROCESSES)
    )


def is_powerpoint_web_app(active_app: dict[str, Any] | None) -> bool:
    """Recognize PowerPoint for the web from a captured browser URL."""
    app = active_app if isinstance(active_app, dict) else {}
    url = str(app.get("browser_url") or app.get("url") or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if host in {"powerpoint.office.com", "powerpoint.cloud.microsoft", "powerpoint.microsoft.com"}:
        return True
    if host in {"www.office.com", "office.com", "www.microsoft365.com", "microsoft365.com"}:
        return "powerpoint" in path
    # SharePoint/OneDrive viewers host many file types. Require both a canonical
    # presentation-file signal and a PowerPoint-specific captured tab title.
    title = str(app.get("name") or app.get("title") or "").casefold()
    process = str(app.get("process_name") or "").strip().casefold()
    if process in _BROWSER_PROCESSES and "powerpoint" in title:
        return True
    office_document = host.endswith(".sharepoint.com") or host in {"onedrive.live.com", "1drv.ms"}
    presentation_path = any(token in (path + "?" + parsed.query).casefold() for token in (".pptx", ".pptm", ":p:"))
    if office_document and presentation_path and "powerpoint" in title:
        return True
    return False


def is_google_slides_app(active_app: dict[str, Any] | None) -> bool:
    """Recognize Google Slides only from its canonical presentation URL."""
    app = active_app if isinstance(active_app, dict) else {}
    parsed = urlparse(str(app.get("browser_url") or app.get("url") or "").strip())
    if (parsed.hostname or "").casefold() == "docs.google.com" and parsed.path.casefold().startswith(
        "/presentation/"
    ):
        return True
    process = str(app.get("process_name") or "").strip().casefold()
    title = str(app.get("name") or app.get("title") or "").casefold()
    return process in _BROWSER_PROCESSES and "google slides" in title


def presentation_backend_for_app(active_app: dict[str, Any] | None) -> str:
    """Return the API backend implied by the captured app, or an empty string."""
    if is_powerpoint_desktop_app(active_app):
        return "powerpoint_desktop"
    if is_powerpoint_web_app(active_app):
        return "powerpoint_officejs"
    if is_google_slides_app(active_app):
        return "google_slides"
    return ""
