"""Safe, seamless rich presentations returned by Wisp addons."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QTextDocument
from PySide6.QtWidgets import QAbstractScrollArea, QTextBrowser

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # packaged builds may deliberately omit QtWebEngine
    QWebEnginePage = None  # type: ignore[assignment]
    QWebEngineSettings = None  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]

MAX_PRESENTATION_HTML = 180_000
_TAGS = {
    "article", "header", "section", "aside", "footer", "div", "span",
    "h1", "h2", "h3", "h4", "p", "strong", "em", "mark", "small",
    "ul", "ol", "li", "dl", "dt", "dd", "pre", "code", "blockquote",
    "table", "caption", "thead", "tbody", "tr", "th", "td", "details",
    "summary", "a", "br", "svg", "g", "path", "circle", "rect", "line", "text",
    "polyline", "polygon",
}
_CLASSES = {
    "formatted-reply", "reply-opening", "reply-kicker", "reply-title", "reply-lede",
    "reply-section", "section-label", "key-point", "caution", "comparison",
    "table-wrap", "steps", "step", "step-number", "step-copy", "metric-grid",
    "metric", "metric-value", "metric-label", "tag-row", "tag", "quote",
    "exact-block", "sources", "source-list", "source-item", "reply-graphic",
    "graphic-primary", "graphic-secondary", "graphic-muted", "graphic-line",
    "two-column", "three-column", "compact", "muted", "accent", "divider",
    "plain-reply", "decision-bracket", "decision-label", "decision-ticket",
    "ticket-field", "ticket-label", "decision-fork", "fork-options", "fork-option",
    "is-chosen", "fork-join", "fork-result", "decision-seal", "seal-mark",
    "seal-copy", "seal-sub", "decision-spotlight", "spotlight-reason",
    "decision-threshold", "threshold-side", "threshold-arrow", "is-after",
    "action-preview", "action-chart", "action-bar", "action-grid", "action-axis", "action-axis-label",
    "action-note", "action-chart-empty", "action-chart-legend", "action-legend-item",
    "action-legend-swatch", "action-series-1", "action-series-2", "action-series-3", "action-series-4",
    "action-formatted-table", "action-canvas-preview", "action-focus-preview", "action-app-header",
    "action-app-badge", "action-app-copy", "action-app-name", "action-app-target", "action-canvas-body",
    "action-preview-title", "action-canvas-hero", "action-chip-row", "action-chip", "action-focus-body",
    "action-focus-change", "action-focus-grid", "action-focus-field", "action-focus-label", "action-focus-value",
    "action-mail-card", "action-mail-row", "action-mail-label", "action-mail-body", "action-event-card",
    "action-event-date", "action-event-copy", "action-event-title", "action-event-meta", "action-slide-card",
    "action-slide-title", "action-slide-rule", "action-slide-copy", "action-change-list", "action-change-item",
    "action-change-mark", "action-change-copy", "action-change-title", "action-change-detail",
    "action-new-value",
}
_GLOBAL_ATTRS = {"class", "aria-label", "aria-hidden", "role", "title"}
_TAG_ATTRS = {
    "a": {"href", "rel"}, "code": {"data-language"},
    "th": {"scope", "colspan", "rowspan"}, "td": {"colspan", "rowspan"},
    "svg": {"viewbox", "preserveaspectratio"}, "path": {"d"},
    "circle": {"cx", "cy", "r"}, "rect": {"x", "y", "width", "height", "rx", "ry"},
    "line": {"x1", "y1", "x2", "y2"}, "polyline": {"points"}, "polygon": {"points"},
    "text": {"x", "y", "text-anchor"},
}
_SVG_TAGS = {"svg", "g", "path", "circle", "rect", "line", "polyline", "polygon", "text"}
_SVG_VALUE = re.compile(r"^[0-9A-Za-z.,+\-\s]+$")


class PresentationContractError(ValueError):
    """An addon presentation failed the host-side safety contract."""


class _PresentationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.stack: list[str] = []
        self.root_seen = False
        self.root_closed = False

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        out: list[str] = []
        seen: set[str] = set()
        for raw_name, raw_value in attrs:
            name = str(raw_name or "").lower()
            value = str(raw_value or "")
            if name in seen or name.startswith("on") or name in {"style", "id", "src", "srcset"}:
                raise PresentationContractError(f"forbidden attribute: {name}")
            seen.add(name)
            if name not in _GLOBAL_ATTRS and name not in _TAG_ATTRS.get(tag, set()):
                raise PresentationContractError(f"attribute {name} is not allowed")
            if name == "class":
                classes = value.split()
                if not classes or any(item not in _CLASSES for item in classes):
                    raise PresentationContractError("unknown presentation class")
                value = " ".join(dict.fromkeys(classes))
            elif name == "href":
                parsed = urlparse(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise PresentationContractError("unsafe link")
            elif tag in _SVG_TAGS and (len(value) > 20_000 or not _SVG_VALUE.fullmatch(value)):
                raise PresentationContractError("unsafe SVG value")
            elif name in {"colspan", "rowspan"} and not re.fullmatch(r"[1-9]\d{0,2}", value):
                raise PresentationContractError("invalid table span")
            output_name = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio"}.get(name, name)
            out.append(f' {output_name}="{html.escape(value, quote=True)}"')
        if tag == "a" and "rel" not in seen:
            out.append(' rel="noreferrer noopener"')
        return "".join(out)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _TAGS:
            raise PresentationContractError(f"tag {tag} is not allowed")
        if not self.stack:
            if self.root_seen or self.root_closed or tag != "article":
                raise PresentationContractError("presentation needs one article root")
            classes = next((value or "" for name, value in attrs if name.lower() == "class"), "")
            if "formatted-reply" not in classes.split():
                raise PresentationContractError("article needs formatted-reply class")
            self.root_seen = True
        elif tag == "article":
            raise PresentationContractError("nested articles are not allowed")
        if tag in _SVG_TAGS - {"svg"} and "svg" not in self.stack:
            raise PresentationContractError("SVG shape outside svg")
        if "svg" in self.stack and tag not in _SVG_TAGS:
            raise PresentationContractError("HTML inside svg")
        self.output.append(f"<{tag}{self._attrs(tag, attrs)}>")
        if tag != "br":
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "br":
            self.handle_starttag(tag, attrs)
            return
        if tag not in _SVG_TAGS - {"svg", "g"} or "svg" not in self.stack:
            raise PresentationContractError("unsupported self-closing element")
        self.output.append(f"<{tag}{self._attrs(tag, attrs)}></{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack or self.stack[-1] != tag:
            raise PresentationContractError(f"mismatched closing tag: {tag}")
        self.stack.pop()
        self.output.append(f"</{tag}>")
        if not self.stack:
            self.root_closed = True

    def handle_data(self, data: str) -> None:
        if not self.stack:
            if data.strip():
                raise PresentationContractError("text outside article")
            return
        self.output.append(html.escape(data, quote=False))

    def handle_comment(self, _data: str) -> None:
        raise PresentationContractError("comments are not allowed")

    def finish(self) -> str:
        if self.stack or not self.root_seen or not self.root_closed:
            raise PresentationContractError("incomplete presentation fragment")
        result = "".join(self.output).strip()
        if not result or len(result) > MAX_PRESENTATION_HTML:
            raise PresentationContractError("presentation is empty or too large")
        return result


def sanitize_presentation_html(fragment: str) -> str:
    """Revalidate addon HTML in the UI process before rendering it."""
    value = str(fragment or "").strip()
    if not value or len(value) > MAX_PRESENTATION_HTML:
        raise PresentationContractError("presentation is empty or too large")
    parser = _PresentationParser()
    parser.feed(value)
    parser.close()
    return parser.finish()


_CSS = r"""
*{box-sizing:border-box}html,body{width:100%;margin:0;overflow:hidden;background:transparent;color:var(--text)}
body{padding:2px 0 5px;font:var(--size)/1.55 "Segoe UI",system-ui,sans-serif}article{width:100%;margin:0;overflow-wrap:anywhere}
h1,h2,h3,h4{margin:0;color:var(--text);line-height:1.18;letter-spacing:-.02em}h1{font-size:1.6em}h2{font-size:1.2em}h3{font-size:1.02em}
p{margin:0 0 13px;max-width:65ch}strong{color:var(--text)}small,.muted{color:var(--muted)}a{color:var(--accent);text-decoration:none}
ul,ol{margin:9px 0 15px;padding-left:23px}li{margin:5px 0}dl{margin:12px 0}dt{font-weight:700;color:var(--accent)}dd{margin:2px 0 11px;color:var(--muted)}
.formatted-reply{--gutter:25px;padding-left:var(--gutter)}.formatted-reply>:first-child{margin-top:0}.formatted-reply>:last-child{margin-bottom:0}
.reply-opening{width:calc(100% + var(--gutter));margin:0 0 19px calc(-1 * var(--gutter));padding:0 0 13px var(--gutter);border-bottom:1px solid var(--line)}
.reply-kicker,.section-label,.ticket-label{display:block;margin:0 0 7px;color:var(--accent);font-size:.68em;font-weight:750;letter-spacing:.1em;text-transform:uppercase}
.reply-title{margin:0 0 8px}.reply-lede{margin:0;color:var(--muted)}.reply-section{margin:0;padding:0}.reply-section+.reply-section{margin-top:25px;padding-top:21px;border-top:1px solid var(--line)}
.key-point,.quote{position:relative;margin:17px 0}.key-point:before,.quote:before{content:"";position:absolute;inset-block:3px;left:calc(-1 * var(--gutter));width:3px;border-radius:3px;background:var(--accent)}
.quote,blockquote{color:var(--muted)}blockquote{position:relative;margin:17px 0;padding:0;border:0}.caution{position:relative;width:calc(100% + var(--gutter));margin:0 0 19px calc(-1 * var(--gutter));padding:15px 0 15px var(--gutter);border-block:1px solid var(--warm);background:var(--warm-soft)}
.caution:before{content:"!";position:absolute;left:7px;color:var(--warm);font-weight:850}.two-column,.three-column,.metric-grid{display:grid;gap:14px}.two-column{grid-template-columns:repeat(2,minmax(0,1fr))}.three-column,.metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.metric{padding:10px 0;border-bottom:1px solid var(--line)}.metric-value{display:block;color:var(--accent);font-size:1.35em;font-weight:750}.metric-label{color:var(--muted);font-size:.78em}
.steps{display:block;margin:13px 0 22px}.step{position:relative;padding:0 0 18px}.step-number{position:absolute;left:calc(-1 * var(--gutter));display:grid;place-items:center;width:20px;height:20px;border:1px solid var(--accent);border-radius:50%;color:var(--accent);font-size:.68em}.step:not(:last-child):after{content:"";position:absolute;top:24px;bottom:4px;left:calc(-1 * var(--gutter) + 9px);width:1px;background:var(--line)}
.tag-row{display:flex;flex-wrap:wrap;gap:7px}.tag{padding:4px 8px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:.76em}
.table-wrap{width:calc(100% + var(--gutter));margin:15px 0 18px calc(-1 * var(--gutter));overflow-x:auto;border-top:2px solid var(--text);border-bottom:1px solid var(--text)}table{width:100%;border-collapse:collapse;font-size:.84em;line-height:1.4}th,td{min-width:96px;padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--accent);font-size:.78em;text-transform:uppercase}th:first-child,td:first-child{padding-left:var(--gutter)}tbody tr:last-child td{border-bottom:0}
pre{max-width:calc(100% + var(--gutter));margin:14px 0 18px calc(-1 * var(--gutter));padding:14px 16px 15px calc(16px + var(--gutter));overflow-x:auto;border-radius:0 12px 12px 0;background:var(--code);color:var(--code-text)}code{font:.82em/1.5 "Cascadia Mono",Consolas,monospace}p code,li code{padding:2px 5px;border-radius:4px;background:var(--soft)}
details{margin:16px 0;border-top:1px solid var(--line);padding-top:11px}summary{width:max-content;color:var(--muted);font-weight:650}.reply-graphic{display:block;width:100%;max-height:170px;margin:15px 0}.graphic-primary{fill:none;stroke:var(--accent);stroke-width:2}.graphic-secondary{fill:none;stroke:var(--accent);stroke-width:2}.graphic-muted{fill:var(--soft);stroke:var(--line);stroke-width:1}.graphic-line{fill:none;stroke:var(--line);stroke-width:1.2}
.divider{height:1px;margin:18px 0;background:var(--line)}.compact{margin-top:7px;margin-bottom:7px}.accent{color:var(--accent)}mark{padding:1px 3px;background:color-mix(in srgb,var(--accent) 24%,transparent);color:var(--text)}
.decision-bracket{position:relative;margin:17px 0;padding:14px 0;border-top:2px solid var(--text);border-bottom:1px solid var(--line)}.decision-label{position:absolute;right:0;top:-.85em;padding-left:8px;color:var(--accent);background:var(--bg);font-size:.68em;font-weight:750;letter-spacing:.08em;text-transform:uppercase}
.decision-ticket{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:16px 0;border-top:2px solid var(--accent);border-bottom:1px solid var(--line)}.ticket-field{min-width:0;padding:12px 13px;border-right:1px solid var(--line)}.ticket-field:last-child{border-right:0}
.decision-fork{margin:16px 0}.fork-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;color:var(--muted)}.fork-option{padding:9px 0;border-bottom:1px solid var(--line)}.fork-option.is-chosen{color:var(--text);border-bottom:2px solid var(--accent)}.fork-join{position:relative;height:44px}.fork-join:before{content:"";position:absolute;left:25%;top:0;width:50%;height:22px;border-left:1px solid var(--line);border-right:2px solid var(--accent);border-bottom:1px solid var(--line);border-radius:0 0 12px 12px}.fork-join:after{content:"";position:absolute;left:50%;top:22px;height:22px;border-left:2px solid var(--accent)}.fork-result{padding-left:13px;border-left:3px solid var(--accent)}
.decision-seal{position:relative;margin:17px 0;padding:5px 0 5px 32px}.seal-mark{position:absolute;left:calc(-1 * var(--gutter));top:0;display:grid;place-items:center;width:50px;height:50px;border:2px solid var(--accent);border-radius:50%;color:var(--accent);transform:rotate(-7deg)}.seal-mark:before{content:"✓";font-size:1.4em;font-weight:800}.seal-sub,.spotlight-reason{margin-top:10px;color:var(--muted)}
.decision-spotlight{margin:15px 0;padding:11px 0}.decision-spotlight mark{background:linear-gradient(transparent 30%,color-mix(in srgb,var(--accent) 24%,transparent) 30%)}.spotlight-reason{padding-top:11px;border-top:1px solid var(--line)}
.decision-threshold{display:grid;grid-template-columns:1fr 28px 1fr;align-items:stretch;margin:16px 0}.threshold-side{padding:13px;border-block:1px solid var(--line)}.threshold-side.is-after{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,transparent)}.threshold-arrow{position:relative}.threshold-arrow:before{content:"→";position:absolute;inset:0;display:grid;place-items:center;color:var(--accent);font-size:1.2em}
.action-preview .reply-title{max-width:760px}.action-chart{min-height:232px;margin-bottom:4px;border-radius:0;background:transparent}.action-bar{fill:var(--accent);opacity:.9}.action-grid{stroke:var(--line);stroke-width:1}.action-axis{stroke:var(--text);stroke-width:1.5}.action-axis-label{fill:var(--muted);font-size:11px}.action-series-1{background:var(--accent);fill:var(--accent);opacity:.95}.action-series-2{background:var(--warm);fill:var(--warm);opacity:.86}.action-series-3{background:var(--text);fill:var(--text);opacity:.62}.action-series-4{background:var(--muted);fill:var(--muted);opacity:.62}.action-chart-legend{display:flex;flex-wrap:wrap;gap:7px 16px;margin:0 0 15px;color:var(--muted);font-size:.76em}.action-legend-item{display:inline-flex;align-items:center;gap:6px}.action-legend-swatch{display:inline-block;width:10px;height:10px;border-radius:0}.action-chart-empty{margin:15px 0;padding:20px 0;border-block:1px solid var(--warm);border-radius:0;color:var(--muted);background:transparent}.action-note{margin-bottom:4px}
.action-formatted-table thead{background:#2f6f7e}.action-formatted-table th{color:#fff;font-weight:750;letter-spacing:.03em}.action-formatted-table td{padding-block:11px}
.action-canvas-preview,.action-focus-preview{--gutter:0;padding:0;overflow:visible;border:0;border-radius:0;background:transparent;box-shadow:none}
.action-app-header{display:flex;align-items:baseline;gap:8px;min-width:0;margin:0 0 21px;padding:9px 0 10px;border-top:3px solid var(--accent);border-bottom:1px solid var(--text);background:transparent}.action-app-name{flex:0 0 auto;color:var(--accent);font-size:.75em;font-weight:800;letter-spacing:.06em;text-transform:uppercase}.action-app-target{min-width:0;overflow:hidden;color:var(--muted);font-size:.78em;text-overflow:ellipsis;white-space:nowrap}.action-app-target:before{content:"/";margin-right:8px;color:var(--line)}.action-app-badge,.action-app-copy{display:none}
.action-canvas-body,.action-focus-body{padding:0}.action-preview-title{max-width:760px;margin:0 0 21px;font-size:1.55em}.action-canvas-hero{position:relative;overflow:visible;margin:0 0 18px;padding:0;border:0;border-radius:0;background:transparent}.action-canvas-hero>.table-wrap{width:100%;margin:0}.action-canvas-hero pre{max-width:100%;margin:0;padding:16px;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:0}.action-canvas-hero .action-chart{background:transparent}.action-preview th{color:var(--text)}.action-preview th:first-child,.action-preview td:first-child{padding-left:11px}.action-new-value{color:var(--accent);font-weight:700}
.action-chip-row,.action-chip{display:none}
.action-focus-change{margin:0}.action-focus-change+.action-focus-grid{margin-top:18px}.action-focus-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;border-top:2px solid var(--text)}.action-focus-field{min-width:0;padding:13px 10px 14px 0;border:0;border-bottom:1px solid var(--line);border-radius:0;background:transparent}.action-focus-field:nth-child(even){padding-left:16px}.action-focus-label{display:block;margin-bottom:5px;color:var(--muted);font-size:.72em;text-transform:uppercase;letter-spacing:.07em}.action-focus-value{color:var(--text);font-weight:650;white-space:pre-wrap}.action-focus-value.accent{color:var(--accent)}
.action-mail-card{overflow:visible;border-block:2px solid var(--text);border-inline:0;border-radius:0;background:transparent}.action-mail-row{display:grid;grid-template-columns:76px 1fr;gap:9px;padding:10px 0;border-bottom:1px solid var(--line)}.action-mail-label{color:var(--muted)}.action-mail-body{padding:18px 0;color:var(--text);background:transparent}
.action-event-card{display:grid;grid-template-columns:92px 1fr;overflow:visible;border-block:2px solid var(--text);border-inline:0;border-radius:0;background:transparent}.action-event-date{display:grid;place-content:center;padding:15px 9px;border-right:1px solid var(--line);text-align:center;background:transparent;color:var(--accent);font-weight:800}.action-event-copy{padding:15px}.action-event-title{margin-bottom:5px;color:var(--text);font-weight:750}.action-event-meta{color:var(--muted)}
.action-slide-card{aspect-ratio:16/9;display:grid;align-content:center;gap:10px;padding:9%;border:1px solid var(--text);border-top:4px solid var(--accent);border-radius:0;background:var(--bg)}.action-slide-title{font-size:1.3em;font-weight:750;line-height:1.15}.action-slide-rule{width:38%;height:3px;border-radius:0;background:var(--accent)}.action-slide-copy{color:var(--muted)}
.action-change-list{display:grid;gap:0;border-top:1px solid var(--line)}.action-change-item{display:grid;grid-template-columns:20px 1fr;gap:8px;padding:11px 0;border-bottom:1px solid var(--line)}.action-change-mark{display:block;width:auto;height:auto;border-radius:0;background:transparent;color:var(--text);font-size:.75em;font-weight:800}.action-change-title{color:var(--text);font-weight:700}.action-change-detail{color:var(--muted)}
@media(max-width:560px){.two-column,.three-column,.metric-grid,.decision-ticket,.fork-options,.decision-threshold,.action-focus-grid{grid-template-columns:1fr}.ticket-field{border-right:0;border-bottom:1px solid var(--line)}.fork-join{display:none}.threshold-arrow{height:28px;transform:rotate(90deg)}.action-focus-field:nth-child(even){padding-left:0}.action-event-card{grid-template-columns:76px 1fr}}
"""


def presentation_document(fragment: str, palette: dict[str, str], font_px: int = 16) -> str:
    """Build a network-isolated full document around a safe fragment."""
    safe = sanitize_presentation_html(fragment)
    variables = {
        "bg": palette.get("bg", "#212121"), "text": palette.get("text", "#eeeeee"),
        "muted": palette.get("muted", "#aaaaaa"), "line": palette.get("line", "#3c3c3c"),
        "accent": palette.get("accent", "#9b8cff"), "warm": palette.get("warm", "#f0ae72"),
        "warm_soft": palette.get("warm_soft", "#3c2b25"),
        "soft": palette.get("soft", "#2e2e2e"), "code": palette.get("code", "#15171c"),
        "code_text": palette.get("code_text", "#eff6ff"), "size": f"{max(13, min(int(font_px), 22))}px",
    }
    css_vars = ";".join(f"--{key.replace('_', '-')}:{html.escape(value)}" for key, value in variables.items())
    policy = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta http-equiv='Content-Security-Policy' content=\"{policy}\">"
        f"<style>:root{{{css_vars}}}{_CSS}</style></head><body>{safe}</body></html>"
    )


if QWebEnginePage is not None:
    class _PresentationPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                if url.scheme().lower() in {"http", "https"}:
                    QDesktopServices.openUrl(url)
                return False
            return url.scheme().lower() in {"about", "data"}


class RichPresentationView(QTextBrowser if QWebEngineView is None else QWebEngineView):
    """A fixed-height rich reply whose parent conversation owns scrolling."""

    def __init__(self, fragment: str, palette: dict[str, str], font_px: int = 16, parent=None) -> None:
        super().__init__(parent)
        self._presentation_fragment = fragment
        self._presentation_font_px = font_px
        document = presentation_document(fragment, palette, font_px)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
        if QWebEngineView is None:
            self.setOpenExternalLinks(True)
            self.setHtml(document)
            self.document().setDocumentMargin(0)
            QTimer.singleShot(0, self._fit_fallback_height)
            return
        self.setPage(_PresentationPage(self))
        self.page().setBackgroundColor(QColor("transparent"))
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)
        self.setFixedHeight(48)
        self._web_loaded = False
        self._measure_attempt = 0
        self._last_measure_width = -1
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.setInterval(70)
        self._measure_timer.timeout.connect(self._measure_native_height)
        self._height_fallback_timer = QTimer(self)
        self._height_fallback_timer.setSingleShot(True)
        self._height_fallback_timer.setInterval(650)
        self._height_fallback_timer.timeout.connect(self._ensure_estimated_height)
        self.loadFinished.connect(self._fit_web_height)
        self.setHtml(document, QUrl("about:blank"))
        self._height_fallback_timer.start()

    def _outer_scroll_area(self) -> QAbstractScrollArea | None:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def _forward_wheel(self, event) -> bool:
        scroll = self._outer_scroll_area()
        if scroll is None:
            return False
        delta = event.angleDelta().y()
        if not delta:
            return False
        bar = scroll.verticalScrollBar()
        step = max(20, bar.singleStep() * 3)
        bar.setValue(bar.value() - int(delta / 120) * step)
        event.accept()
        return True

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._forward_wheel(event):
            super().wheelEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and self._forward_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def _fit_fallback_height(self) -> None:
        height = int(self.document().size().height()) + 8
        self.setFixedHeight(max(48, min(height, 30_000)))

    def _fit_web_height(self, ok: bool) -> None:
        for child in self.findChildren(QObject):
            child.installEventFilter(self)
        self._web_loaded = bool(ok)
        self._measure_attempt = 0
        self._measure_timer.start()
        self._height_fallback_timer.start()

    def _measure_native_height(self) -> None:
        """Measure once at a short viewport so content height cannot feed back."""
        if not getattr(self, "_web_loaded", False):
            return
        try:
            height = int(round(float(self.page().contentsSize().height())))
        except (AttributeError, TypeError, ValueError):
            height = 0
        if height <= 48 and self._measure_attempt < 4:
            self._last_measure_width = self.width()
            self._measure_attempt += 1
            self._measure_timer.start(80)
            return
        if height <= 48:
            height = self._estimated_web_height()
        height = max(48, min(height or 160, 30_000))
        self._last_measure_width = self.width()
        if abs(height - self.height()) > 1:
            self.setFixedHeight(height)
        self._height_fallback_timer.stop()

    def _estimated_web_height(self) -> int:
        """Conservative fallback when an offscreen/failed GPU reports no size."""
        document = QTextDocument()
        font = QFont("Segoe UI")
        font.setPixelSize(max(13, min(int(self._presentation_font_px), 22)))
        document.setDefaultFont(font)
        document.setDocumentMargin(0)
        document.setTextWidth(max(260, self.width() - 25))
        document.setHtml(self._presentation_fragment)
        parallel_layout = bool(re.search(
            r'class="[^"]*(?:decision-ticket|two-column|three-column|metric-grid|fork-options|decision-threshold)',
            self._presentation_fragment,
        ))
        factor = 0.82 if parallel_layout else 0.92
        return int(document.size().height() * factor) + 18

    def _ensure_estimated_height(self) -> None:
        """Guarantee that a failed WebEngine measurement never clips the reply."""
        if self.height() <= 48:
            self.setFixedHeight(max(48, min(self._estimated_web_height(), 30_000)))

    def _apply_web_height(self, value) -> None:
        """Compatibility callback retained for callers that provide a numeric height."""
        try:
            height = int(float(value)) + 4
        except (TypeError, ValueError):
            height = 160
        height = max(48, min(height, 30_000))
        if abs(height - self.height()) > 1:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        timer = getattr(self, "_measure_timer", None)
        last_width = getattr(self, "_last_measure_width", -1)
        if (
            timer is not None
            and getattr(self, "_web_loaded", False)
            # Ignore the ~14 px width oscillation caused by the outer
            # conversation scrollbar appearing; treating that as a real resize
            # creates a height/scrollbar feedback loop.
            and (last_width < 0 or abs(self.width() - last_width) > 32)
        ):
            self._measure_attempt = 0
            self.setFixedHeight(48)
            timer.start()
            fallback_timer = getattr(self, "_height_fallback_timer", None)
            if fallback_timer is not None:
                fallback_timer.start()
