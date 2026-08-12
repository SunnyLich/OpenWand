"""One-time compatibility migration from Wisp to OpenWand namespaces."""
from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

LEGACY_APP_NAME = "Wisp"
APP_NAME = "OpenWand"
LEGACY_ENV_PREFIX = "WISP_"
ENV_PREFIX = "OPENWAND_"

_BRANDED_VALUE_KEYS = {
    "CHAT_CONVERSATION_OWNER",
    "CHAT_EXECUTION_MODE",
}
_ENV_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<separator>\s*=)(?P<value>.*?)(?P<newline>\r?\n)?$"
)


def _openwand_value(key: str, value: str) -> str:
    """Translate the two persisted enum values that used the old brand."""
    if key in _BRANDED_VALUE_KEYS and str(value).strip().lower() == "wisp":
        return "openwand"
    return value


def migrate_process_environment(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Expose legacy ``WISP_*`` process values through ``OPENWAND_*`` names.

    Explicit OpenWand values always win. The returned mapping contains only
    values copied or translated by this call, which keeps the operation easy to
    audit and idempotent.
    """
    target = os.environ if environ is None else environ
    migrated: dict[str, str] = {}
    for key, value in list(target.items()):
        if not key.startswith(LEGACY_ENV_PREFIX):
            continue
        new_key = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX) :]
        if new_key not in target:
            target[new_key] = value
            migrated[new_key] = value
        target.pop(key, None)

    for key in _BRANDED_VALUE_KEYS:
        value = target.get(key)
        if value is None:
            continue
        translated = _openwand_value(key, value)
        if translated != value:
            target[key] = translated
            migrated[key] = translated
    return migrated


def _translated_env_line(
    line: str,
    *,
    existing_keys: set[str],
) -> tuple[str | None, str | None]:
    """Return a migrated env line and the key it defines, if any."""
    match = _ENV_ASSIGNMENT.match(line)
    if not match:
        return line, None
    key = match.group("key")
    new_key = key
    if key.startswith(LEGACY_ENV_PREFIX):
        new_key = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX) :]
        if new_key in existing_keys:
            return None, None

    raw_value = match.group("value")
    stripped = raw_value.strip()
    quote = stripped[:1] if stripped[:1] in {'"', "'"} and stripped[-1:] == stripped[:1] else ""
    semantic_value = stripped[1:-1] if quote else stripped
    translated = _openwand_value(new_key, semantic_value)
    if translated != semantic_value:
        leading = raw_value[: len(raw_value) - len(raw_value.lstrip())]
        trailing = raw_value[len(raw_value.rstrip()) :]
        raw_value = f"{leading}{quote}{translated}{quote}{trailing}"

    return (
        f"{match.group('indent')}{new_key}{match.group('separator')}"
        f"{raw_value}{match.group('newline') or ''}",
        new_key,
    )


def migrate_env_file(path: Path) -> bool:
    """Rename legacy keys and branded enum values in one ``.env`` file."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        original = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False

    lines = original.splitlines(keepends=True)
    existing_keys = {
        match.group("key")
        for line in lines
        if (match := _ENV_ASSIGNMENT.match(line)) is not None
    }
    migrated_lines: list[str] = []
    for line in lines:
        translated, new_key = _translated_env_line(line, existing_keys=existing_keys)
        if translated is None:
            continue
        migrated_lines.append(translated)
        if new_key:
            existing_keys.add(new_key)
    migrated = "".join(migrated_lines)
    if migrated == original:
        return False

    try:
        temporary = path.with_name(f".{path.name}.openwand-migration.tmp")
        temporary.write_text(migrated, encoding="utf-8", newline="")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def migrate_settings_files(env_path: Path) -> list[Path]:
    """Migrate the main settings file and every file-backed profile."""
    env_path = Path(env_path)
    candidates = [env_path]
    profile_dir = env_path.parent / "settings_profiles"
    if profile_dir.is_dir():
        candidates.extend(sorted(profile_dir.glob("*.env")))
    return [path for path in candidates if migrate_env_file(path)]


def migrate_directory(source: Path, destination: Path) -> bool:
    """Move legacy app data into the OpenWand directory without overwriting.

    A whole-directory rename is used when possible. If an OpenWand directory
    already exists, missing descendants are moved into it while conflicts stay
    in the legacy directory for manual recovery.
    """
    source = Path(source)
    destination = Path(destination)
    if source == destination or not source.is_dir():
        return False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            source.replace(destination)
            return True
        if not destination.is_dir():
            return False
    except OSError:
        return False

    moved = False
    try:
        for child in list(source.iterdir()):
            target = destination / child.name
            if not target.exists():
                child.replace(target)
                moved = True
            elif child.is_dir() and target.is_dir():
                moved = migrate_directory(child, target) or moved
        try:
            source.rmdir()
        except OSError:
            pass
    except OSError:
        return moved
    return moved
