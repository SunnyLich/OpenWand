"""Isolated process entry point for one selected action script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"openwand_action_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("OpenWand could not load this action script.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    """Read one JSON request, run the script, and emit one JSON response."""
    try:
        path = Path(sys.argv[1]).resolve()
        payload = json.loads(sys.stdin.read() or "{}")
        module = _load(path)
        run = getattr(module, "run", None)
        if not callable(run):
            raise RuntimeError(f"{path.name} needs a run(payload) function.")
        value = run(payload)
        result = dict(value) if isinstance(value, dict) else {"output": "" if value is None else str(value)}
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 - failure must cross the process boundary
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
