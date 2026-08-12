"""Real Settings workflows for provider connections and model discovery."""

from __future__ import annotations

import importlib.util
import os
import sys
import time

import pytest

pytestmark = [
    pytest.mark.workflow,
    pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="PySide6 not installed"),
]


def test_numbered_custom_connections_round_trip_and_migrate_legacy() -> None:
    from core.custom_connections import env_values, load_connections, route_id, secret_name

    connections = [
        {"id": "studio", "alias": "LM Studio", "base_url": "http://localhost:1234/v1"},
        {"id": "llama", "alias": "llama.cpp", "base_url": "http://localhost:8080/v1"},
    ]
    saved = env_values(connections)
    assert load_connections(saved) == connections
    assert route_id("studio") == "custom@studio"
    assert secret_name("studio") == "OPENWAND_CUSTOM_API_KEY_STUDIO"
    assert load_connections({"CUSTOM_BASE_URL": "http://legacy.test/v1"}) == [
        {"id": "legacy", "alias": "", "base_url": "http://legacy.test/v1"}
    ]


def test_runtime_builds_each_custom_route_with_its_own_url_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import config
    from core.llm_clients import client

    monkeypatch.setattr(
        config,
        "CUSTOM_CONNECTIONS",
        [
            {"id": "studio", "alias": "LM Studio", "base_url": "http://localhost:1234/v1"},
            {"id": "llama", "alias": "llama.cpp", "base_url": "http://localhost:8080/v1"},
        ],
        raising=False,
    )
    secrets = {
        "OPENWAND_CUSTOM_API_KEY_STUDIO": "studio-key",
        "OPENWAND_CUSTOM_API_KEY_LLAMA": "llama-key",
    }
    monkeypatch.setattr(client.secret_store, "get_secret", lambda name: secrets.get(name, ""))
    calls: list[dict] = []
    monkeypatch.setattr(
        client.sdk_clients,
        "openai_client",
        lambda **kwargs: calls.append(kwargs) or object(),
    )

    client._build_dynamic_openai_client("custom@studio")
    client._build_dynamic_openai_client("custom@llama")

    assert calls == [
        {
            "api_key": "studio-key",
            "base_url": "http://localhost:1234/v1",
            "max_retries": client._OPENAI_MAX_RETRIES,
        },
        {
            "api_key": "llama-key",
            "base_url": "http://localhost:8080/v1",
            "max_retries": client._OPENAI_MAX_RETRIES,
        },
    ]
    assert client._route_endpoint("custom@studio") == "http://localhost:1234/v1"
    assert client._route_endpoint("custom@llama") == "http://localhost:8080/v1"


def _new_dialog(monkeypatch: pytest.MonkeyPatch, *, env: dict[str, str] | None = None):
    from ui.settings_panel import dialog as settings_dialog

    persisted = env if env is not None else {}
    monkeypatch.setattr(settings_dialog.SettingsDialog, "_schedule_open_status_refresh", lambda _self: None)
    monkeypatch.setattr(settings_dialog, "_read_env", lambda: dict(persisted))
    dialog = settings_dialog.SettingsDialog()
    dialog.show()
    dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("Connections"))
    return dialog


def _close(dialog, app) -> None:
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def _remove_loaded_rows(dialog) -> None:
    dialog._loading_values = True
    try:
        for row in list(dialog._api_key_rows):
            dialog._remove_api_key_row(row)
    finally:
        dialog._loading_values = False


def _install_save_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    persisted: dict[str, str],
) -> dict[str, str]:
    """Keep the real Save button/state machine while isolating external effects."""

    import config
    from core import secret_store, tts
    from core.llm_clients import client as llm
    from core.system import autostart
    from ui.settings_panel import dialog as settings_dialog
    from ui.shared import theme

    secrets: dict[str, str] = {}

    def write_env(values: dict[str, str], remove_keys: set[str] | None = None) -> None:
        for key in remove_keys or set():
            persisted.pop(key, None)
        persisted.update({key: str(value) for key, value in values.items()})

    monkeypatch.setattr(settings_dialog, "_read_env", lambda: dict(persisted))
    monkeypatch.setattr(settings_dialog, "_write_env", write_env)
    monkeypatch.setattr(
        settings_dialog.settings_profiles,
        "migrate_legacy_profiles",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        settings_dialog.settings_profiles,
        "save_profile",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(config, "reload", lambda: None)
    monkeypatch.setattr(llm, "reset_clients", lambda: None)
    monkeypatch.setattr(tts, "reset_connections", lambda: None)
    monkeypatch.setattr(theme, "apply_app_theme", lambda: None)
    monkeypatch.setattr(autostart, "sync_start_on_login", lambda _enabled: None)
    monkeypatch.setattr(secret_store, "migrate_env_secrets", lambda _env: None)
    monkeypatch.setattr(secret_store, "set_secret", lambda name, value: secrets.__setitem__(name, value))
    monkeypatch.setattr(secret_store, "delete_secret", lambda name: secrets.pop(name, None))
    monkeypatch.setattr(secret_store, "has_secret", lambda name: bool(secrets.get(name)))
    monkeypatch.setattr(secret_store, "get_secret", lambda name: secrets.get(name, ""))
    monkeypatch.setattr(secret_store, "get_keychain_secret", lambda name: secrets.get(name, ""))
    monkeypatch.setattr(
        settings_dialog.SettingsDialog,
        "_capability_warnings_for_values",
        lambda _self, _values: ([], {}),
    )
    return secrets


def test_add_alias_search_filter_and_expand_every_connection_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Add connection creates a compact inline provider row for the full catalog."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from ui.settings_panel import dialog as settings_dialog

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = _new_dialog(monkeypatch)
    try:
        _remove_loaded_rows(dialog)
        add_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "+ Add connection"
        )

        for index, provider in enumerate(settings_dialog._CONNECTION_PROVIDER_IDS):
            add_button.click()
            app.processEvents()
            assert len(dialog._api_key_rows) == index + 1
            row = dialog._api_key_rows[-1]
            assert QApplication.activeModalWidget() is None
            assert row["provider"].currentData() == ""
            assert row["provider"].itemText(0) == "Choose a provider"
            assert {
                row["provider"].itemData(option)
                for option in range(1, row["provider"].count())
            } == set(settings_dialog._CONNECTION_PROVIDER_IDS)
            assert all(
                provider_id
                for _label, provider_id in dialog._get_api_key_display_options()
            )

            row["provider"].setCurrentIndex(row["provider"].findData(provider))
            app.processEvents()
            assert row["provider"].currentData() == provider
            assert row["alias"].text() == ""
            assert row["custom_details"].isHidden() == (provider != "custom")
            row["alias"].setText(f"alias-{provider}")
            assert row["alias"].text() == f"alias-{provider}"

        rows = list(dialog._api_key_rows)
        dialog._connections_expanded = False
        dialog._refresh_connection_rows_filter()
        assert sum(not row["widget"].isHidden() for row in rows) == 6
        assert dialog._connections_show_more_btn.isVisible()
        dialog._connections_show_more_btn.click()
        assert all(not row["widget"].isHidden() for row in rows)
        dialog._connections_show_more_btn.click()
        assert sum(not row["widget"].isHidden() for row in rows) == 6

        dialog._connections_expanded = True
        dialog._refresh_connection_rows_filter()
        local_providers = {"custom"}
        queries = (
            "",
            "no-such-connection",
            *settings_dialog._CONNECTION_PROVIDER_IDS,
            *(f"alias-{provider}" for provider in settings_dialog._CONNECTION_PROVIDER_IDS),
        )
        for mode in ("all", "cloud", "local"):
            dialog._connections_filter.setCurrentIndex(dialog._connections_filter.findData(mode))
            for query in queries:
                dialog._connections_search.setText(query)
                app.processEvents()
                expected = []
                for candidate in rows:
                    candidate_provider = candidate["provider"].currentData()
                    haystack = (
                        f"{candidate_provider} "
                        f"{settings_dialog._PROVIDER_LABELS[candidate_provider]} "
                        f"{candidate['alias'].text()}"
                    ).lower()
                    matches_text = not query or query in haystack
                    matches_mode = (
                        mode == "all"
                        or (mode == "local" and candidate_provider in local_providers)
                        or (mode == "cloud" and candidate_provider not in local_providers)
                    )
                    if matches_text and matches_mode:
                        expected.append(candidate)
                assert [
                    candidate for candidate in rows if not candidate["widget"].isHidden()
                ] == expected

        dialog._connections_filter.setCurrentIndex(dialog._connections_filter.findData("all"))
        for expanded in (False, True):
            dialog._connections_expanded = expanded
            dialog._connections_search.setText("alias-openai")
            dialog._refresh_connection_rows_filter()
            app.processEvents()
            assert [candidate for candidate in rows if not candidate["widget"].isHidden()] == [
                rows[settings_dialog._CONNECTION_PROVIDER_IDS.index("openai")]
            ]
            assert dialog._connections_show_more_btn.isHidden()

        dialog._connections_search.clear()
        dialog._connections_filter.setCurrentIndex(dialog._connections_filter.findData("local"))
        for expanded in (False, True):
            dialog._connections_expanded = expanded
            dialog._refresh_connection_rows_filter()
            app.processEvents()
            assert {
                candidate["provider"].currentData()
                for candidate in rows
                if not candidate["widget"].isHidden()
            } == local_providers
            assert dialog._connections_show_more_btn.isHidden()
    finally:
        _close(dialog, app)


def test_connection_save_keychain_remove_last_and_cancel_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save stores secrets; only saved removal of the last provider row clears them."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton


    app = QApplication.instance() or QApplication(sys.argv)
    persisted: dict[str, str] = {}
    secrets = _install_save_boundaries(monkeypatch, persisted)
    dialog = _new_dialog(monkeypatch, env=persisted)
    try:
        _remove_loaded_rows(dialog)
        first = dialog._add_api_key_row("openai", alias="Primary")
        first["key"].setText("openai-acceptance-key")
        dialog._fields["CUSTOM_BASE_URL"].setText("http://localhost:1234/v1")
        dialog._fields["CUSTOM_API_KEY"].setText("custom-acceptance-key")
        dialog._refresh_dirty_state()
        assert dialog._apply_btn.isEnabled()
        dialog._apply_btn.click()
        app.processEvents()

        assert secrets == {
            "OPENAI_API_KEY": "openai-acceptance-key",
            "CUSTOM_API_KEY": "custom-acceptance-key",
        }
        assert first["key"].text() == ""
        assert dialog._fields["CUSTOM_API_KEY"].text() == ""
        assert persisted["CUSTOM_BASE_URL"] == "http://localhost:1234/v1"
        assert persisted["OPENWAND_CONNECTION_ALIAS_OPENAI"] == "Primary"

        sibling = dialog._add_api_key_row("openai", alias="Sibling")
        remove_first = next(
            button for button in first["widget"].findChildren(QPushButton) if button.text() == "✕"
        )
        remove_first.click()
        dialog._refresh_dirty_state()
        dialog._apply_btn.click()
        app.processEvents()
        assert secrets["OPENAI_API_KEY"] == "openai-acceptance-key"

        remove_last = next(
            button for button in sibling["widget"].findChildren(QPushButton) if button.text() == "✕"
        )
        remove_last.click()
        assert secrets["OPENAI_API_KEY"] == "openai-acceptance-key"
        dialog._refresh_dirty_state()
        dialog._apply_btn.click()
        app.processEvents()
        assert "OPENAI_API_KEY" not in secrets
        assert "OPENWAND_CONNECTION_ALIAS_OPENAI" not in persisted
        dialog._load_values()
        assert all(row["provider"].currentData() != "openai" for row in dialog._api_key_rows)

        secrets["OPENAI_API_KEY"] = "clear-on-provider-change"
        changed = dialog._add_api_key_row("openai", alias="Changed")
        changed["provider"].setCurrentIndex(changed["provider"].findData("anthropic"))
        changed["key"].setText("anthropic-after-change")
        dialog._refresh_dirty_state()
        dialog._apply_btn.click()
        app.processEvents()
        assert "OPENAI_API_KEY" not in secrets
        assert secrets["ANTHROPIC_API_KEY"] == "anthropic-after-change"

        secrets["OPENAI_API_KEY"] = "keep-after-change-back"
        returning = dialog._add_api_key_row("openai", alias="Returning")
        returning["provider"].setCurrentIndex(returning["provider"].findData("anthropic"))
        returning["provider"].setCurrentIndex(returning["provider"].findData("openai"))
        dialog._refresh_dirty_state()
        dialog._apply_btn.click()
        app.processEvents()
        assert secrets["OPENAI_API_KEY"] == "keep-after-change-back"

        secrets["OPENAI_API_KEY"] = "keep-on-cancel"
        cancel_remove = next(
            button for button in returning["widget"].findChildren(QPushButton) if button.text() == "✕"
        )
        cancel_remove.click()
        cancel = dialog.findChild(QPushButton, "settingsCancelButton")
        assert cancel is not None
        cancel.click()
        assert secrets["OPENAI_API_KEY"] == "keep-on-cancel"
    finally:
        _close(dialog, app)


def test_custom_endpoint_selector_lists_presets_and_reveals_custom_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every Custom connection owns its endpoint and reveals its own address."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ui.settings_panel import dialog as settings_dialog

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = _new_dialog(monkeypatch)
    try:
        _remove_loaded_rows(dialog)
        connection = dialog._add_api_key_row("openai", alias="Local one")
        assert connection["custom_details"].isHidden()
        connection["provider"].setCurrentIndex(connection["provider"].findData("custom"))
        app.processEvents()
        selector = connection["endpoint_combo"]
        address = connection["custom_address"]
        assert selector.objectName() == "settingsCustomConnectionEndpoint"
        assert not connection["custom_details"].isHidden()
        assert selector.itemText(selector.count() - 1) == "Custom endpoint"
        assert selector.itemData(selector.count() - 1) == ""
        for name, url, _model_hint, _api_key_hint in settings_dialog.SettingsDialog._CUSTOM_ENDPOINTS:
            selector.setCurrentIndex(selector.count() - 1)
            app.processEvents()
            address.clear()
            index = selector.findData(url)
            assert index >= 0
            assert selector.itemText(index) == f"{name} [{url}]"
            selector.setCurrentIndex(index)
            app.processEvents()
            assert address.text() == url
            assert address.isHidden()

        selector.setCurrentIndex(selector.count() - 1)
        app.processEvents()
        assert not address.isHidden()
        assert address.text() == ""
        address.setText("https://custom.example.test/v1")
        assert address.text() == "https://custom.example.test/v1"

        route_id = f"custom@{connection['connection_id']}"
        assert route_id in {provider for _label, provider in dialog._get_api_key_display_options()}
    finally:
        _close(dialog, app)


def test_saved_unknown_endpoint_reopens_as_custom_without_losing_its_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An address outside the preset list must survive reopening as Custom."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    saved_url = "https://private-gateway.example.test/v1"
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = _new_dialog(
        monkeypatch,
        env={
            "OPENWAND_CUSTOM_CONNECTION_COUNT": "1",
            "OPENWAND_CUSTOM_CONNECTION_1_ID": "private",
            "OPENWAND_CUSTOM_CONNECTION_1_ALIAS": "Private gateway",
            "OPENWAND_CUSTOM_CONNECTION_1_BASE_URL": saved_url,
        },
    )
    try:
        app.processEvents()
        custom_rows = [row for row in dialog._api_key_rows if row["provider"].currentData() == "custom"]
        assert len(custom_rows) == 1
        row = custom_rows[0]
        assert row["endpoint_combo"].currentData() == ""
        assert row["endpoint_combo"].currentText() == "Custom endpoint"
        assert not row["custom_address"].isHidden()
        assert row["custom_address"].text() == saved_url
    finally:
        _close(dialog, app)


def test_two_custom_connections_save_reload_and_route_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two local/custom rows retain distinct URLs, secrets, aliases, and route ids."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    persisted: dict[str, str] = {}
    secrets = _install_save_boundaries(monkeypatch, persisted)
    dialog = _new_dialog(monkeypatch, env=persisted)
    try:
        _remove_loaded_rows(dialog)
        first = dialog._add_api_key_row("custom", alias="LM Studio")
        second = dialog._add_api_key_row("custom", alias="llama.cpp")
        first["custom_address"].setText("http://localhost:1234/v1")
        second["custom_address"].setText("http://localhost:8080/v1")
        first["key"].setText("first-secret")
        second["key"].setText("second-secret")

        first_route = f"custom@{first['connection_id']}"
        second_route = f"custom@{second['connection_id']}"
        assert first_route != second_route
        route_options = dialog._get_api_key_display_options()
        assert ("Custom (OpenAI-compatible) (LM Studio)", first_route) in route_options
        assert ("Custom (OpenAI-compatible) (llama.cpp)", second_route) in route_options

        model_row = dialog._model_section_rows["LLM"][0]
        dialog._fill_credential_combo(model_row["api_key_combo"], second_route)
        assert model_row["api_key_combo"].currentData() == second_route
        dialog._refresh_dirty_state()
        dialog._apply_btn.click()
        app.processEvents()

        assert persisted["OPENWAND_CUSTOM_CONNECTION_COUNT"] == "2"
        assert persisted["OPENWAND_CUSTOM_CONNECTION_1_BASE_URL"] == "http://localhost:1234/v1"
        assert persisted["OPENWAND_CUSTOM_CONNECTION_2_BASE_URL"] == "http://localhost:8080/v1"
        assert persisted["LLM_PROVIDER"] == second_route
        assert secrets[f"OPENWAND_CUSTOM_API_KEY_{first['connection_id'].upper().replace('-', '_')}"] == "first-secret"
        assert secrets[f"OPENWAND_CUSTOM_API_KEY_{second['connection_id'].upper().replace('-', '_')}"] == "second-secret"
    finally:
        _close(dialog, app)

    reloaded = _new_dialog(monkeypatch, env=persisted)
    try:
        rows = [row for row in reloaded._api_key_rows if row["provider"].currentData() == "custom"]
        assert [row["alias"].text() for row in rows] == ["LM Studio", "llama.cpp"]
        assert [row["custom_address"].text() for row in rows] == [
            "http://localhost:1234/v1",
            "http://localhost:8080/v1",
        ]
        assert reloaded._model_section_rows["LLM"][0]["api_key_combo"].currentData() == second_route
    finally:
        _close(reloaded, app)


def _wait_until(app, predicate, *, timeout: float = 5.0) -> None:
    """Process queued Qt events until a background workflow reaches its boundary."""

    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def test_model_refresh_and_manual_name_every_provider_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every selectable provider can refresh models and retain an exact manual name."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.auth import copilot_auth
    from core.llm_clients import client as llm
    from ui.settings_panel import dialog as settings_dialog

    app = QApplication.instance() or QApplication(sys.argv)
    calls: list[tuple[str, str, str]] = []
    expected_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(copilot_auth, "get_token", lambda: "copilot-key")
    monkeypatch.setattr(settings_dialog.secret_store, "get_keychain_secret", lambda name: f"stored-{name}")

    def safe_list_models(provider: str, *, api_key: str = "", base_url: str = ""):
        calls.append((provider, api_key, base_url))
        return [f"{provider}-live-a", f"{provider}-live-b"], ""

    monkeypatch.setattr(llm, "safe_list_models", safe_list_models)
    dialog = _new_dialog(monkeypatch)
    try:
        _remove_loaded_rows(dialog)
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("LLM"))
        app.processEvents()
        row = dialog._model_section_rows["LLM"][0]
        providers = (*settings_dialog._CONNECTION_PROVIDER_IDS, "ollama", "chatgpt")
        for provider in providers:
            connection = (
                dialog._add_api_key_row(provider)
                if provider in settings_dialog._CONNECTION_PROVIDER_IDS
                else None
            )
            route_provider = provider
            if provider == "custom":
                assert connection is not None
                route_provider = f"custom@{connection['connection_id']}"
                connection["custom_address"].setText("https://custom.example/v1")
                connection["key"].setText("custom-key")
            dialog._fill_credential_combo(row["api_key_combo"], route_provider)
            row["api_key_combo"].setCurrentIndex(row["api_key_combo"].findData(route_provider))

            credential_cases: list[tuple[str, str]]
            if provider in settings_dialog._PROVIDER_KEY_NAMES and provider != "custom":
                assert connection is not None
                key_name = settings_dialog._PROVIDER_KEY_NAMES[provider]
                connection["key"].setText(f"typed-{provider}")
                credential_cases = [
                    (f"typed-{provider}", ""),
                    (f"stored-{key_name}", ""),
                ]
            elif provider == "custom":
                assert connection is not None
                secret_name = f"OPENWAND_CUSTOM_API_KEY_{connection['connection_id'].upper().replace('-', '_')}"
                credential_cases = [
                    ("custom-key", "https://custom.example/v1"),
                    (f"stored-{secret_name}", "https://custom.example/v1"),
                ]
            elif provider == "copilot":
                assert connection is not None
                connection["key"].setText("typed-copilot")
                credential_cases = [("typed-copilot", ""), ("copilot-key", "")]
            else:
                credential_cases = [("", "")]

            for case_index, (expected_key, expected_url) in enumerate(credential_cases):
                if case_index == 1:
                    if provider == "custom":
                        assert connection is not None
                        connection["key"].clear()
                    elif connection is not None:
                        connection["key"].clear()
                expected_calls.append((route_provider, expected_key, expected_url))
                row["refresh_btn"].click()
                _wait_until(app, row["refresh_btn"].isEnabled)
                assert calls[-1] == expected_calls[-1]
                assert [
                    row["model_combo"].itemData(index)
                    for index in range(row["model_combo"].count())
                ] == [
                    f"{route_provider}-live-a",
                    f"{route_provider}-live-b",
                    settings_dialog._CUSTOM_MODEL_SENTINEL,
                ]
                assert row["refresh_btn"].toolTip() == "Live: 2 models"

            row["model_combo"].setCurrentIndex(
                row["model_combo"].findData(settings_dialog._CUSTOM_MODEL_SENTINEL)
            )
            manual = f"exact/{provider}-manual-model"
            row["model_edit"].setText(manual)
            assert row["model_edit"].isVisible()
            assert dialog._model_value(row) == manual

        assert calls == expected_calls

        monkeypatch.setattr(llm, "safe_list_models", lambda *_args, **_kwargs: ([], "provider offline"))
        row["refresh_btn"].click()
        _wait_until(app, row["refresh_btn"].isEnabled)
        assert "provider offline" in row["refresh_btn"].toolTip()
        assert dialog._model_value(row) == manual
    finally:
        _close(dialog, app)


def test_custom_endpoint_and_exact_manual_model_reach_real_test_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local and remote Custom presets reach the production route probe unchanged."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from core.llm_clients import client as llm
    from ui.settings_panel import dialog as settings_dialog

    app = QApplication.instance() or QApplication(sys.argv)
    client_calls: list[dict[str, str]] = []
    completion_calls: list[dict[str, object]] = []

    class FakeStream:
        def __enter__(self):
            return iter([object()])

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    class FakeCompletions:
        def create(self, **kwargs):
            completion_calls.append(dict(kwargs))
            return FakeStream() if kwargs.get("stream") else object()

    class FakeClient:
        class Chat:
            completions = FakeCompletions()

        chat = Chat()

    def openai_client(**kwargs):
        client_calls.append(dict(kwargs))
        return FakeClient()

    monkeypatch.setattr(llm.sdk_clients, "openai_client", openai_client)
    dialog = _new_dialog(monkeypatch)
    try:
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("LLM"))
        app.processEvents()
        row = dialog._model_section_rows["LLM"][0]
        for fallback in list(dialog._model_section_rows["LLM"])[1:]:
            dialog._remove_model_section_row("LLM", fallback)
        connection = dialog._add_api_key_row("custom", alias="Route under test")
        route_id = f"custom@{connection['connection_id']}"
        dialog._fill_credential_combo(row["api_key_combo"], route_id)
        row["api_key_combo"].setCurrentIndex(row["api_key_combo"].findData(route_id))
        row["model_combo"].setCurrentIndex(
            row["model_combo"].findData(settings_dialog._CUSTOM_MODEL_SENTINEL)
        )
        endpoint_selector = connection["endpoint_combo"]
        test_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Test Chat model"
        )

        cases = (
            ("LM Studio (local)", "http://localhost:1234/v1", "exact/local-model"),
            ("OpenRouter", "https://openrouter.ai/api/v1", "exact/remote-model"),
        )
        for index, (preset, expected_url, exact_model) in enumerate(cases, start=1):
            preset_index = endpoint_selector.findData(expected_url)
            assert preset_index >= 0
            assert endpoint_selector.itemText(preset_index).startswith(f"{preset} [")
            endpoint_selector.setCurrentIndex(preset_index)
            app.processEvents()
            connection["key"].setText(f"custom-route-key-{index}")
            row["model_edit"].setText(exact_model)
            assert dialog._model_value(row) == exact_model

            test_button.click()
            _wait_until(
                app,
                lambda index=index: (
                    len(client_calls) == index and not dialog._running_test_tokens
                ),
            )

            assert client_calls[-1] == {
                "api_key": f"custom-route-key-{index}",
                "base_url": expected_url,
            }
            assert completion_calls[-1]["model"] == exact_model
            assert f"✓ Primary — {route_id} /" in dialog._llm_test_status_lbl.text()
            assert exact_model in dialog._llm_test_status_lbl.text()
    finally:
        _close(dialog, app)


def test_every_provider_reaches_its_real_chat_route_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 25 chat providers traverse Settings, validation, and their real adapter."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from core.auth import chatgpt as chatgpt_auth
    from core.auth import copilot_auth, copilot_client
    from core.llm_clients import client as llm
    from ui.settings_panel import dialog as settings_dialog

    app = QApplication.instance() or QApplication(sys.argv)
    openai_requests: list[tuple[dict[str, object], dict[str, object]]] = []
    response_requests: list[tuple[dict[str, object], dict[str, object]]] = []
    anthropic_requests: list[tuple[dict[str, object], dict[str, object]]] = []
    copilot_requests: list[tuple[tuple[object, ...], dict[str, object]]] = []
    ollama_readiness: list[dict[str, object]] = []

    class FakeStream:
        def __enter__(self):
            return iter([object()])

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    class FakeCompletions:
        def __init__(self, factory_kwargs: dict[str, object]) -> None:
            self._factory_kwargs = factory_kwargs

        def create(self, **kwargs):
            openai_requests.append((dict(self._factory_kwargs), dict(kwargs)))
            return FakeStream() if kwargs.get("stream") else object()

    class FakeResponses:
        def __init__(self, factory_kwargs: dict[str, object]) -> None:
            self._factory_kwargs = factory_kwargs

        def create(self, **kwargs):
            response_requests.append((dict(self._factory_kwargs), dict(kwargs)))
            return object()

    class FakeOpenAIClient:
        def __init__(self, factory_kwargs: dict[str, object]) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions(factory_kwargs)})()
            self.responses = FakeResponses(factory_kwargs)

    class FakeAnthropicMessages:
        def __init__(self, factory_kwargs: dict[str, object]) -> None:
            self._factory_kwargs = factory_kwargs

        def create(self, **kwargs):
            anthropic_requests.append((dict(self._factory_kwargs), dict(kwargs)))
            return object()

    class FakeAnthropicClient:
        def __init__(self, factory_kwargs: dict[str, object]) -> None:
            self.messages = FakeAnthropicMessages(factory_kwargs)

    monkeypatch.setattr(
        llm.sdk_clients,
        "openai_client",
        lambda **kwargs: FakeOpenAIClient(dict(kwargs)),
    )
    monkeypatch.setattr(
        llm.sdk_clients,
        "anthropic_client",
        lambda **kwargs: FakeAnthropicClient(dict(kwargs)),
    )
    monkeypatch.setattr(llm.sdk_clients, "httpx_client", lambda **_kwargs: object())
    monkeypatch.setattr(chatgpt_auth, "get_tokens", lambda: {"access_token": "oauth", "account_id": "acct"})
    monkeypatch.setattr(copilot_auth, "get_effective_token", lambda: "copilot-token")
    monkeypatch.setattr(
        settings_dialog.secret_store,
        "get_keychain_secret",
        lambda name: f"stored-{name}",
    )
    monkeypatch.setattr(
        copilot_client,
        "ask",
        lambda *args, **kwargs: copilot_requests.append((args, dict(kwargs))) or "OK",
    )
    monkeypatch.setattr(
        llm,
        "_ensure_ollama_running",
        lambda **kwargs: ollama_readiness.append(dict(kwargs)),
    )
    llm._codex_client = None
    llm._dynamic_openai_clients.clear()

    dialog = _new_dialog(monkeypatch)
    try:
        _remove_loaded_rows(dialog)
        connection_rows: dict[str, dict] = {}
        for provider in settings_dialog._CONNECTION_PROVIDER_IDS:
            connection = dialog._add_api_key_row(provider)
            connection_rows[provider] = connection
            if provider not in {"ollama", "custom", "copilot"}:
                connection["key"].setText(f"typed-{provider}")
            elif provider == "copilot":
                connection["key"].setText("typed-copilot")
            elif provider == "custom":
                connection["custom_address"].setText("https://custom.runtime.example/v1")
                connection["key"].setText("typed-custom")
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("LLM"))
        app.processEvents()

        row = dialog._model_section_rows["LLM"][0]
        for fallback in list(dialog._model_section_rows["LLM"])[1:]:
            dialog._remove_model_section_row("LLM", fallback)
        test_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Test Chat model"
        )
        providers = (*settings_dialog._CONNECTION_PROVIDER_IDS, "ollama", "chatgpt")
        before_counts = (0, 0, 0, 0)
        selected_models: dict[str, str] = {}

        for provider in providers:
            route_provider = (
                f"custom@{connection_rows['custom']['connection_id']}"
                if provider == "custom"
                else provider
            )
            dialog._fill_credential_combo(row["api_key_combo"], route_provider)
            row["api_key_combo"].setCurrentIndex(row["api_key_combo"].findData(route_provider))
            app.processEvents()
            models = list(settings_dialog._PROVIDER_MODELS.get(provider, []))
            model = models[0] if models else f"exact/{provider}-runtime-model"
            selected_models[provider] = model
            model_index = row["model_combo"].findData(model)
            if model_index >= 0:
                row["model_combo"].setCurrentIndex(model_index)
            else:
                row["model_combo"].setCurrentIndex(
                    row["model_combo"].findData(settings_dialog._CUSTOM_MODEL_SENTINEL)
                )
                row["model_edit"].setText(model)

            if provider in settings_dialog._PROVIDER_KEY_NAMES:
                key_name = (
                    f"OPENWAND_CUSTOM_API_KEY_{connection_rows['custom']['connection_id'].upper().replace('-', '_')}"
                    if provider == "custom"
                    else settings_dialog._PROVIDER_KEY_NAMES[provider]
                )
                credential_cases = [
                    (f"typed-{provider}" if provider != "custom" else "typed-custom", False),
                    (f"stored-{key_name}", True),
                ]
            else:
                credential_cases = [("ollama" if provider == "ollama" else "", False)]

            for expected_key, use_stored in credential_cases:
                if use_stored:
                    connection_rows[provider]["key"].clear()
                test_button.click()
                # The mocked route returns immediately; allow a loaded Windows
                # runner time to schedule and drain the real Settings worker
                # thread without treating scheduler delay as a provider failure.
                _wait_until(
                    app,
                    lambda: not dialog._running_test_tokens,
                    timeout=15.0,
                )
                assert f"✓ Primary — {route_provider} / {model}: Passed" in dialog._llm_test_status_lbl.text()
                after_counts = (
                    len(openai_requests),
                    len(response_requests),
                    len(anthropic_requests),
                    len(copilot_requests),
                )
                assert sum(after_counts) == sum(before_counts) + 1
                before_counts = after_counts
                if llm._is_openai_compat_provider(route_provider):
                    factory, request = openai_requests[-1]
                    assert request["model"] == model
                    assert factory["api_key"] == expected_key
                    expected_base_url = (
                        "https://custom.runtime.example/v1"
                        if provider == "custom"
                        else llm._openai_compat_base_url(provider)
                    )
                    if provider == "openai":
                        assert "base_url" not in factory
                    elif expected_base_url:
                        assert factory["base_url"] == expected_base_url
                    else:
                        assert "base_url" not in factory
                elif provider == "anthropic":
                    factory, request = anthropic_requests[-1]
                    assert factory == {"api_key": expected_key}
                    assert request["model"] == model

        assert len(openai_requests) == sum(
            2 if provider in settings_dialog._PROVIDER_KEY_NAMES else 1
            for provider in providers
            if provider in llm._OPENAI_COMPAT_PROVIDER_SET
        )

        assert [factory["api_key"] for factory, _request in anthropic_requests] == [
            "typed-anthropic",
            "stored-ANTHROPIC_API_KEY",
        ]
        assert all(
            request
            == {
                "model": selected_models["anthropic"],
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "Reply with OK."}],
            }
            for _factory, request in anthropic_requests
        )
        assert response_requests[0][0]["base_url"] == "https://chatgpt.com/backend-api/codex"
        assert response_requests[0][1]["model"] == selected_models["chatgpt"]
        assert copilot_requests == [
            (
                ("Reply with OK.", selected_models["copilot"]),
                {"system": "Return exactly OK.", "allow_tools": False},
            )
        ]
        assert ollama_readiness == [{}, {}]
    finally:
        llm._codex_client = None
        llm._dynamic_openai_clients.clear()
        _close(dialog, app)


def test_every_model_route_add_remove_reorder_apply_and_test_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat, Image, and Memory routes share one complete visible row workflow."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from core.llm_clients import client as llm

    app = QApplication.instance() or QApplication(sys.argv)
    calls: list[tuple[str, str, str, bool]] = []
    model_list_calls: list[str] = []

    def test_route(provider, model, route_name, *, image=False, **_kwargs):
        calls.append((provider, model, route_name, image))
        return True, f"{route_name} route OK"

    monkeypatch.setattr(llm, "test_route_connection", test_route)
    monkeypatch.setattr(
        llm,
        "safe_list_models",
        lambda provider, **_kwargs: (model_list_calls.append(provider) or ["live-model"], ""),
    )
    dialog = _new_dialog(monkeypatch)

    def set_route(row: dict, model: str) -> None:
        dialog._fill_credential_combo(row["api_key_combo"], "ollama")
        row["api_key_combo"].setCurrentIndex(row["api_key_combo"].findData("ollama"))
        dialog._fill_model_combo(row, [], "ollama", model)
        assert dialog._model_value(row) == model

    try:
        dialog._tabs.setCurrentIndex(dialog._tab_base_names.index("LLM"))
        app.processEvents()
        for section in ("LLM", "VISION_LLM", "MEMORY_LLM"):
            dialog._model_route_buttons[section].click()
            app.processEvents()
            assert not dialog._model_route_cards[section].isHidden()
            rows = dialog._model_section_rows[section]
            for extra in list(rows)[1:]:
                dialog._remove_model_section_row(section, extra)
            set_route(rows[0], f"{section.lower()}-primary")

            dialog._model_route_add_buttons[section].click()
            fallback = rows[-1]
            set_route(fallback, f"{section.lower()}-fallback")
            dialog._model_route_rows_containers[section].rowDropped.emit(
                fallback["widget"], 0
            )
            assert rows[0] is fallback
            assert rows[0]["priority_lbl"].text() == "<b>1</b>"

            old_primary = rows[1]
            remove = next(
                button
                for button in old_primary["widget"].findChildren(QPushButton)
                if button.text() == "✕"
            )
            remove.click()
            assert rows == [fallback]

        llm_rows = dialog._model_section_rows["LLM"]
        set_route(llm_rows[0], "shared-primary")
        dialog._model_route_add_buttons["LLM"].click()
        set_route(llm_rows[-1], "shared-fallback")
        apply_all = next(
            button
            for button in dialog._model_route_cards["LLM"].findChildren(QPushButton)
            if button.text() == "Apply to all"
        )
        apply_all.click()
        for section in ("LLM", "VISION_LLM", "MEMORY_LLM"):
            assert [
                (row["api_key_combo"].currentData(), dialog._model_value(row))
                for row in dialog._model_section_rows[section]
            ] == [("ollama", "shared-primary"), ("ollama", "shared-fallback")]

            refresh = dialog._model_section_rows[section][0]["refresh_btn"]
            refresh.click()
            _wait_until(app, refresh.isEnabled)
            assert refresh.toolTip() == "Live: 1 models"
            assert dialog._model_value(dialog._model_section_rows[section][0]) == "shared-primary"
        assert model_list_calls == ["ollama", "ollama", "ollama"]

        test_specs = (
            ("LLM", "Test Chat model", "LLM", False),
            ("VISION_LLM", "Test Image model", "VISION_LLM", True),
            ("MEMORY_LLM", "Test Memory model", "MEMORY_LLM", False),
        )
        for section, label, route_name, image in test_specs:
            dialog._model_route_buttons[section].click()
            button = next(
                candidate
                for candidate in dialog._model_route_cards[section].findChildren(QPushButton)
                if candidate.text() == label
            )
            before = len(calls)
            button.click()
            _wait_until(app, lambda: not dialog._running_test_tokens)
            assert calls[before:] == [
                ("ollama", "shared-primary", route_name, image),
                ("ollama", "shared-fallback", route_name, image),
            ]
            status = getattr(dialog, f"_{'llm' if section == 'LLM' else 'vision' if section == 'VISION_LLM' else 'memory'}_test_status_lbl")
            assert "✓ Primary" in status.text()
            assert "✓ Fallback 1" in status.text()
    finally:
        _close(dialog, app)
