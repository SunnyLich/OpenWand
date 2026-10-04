"""Shared helpers for reading and writing environment-style config."""
from __future__ import annotations

import base64
import json
import os
import re
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values
from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

# Tri-state screenshot context modes (per caller hotkey):
#   "off"   — never capture
#   "auto"  — always capture at hotkey time and attach it to the query
#   "model" — expose the capture_screen tool so the model grabs one on demand
SCREENSHOT_MODES = ("off", "auto", "model")
FILE_ACCESS_MODES = ("off", "read", "ask", "auto")
LITERAL_TEXT_KEYS = {
    "SYSTEM_PROMPT_UTILITY",
    "OPENWAND_CODEX_SYSTEM_PROMPT",
    "OPENWAND_CLAUDE_SYSTEM_PROMPT",
    "CHAT_ELABORATE_PROMPT",
    "LIVE_VOICE_SYSTEM_PROMPT",
    "GPT_SOVITS_PROMPT_TEXT",
}
_CALLER_PROMPT_KEY = re.compile(r"^CALLER_\d+_INTENT_\d+_PROMPT$")
_LITERAL_PREFIX = "openwand-json-b64:"


def is_literal_text_key(name: str) -> bool:
    """Identify user-authored text that must not use .env interpolation."""
    return name in LITERAL_TEXT_KEYS or _CALLER_PROMPT_KEY.fullmatch(name) is not None


def _decode_literal_value(value: str) -> str:
    """Decode values written by the literal prompt serializer; accept legacy text."""
    if not value.startswith(_LITERAL_PREFIX):
        return value
    try:
        payload = base64.b64decode(value[len(_LITERAL_PREFIX):], altchars=b"-_", validate=True)
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError):
        return value
    return decoded if isinstance(decoded, str) else value


def normalize_screenshot_mode(value, default: str = "off") -> str:
    """Map a raw value (incl. legacy booleans) to "off" | "auto" | "model"."""
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in {"auto", "on", "true", "1", "yes", "always"}:
        return "auto"
    if v in {"model", "decide", "ask", "tool", "tools"}:
        return "model"
    if v in {"off", "false", "0", "no", "none", ""}:
        return "off"
    return default


def env_screenshot_mode(name: str, default: str = "off") -> str:
    """Handle env screenshot mode for system env utils."""
    return normalize_screenshot_mode(os.getenv(name), default)


def normalize_file_access_mode(value, default: str = "off") -> str:
    """Map a raw value to off/read/ask/auto local-file access."""
    v = str(value if value is not None else default).strip().lower()
    aliases = {
        "none": "off",
        "never": "off",
        "disabled": "off",
        "readonly": "read",
        "read-only": "read",
        "read_only": "read",
        "on": "ask",
        "true": "ask",
        "yes": "ask",
        "model": "ask",
        "write": "ask",
        "always": "auto",
    }
    v = aliases.get(v, v)
    return v if v in FILE_ACCESS_MODES else default


def env_file_access_mode(name: str, default: str = "off") -> str:
    """Read a per-caller local-file access mode from the environment."""
    return normalize_file_access_mode(os.getenv(name), default)


# Per-caller tool override modes:
#   "on"    — tool is offered to the model for this caller
#   "model" — legacy spelling for "on"; kept for old settings files
#   "off"   — never offered
# Context-fetch tools are governed by context controls, not this mapping.
# Tools absent from the mapping follow their default (enabled for addon tools,
# Local files dropdown for file tools).
TOOL_OVERRIDE_MODES = ("on", "model", "off")
MCP_SERVER_OVERRIDE_PREFIX = "mcp_server."
PUBLIC_WEB_TOOL_NAMES = ("web_search", "retrieve_website")
CONTEXT_GOVERNED_TOOL_NAMES = {
    "background_task_status",
    "delegate_background_task",
    "get_context",
    "get_context.browser",
    "get_context.documents",
    "git_status",
    "git_diff",
    "github_repo",
    "github_issue",
    "memory_search",
    "capture_screen",
}


def safe_mcp_server_id(server_name: str) -> str:
    """Return the stable id used for MCP server-level tool overrides."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(server_name or "").strip())
    return cleaned or "server"


def mcp_server_override_key(server_name: str) -> str:
    """Return the synthetic override key for one MCP server group."""
    return f"{MCP_SERVER_OVERRIDE_PREFIX}{safe_mcp_server_id(server_name)}"


def is_mcp_server_override_key(name: str) -> bool:
    """Return True when an override name targets an MCP server group."""
    return str(name or "").startswith(MCP_SERVER_OVERRIDE_PREFIX)


def mcp_server_id_from_tool(name: str, description: str = "") -> str | None:
    """Infer the MCP server id for a bridge-exposed tool.

    The bridge descriptions start with ``[MCP:<server>]``. The fallback handles
    older payloads that only preserved the generated ``mcp_<server>_<tool>``
    name; it is intentionally best-effort because underscores make that form
    ambiguous.
    """
    match = re.match(r"^\[MCP:([^\]]+)\]", str(description or "").strip())
    if match:
        return safe_mcp_server_id(match.group(1))
    text = str(name or "")
    if not text.startswith("mcp_"):
        return None
    parts = text.split("_", 2)
    if len(parts) >= 3 and parts[1]:
        return safe_mcp_server_id(parts[1])
    return None


def parse_tool_modes(value: str | None) -> dict[str, str]:
    """Parse a tool override list like "web_search:on,my_tool:model"."""
    modes: dict[str, str] = {}
    for entry in (value or "").split(","):
        name, _, mode = entry.strip().partition(":")
        name = name.strip()
        mode = mode.strip().lower()
        if name and name not in CONTEXT_GOVERNED_TOOL_NAMES and mode in TOOL_OVERRIDE_MODES:
            modes[name] = mode
    return modes


def format_tool_modes(modes: dict[str, str]) -> str:
    """Inverse of parse_tool_modes; drops entries that are not real overrides."""
    return ",".join(
        f"{name}:{str(mode).strip().lower()}"
        for name, mode in sorted(modes.items())
        if str(mode).strip().lower() in TOOL_OVERRIDE_MODES
        and str(name).strip() not in CONTEXT_GOVERNED_TOOL_NAMES
    )


def env_bool(name: str, default: bool = False) -> bool:
    """Handle env bool for system env utils."""
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def env_int(name: str, default: int) -> int:
    """Handle env int for system env utils."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Handle env float for system env utils."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def read_env_file(path: Path) -> dict[str, str]:
    """Read env file."""
    if not path.exists():
        return {}
    try:
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError):
        return {}
    return {
        key: value
        for key, value in _resolve_env_variables(values).items()
        if key is not None and value is not None
    }


def literal_env_values(path: Path) -> dict[str, str]:
    """Read prompt fields without environment-variable expansion."""
    if not path.exists():
        return {}
    try:
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError):
        return {}
    return {
        key: _decode_literal_value(value)
        for key, value in values.items()
        if key is not None and value is not None and is_literal_text_key(key)
    }


def _resolve_env_variables(values: dict[str, str | None]) -> dict[str, str | None]:
    """Expand ``${VAR}`` references the way python-dotenv's interpolation does.

    dotenv's own implementation copies the whole of ``os.environ`` into a fresh
    dict for every single entry, making the cost of reading a file quadratic in
    its size for no benefit (~4x slower on OpenWand's own settings file). Semantics
    are unchanged -- later entries still shadow the process environment, and only
    values that actually contain a reference pay for a lookup table.
    """
    base = dict(os.environ)
    resolved: dict[str, str | None] = {}
    for name, value in values.items():
        if value is not None and is_literal_text_key(name):
            value = _decode_literal_value(value)
        elif value is not None and "${" in value:
            env: dict[str, str | None] = {**base, **resolved}
            value = "".join(atom.resolve(env) for atom in parse_variables(value))
        resolved[name] = value
    return resolved


def format_env_value(value: str, *, literal: bool = False) -> str:
    """Format env value."""
    if literal:
        # Encode serialized text as .env-safe ASCII. dotenv's quoted-string
        # parser does not decode every JSON escape (for example, \u0000).
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        return _LITERAL_PREFIX + base64.urlsafe_b64encode(payload).decode("ascii")
    if any(ch in value for ch in ("\n", "\r", '"', "#")):
        escaped = (
            value.replace("\\", "\\\\")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "\\n")
            .replace('"', '\\"')
        )
        return f'"{escaped}"'
    return value


def write_env_file(
    path: Path,
    values: dict[str, str],
    remove_keys: set[str] | None = None,
) -> None:
    """Write env file."""
    remove_keys = remove_keys or set()
    chunks: list[str] = []
    written: set[str] = set()
    newline = "\n"

    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as env_file:
            source = env_file.read()
        first_newline = re.search(r"\r\n|\n|\r", source)
        if first_newline:
            newline = first_newline.group(0)
        for binding in parse_stream(StringIO(source)):
            key = binding.key
            original = binding.original.string
            if key not in remove_keys and key not in values:
                chunks.append(original)
                continue

            # The parser includes all physical lines of a quoted value in one
            # binding, so replacing it cannot leave apparent settings behind.
            prefix = re.match(r"\s*(?:export[^\S\r\n]+)?", original).group(0)
            if key in remove_keys:
                last_newline = max(prefix.rfind("\n"), prefix.rfind("\r"))
                chunks.append(prefix[: last_newline + 1])
                continue
            ending = re.search(r"(?:\r\n|\n|\r)$", original)
            chunks.append(
                f"{prefix}{key}={format_env_value(values[key], literal=is_literal_text_key(key))}"
                f"{ending.group(0) if ending else ''}"
            )
            written.add(key)

    for key, value in values.items():
        if key not in written:
            if chunks and not chunks[-1].endswith(("\r", "\n")):
                chunks.append(newline)
            chunks.append(f"{key}={format_env_value(value, literal=is_literal_text_key(key))}{newline}")

    result = "".join(chunks)
    if not result.endswith(("\r", "\n")):
        result += newline
    with path.open("w", encoding="utf-8", newline="") as env_file:
        env_file.write(result)
