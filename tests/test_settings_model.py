"""Tests for test settings model."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import config
from core.action_files import save_callers
from core.action_files.edit import update_toml_values
from core.settings_model import AppSettings


def _snapshot_config_globals() -> dict[str, object]:
    """Return a shallow snapshot of config globals mutated by config.reload()."""
    snapshot: dict[str, object] = {}
    for name, value in vars(config).items():
        if not name.isupper():
            continue
        if isinstance(value, list):
            snapshot[name] = list(value)
        elif isinstance(value, dict):
            snapshot[name] = dict(value)
        else:
            snapshot[name] = value
    return snapshot


def _restore_config_globals(snapshot: dict[str, object]) -> None:
    """Restore config globals after a reload-based settings test."""
    for name, value in snapshot.items():
        current = getattr(config, name, None)
        if isinstance(current, list) and isinstance(value, list):
            current[:] = value
        elif isinstance(current, dict) and isinstance(value, dict):
            current.clear()
            current.update(value)
        else:
            setattr(config, name, value)


def _write_file_backed_caller(
    root: Path,
    *,
    label: str = "General",
    profile: str = "default",
    context: dict[str, str] | None = None,
    file_access: str = "off",
) -> None:
    """Create the caller source used by config beside an isolated settings file."""
    save_callers(
        root,
        [
            {
                "folder": "general",
                "hotkey": "ctrl+q",
                "enabled": True,
                "label": label,
                "file_access": file_access,
                "context": context or {},
                "actions": [],
            }
        ],
    )
    update_toml_values(root / "general" / "caller.toml", {"profile": profile})


@pytest.mark.usefixtures("isolated_default_profile")
def test_get_settings_returns_typed_snapshot(tmp_path: Path):
    previous_config = _snapshot_config_globals()
    env_path = tmp_path / ".env"
    _write_file_backed_caller(tmp_path / "callers", label="Typed")
    try:
        with patch.object(config, "_ENV_FILE", env_path), patch.object(
            config, "_reload_dotenv", lambda: None
        ), patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "anthropic",
                "LLM_MODEL": "claude-test",
                "CALLER_COUNT": "1",
                "CALLER_1_LABEL": "Typed",
                "VOICE_CONTEXT_MEMORY_MODE": "model",
                "BUBBLE_WIDTH": "420",
                "BUBBLE_FONT_SIZE": "14",
                "BUBBLE_SCROLL_ENABLED": "false",
                "BUBBLE_SCROLL_SNAP_DELAY_MS": "1800",
                "PRIVACY_MODE": "builtin",
                "TRUST_PRIVACY_MODE": "true",
                "START_ON_LOGIN": "true",
            },
            clear=False,
        ):
            config.reload()

        settings = config.get_settings()

        assert isinstance(settings, AppSettings)
        assert settings.llm.provider == "anthropic"
        assert settings.llm.model == "claude-test"
        assert settings.ui.bubble_width == 420
        assert settings.ui.bubble_font_size == 14
        assert settings.ui.bubble_scroll_enabled is False
        assert settings.ui.bubble_scroll_snap_delay_ms == 1800
        assert settings.ui.start_on_login is True
        assert settings.privacy.mode == "builtin"
        assert settings.privacy.trust_privacy_mode is True
        assert settings.privacy.prompt_injection_protection is True
        assert settings.privacy.prompt_injection_warn is True
        assert settings.callers.callers[0]["label"] == "Typed"
        assert settings.callers.voice["context_memory_mode"] == "model"
    finally:
        _restore_config_globals(previous_config)


def test_audio_settings_include_live_voice_fields():
    """Verify AudioSettings maps the LIVE_VOICE_* config globals."""
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "LIVE_VOICE_PROVIDER": "google",
                "LIVE_VOICE_MODEL": "gemini-test-live",
                "LIVE_VOICE_VOICE_NAME": "Kore",
                "LIVE_VOICE_HALF_DUPLEX": "true",
            },
            clear=False,
        ):
            config.reload()

        audio = config.get_settings().audio
        assert audio.live_voice_provider == "google"
        assert audio.live_voice_model == "gemini-test-live"
        assert audio.live_voice_voice == "Kore"
        assert audio.live_voice_half_duplex is True
    finally:
        _restore_config_globals(previous_config)


def test_active_profile_overrides_model_and_budgets():
    """Verify active profile owns model choices and budget settings."""
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "base-model",
                "PROFILE_COUNT": "1",
                "PROFILE_1_ID": "deep-work",
                "PROFILE_1_LABEL": "Deep Work",
                "PROFILE_1_LLM_PROVIDER": "anthropic",
                "PROFILE_1_LLM_MODEL": "claude-profile",
                "PROFILE_1_CONTEXT_BROWSER_MAX_CHARS": "22222",
                "PROFILE_1_CONTEXT_TOOL_DOCUMENT_MAX_CHARS": "77777",
                "PROFILE_1_TOOL_TURN_MAX_CALLS": "6",
                "PROFILE_1_TOOL_TURN_MAX_RESULT_CHARS": "33333",
                "PROFILE_1_TOOL_TURN_MAX_TOTAL_CHARS": "99999",
                "PROFILE_1_CONTEXT_BROWSER_MODE": "model",
                "CALLER_COUNT": "1",
                "SETTINGS_PROFILE": "deep-work",
            },
            clear=True,
        ):
            config.reload()

        settings = config.get_settings()

        assert config.ACTIVE_PROFILE == "deep-work"
        assert config.LLM_PROVIDER == "anthropic"
        assert config.LLM_MODEL == "claude-profile"
        assert config.CONTEXT_BROWSER_MAX_CHARS == 22222
        assert config.CONTEXT_TOOL_DOCUMENT_MAX_CHARS == 77777
        assert config.TOOL_TURN_MAX_CALLS == 6
        assert settings.active_profile == "deep-work"
        assert settings.llm.provider == "anthropic"
        assert settings.tool_turn.max_total_chars == 99999
    finally:
        _restore_config_globals(previous_config)


def test_file_backed_caller_can_select_profile_without_changing_active_profile(tmp_path: Path):
    """Caller profile and context now come from caller.toml, not legacy env keys."""
    previous_config = _snapshot_config_globals()
    env_path = tmp_path / ".env"
    _write_file_backed_caller(
        tmp_path / "callers",
        profile="coding-lite",
        file_access="read",
        context={"ambient": "model", "browser": "model", "memory": "off", "files": "on"},
    )
    try:
        with patch.object(config, "_ENV_FILE", env_path), patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "PROFILE_COUNT": "1",
                "PROFILE_1_ID": "coding-lite",
                "PROFILE_1_LABEL": "Coding Lite",
                "PROFILE_1_CONTEXT_DOCUMENTS_MODE": "model",
                "PROFILE_1_CONTEXT_BROWSER_MODE": "model",
                "PROFILE_1_CONTEXT_MEMORY_MODE": "off",
                "PROFILE_1_FILE_ACCESS": "read",
                "CALLER_COUNT": "1",
                "CALLER_1_PROFILE": "coding-lite",
            },
            clear=True,
        ):
            config.reload()

        row = config.CALLER_ROWS[0]

        assert config.ACTIVE_PROFILE == "default"
        assert row["profile"] == "coding-lite"
        assert row["context_documents_mode"] == "model"
        assert row["context_browser_mode"] == "model"
        assert row["context_memory_mode"] == "off"
        assert row["file_access"] == "read"
    finally:
        _restore_config_globals(previous_config)


def test_default_profile_preserves_legacy_second_caller_defaults():
    """Verify reloading the default profile preserves file-backed callers."""
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(os.environ, {}, clear=True):
            config.reload()

        default_profile = config.resolve_profile("default")

        assert config.ACTIVE_PROFILE == "default"
        assert default_profile.caller_defaults["context_documents_mode"] == "off"
        for index, previous_row in enumerate(previous_config["CALLER_ROWS"]):
            row = config.CALLER_ROWS[index]
            for key in (
                "context_ambient",
                "context_documents_mode",
                "context_memory_mode",
            ):
                assert row[key] == previous_row[key]
    finally:
        _restore_config_globals(previous_config)


def test_trust_privacy_mode_can_be_disabled():
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "TRUST_PRIVACY_MODE": "false",
            },
            clear=True,
        ):
            config.reload()

        assert config.TRUST_PRIVACY_MODE is False
        assert config.PRIVACY_MODE == "off"
        assert config.get_settings().privacy.trust_privacy_mode is False
    finally:
        _restore_config_globals(previous_config)


def test_trust_privacy_mode_defaults_on():
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(os.environ, {}, clear=True):
            config.reload()

        assert config.TRUST_PRIVACY_MODE is True
        assert config.PRIVACY_MODE == "builtin"
        assert config.get_settings().privacy.trust_privacy_mode is True
        assert config.get_settings().privacy.hide_secrets is True
        assert config.get_settings().privacy.hide_contact_details is True
    finally:
        _restore_config_globals(previous_config)


def test_explicit_privacy_mode_derives_legacy_compatibility_flags():
    """The new selector should be authoritative while old readers keep working."""
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "PRIVACY_MODE": "advanced",
                "TRUST_PRIVACY_MODE": "false",
                "PRIVACY_AI_ENABLED": "false",
            },
            clear=True,
        ):
            config.reload()

        assert config.PRIVACY_MODE == "advanced"
        assert config.TRUST_PRIVACY_MODE is True
        assert config.PRIVACY_AI_ENABLED is True
        assert config.get_settings().privacy.mode == "advanced"
    finally:
        _restore_config_globals(previous_config)


def test_privacy_category_settings_are_independently_configurable():
    previous_config = _snapshot_config_globals()
    try:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {
                "PRIVACY_HIDE_SECRETS": "false",
                "PRIVACY_HIDE_CONTACT_DETAILS": "true",
                "PRIVACY_HIDE_FINANCIAL_DETAILS": "false",
                "PRIVACY_HIDE_GOVERNMENT_IDS": "true",
                "PRIVACY_HIDE_URLS": "false",
            },
            clear=True,
        ):
            config.reload()

        privacy = config.get_settings().privacy
        assert privacy.hide_secrets is False
        assert privacy.hide_contact_details is True
        assert privacy.hide_financial_details is False
        assert privacy.hide_government_ids is True
        assert privacy.hide_urls is False
    finally:
        _restore_config_globals(previous_config)
