"""Keep opt-in acceptance runs away from personal OAuth credential files."""

from __future__ import annotations

import os
from pathlib import Path


def isolated_auth_file(name: str) -> Path | None:
    """Return a credential path only inside a marked, disposable test state."""
    if os.environ.get("OPENWAND_USER_JOURNEYS") != "1":
        return None
    raw = os.environ.get("OPENWAND_E2E_STATE", "")
    state = Path(raw).resolve() if raw else None
    if state is None or not (state / ".user-journey-state").is_file():
        raise RuntimeError("User journeys require marked disposable OAuth state")
    if Path(name).name != name:
        raise ValueError("Acceptance credential names must be plain filenames")
    return state / "auth-cache" / name
