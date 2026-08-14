"""Real Settings UI acceptance for ChatGPT, GitHub, and Copilot authentication."""

from __future__ import annotations

import importlib.util
import os
import sys
import webbrowser

import pytest

pytestmark = [
    pytest.mark.workflow,
    pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="PySide6 not installed"),
]


def _new_settings_dialog(monkeypatch: pytest.MonkeyPatch):
    """Construct real Settings without starting unrelated status threads."""

    from ui.settings_panel import dialog as settings_dialog

    monkeypatch.setattr(settings_dialog.SettingsDialog, "_schedule_open_status_refresh", lambda _self: None)
    return settings_dialog.SettingsDialog()


def _close_settings(dialog, app) -> None:
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent

    dialog.close()
    app.processEvents()
    if shiboken6.isValid(dialog):
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_oauth_logins_are_compact_feature_labeled_rows_with_inline_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each real OAuth flow owns one row, with its detail line directly beneath it."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = _new_settings_dialog(monkeypatch)
    try:
        dialog.show()
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("Connections"))
        app.processEvents()

        assert 'font-family: "Bitter"' not in dialog.styleSheet()
        assert f'font-family: "{dialog.font().family()}"' in dialog.styleSheet()

        for key, feature_list in (
            ("chatgpt", "Allows you to use ChatGPT subscription models in Model settings."),
            (
                "github",
                "Allows authenticated GitHub tools to give the model repository metadata and "
                "issues/PRs as context, and lets you use Copilot models when your account has "
                "Copilot access.",
            ),
        ):
            row = dialog.findChild(QWidget, f"{key}OAuthRow")
            assert row is not None
            outer = row.layout()
            assert outer.count() == 3
            assert outer.itemAt(1).widget() is getattr(dialog, f"_{key}_purpose_lbl")
            assert outer.itemAt(2).widget() is getattr(dialog, f"_{key}_message_lbl")
            assert getattr(dialog, f"_{key}_purpose_lbl").text() == feature_list
            assert getattr(dialog, f"_{key}_message_lbl").isHidden()
            provider_icon = row.findChild(QLabel, "oauthProviderIcon")
            assert provider_icon.text() == ""
            assert provider_icon.pixmap() is not None
            assert not provider_icon.pixmap().isNull()
            assert provider_icon.property("providerIconAsset") in {
                "provider-icons/chatgpt.svg",
                "provider-icons/github-invertocat.svg",
            }
            assert row.findChild(QLabel, "oauthProviderName").font().family() != "Bitter"
            assert row.findChild(QLabel, "oauthLoginStatus").font().family() != "Bitter"
            assert getattr(dialog, f"_{key}_purpose_lbl").font().family() != "Bitter"
            assert row.findChild(QPushButton, f"{key}OAuthSignIn").text() == "Sign in"
            assert row.findChild(QPushButton, f"{key}OAuthSignOut").text() == "Sign out"

        assert dialog.findChild(QWidget, "copilotOAuthRow") is None
        assert dialog.findChild(QLabel, "oauthCredentialNote") is None

        dialog._set_oauth_status(
            "github",
            "Status unavailable",
            signed_in=None,
            message="Credential store is locked",
        )
        assert dialog._github_message_lbl.isVisible()
        assert dialog._github_message_lbl.text() == "Credential store is locked"
        dialog._set_oauth_status("github", "Not logged in", signed_in=False)
        assert dialog._github_message_lbl.isHidden()
        assert dialog._github_login_btn.isEnabled()
        assert not dialog._github_logout_btn.isEnabled()
    finally:
        _close_settings(dialog, app)


def test_chatgpt_settings_login_status_and_logout_real_button_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sign in, status refresh, error display, and sign out use the visible buttons."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.auth import chatgpt as chatgpt_auth

    app = QApplication.instance() or QApplication(sys.argv)
    store: dict[str, object] = {"tokens": None}
    starts: list[str] = []
    clears: list[str] = []
    browser_callbacks: dict[str, object] = {}
    monkeypatch.setattr(chatgpt_auth, "get_tokens", lambda: store["tokens"])
    monkeypatch.setattr(
        chatgpt_auth,
        "validate_login",
        lambda **_kwargs: (bool(store["tokens"]), "acct-123456789"),
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "start_browser_login",
        lambda on_success, _on_error: (
            starts.append("browser"),
            browser_callbacks.__setitem__("success", on_success),
        ),
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "clear_tokens",
        lambda: (clears.append("chatgpt"), store.__setitem__("tokens", None)),
    )
    dialog = _new_settings_dialog(monkeypatch)
    try:
        dialog.show()
        app.processEvents()
        dialog._refresh_chatgpt_status()
        assert dialog._chatgpt_status_lbl.text() == "Not logged in"

        dialog._cgpt_login_btn.click()
        app.processEvents()
        assert starts == ["browser"]
        assert dialog._auth_poll_timer.isActive()

        # An unrelated shared Codex credential must not complete this flow.
        store["tokens"] = {"account_id": "existing-codex-account"}
        dialog._auth_poll_tick()
        assert dialog._auth_poll_timer.isActive()

        store["tokens"] = {"account_id": "acct-123456789"}
        browser_callbacks["success"](store["tokens"])
        dialog._auth_poll_tick()
        assert not dialog._auth_poll_timer.isActive()
        dialog._refresh_chatgpt_status()
        assert dialog._chatgpt_status_lbl.text() == "Logged in"
        assert "#80c080" in dialog._chatgpt_status_lbl.styleSheet()

        with monkeypatch.context() as status_error:
            status_error.setattr(
                chatgpt_auth,
                "validate_login",
                lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("credential store locked")),
            )
            dialog._refresh_chatgpt_status()
            assert dialog._chatgpt_status_lbl.text() == "Status unavailable"
            assert "credential store locked" in dialog._chatgpt_message_lbl.text()
            assert "#c04040" in dialog._chatgpt_message_lbl.styleSheet()

        dialog._cgpt_logout_btn.click()
        app.processEvents()
        assert clears == ["chatgpt"]
        assert store["tokens"] is None
        assert dialog._chatgpt_status_lbl.text() == "Not logged in"
    finally:
        _close_settings(dialog, app)


@pytest.mark.parametrize(
    ("client_id", "scopes", "expected_client_id"),
    (("", "", "bundled-client"), ("custom-client", "repo read:user", "custom-client")),
    ids=("bundled-default", "custom-override"),
)
def test_github_settings_device_status_logout_and_override_real_button_workflow(
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
    scopes: str,
    expected_client_id: str,
) -> None:
    """Both client-ID modes flow from visible fields through device login and logout."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import config
    from core.auth import github as github_auth

    app = QApplication.instance() or QApplication(sys.argv)
    store: dict[str, object] = {"tokens": None}
    starts: list[tuple[str, str]] = []
    opened: list[str] = []
    clears: list[str] = []
    monkeypatch.setattr(config, "GITHUB_DEFAULT_CLIENT_ID", "bundled-client", raising=False)
    monkeypatch.setattr(github_auth, "has_configured_client_id", lambda: True)
    monkeypatch.setattr(github_auth, "get_tokens", lambda: store["tokens"])
    monkeypatch.setattr(
        github_auth,
        "validate_login",
        lambda **_kwargs: (
            bool(store["tokens"]),
            str(((store["tokens"] or {}).get("user") or {}).get("login") or ""),
        ),
    )
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    def start_device_login(on_code, on_success, _on_error) -> None:
        starts.append((config.GITHUB_CLIENT_ID, config.GITHUB_OAUTH_SCOPES))
        on_code("https://github.com/login/device", "ABCD-1234")
        store["tokens"] = {
            "user": {"login": "octo-user"},
            "scope": config.GITHUB_OAUTH_SCOPES,
        }
        on_success(store["tokens"])

    monkeypatch.setattr(github_auth, "start_device_login", start_device_login)
    monkeypatch.setattr(
        github_auth,
        "clear_tokens",
        lambda: (clears.append("github"), store.__setitem__("tokens", None)),
    )
    dialog = _new_settings_dialog(monkeypatch)
    try:
        dialog.show()
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("Connections"))
        app.processEvents()
        dialog._fields["GITHUB_CLIENT_ID"].setText(client_id)
        dialog._fields["GITHUB_OAUTH_SCOPES"].setText(scopes)
        dialog._refresh_github_status()
        assert dialog._github_status_lbl.text() == "Not logged in"

        dialog._github_login_btn.click()
        app.processEvents()
        assert starts == [(expected_client_id, scopes)]
        dialog._github_auth_poll_tick()
        assert "ABCD-1234" in dialog._github_message_lbl.text()
        assert opened == ["https://github.com/login/device"]
        dialog._github_auth_poll_tick()
        assert not dialog._github_auth_poll_timer.isActive()
        dialog._refresh_github_status()
        assert "octo-user" in dialog._github_status_lbl.text()
        if scopes:
            assert scopes in dialog._github_status_lbl.toolTip()

        with monkeypatch.context() as status_error:
            status_error.setattr(
                github_auth,
                "validate_login",
                lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("GitHub keychain denied")),
            )
            dialog._refresh_github_status()
            assert dialog._github_status_lbl.text() == "Status unavailable"
            assert "GitHub keychain denied" in dialog._github_message_lbl.text()
            assert "#c04040" in dialog._github_message_lbl.styleSheet()

        dialog._github_logout_btn.click()
        app.processEvents()
        assert clears == ["github"]
        assert store["tokens"] is None
        assert dialog._github_status_lbl.text() == "Not logged in"
    finally:
        _close_settings(dialog, app)


def test_copilot_token_is_a_provider_credential_not_a_separate_oauth_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copilot PATs use the normal provider row and have no misleading OAuth test controls."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from core.auth import copilot_auth

    app = QApplication.instance() or QApplication(sys.argv)
    store: dict[str, str] = {"token": ""}
    saved: list[str] = []
    monkeypatch.setattr(
        copilot_auth,
        "save_token",
        lambda token: (saved.append(token), store.__setitem__("token", token)),
    )
    dialog = _new_settings_dialog(monkeypatch)
    try:
        dialog.show()
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("Connections"))
        app.processEvents()
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert "Connect token" not in button_texts
        assert "Test connection" not in button_texts
        assert "Clear token" not in button_texts
        row = dialog._add_api_key_row(provider="copilot")
        row["key"].setText("github_pat_acceptance")

        assert dialog._save_api_keys_to_keychain() is True
        assert saved == ["github_pat_acceptance"]
        assert row["key"].text() == ""
        assert "stored in keychain" in row["key"].placeholderText().lower()
    finally:
        _close_settings(dialog, app)
