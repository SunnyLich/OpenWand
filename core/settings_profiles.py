"""Isolated, file-backed Settings profiles.

The legacy Settings UI stores custom profiles as ``PROFILE_N_*`` keys inside
the main ``.env`` while built-in presets use a separate override namespace.
This module provides one coherent storage model without coupling it to Qt:

* one complete ``.env``-style file per profile;
* credentials and process-wide bootstrap values stay shared;
* the selected profile is mirrored into the main ``.env`` as the runtime
  working copy, so existing config consumers do not need profile awareness;
* legacy profile rows can be copied into files without deleting their source.

All helpers are pure or path-scoped, which makes migration and switching safe
to prove against temporary directories before Settings uses them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.system.env_utils import read_env_file, write_env_file

PROFILE_DIRECTORY_NAME = "settings_profiles"
PROFILE_FILE_SUFFIX = ".env"
PROFILE_ID_KEY = "OPENWAND_PROFILE_ID"
PROFILE_LABEL_KEY = "OPENWAND_PROFILE_LABEL"

_LEGACY_PRESET_KEY = "OPENWAND_SETTINGS_PRESET"
_LEGACY_PRESET_PREFIX = "OPENWAND_PRESET_"
_PROFILE_META_KEYS = {
    "ACTIVE_PROFILE",
    "SETTINGS_PROFILE",
    "PROFILE_COUNT",
    PROFILE_ID_KEY,
    PROFILE_LABEL_KEY,
}
_SHARED_EXACT_KEYS = {
    "OPENWAND_ONBOARDING_COMPLETE",
    "OPENWAND_ONBOARDING_MODE",
    "START_ON_LOGIN",
    "APP_LANGUAGE",
    "GITHUB_CLIENT_ID",
    "GITHUB_OAUTH_SCOPES",
    "COPILOT_CLI_URL",
    "COPILOT_CLI_PATH",
}
_SHARED_PREFIXES = (
    "PROFILE_",
    "OPENWAND_CONNECTION_ALIAS_",
)


@dataclass(frozen=True)
class SettingsProfile:
    """A discovered profile file and its user-facing identity."""

    profile_id: str
    label: str
    path: Path


def normalize_profile_id(value: str, default: str = "default") -> str:
    """Return the stable, filename-safe id used by profile storage."""
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value or default).strip().lower()).strip("-")
    return text or default


def profiles_directory(env_path: Path) -> Path:
    """Return the profile directory belonging to one main Settings file."""
    return Path(env_path).parent / PROFILE_DIRECTORY_NAME


def profile_path(env_path: Path, profile_id: str) -> Path:
    """Return a contained profile path for ``profile_id``."""
    safe_id = normalize_profile_id(profile_id)
    return profiles_directory(env_path) / f"{safe_id}{PROFILE_FILE_SUFFIX}"


def is_shared_setting(key: str) -> bool:
    """Return whether a key stays outside individual profile files."""
    name = str(key or "").strip()
    return (
        not name
        or name in _PROFILE_META_KEYS
        or name in _SHARED_EXACT_KEYS
        or name == _LEGACY_PRESET_KEY
        or name.startswith(_LEGACY_PRESET_PREFIX)
        or name.endswith("_API_KEY")
        or any(name.startswith(prefix) for prefix in _SHARED_PREFIXES)
    )


def profile_settings(values: dict[str, str]) -> dict[str, str]:
    """Strip shared/legacy metadata from a complete Settings snapshot."""
    return {
        str(key): str(value)
        for key, value in values.items()
        if not is_shared_setting(str(key))
    }


def read_profile(env_path: Path, profile_id: str) -> dict[str, str]:
    """Read one profile's settings without its file metadata."""
    values = read_env_file(profile_path(env_path, profile_id))
    values.pop(PROFILE_ID_KEY, None)
    values.pop(PROFILE_LABEL_KEY, None)
    return values


def save_profile(
    env_path: Path,
    profile_id: str,
    label: str,
    values: dict[str, str],
) -> SettingsProfile:
    """Create or replace one isolated profile file."""
    safe_id = normalize_profile_id(profile_id)
    path = profile_path(env_path, safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_env_file(path)
    stored = {
        PROFILE_ID_KEY: safe_id,
        PROFILE_LABEL_KEY: str(label or safe_id).strip() or safe_id,
        **profile_settings(values),
    }
    write_env_file(path, stored, remove_keys=set(existing) - set(stored))
    return SettingsProfile(safe_id, stored[PROFILE_LABEL_KEY], path)


def list_profiles(env_path: Path) -> list[SettingsProfile]:
    """Return valid profile files sorted by label and id."""
    directory = profiles_directory(env_path)
    if not directory.is_dir():
        return []
    profiles: list[SettingsProfile] = []
    for path in directory.glob(f"*{PROFILE_FILE_SUFFIX}"):
        values = read_env_file(path)
        profile_id = normalize_profile_id(values.get(PROFILE_ID_KEY, path.stem), path.stem)
        if path != profile_path(env_path, profile_id):
            continue
        label = str(values.get(PROFILE_LABEL_KEY) or profile_id).strip() or profile_id
        profiles.append(SettingsProfile(profile_id, label, path))
    return sorted(profiles, key=lambda item: (item.label.casefold(), item.profile_id))


def delete_profile(env_path: Path, profile_id: str) -> bool:
    """Delete one exact profile file, returning whether it existed."""
    path = profile_path(env_path, profile_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def rename_profile(env_path: Path, profile_id: str, label: str) -> SettingsProfile:
    """Change a profile's display label without changing its stable id."""
    return save_profile(env_path, profile_id, label, read_profile(env_path, profile_id))


def activation_write_plan(
    existing_env: dict[str, str],
    profile_id: str,
    values: dict[str, str],
) -> tuple[dict[str, str], set[str]]:
    """Return main-env writes/removals needed to activate a profile.

    The main file remains the compatibility working copy consumed by the
    existing runtime. Legacy profile records are deliberately retained until a
    later cleanup release; preset markers and stale top-level profile settings
    are removed immediately.
    """
    safe_id = normalize_profile_id(profile_id)
    owned = profile_settings(values)
    writes = {
        **owned,
        "ACTIVE_PROFILE": safe_id,
        "SETTINGS_PROFILE": safe_id,
    }
    removals = {
        key
        for key in existing_env
        if (
            (not is_shared_setting(key) and key not in owned)
            or key == _LEGACY_PRESET_KEY
            or key.startswith(_LEGACY_PRESET_PREFIX)
        )
    }
    return writes, removals


def legacy_profile_rows(env: dict[str, str]) -> list[tuple[int, str, str, dict[str, str]]]:
    """Decode legacy ``PROFILE_N_*`` rows without mutating the source."""
    try:
        count = max(0, int(str(env.get("PROFILE_COUNT", "0") or "0")))
    except ValueError:
        count = 0
    rows: list[tuple[int, str, str, dict[str, str]]] = []
    for slot in range(1, count + 1):
        prefix = f"PROFILE_{slot}_"
        profile_id = normalize_profile_id(env.get(f"{prefix}ID", ""), "")
        if not profile_id:
            continue
        label = str(env.get(f"{prefix}LABEL") or profile_id).strip() or profile_id
        scoped = {
            key[len(prefix):]: str(value)
            for key, value in env.items()
            if key.startswith(prefix) and key[len(prefix):] not in {"ID", "LABEL"}
        }
        rows.append((slot, profile_id, label, scoped))
    return rows


def migrate_legacy_profiles(
    env_path: Path,
    env: dict[str, str],
    *,
    builtin_profiles: dict[str, tuple[str, dict[str, str]]] | None = None,
) -> list[SettingsProfile]:
    """Copy legacy profiles and missing built-ins into isolated files.

    Migration is additive and idempotent: it never edits the main file and it
    never overwrites an existing profile file. Each legacy profile starts as a
    complete copy of the current non-shared configuration, with its scoped
    ``PROFILE_N_*`` values layered on top.
    """
    existing_ids = {profile.profile_id for profile in list_profiles(env_path)}
    base = profile_settings(env)
    for _slot, profile_id, label, scoped in legacy_profile_rows(env):
        if profile_id in existing_ids:
            continue
        save_profile(env_path, profile_id, label, {**base, **scoped})
        existing_ids.add(profile_id)
    for profile_id, (label, defaults) in (builtin_profiles or {}).items():
        safe_id = normalize_profile_id(profile_id)
        if safe_id in existing_ids:
            continue
        save_profile(env_path, safe_id, label, {**base, **defaults})
        existing_ids.add(safe_id)
    return list_profiles(env_path)
