"""Shared, content-first HTML shells for application action previews."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

_APP_NAMES = {
    "browser": "Browser",
    "chrome": "Google Chrome",
    "calc": "LibreOffice Calc",
    "excel": "Microsoft Excel",
    "google_sheets": "Google Sheets",
    "vscode": "Visual Studio Code",
    "presentation": "Presentation",
    "powerpoint_desktop": "Microsoft PowerPoint",
    "powerpoint_web": "PowerPoint",
    "google_slides": "Google Slides",
    "email": "Mail",
    "calendar": "Calendar",
}


def app_name(app: str, *, fallback: str = "Wisp") -> str:
    """Return a stable product name for one action target."""
    key = str(app or "").strip().lower()
    return _APP_NAMES.get(key, fallback)


def app_initials(name: str) -> str:
    """Return a compact two-character mark for the shared app header."""
    words = [word for word in str(name or "").replace("/", " ").split() if word]
    if not words:
        return "W"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def chips(items: Iterable[str]) -> str:
    """Discard secondary metadata so the preview stays about the artifact."""
    del items
    return ""


def app_header(*, app: str, target: str, badge: str = "") -> str:
    """Render the shared application identity and exact target."""
    clean_app = " ".join(str(app or "Wisp").split())[:80]
    clean_target = " ".join(str(target or "").split())[:240]
    del badge
    return f"""
<header class="action-app-header">
  <div class="action-app-name">{escape(clean_app)}</div>
  <div class="action-app-target">{escape(clean_target)}</div>
</header>""".strip()


def canvas_preview(
    *,
    app: str,
    target: str,
    title: str,
    hero_html: str,
    chips_html: str = "",
    body_html: str = "",
    badge: str = "",
) -> str:
    """Render the artifact-first Canvas direction."""
    return f"""
<article class="formatted-reply action-preview action-canvas-preview">
  {app_header(app=app, target=target, badge=badge)}
  <section class="action-canvas-body">
    <h1 class="action-preview-title">{escape(str(title or 'Proposed change'))}</h1>
    <div class="action-canvas-hero">{hero_html}</div>
    {chips_html}
    {body_html}
  </section>
</article>""".strip()


def focus_preview(
    *,
    app: str,
    target: str,
    title: str,
    change_html: str,
    details_html: str = "",
    badge: str = "",
) -> str:
    """Render the change-only Focus direction."""
    return f"""
<article class="formatted-reply action-preview action-focus-preview">
  {app_header(app=app, target=target, badge=badge)}
  <section class="action-focus-body">
    <h1 class="action-preview-title">{escape(str(title or 'Proposed change'))}</h1>
    <div class="action-focus-change">{change_html}</div>
    {details_html}
  </section>
</article>""".strip()


def focus_field(label: str, value: str, *, accent: bool = False) -> str:
    """Render one exact changed property for Focus previews."""
    classes = "action-focus-value accent" if accent else "action-focus-value"
    return (
        '<div class="action-focus-field">'
        f'<span class="action-focus-label">{escape(str(label or ""))}</span>'
        f'<div class="{classes}">{escape(str(value or ""))}</div>'
        "</div>"
    )


__all__ = [
    "app_header",
    "app_initials",
    "app_name",
    "canvas_preview",
    "chips",
    "focus_field",
    "focus_preview",
]
