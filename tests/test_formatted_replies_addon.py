from __future__ import annotations

import pytest

from addons import formatted_replies
from addons.formatted_replies.formatter_contract import FormatContractError, sanitize_formatted_html
from ui.addon_presentations import PresentationContractError, presentation_document, sanitize_presentation_html

DECISION_HTML = (
    '<article class="formatted-reply">'
    '<section class="reply-section">'
    '<div class="decision-ticket">'
    '<div class="ticket-field"><span class="ticket-label">Chosen</span><p>AI-02</p></div>'
    '<div class="ticket-field"><span class="ticket-label">Because</span><p>Risk is 42%.</p></div>'
    '<div class="ticket-field"><span class="ticket-label">Revisit</span><p>After launch.</p></div>'
    '</div></section></article>'
)


def test_formatter_contract_accepts_decision_vocabulary_and_rejects_script() -> None:
    assert sanitize_formatted_html(DECISION_HTML) == DECISION_HTML
    with pytest.raises(FormatContractError):
        sanitize_formatted_html(
            '<article class="formatted-reply"><script>alert(1)</script></article>'
        )


def test_ui_revalidates_fragment_and_builds_network_isolated_document() -> None:
    assert sanitize_presentation_html(DECISION_HTML) == DECISION_HTML
    document = presentation_document(
        DECISION_HTML,
        {"accent": "#a99bff", "warm": "#f0ae72", "warm_soft": "#3c2b25"},
    )
    assert "default-src 'none'" in document
    assert "decision-ticket" in document
    assert "--warm:#f0ae72" in document
    assert "--warm-soft:#3c2b25" in document
    assert "background:var(--warm-soft)" in document
    with pytest.raises(PresentationContractError):
        sanitize_presentation_html(
            '<article class="formatted-reply"><p onclick="bad()">No</p></article>'
        )


def test_addon_keeps_canonical_reply_and_records_separate_formatting_tokens(monkeypatch) -> None:
    monkeypatch.setattr(formatted_replies, "addon_setting", lambda _addon, key, default=None: default)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Choose AI-02. Risk is 42%.", "user_prompt": "What should we choose?"},
    )
    assert started["state"]["canonical"] == "Choose AI-02. Risk is 42%."
    assert started["llm"]["route"] == "chat"
    assert started["llm"]["model"] == ""
    completed = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": (
                '<article class="formatted-reply"><section class="reply-section">'
                '<p>Choose AI-02. Risk is 42%.</p></section></article>'
            ),
            "input_tokens_estimate": 510,
            "output_tokens_estimate": 72,
        },
    )
    assert completed["status"] == "Formatted"
    assert completed["token_usage"] == {
        "formatting_input_estimate": 510,
        "formatting_output_estimate": 72,
        "verification_input_estimate": 0,
        "verification_output_estimate": 0,
    }


def test_addon_can_use_chat_route_without_changing_original_writer(monkeypatch) -> None:
    def setting(_addon, key, default=None):
        return "Chat route" if key == "formatter_route" else default

    monkeypatch.setattr(formatted_replies, "addon_setting", setting)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Use AI-02.", "user_prompt": "Choose."},
    )
    assert started["llm"]["route"] == "chat"
    assert started["state"]["route"] == "chat"


def test_addon_local_model_is_an_explicit_personal_choice(monkeypatch) -> None:
    def setting(_addon, key, default=None):
        values = {
            "formatter_model": "Local (Ollama)",
            "formatter_local_model": "personal-local:latest",
        }
        return values.get(key, default)

    monkeypatch.setattr(formatted_replies, "addon_setting", setting)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Format locally.", "user_prompt": "Format."},
    )
    assert started["llm"]["route"] == "ollama-local"
    assert started["llm"]["model"] == "personal-local:latest"


def test_addon_host_preserves_approved_small_formatter_routes() -> None:
    from core.addon_manager import _safe_message_action_result

    for route in ("chatgpt-mini", "chatgpt-nano"):
        result = _safe_message_action_result({
            "llm": {"prompt": "Format this", "route": route},
            "state": {"route": route},
        })
        assert result["llm"]["route"] == route
        assert result["state"]["route"] == route

    local = _safe_message_action_result({
        "llm": {"prompt": "Format this", "route": "ollama-local", "model": "qwen3:8b"},
        "state": {"route": "ollama-local", "model": "qwen3:8b"},
    })
    assert local["llm"]["route"] == "ollama-local"
    assert local["llm"]["model"] == "qwen3:8b"


def test_addon_settings_discover_installed_ollama_models(monkeypatch) -> None:
    from types import SimpleNamespace

    from core import addon_store
    from core.addon_manager import AddonManager
    from core.llm_clients import client as llm_client

    addon = SimpleNamespace(
        id="formatted-replies",
        enabled=False,
        host=None,
        manifest=SimpleNamespace(settings=[{
            "key": "formatter_local_model",
            "label": "Local formatting model",
            "type": "ollama_model",
            "default": "",
        }]),
    )
    manager = object.__new__(AddonManager)
    manager._find = lambda _name: addon
    monkeypatch.setattr(llm_client, "safe_list_models", lambda _provider: (["qwen3:8b", "gemma3:4b"], ""))
    monkeypatch.setattr(addon_store, "get_setting", lambda _addon, _key, default=None: default)

    settings = manager.get_settings("formatted-replies")
    assert settings[0]["type"] == "choice"
    assert settings[0]["options"] == ["qwen3:8b", "gemma3:4b"]
    assert settings[0]["value"] == "qwen3:8b"


def test_format_failure_keeps_quiet_diagnostic_on_the_message(qapp) -> None:
    from core.addon_manager import _safe_message_action_result
    from ui.chat_window import ChatWindow

    safe_result = _safe_message_action_result({
        "status": "Formatting failed. Original kept.",
        "error_detail": "protected content changed: '7 days'",
    })
    conversations = [{
        "id": "diagnostic",
        "messages": [
            {"id": "u1", "role": "user", "content": "Format it."},
            {"id": "a1", "role": "assistant", "content": "Review after 7 days."},
        ],
    }]
    window = ChatWindow(conversations, lambda _messages: iter(()))
    try:
        result = window.apply_addon_message_action_result(
            conversation_id="diagnostic",
            message_id="a1",
            addon_id="formatted-replies",
            action_id="format-reply",
            result=safe_result,
        )
        assert result["updated"] is True
        message = conversations[0]["messages"][1]
        assert message["addon_action_status"]["formatted-replies"].endswith("Original kept.")
        assert message["addon_action_errors"]["formatted-replies"] == (
            "protected content changed: '7 days'"
        )
    finally:
        window.close()


def test_addon_repairs_once_then_rejects_changed_protected_value(monkeypatch) -> None:
    monkeypatch.setattr(formatted_replies, "addon_setting", lambda _addon, key, default=None: default)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Choose AI-02. Risk is 42%.", "user_prompt": "Choose."},
    )
    repairing = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": (
                '<article class="formatted-reply"><section class="reply-section">'
                '<p>Choose AI-03. Risk is 40%.</p></section></article>'
            ),
        },
    )
    assert repairing["status"].startswith("Repairing format")
    assert repairing["state"]["format_retry"] == 1
    assert "visible escaped code" in repairing["llm"]["prompt"]
    completed = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": repairing["state"],
            "text": (
                '<article class="formatted-reply"><section class="reply-section">'
                '<p>Choose AI-03. Risk is 40%.</p></section></article>'
            ),
        },
    )
    assert "Original kept" in completed["status"]
    assert "Exact content could not be preserved" in completed["status"]
    assert "AI-02" in completed["error_detail"]
    assert "presentation" not in completed


def test_addon_repairs_local_model_contract_errors_once(monkeypatch) -> None:
    def setting(_addon, key, default=None):
        if key == "formatter_model":
            return "Local (Ollama)"
        return default

    monkeypatch.setattr(formatted_replies, "addon_setting", setting)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Keep this sentence.", "user_prompt": "Format it."},
    )
    repairing = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": '<article class="formatted-reply"><div class="invented-card">Keep this sentence.</div></article>',
        },
    )
    assert repairing["status"].startswith("Repairing format")
    assert repairing["llm"]["route"] == "ollama-local"
    assert "unknown or empty class" in repairing["llm"]["prompt"]
    completed = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": repairing["state"],
            "text": '<article class="formatted-reply"><p>Keep this sentence.</p></article>',
        },
    )
    assert completed["status"] == "Formatted"


def test_addon_repair_preserves_svg_source_and_accumulates_formatting_tokens(monkeypatch) -> None:
    from addons.formatted_replies.formatter_contract import protected_code_blocks, protected_tokens

    monkeypatch.setattr(formatted_replies, "addon_setting", lambda _addon, key, default=None: default)
    canonical = (
        '```svg\n<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M1 2 3"/></svg>\n```'
    )
    assert "http://www.w3.org/2000/svg" in protected_code_blocks(canonical)[0]
    assert "http://www.w3.org/2000/svg" not in protected_tokens(canonical)
    assert 'http://www.w3.org/2000/svg"' not in protected_tokens(canonical)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": canonical, "user_prompt": "Show this SVG source."},
    )
    repairing = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": (
                '<article class="formatted-reply"><svg viewBox="0 0 10 10">'
                '<path d="M1 2 3"></path></svg></article>'
            ),
            "input_tokens_estimate": 500,
            "output_tokens_estimate": 80,
        },
    )
    assert repairing["status"].startswith("Repairing format")
    repaired = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": repairing["state"],
            "text": (
                '<article class="formatted-reply"><pre><code>'
                '&lt;svg xmlns="http://www.w3.org/2000/svg"&gt;'
                '&lt;path d="M1 2 3"/&gt;&lt;/svg&gt;'
                '</code></pre></article>'
            ),
            "input_tokens_estimate": 620,
            "output_tokens_estimate": 95,
        },
    )
    assert repaired["status"] == "Formatted"
    assert repaired["token_usage"]["formatting_input_estimate"] == 1120
    assert repaired["token_usage"]["formatting_output_estimate"] == 175


def test_markdown_list_numbers_are_structure_but_numeric_content_stays_protected(monkeypatch) -> None:
    """Converting 1./2. to an HTML ordered list must not create a false failure."""
    monkeypatch.setattr(formatted_replies, "addon_setting", lambda _addon, key, default=None: default)
    canonical = "1. Clear the desk.\n2. Review after 7 days.\n\n```text\nRule 3 stays exact.\n```"
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": canonical, "user_prompt": "Format these steps."},
    )
    completed = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": (
                '<article class="formatted-reply"><ol><li>Clear the desk.</li>'
                '<li>Review after 7 days.</li></ol><pre><code>'
                'Rule 3 stays exact.</code></pre></article>'
            ),
        },
    )
    assert completed["status"] == "Formatted"

    changed_content = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": (
                '<article class="formatted-reply"><ol><li>Clear the desk.</li>'
                '<li>Review after 8 days.</li></ol><pre><code>'
                'Rule 3 stays exact.</code></pre></article>'
            ),
        },
    )
    assert changed_content["status"].startswith("Repairing format")


def test_optional_verification_is_a_second_separately_counted_operation(monkeypatch) -> None:
    def setting(_addon, key, default=None):
        return True if key == "verify_meaning" else default

    monkeypatch.setattr(formatted_replies, "addon_setting", setting)
    started = formatted_replies.run_message_action(
        "format-reply",
        {"text": "Use AI-02.", "user_prompt": "Choose."},
    )
    waiting = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": started["state"],
            "text": '<article class="formatted-reply"><p>Use AI-02.</p></article>',
            "input_tokens_estimate": 400,
            "output_tokens_estimate": 30,
        },
    )
    assert waiting["status"] == "Checking meaning…"
    completed = formatted_replies.resume_message_action(
        "format-reply",
        {
            "state": waiting["state"],
            "text": "PASS — meaning retained.",
            "input_tokens_estimate": 190,
            "output_tokens_estimate": 8,
        },
    )
    assert completed["status"] == "Formatted · meaning checked"
    assert completed["token_usage"]["verification_input_estimate"] == 190
    assert completed["token_usage"]["verification_output_estimate"] == 8


def test_chat_message_action_persists_presentation_beside_canonical_text(qapp) -> None:
    from ui.chat_window import ChatWindow

    conversations = [{
        "id": "conversation-1",
        "messages": [
            {"id": "user-1", "role": "user", "content": "Choose."},
            {"id": "assistant-1", "role": "assistant", "content": "Use AI-02 at 42%."},
        ],
    }]
    requested: list[dict] = []
    window = ChatWindow(
        conversations,
        lambda _messages: iter(()),
        on_addon_message_action=requested.append,
    )
    window.update_addon_message_actions([{
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }])
    window._request_addon_message_action(0, 1, "formatted-replies", "format-reply")
    qapp.processEvents()
    assert requested[0]["text"] == "Use AI-02 at 42%."
    from ui.shared.activity_spinner import ActivitySpinner
    spinner = window.findChild(ActivitySpinner)
    assert spinner is not None and spinner.is_active()
    window.apply_addon_message_action_result(
        conversation_id="conversation-1",
        message_id="assistant-1",
        addon_id="formatted-replies",
        action_id="format-reply",
        result={
            "status": "Formatted",
            "presentation": {"html": DECISION_HTML, "label": "Formatted"},
            "token_usage": {"formatting_input_estimate": 500, "formatting_output_estimate": 80},
        },
    )
    assert conversations[0]["messages"][1]["content"] == "Use AI-02 at 42%."
    stored = conversations[0]["messages"][1]["addon_presentations"]["formatted-replies"]
    assert stored["html"] == DECISION_HTML
    assert stored["token_usage"]["formatting_input_estimate"] == 500
    window.close()


def test_format_and_original_toggle_stay_in_the_same_chat_window(qapp) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from ui.addon_presentations import RichPresentationView
    from ui.chat_window import ChatWindow, _MessageTextView

    conversations = [{
        "id": "same-window",
        "messages": [
            {"id": "user-1", "role": "user", "content": "Choose."},
            {"id": "assistant-1", "role": "assistant", "content": "Use AI-02."},
        ],
    }]
    requested = []
    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(
        conversations,
        lambda _messages: iter(()),
        on_addon_message_action=requested.append,
        addon_message_actions=[action],
    )
    try:
        window.resize(1000, 700)
        window.show()
        qapp.processEvents()
        original_top_levels = set(qapp.topLevelWidgets())

        assistant_view = next(
            view for view in window.findChildren(_MessageTextView)
            if view._presentation == "assistant"
        )
        message_wrapper = assistant_view.parentWidget()
        page_container = window._stack.currentWidget().widget()
        left_inset = message_wrapper.mapTo(page_container, QPoint(0, 0)).x()
        assert 16 <= left_inset <= 40

        format_button = next(
            button for button in window.findChildren(QPushButton)
            if button.text() == "Format"
        )
        assert format_button.isEnabled()
        assert format_button.height() >= 30 and format_button.width() >= 72
        QTest.mouseClick(
            format_button,
            Qt.MouseButton.LeftButton,
            pos=format_button.rect().center(),
        )
        qapp.processEvents()
        assert requested and requested[0]["message_id"] == "assistant-1"
        assert window._active_idx == 0
        assert set(qapp.topLevelWidgets()) == original_top_levels

        window.apply_addon_message_action_result(
            conversation_id="same-window",
            message_id="assistant-1",
            addon_id="formatted-replies",
            action_id="format-reply",
            result={
                "status": "Formatted",
                "presentation": {"html": DECISION_HTML, "label": "Formatted"},
            },
        )
        qapp.processEvents()
        assert window._active_idx == 0
        assert set(qapp.topLevelWidgets()) == original_top_levels

        rich = window._stack.currentWidget().findChild(RichPresentationView)
        toggle = next(
            button for button in window.findChildren(QPushButton)
            if button.text() == "Show original"
        )
        wrapper = toggle.parentWidget().parentWidget()
        originals = wrapper.findChildren(
            _MessageTextView,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        assert rich is not None and rich.parentWidget() is wrapper
        assert len(originals) == 1 and originals[0].parentWidget() is wrapper
        assert not originals[0].isWindow()

        toggle.click()
        qapp.processEvents()
        assert toggle.text() == "Show formatted"
        assert originals[0].isVisible()
        assert not rich.isVisible()
        assert not originals[0].isWindow()
        assert set(qapp.topLevelWidgets()) == original_top_levels

        toggle.click()
        qapp.processEvents()
        assert toggle.text() == "Show original"
        assert rich.isVisible()
        assert not originals[0].isVisible()
        assert set(qapp.topLevelWidgets()) == original_top_levels
    finally:
        window.close()


def test_just_finished_last_reply_format_works_without_reopening_chat(qapp) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from ui.chat_window import ChatWindow

    conversations = [{
        "id": "live-last-reply",
        "messages": [{"id": "user-1", "role": "user", "content": "Answer now."}],
    }]
    requested = []
    window = ChatWindow(
        conversations,
        lambda _messages: iter(()),
        on_addon_message_action=requested.append,
        addon_message_actions=[{
            "addon_id": "formatted-replies",
            "id": "format-reply",
            "label": "Format",
            "role": "assistant",
            "presentation": True,
            "auto": False,
        }],
    )
    try:
        window.resize(1000, 700)
        window.show()
        window._current_ai_text = "This is the newly completed last reply."
        window._current_ai_reply_text = "This is the newly completed last reply."
        window._on_finished()
        qapp.processEvents()

        stored = conversations[0]["messages"][-1]
        assert stored["role"] == "assistant" and stored["id"]
        format_button = next(
            button for button in window.findChildren(QPushButton)
            if button.objectName() == "addonMessageActionButton"
            and button.text() == "Format"
        )
        assert format_button.isEnabled()
        QTest.mouseClick(
            format_button,
            Qt.MouseButton.LeftButton,
            pos=format_button.rect().center(),
        )
        qapp.processEvents()
        assert requested and requested[-1]["message_id"] == stored["id"]
        assert requested[-1]["conversation_id"] == "live-last-reply"
    finally:
        window.close()


def test_multiple_message_formats_can_run_independently(qapp) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from ui.chat_window import ChatWindow

    conversations = [{
        "id": "parallel-formats",
        "messages": [
            {"id": "u1", "role": "user", "content": "First?"},
            {"id": "a1", "role": "assistant", "content": "First answer."},
            {"id": "u2", "role": "user", "content": "Second?"},
            {"id": "a2", "role": "assistant", "content": "Second answer."},
        ],
    }]
    requested = []
    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(
        conversations,
        lambda _messages: iter(()),
        on_addon_message_action=requested.append,
        addon_message_actions=[action],
    )

    def button_for(message_index: int) -> QPushButton:
        return next(
            button for button in window._stack.currentWidget().findChildren(QPushButton)
            if button.objectName() == "addonMessageActionButton"
            and button.property("message_index") == message_index
        )

    try:
        window.resize(1000, 760)
        window.show()
        qapp.processEvents()
        QTest.mouseClick(button_for(1), Qt.MouseButton.LeftButton, pos=button_for(1).rect().center())
        qapp.processEvents()
        assert not button_for(1).isEnabled()
        assert button_for(3).isEnabled()

        second = button_for(3)
        QTest.mouseClick(second, Qt.MouseButton.LeftButton, pos=second.rect().center())
        qapp.processEvents()
        assert {item["message_id"] for item in requested} == {"a1", "a2"}
        assert not button_for(1).isEnabled() and not button_for(3).isEnabled()

        window.apply_addon_message_action_result(
            conversation_id="parallel-formats",
            message_id="a2",
            addon_id="formatted-replies",
            action_id="format-reply",
            result={"status": "Formatted", "presentation": {"html": DECISION_HTML}},
        )
        qapp.processEvents()
        assert "formatted-replies" not in conversations[0]["messages"][1].get("addon_presentations", {})
        assert "formatted-replies" in conversations[0]["messages"][3]["addon_presentations"]

        window.apply_addon_message_action_result(
            conversation_id="parallel-formats",
            message_id="a1",
            addon_id="formatted-replies",
            action_id="format-reply",
            result={"status": "Formatted", "presentation": {"html": DECISION_HTML}},
        )
        qapp.processEvents()
        assert "formatted-replies" in conversations[0]["messages"][1]["addon_presentations"]
        assert "formatted-replies" in conversations[0]["messages"][3]["addon_presentations"]
    finally:
        window.close()


def test_addon_enable_switches_chat_ui_and_disable_restores_original(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QPushButton

    import config
    from ui import chat_window as chat_module
    from ui.addon_presentations import RichPresentationView
    from ui.chat_window import ChatWindow

    monkeypatch.setattr(config, "THEME_MODE", "dark", raising=False)
    monkeypatch.setattr(config, "THEME_DARK_BG", "#1c1e26", raising=False)
    monkeypatch.setattr(config, "THEME_DARK_SURFACE", "#17181d", raising=False)
    monkeypatch.setattr(config, "THEME_DARK_TEXT", "#e8e8f0", raising=False)
    monkeypatch.setattr(config, "THEME_DARK_ACCENT", "#8b87ff", raising=False)
    conversations = [{
        "id": "mode-boundary",
        "messages": [
            {"id": "user-1", "role": "user", "content": "Choose."},
            {
                "id": "assistant-1",
                "role": "assistant",
                "content": "Use AI-02.",
                "addon_presentations": {
                    "formatted-replies": {"html": DECISION_HTML, "label": "Formatted"}
                },
                "addon_action_status": {"formatted-replies": "Formatted"},
            },
        ],
    }]
    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(conversations, lambda _messages: iter(()))
    try:
        window._input.setPlainText("unsent draft")
        assert window._formatted_replies_ui_enabled is False
        assert chat_module._BG == "#1c1e26"
        assert window._stack.currentWidget().findChild(RichPresentationView) is None

        window.update_addon_message_actions([action])
        qapp.processEvents()
        assert window._formatted_replies_ui_enabled is True
        assert chat_module._BG == "#151722"
        assert window._input.toPlainText() == "unsent draft"
        assert window._stack.currentWidget().findChild(RichPresentationView) is not None

        window.update_addon_message_actions([])
        qapp.processEvents()
        assert window._formatted_replies_ui_enabled is False
        assert chat_module._BG == "#1c1e26"
        assert window._input.toPlainText() == "unsent draft"
        assert window._stack.currentWidget().findChild(RichPresentationView) is None
        assert not any(
            button.text() in {"Format", "Reformat", "Show original", "Show formatted"}
            for button in window.findChildren(QPushButton)
        )
    finally:
        window.close()
        chat_module._refresh_chat_palette(False)


def test_chat_first_paint_uses_addon_owned_light_palette(qapp, monkeypatch) -> None:
    import config
    from ui import chat_window as chat_module
    from ui.chat_window import ChatWindow

    monkeypatch.setattr(config, "THEME_MODE", "light", raising=False)
    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(
        [{"id": "first-paint", "messages": []}],
        lambda _messages: iter(()),
        addon_message_actions=[action],
    )
    try:
        assert window._formatted_replies_ui_enabled is True
        assert chat_module._BG == "#f1f7f6"
        assert chat_module._ACCENT == "#116f65"
    finally:
        window.close()
        chat_module._refresh_chat_palette(False)


def test_enabled_addon_uses_approved_chat_shell_geometry(qapp) -> None:
    from PySide6.QtWidgets import QFrame, QLineEdit, QPushButton

    from ui.chat_window import ChatWindow

    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(
        [{
            "id": "approved-shell",
            "messages": [
                {"role": "user", "content": "Short question"},
                {"role": "assistant", "content": "A readable answer without a full-width box."},
            ],
        }],
        lambda _messages: iter(()),
        addon_message_actions=[action],
    )
    try:
        window.resize(1180, 760)
        window.show()
        qapp.processEvents()
        sidebar = window.findChild(QFrame, "formattedChatSidebar")
        if sidebar is None:
            from PySide6.QtWidgets import QWidget
            sidebar = window.findChild(QWidget, "formattedChatSidebar")
        composer = window.findChild(QFrame, "formattedComposer")
        search = window.findChild(QLineEdit)
        options = window.findChild(QPushButton, "conversationOptionsButton")
        delete_all = window.findChild(QPushButton, "deleteAllConversationsButton")
        assert sidebar is not None and sidebar.width() == 260
        assert composer is not None and composer.maximumWidth() == 768
        assert search is not None and search.placeholderText() == "Search chats"
        assert options is not None and options.text() == "Conversation options"
        assert options.width() >= 132
        assert delete_all is not None and delete_all.text() == "Delete all conversations"
        assert window._past_notice.isVisible() is False
        assert window._context_controls == {}
    finally:
        window.close()


def test_addon_ui_switch_waits_until_streaming_finishes(qapp) -> None:
    from ui.chat_window import ChatWindow

    action = {
        "addon_id": "formatted-replies",
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": False,
    }
    window = ChatWindow(
        [{"id": "stream-boundary", "messages": []}],
        lambda _messages: iter(()),
    )
    try:
        window._streaming = True
        window.update_addon_message_actions([action])
        assert window._formatted_replies_ui_enabled is True
        assert window._pending_addon_ui_refresh is True

        window._streaming = False
        window._apply_addon_ui_mode()
        qapp.processEvents()
        assert window._pending_addon_ui_refresh is False
        assert window._input is not None
    finally:
        window.close()


def test_ui_host_waits_for_addon_state_before_first_chat_paint() -> None:
    from runtime.workers.ui_host import QtProtocolHost

    host = QtProtocolHost.__new__(QtProtocolHost)
    host._chat = None
    host._chat_message_actions_cache = []
    host._chat_message_actions_ready = False
    host._pending_chat_show_new = None
    events: list[tuple[str, dict]] = []
    host.emit = lambda event, payload=None: events.append((event, payload or {}))

    pending = host._show_chat(force_new=True)
    assert pending == {"shown": False, "pending_actions": True}
    assert host._pending_chat_show_new is True
    assert events == [("ui.chat.message_actions.requested", {})]

    host._show_chat = lambda force_new=False: {"shown": True, "new": force_new}  # type: ignore[method-assign]
    action = {"addon_id": "formatted-replies", "id": "format-reply", "label": "Format"}
    applied = host._chat_message_actions([action])
    assert host._chat_message_actions_ready is True
    assert host._chat_message_actions_cache == [action]
    assert applied["chat"] == {"shown": True, "new": True}
