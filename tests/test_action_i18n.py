from __future__ import annotations

from xml.etree import ElementTree

from ui.action_i18n import ACTION_I18N_SOURCES, localize_action_preview_html, translate_action_text
from ui.addon_presentations import sanitize_presentation_html


def test_traditional_chinese_catalog_covers_every_action_surface() -> None:
    root = ElementTree.parse("ui/locales/qt/openwand_zh-Hant.ts").getroot()
    translations = {
        str(message.findtext("source") or ""): str(message.findtext("translation") or "").strip()
        for message in root.findall("./context/message")
    }
    missing = sorted(source for source in ACTION_I18N_SOURCES if not translations.get(source))
    assert missing == []


def test_action_text_localizes_templates_without_changing_dynamic_values() -> None:
    translations = {
        "Vertical bar chart from {range}": "CHART {range}",
        "OpenWand couldn't apply the code change: {error}": "FAILED: {error}",
    }
    def translate(source: str) -> str:
        return translations.get(source, source)

    assert translate_action_text("Vertical bar chart from Sheet 1.A1:B4", translator=translate) == "CHART Sheet 1.A1:B4"
    assert translate_action_text("OpenWand couldn't apply the code change: E_ACCESS", translator=translate) == "FAILED: E_ACCESS"
    assert translate_action_text("user-authored summary", translator=translate) == "user-authored summary"


def test_action_html_localizes_chrome_but_preserves_summary_cells_file_and_code() -> None:
    fragment = """
<article class="formatted-reply action-preview">
  <header class="reply-opening">
    <div class="reply-kicker">VS CODE ACTION - PREVIEW</div>
    <h1 class="reply-title">Apply</h1>
    <p class="reply-lede">Review the exact saved-file change before OpenWand applies it.</p>
  </header>
  <section class="reply-section">
    <div class="decision-ticket">
      <div class="ticket-field"><span class="ticket-label">File</span>Apply</div>
    </div>
    <table><tbody><tr><td>Apply</td></tr></tbody></table>
    <pre><code data-language="diff">+print("Apply")\n</code></pre>
  </section>
  <aside class="key-point action-note"><strong>Nothing has changed yet.</strong> Apply writes only this fingerprint-checked file range.</aside>
</article>
""".strip()
    translated = {
        "VS CODE ACTION - PREVIEW": "VS CODE 操作 - 預覽",
        "Review the exact saved-file change before OpenWand applies it.": "檢視確切變更。",
        "File": "檔案",
        "Nothing has changed yet.": "尚未變更。",
        "Apply writes only this fingerprint-checked file range.": "只寫入已核對的範圍。",
        "Apply": "套用",
    }
    result = localize_action_preview_html(fragment, translator=lambda source: translated.get(source, source))

    assert "VS CODE 操作 - 預覽" in result
    assert "檢視確切變更。" in result
    assert '<span class="ticket-label">檔案</span>Apply' in result
    assert "<h1 class=\"reply-title\">Apply</h1>" in result
    assert "<td>Apply</td>" in result
    assert '+print("Apply")' in result
    assert sanitize_presentation_html(result) == result
