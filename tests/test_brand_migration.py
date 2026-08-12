from __future__ import annotations

from core.system import brand_migration


def test_process_environment_migrates_wisp_namespace_and_values():
    env = {
        "WISP_CODEX_MODEL": "legacy-model",
        "OPENWAND_CODEX_MODEL": "new-model",
        "WISP_USER_DATA_DIR": "/legacy/data",
        "CHAT_EXECUTION_MODE": "wisp",
        "CHAT_CONVERSATION_OWNER": "agent",
    }

    migrated = brand_migration.migrate_process_environment(env)

    assert env["OPENWAND_CODEX_MODEL"] == "new-model"
    assert env["OPENWAND_USER_DATA_DIR"] == "/legacy/data"
    assert not any(key.startswith("WISP_") for key in env)
    assert env["CHAT_EXECUTION_MODE"] == "openwand"
    assert env["CHAT_CONVERSATION_OWNER"] == "agent"
    assert migrated == {
        "OPENWAND_USER_DATA_DIR": "/legacy/data",
        "CHAT_EXECUTION_MODE": "openwand",
    }


def test_env_file_migration_renames_keys_without_overwriting_openwand_values(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# Keep comments and unrelated settings.\n"
        "WISP_CODEX_MODEL=legacy-model\n"
        "OPENWAND_CODEX_MODEL=new-model\n"
        "WISP_PROFILE_ID=local\n"
        "CHAT_EXECUTION_MODE=wisp\n"
        'CHAT_CONVERSATION_OWNER="wisp"\n'
        "APP_LANGUAGE=en\n",
        encoding="utf-8",
    )

    assert brand_migration.migrate_env_file(env_path) is True
    assert env_path.read_text(encoding="utf-8") == (
        "# Keep comments and unrelated settings.\n"
        "OPENWAND_CODEX_MODEL=new-model\n"
        "OPENWAND_PROFILE_ID=local\n"
        "CHAT_EXECUTION_MODE=openwand\n"
        'CHAT_CONVERSATION_OWNER="openwand"\n'
        "APP_LANGUAGE=en\n"
    )
    assert brand_migration.migrate_env_file(env_path) is False


def test_settings_migration_includes_file_backed_profiles(tmp_path):
    env_path = tmp_path / ".env"
    profile_path = tmp_path / "settings_profiles" / "local.env"
    profile_path.parent.mkdir()
    env_path.write_text("WISP_ONBOARDING_COMPLETE=True\n", encoding="utf-8")
    profile_path.write_text("WISP_PROFILE_ID=local\n", encoding="utf-8")

    changed = brand_migration.migrate_settings_files(env_path)

    assert changed == [env_path, profile_path]
    assert env_path.read_text(encoding="utf-8") == "OPENWAND_ONBOARDING_COMPLETE=True\n"
    assert profile_path.read_text(encoding="utf-8") == "OPENWAND_PROFILE_ID=local\n"


def test_directory_migration_merges_missing_data_and_preserves_conflicts(tmp_path):
    legacy = tmp_path / "Wisp"
    current = tmp_path / "OpenWand"
    (legacy / "nested").mkdir(parents=True)
    (current / "nested").mkdir(parents=True)
    (legacy / "nested" / "history.json").write_text("legacy-history", encoding="utf-8")
    (legacy / "settings.env").write_text("legacy-settings", encoding="utf-8")
    (current / "settings.env").write_text("new-settings", encoding="utf-8")

    assert brand_migration.migrate_directory(legacy, current) is True
    assert (current / "nested" / "history.json").read_text(encoding="utf-8") == "legacy-history"
    assert (current / "settings.env").read_text(encoding="utf-8") == "new-settings"
    assert (legacy / "settings.env").read_text(encoding="utf-8") == "legacy-settings"
