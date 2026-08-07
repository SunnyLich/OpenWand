"""Out-of-process execution for selected action scripts."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.action_files.contracts import Access, ActionFile


@dataclass(frozen=True)
class ActionScriptResult:
    """Validated response returned by an isolated action script."""

    output: str = ""
    prompt: str = ""
    paste_back: bool | None = None


def action_from_dict(value: dict[str, Any]) -> ActionFile:
    """Rebuild a trusted action received through the existing UI wire shape."""
    access: list[Access] = []
    for raw in value.get("access") or []:
        try:
            access.append(Access(str(raw).strip().casefold()))
        except ValueError:
            continue
    paste_back = value.get("paste_back")
    return ActionFile(
        path=str(value.get("path") or ""),
        name=str(value.get("name") or ""),
        label=str(value.get("label") or ""),
        hint=str(value.get("hint") or ""),
        prompt=str(value.get("prompt") or ""),
        context=tuple(str(item) for item in value.get("context") or []),
        paste_back=paste_back if isinstance(paste_back, bool) else None,
        run_script_first=bool(value.get("run_script_first")),
        access=tuple(access),
        capability=str(value.get("capability") or ""),
        planner=str(value.get("planner") or ""),
        has_code=bool(value.get("has_code")),
        script_path=str(value.get("script_path") or ""),
        template=str(value.get("template") or ""),
        enabled=bool(value.get("enabled", True)),
        available=bool(value.get("available", True)),
        unavailable_reason=str(value.get("unavailable_reason") or ""),
    )


def run_action_script(
    action: ActionFile,
    *,
    context: dict[str, Any],
    prompt: str,
    model_response: str = "",
    timeout: float = 60.0,
) -> ActionScriptResult:
    """Run a chosen action's ``run(payload)`` function in a fresh process."""
    if not action.has_code or not action.script_path:
        raise ValueError("This action has no script to run.")
    script = Path(action.script_path)
    if not script.is_file():
        raise FileNotFoundError(f"The action script is missing: {script}")
    payload = {
        "action": action.to_dict(),
        "context": context,
        "prompt": str(prompt),
        "model_response": str(model_response),
        "run_script_first": action.run_script_first,
    }
    completed = subprocess.run(
        [sys.executable, "-m", "core.action_files.worker", str(script)],
        input=json.dumps(payload, ensure_ascii=False, default=str),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1.0, float(timeout)),
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        response = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no response"
        raise RuntimeError(f"The action script returned an unreadable response: {detail}") from exc
    if completed.returncode != 0 or not bool(response.get("ok")):
        detail = str(response.get("error") or completed.stderr.strip() or "Action script failed.")
        raise RuntimeError(detail)
    raw = response.get("result")
    value = raw if isinstance(raw, dict) else {}
    paste_back = value.get("paste_back")
    return ActionScriptResult(
        output=str(value.get("output") or ""),
        prompt=str(value.get("prompt") or ""),
        paste_back=paste_back if isinstance(paste_back, bool) else None,
    )


__all__ = ["ActionScriptResult", "action_from_dict", "run_action_script"]
