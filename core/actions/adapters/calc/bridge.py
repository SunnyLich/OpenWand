"""Provision LibreOffice's persistent Wisp UNO connection."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

_CONNECTION_ITEM_RE = re.compile(
    r'<item\s+oor:path="/org\.openoffice\.Setup/Office">\s*'
    r'<prop\s+oor:name="ooSetupConnectionURL"[^>]*>\s*<value>.*?</value>\s*'
    r"</prop>\s*</item>",
    flags=re.DOTALL,
)
_PIPE_RE = re.compile(r"pipe,name=(wisp_calc_[A-Za-z0-9_-]{16,80});urp")
_PIPE_NAME_RE = re.compile(r"^wisp_calc_[A-Za-z0-9_-]{16,80}$")
_EMPTY_REGISTRY = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
</oor:items>
"""


def libreoffice_user_profile() -> Path:
    """Return the current user's normal LibreOffice profile directory."""
    override = str(os.environ.get("WISP_LIBREOFFICE_USER_PROFILE") or "").strip()
    if override:
        return Path(override).expanduser()
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if not appdata:
        raise RuntimeError("The Windows application-data directory is unavailable.")
    return Path(appdata) / "LibreOffice" / "4" / "user"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def calc_connection_endpoint(pipe_name: str) -> str:
    """Build the user-local named-pipe endpoint stored in LibreOffice's profile."""
    normalized = str(pipe_name or "").strip()
    if not _PIPE_NAME_RE.fullmatch(normalized):
        raise ValueError("The Calc connection pipe name is invalid.")
    return f"pipe,name={normalized};urp;StarOffice.ComponentContext"


def configure_calc_connection(
    pipe_name: str = "",
    profile: Path | None = None,
) -> dict[str, str | int | bool]:
    """Persist Wisp's endpoint without replacing unrelated LibreOffice settings."""
    profile_path = Path(profile) if profile is not None else libreoffice_user_profile()
    registry_path = profile_path / "registrymodifications.xcu"
    content = (
        registry_path.read_text(encoding="utf-8")
        if registry_path.is_file()
        else _EMPTY_REGISTRY
    )
    existing = _PIPE_RE.search(content)
    normalized_pipe = str(pipe_name or "").strip()
    if not normalized_pipe:
        normalized_pipe = existing.group(1) if existing else f"wisp_calc_{secrets.token_hex(16)}"
    endpoint = calc_connection_endpoint(normalized_pipe)
    item = (
        '<item oor:path="/org.openoffice.Setup/Office">'
        '<prop oor:name="ooSetupConnectionURL" oor:op="fuse">'
        f"<value>{escape(endpoint)}</value>"
        "</prop></item>"
    )
    if _CONNECTION_ITEM_RE.search(content):
        updated = _CONNECTION_ITEM_RE.sub(item, content, count=1)
    else:
        closing = "</oor:items>"
        if closing not in content:
            raise RuntimeError("LibreOffice's user registry is malformed.")
        updated = content.replace(closing, f"{item}\n{closing}", 1)
    _atomic_write(registry_path, updated)
    return {
        "configured": True,
        "changed": updated != content,
        "pipe_name": normalized_pipe,
        "endpoint": endpoint,
        "registry_path": str(registry_path),
    }


def configured_calc_connection_pipe(profile: Path | None = None) -> str:
    """Read Wisp's configured user-local endpoint, or an empty string when absent."""
    profile_path = Path(profile) if profile is not None else libreoffice_user_profile()
    registry_path = profile_path / "registrymodifications.xcu"
    if not registry_path.is_file():
        return ""
    match = _PIPE_RE.search(registry_path.read_text(encoding="utf-8"))
    return match.group(1) if match else ""
