"""Tests for Qt-free chat reply rendering helpers."""

from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from ui.chat_rendering import (
    _assistant_text_to_html,
    _compact_markdown_tables,
    _user_text_to_html,
    render_markdown_html,
)
from ui.latex_rendering import render_latex_image
from ui.text_annotations import (
    annotation_tooltip_anchor,
    annotations_from_keyword_rules,
    normalize_range_annotations,
)

_REPLY_CORPUS = json.loads(
    (Path(__file__).with_name("fixtures") / "chat_reply_rendering_corpus.json").read_text(
        encoding="utf-8"
    )
)


class _VisibleTextParser(HTMLParser):
    """Extract user-visible text while ignoring the renderer's CSS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"style", "script"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        value = " ".join(self.parts)
        return re.sub(r"\s+([.,;:!?])", r"\1", value)


def _visible_rendered_text(rendered: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(rendered)
    parser.close()
    return parser.text()


def test_reply_rendering_corpus_has_at_least_twenty_distinct_structures():
    assert len(_REPLY_CORPUS) >= 20
    assert len({case["id"] for case in _REPLY_CORPUS}) == len(_REPLY_CORPUS)
    assert sum(bool(case.get("known_gap")) for case in _REPLY_CORPUS) <= 2


@pytest.mark.parametrize("case", _REPLY_CORPUS, ids=lambda case: case["id"])
def test_reply_rendering_corpus_preserves_content_and_expected_structure(case):
    rendered = _assistant_text_to_html(case["markdown"])
    visible = _visible_rendered_text(rendered)

    for expected in case["visible"]:
        assert expected in visible
    for tag in case["tags"]:
        assert tag in rendered
    expects_rule = bool(case["editorial_lead"]) or case["id"] == "horizontal-rule"
    assert ("<hr style=" in rendered) is expects_rule
    assert "<script>" not in rendered


def test_reply_rendering_corpus_fits_without_clipping_at_common_widths(qapp):
    """Every corpus reply remains fully laid out from narrow to wide chat columns."""
    from ui.chat_window import _MessageTextView

    for case in _REPLY_CORPUS:
        rendered = _assistant_text_to_html(case["markdown"])
        for width in (320, 520, 760):
            view = _MessageTextView("#000000", presentation="assistant")
            try:
                view.setProperty("openwand_has_table", "<table" in rendered)
                view.resize(width, 48)
                view.setHtml(rendered)
                view.show()
                qapp.processEvents()
                view._sync_height()
                qapp.processEvents()

                document_height = view.document().documentLayout().documentSize().height()
                assert view.height() >= document_height, (case["id"], width)
                assert view.horizontalScrollBar().maximum() == 0, (case["id"], width)
                assert view.document().toPlainText().strip(), (case["id"], width)
            finally:
                view.close()
                view.deleteLater()
                qapp.processEvents()


def test_assistant_html_preserves_markdown_blocks():
    """Verify assistant replies render paragraphs, lists, and code blocks."""
    rendered = _assistant_text_to_html(
        "First line\nSecond line\n\n- one\n- two\n\n```py\nprint('hi')\n```"
    )

    assert "First line<br>Second line" in rendered
    assert "<ul>" in rendered
    assert "<li>one</li>" in rendered
    assert "<pre><code>print(&#x27;hi&#x27;)</code></pre>" in rendered


def test_model_style_ordered_sections_preserve_explicit_numbers_across_paragraphs():
    """Loose model prose between steps must not reset every visible item to one."""
    rendered = _assistant_text_to_html(
        "1. Restart the application\n\nRestart it completely.\n\n"
        "2. Check audio output\n\nConfirm the selected device.\n\n"
        "3. Reset speech output"
    )

    assert "<ol>" in rendered
    assert '<ol start="2">' in rendered
    assert '<ol start="3">' in rendered


def test_model_style_nested_lists_preserve_parent_child_hierarchy():
    rendered = _assistant_text_to_html(
        "1. The speech engine\n"
        "    - Voice may be missing\n"
        "    - Backend may be incompatible\n"
        "2. The audio route\n"
        "    - Output device may have changed"
    )

    assert "<ol" in rendered
    assert "<ul" in rendered
    assert re.search(r'<li>The speech engine\s*<ul', rendered)
    assert re.search(r'</ul>\s*</li>\s*<li>The audio route', rendered)


def test_horizontal_rules_and_blockquotes_render_semantically():
    rendered = _assistant_text_to_html(
        "Before\n\n---\n\n> **Native Markdown** by default.\n\nAfter"
    )

    assert "<hr style=" in rendered
    assert "<blockquote style=" in rendered
    assert "<strong>Native Markdown</strong>" in rendered
    assert "> **Native Markdown**" not in rendered
    assert ">---<" not in rendered


def test_task_list_uses_one_marker_instead_of_bullet_plus_checkbox():
    rendered = _assistant_text_to_html("- [ ] Pending\n- [x] Complete")

    assert rendered.count('list-style-type:none') == 2
    assert "☐ Pending" in rendered
    assert "☑ Complete" in rendered


def test_plain_markdown_reply_gets_native_editorial_treatment_without_formatter():
    """Common reply structure looks polished without an addon-generated presentation."""
    rendered = _assistant_text_to_html(
        "Here’s what happened:\n\n"
        "- The package moved.\n"
        "- The saved value was `False`; it is now **True**.\n\n"
        "Restart the application."
    )

    assert "Here’s what happened:" in rendered
    assert "<hr style=" in rendered
    assert "<ul>" in rendered
    assert "<code>False</code>" in rendered
    assert "<strong>True</strong>" in rendered
    assert "line-height: 1.5" in rendered


def test_normal_opening_paragraph_is_not_mistaken_for_editorial_lead():
    rendered = _assistant_text_to_html(
        "This is a regular opening paragraph.\n\nThis is the next paragraph."
    )

    assert "<hr style=" not in rendered


def test_public_markdown_renderer_matches_chat_visuals():
    rendered = render_markdown_html(
        "# Heading\n\n- [x] Done\n\n"
        "| Item | State |\n| --- | --- |\n| Preview | Ready |"
    )

    assert "<h1>Heading</h1>" in rendered
    assert "☑ Done" in rendered
    assert "<table" in rendered
    assert "Preview" in rendered


def test_assistant_html_keeps_inline_code_literal():
    """Verify inline markdown does not style text inside code spans."""
    rendered = _assistant_text_to_html("Use `**literal**` and **bold**")

    assert "<code>**literal**</code>" in rendered
    assert "<strong>bold</strong>" in rendered


def test_assistant_html_renders_inline_and_display_latex_math():
    """Common model-produced TeX is formatted instead of shown as source."""
    rendered = _assistant_text_to_html(
        r"Energy is $E=mc^2$." "\n\n" r"$$\frac{-b \pm \sqrt{b^2-4ac}}{2a}$$"
    )

    encoded_images = re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", rendered)
    assert len(encoded_images) == 2
    display_svg = base64.b64decode(encoded_images[-1]).decode("utf-8")
    assert "<path" in display_svg
    assert display_svg.count("<rect") >= 2  # radical overbar and fraction rule
    assert 'fill="#e9e6e0"' in display_svg
    assert "$$" not in rendered
    assert r"\frac" not in rendered


def test_currency_amounts_are_not_paired_as_cross_line_latex():
    """Spreadsheet summaries keep dollar amounts as text instead of giant equations."""
    text = (
        "- Total: $93,900\n"
        "- Monthly average: $15,650\n"
        "- February: +$1,700 (+13.7%)\n"
        "- March: -$500 (-3.5%)\n"
        "- April: +$2,300 (+16.9%)"
    )

    rendered = _assistant_text_to_html(text)

    assert "data:image/svg+xml" not in rendered
    for amount in ("$93,900", "$15,650", "$1,700", "$500", "$2,300"):
        assert amount in rendered

    same_line = _assistant_text_to_html(
        "Revenue moved from $500 to $600; net was $500 - $300 = $200."
    )
    assert "data:image/svg+xml" not in same_line
    assert "$500 - $300 = $200" in same_line


def test_numeric_inline_equations_still_render_as_latex():
    """The currency guard must preserve genuinely mathematical numeric spans."""
    rendered = _assistant_text_to_html("Check $2 + 2 = 4$ and $2$.")

    assert rendered.count("data:image/svg+xml;base64,") == 2


def test_latex_is_not_interpreted_inside_inline_or_fenced_code():
    """Code examples keep their literal delimiters and TeX commands."""
    rendered = _assistant_text_to_html(
        r"Use `$x^2$` here." "\n\n```tex\n" r"\frac{a}{b}" "\n```"
    )

    assert "<code>$x^2$</code>" in rendered
    assert r"\frac{a}{b}" in rendered
    assert "data:image/svg+xml" not in rendered


def test_multiline_latex_matrix_and_tts_progress_stay_formatted():
    """Display blocks remain structured while chat mirrors read progress."""
    text = "$$\n" + r"\begin{bmatrix}a & b\\c & d\end{bmatrix}" + "\n$$"

    rendered = _assistant_text_to_html(text, read_count=2)

    assert "data:image/svg+xml;base64," in rendered
    assert "bmatrix" not in rendered
    assert "$$" not in rendered


def test_invalid_latex_falls_back_without_crashing_the_transcript():
    rendered = _assistant_text_to_html(r"Bad but visible: $\frac{a}{$")

    assert "Bad but visible:" in rendered


def test_svg_math_renderer_handles_varied_equation_structures():
    expressions = [
        r"\int_{-\infty}^{\infty}e^{-x^2}\,dx=\sqrt{\pi}",
        r"e^x=\sum_{n=0}^{\infty}\frac{x^n}{n!}",
        r"\lim_{x\to0}\frac{\sin x}{x}=1",
        r"f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}",
        r"\det(A)=\begin{vmatrix}a&b\\c&d\end{vmatrix}=ad-bc",
        r"\vec F=m\vec a,\qquad\nabla\cdot\vec E=\frac{\rho}{\varepsilon_0}",
        r"1+\cfrac{1}{2+\cfrac{1}{3+\cfrac{1}{x}}}",
        r"(a+b)^n=\sum_{k=0}^{n}\binom{n}{k}a^{n-k}b^k",
    ]

    for expression in expressions:
        rendered = render_latex_image(expression, size=22, color="#e9e6e0")
        assert rendered is not None, expression
        assert rendered.width > 20
        assert rendered.height > 15
        assert rendered.data_uri.startswith("data:image/svg+xml;base64,")


def test_assistant_html_renders_pipe_tables_as_themed_grids():
    """GitHub-style tables should never expose their pipe/divider syntax."""
    rendered = _assistant_text_to_html(
        "| Aspect | Small model | Typical model |\n"
        "|:---|:---:|---:|\n"
        "| Memory | Similar (~4 GB) | Similar |\n"
        "| Speed | Much higher | Lower |"
    )

    assert "<table" in rendered
    assert "<thead><tr>" in rendered
    assert "<th style=" in rendered
    assert "text-align:center" in rendered
    assert "text-align:right" in rendered
    assert "Similar (~4 GB)" in rendered
    assert "|:---|" not in rendered


def test_original_table_uses_same_editorial_rules_as_formatted_tables(monkeypatch):
    """Canonical Markdown tables use clean horizontal rules, not legacy boxed cells."""
    from ui import chat_rendering

    monkeypatch.setitem(chat_rendering._RENDER_PALETTE, "table_text", "#112233")
    monkeypatch.setitem(chat_rendering._RENDER_PALETTE, "table_accent", "#227766")
    monkeypatch.setitem(chat_rendering._RENDER_PALETTE, "table_border", "#ccd8d5")
    rendered = _assistant_text_to_html(
        "Approach | Clarity | Risk\n"
        "--- | --- | ---\n"
        "Styled Markdown | Good | Low\n"
        "Semantic blocks | Excellent | Medium"
    )

    assert "border-top:2px solid #112233" in rendered
    assert "color:#227766" in rendered
    assert "padding:9px 11px" in rendered
    assert "background:transparent" in rendered
    assert "border-left" not in rendered
    assert "border-right" not in rendered


def test_table_cells_keep_inline_markdown_and_escaped_pipes():
    """Table parsing preserves safe inline formatting and literal pipes."""
    rendered = _assistant_text_to_html(
        "Name | Detail\n"
        "--- | ---\n"
        "**Mode** | `a|b` and left\\|right"
    )

    assert "<strong>Mode</strong>" in rendered
    assert "<code>a|b</code>" in rendered
    assert "left|right" in rendered


def test_compact_table_rendering_for_narrow_speech_bubbles():
    """The bubble uses a stacked object view instead of raw Markdown pipes."""
    compact = _compact_markdown_tables(
        "| Aspect | Small model | Typical model |\n"
        "|---|---|---|\n"
        "| Memory | Similar (~4 GB) | Similar |"
    )

    assert compact.splitlines() == [
        "**Aspect  ·  Small model  ·  Typical model**",
        "**Memory** — Similar (~4 GB)  ·  Similar",
    ]
    assert "|---|" not in compact


def test_tts_highlight_does_not_flatten_table_back_to_pipe_syntax():
    """Mirrored read progress keeps the structured table presentation stable."""
    text = "| Name | Value |\n|---|---|\n| Memory | 4 GB |"

    rendered = _assistant_text_to_html(text, read_count=2)

    assert "<table" in rendered
    assert "|---|" not in rendered


def test_empty_annotations_keep_assistant_html_unchanged():
    """Empty annotations stay on the old rendering path."""
    text = "First line\n\n- one\n\n**bold**"

    assert _assistant_text_to_html(text) == _assistant_text_to_html(text, annotations=[])


def test_assistant_annotations_escape_untrusted_text_and_tooltips():
    """Annotation tags/styles are sanitized and tooltips do not inject raw HTML."""
    text = "Mark <script>alert(1)</script>"
    rendered = _assistant_text_to_html(
        text,
        annotations=[
            {
                "start": 5,
                "end": len(text),
                "tag": "mark",
                "style": "background-color:#ffcc00; position:absolute",
                "tooltip": '"quoted" <tip>',
                "id": "unsafe",
            }
        ],
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<mark " in rendered
    assert "background-color:#ffcc00" in rendered
    assert "position:absolute" not in rendered
    assert "title=" not in rendered
    assert "quoted" not in rendered
    annotation = normalize_range_annotations(
        [{"start": 5, "end": len(text), "tooltip": '"quoted" <tip>', "id": "unsafe"}],
        text,
    )[0]
    assert annotation_tooltip_anchor(annotation) in rendered


def test_annotations_preserve_inline_code_and_markdown_structure():
    """Annotations decorate text nodes without taking over markdown structure."""
    text = "Use `CUDA` and **CUDA** now"
    annotations = annotations_from_keyword_rules(
        text,
        [{"match": "CUDA", "tag": "mark", "style": "background-color:#ffd166"}],
    )

    rendered = _assistant_text_to_html(text, annotations=annotations)

    assert "<code>CUDA</code>" in rendered
    assert "<strong><mark" in rendered
    assert rendered.count("background-color:#ffd166") == 1


def test_annotation_code_word_does_not_inherit_markdown_code_background():
    """Addon code-word styling should not accidentally use markdown code tags."""
    rendered = _assistant_text_to_html(
        "inspect code",
        annotations=[
            {
                "start": 8,
                "end": 12,
                "tag": "span",
                "style": "font-family:Consolas, Cascadia Mono, monospace; color:#8bd17c",
            }
        ],
    )

    assert "<span style=\"font-family:Consolas, Cascadia Mono, monospace; color:#8bd17c\">code</span>" in rendered
    assert "<code>code</code>" not in rendered


def test_tts_read_highlight_composes_with_annotation_background():
    """Read-position foreground styling should not erase addon highlighting."""
    text = "**CUDA** ready"
    rendered = _assistant_text_to_html(
        text,
        read_count=1,
        annotations=[{"start": 2, "end": 6, "style": "background-color:#abc123"}],
    )

    assert "background-color:#abc123" in rendered
    assert "font-weight:bold" in rendered
    assert "color:" in rendered


def test_user_text_annotations_escape_and_preserve_newlines():
    """User messages can opt into safe annotation rendering."""
    rendered = _user_text_to_html(
        "hello\n<world>",
        annotations=[{"start": 6, "end": 13, "tag": "u", "style": "text-decoration-color:#00ffaa"}],
    )

    assert "<br>" in rendered
    assert "&lt;world&gt;" in rendered
    assert "<u " in rendered
    assert "text-decoration-color:#00ffaa" in rendered


def test_user_message_renders_latex_without_enabling_raw_html():
    rendered = _user_text_to_html(r"Is $x_1 \le x_2$ when <x>?")

    assert "data:image/svg+xml;base64," in rendered
    assert "&lt;x&gt;" in rendered
