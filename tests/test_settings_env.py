"""Tests for test settings env."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.settings_profiles import (
    PROFILE_ID_KEY,
    PROFILE_LABEL_KEY,
    activation_write_plan,
    migrate_legacy_profiles,
    read_profile,
    save_profile,
)
from core.system.env_utils import read_env_file, write_env_file
from ui import settings_env


class SettingsEnvTests(unittest.TestCase):
    def test_write_env_removes_secret_keys(self):
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "OPENAI_API_KEY=old\nLLM_MODEL=old-model\n# comment\n",
                encoding="utf-8",
            )
            with patch.object(settings_env, "ENV_PATH", env_path):
                settings_env.write_settings_env(
                    {"LLM_MODEL": "new-model"},
                    remove_keys={"OPENAI_API_KEY"},
                )

            text = env_path.read_text(encoding="utf-8")
            self.assertNotIn("OPENAI_API_KEY", text)
            self.assertIn("LLM_MODEL=new-model", text)
            self.assertIn("# comment", text)


def test_isolated_profiles_switch_without_cross_contamination(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    base = {
        "ACTIVE_PROFILE": "a",
        "OPENAI_API_KEY": "must-stay-shared",
        "START_ON_LOGIN": "True",
        "CONTEXT_DEFAULTS_FIRST_PROMPT_ONLY": "True",
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "model-a",
        "THEME_MODE": "dark",
    }
    write_env_file(env_path, base)
    save_profile(env_path, "a", "A", {**base, "LLM_MODEL": "model-a"})
    save_profile(env_path, "b", "B", {**base, "LLM_MODEL": "model-b", "THEME_MODE": "light"})

    profile_b = read_profile(env_path, "b")
    writes, removals = activation_write_plan(read_env_file(env_path), "b", profile_b)
    write_env_file(env_path, writes, remove_keys=removals)

    active = read_env_file(env_path)
    assert active["ACTIVE_PROFILE"] == "b"
    assert active["SETTINGS_PROFILE"] == "b"
    assert active["LLM_MODEL"] == "model-b"
    assert active["THEME_MODE"] == "light"
    assert active["OPENAI_API_KEY"] == "must-stay-shared"
    assert active["START_ON_LOGIN"] == "True"
    assert active["CONTEXT_DEFAULTS_FIRST_PROMPT_ONLY"] == "True"
    assert read_profile(env_path, "a")["LLM_MODEL"] == "model-a"
    assert "CONTEXT_DEFAULTS_FIRST_PROMPT_ONLY" not in read_profile(env_path, "a")


def test_legacy_rows_and_low_setup_are_copied_to_complete_profile_files(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    legacy = {
        "PROFILE_COUNT": "1",
        "PROFILE_1_ID": "a",
        "PROFILE_1_LABEL": "A",
        "PROFILE_1_LLM_PROVIDER": "chatgpt",
        "PROFILE_1_LLM_MODEL": "gpt-5.5",
        "ACTIVE_PROFILE": "default",
        "SETTINGS_PROFILE": "default",
        "OPENWAND_SETTINGS_PRESET": "low_setup",
        "OPENWAND_PRESET_LOW_SETUP_LLM_PROVIDER": "ollama",
        "OPENWAND_PRESET_LOW_SETUP_LLM_MODEL": "corrupted-preset-model",
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "working-copy-model",
        "THEME_MODE": "dark",
    }
    write_env_file(env_path, legacy)

    migrated = migrate_legacy_profiles(
        env_path,
        legacy,
        builtin_profiles={
            "low_setup": (
                "Low setup",
                {"LLM_PROVIDER": "chatgpt", "LLM_MODEL": "gpt-5.5"},
            )
        },
    )

    assert [(profile.profile_id, profile.label) for profile in migrated] == [
        ("a", "A"),
        ("low_setup", "Low setup"),
    ]
    assert read_profile(env_path, "a") == {
        "LLM_MODEL": "gpt-5.5",
        "LLM_PROVIDER": "chatgpt",
        "THEME_MODE": "dark",
    }
    low_setup = read_profile(env_path, "low_setup")
    assert low_setup["LLM_PROVIDER"] == "chatgpt"
    assert low_setup["LLM_MODEL"] == "gpt-5.5"
    assert low_setup["THEME_MODE"] == "dark"
    assert "OPENWAND_SETTINGS_PRESET" not in low_setup
    assert not any(key.startswith("OPENWAND_PRESET_") for key in low_setup)

    # Migration is idempotent and never rewrites an already isolated profile.
    save_profile(env_path, "a", "A", {"LLM_MODEL": "user-edited-a"})
    migrate_legacy_profiles(
        env_path,
        legacy,
        builtin_profiles={"low_setup": ("Low setup", {"LLM_MODEL": "gpt-5.5"})},
    )
    assert read_profile(env_path, "a")["LLM_MODEL"] == "user-edited-a"


def test_profile_files_never_store_credentials_or_registry_metadata(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    record = save_profile(
        env_path,
        "Research Team",
        "Research Team",
        {
            "ACTIVE_PROFILE": "old",
            "PROFILE_COUNT": "9",
            "ANTHROPIC_API_KEY": "secret",
            "OPENWAND_CONNECTION_ALIAS_ANTHROPIC": "Work key",
            "LLM_MODEL": "claude-test",
        },
    )

    raw = read_env_file(record.path)
    assert raw == {
        PROFILE_ID_KEY: "research-team",
        PROFILE_LABEL_KEY: "Research Team",
        "LLM_MODEL": "claude-test",
    }


if __name__ == "__main__":
    unittest.main()
