"""Standalone launcher for OpenWand's scoped multi-agent task engine.

This module intentionally has no Qt, overlay, supervisor, or worker imports.
It can be exercised from a terminal before the same task contract is handed to
the OpenWand UI::

    python -m standalone.background_agents demo --workspace .tmp/agent-demo
    python -m standalone.background_agents start --spec task.json
    python -m standalone.background_agents status --state agent-job.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agent.runner import AgentTaskRunner
from core.agent.task_spec import (
    agent_task_spec_from_dict,
    default_agent_specs,
    default_communication_specs,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    for attempt in range(20):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            break
        except PermissionError:
            # Windows can briefly deny readers while another process replaces
            # the state file. Polling clients should see a short delay, not a
            # failed status request.
            if attempt == 19:
                raise
            time.sleep(0.01)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _scripted_model_from_env():
    """Return the existing opt-in Agent Team test script as a model callback."""
    script_path = str(os.getenv("OPENWAND_BRAIN_AGENT_TEST_SCRIPT") or "").strip()
    if not script_path:
        return None
    raw = json.loads(Path(script_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("OPENWAND_BRAIN_AGENT_TEST_SCRIPT must contain a JSON array")
    responses = [item if isinstance(item, str) else json.dumps(item) for item in raw]
    index = 0

    def scripted(_prompt: str) -> str:
        nonlocal index
        if index >= len(responses):
            return json.dumps(
                {
                    "thought": "script exhausted",
                    "status": "complete",
                    "next_agent": "same",
                    "tool_calls": [],
                    "final": "Done.",
                }
            )
        response = responses[index]
        index += 1
        return response

    return scripted


def _update_state(path: Path, **updates: Any) -> dict[str, Any]:
    """Atomically merge updates into a small, externally readable job file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = _read_json(path) if path.exists() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        state = {}
    state.update(updates)
    state["updated_at"] = _now()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            # On Windows, an external status reader can briefly hold the
            # destination open and prevent an otherwise atomic replacement.
            if attempt == 19:
                raise
            time.sleep(0.01)
    return state


def quick_task_payload(objective: str, scope_folder: str | Path) -> dict[str, Any]:
    """Build a conservative task contract for a quick background launch."""
    cleaned = " ".join(str(objective or "").split())
    title = cleaned[:72].rstrip()
    if len(cleaned) > len(title):
        title = title.rstrip(" .") + "…"
    return {
        "title": title or "Agent Team task",
        "objective": str(objective or "").strip(),
        "scope_folder": str(Path(scope_folder).expanduser().resolve()),
        "sandbox_mode": "workspace-write: scope folder only",
        "approval_policy": "ask before escalation",
        "provider": "same as app",
        "model": "",
        "reasoning_effort": "medium",
        "max_runtime_minutes": 60,
        "max_turns": 30,
        "allow_shell": True,
        "allow_network": False,
        "allow_git": True,
        "allow_file_create": True,
        "allow_file_edit": True,
        "allow_file_delete": False,
        "blocked_file_globs": [".env", "private/*", ".git/*"],
        "completion_criteria": (
            "Complete the requested work, run relevant local checks, and report "
            "the changed files and verification results."
        ),
        "agents": default_agent_specs("English"),
        "communications": default_communication_specs("English"),
    }


def _demo_payload(workspace: Path) -> dict[str, Any]:
    payload = quick_task_payload(
        "Create demo_agent_output.py with a greeting function and verify that it compiles.",
        workspace,
    )
    payload.update(
        {
            "title": "Standalone Agent Team demo",
            "approval_policy": "never escalate",
            "max_turns": 6,
            "allow_git": False,
            "git_permission_mode": "never permit",
            "shell_permission_mode": "auto",
            "file_create_permission_mode": "auto",
            "file_edit_permission_mode": "auto",
        }
    )
    return payload


class _OfflineDemoModel:
    """Deterministic model double used to prove orchestration without a network."""

    def __init__(self) -> None:
        self._responses = [
            {
                "thought": "Give the implementation to the builder.",
                "status": "continue",
                "next_agent": "Builder",
                "reason": "The builder owns the code change.",
                "tool_calls": [
                    {
                        "tool": "send_message",
                        "args": {"to": "Builder", "message": "Create the demo module, then ask Reviewer to verify it."},
                    }
                ],
                "final": None,
            },
            {
                "thought": "Create the requested Python module.",
                "status": "continue",
                "next_agent": "Reviewer",
                "reason": "The implementation is ready for verification.",
                "tool_calls": [
                    {
                        "tool": "create_file",
                        "args": {
                            "path": "demo_agent_output.py",
                            "content": "def greeting() -> str:\n    return \"Hello from a standalone background agent!\"\n",
                        },
                    },
                    {
                        "tool": "send_message",
                        "args": {"to": "Reviewer", "message": "Please compile-check demo_agent_output.py."},
                    },
                ],
                "final": None,
            },
            {
                "thought": "Run the local syntax check and report back.",
                "status": "continue",
                "next_agent": "Coordinator",
                "reason": "The coordinator can close the task after review.",
                "tool_calls": [
                    {
                        "tool": "run_command",
                        "args": {"args": [sys.executable, "-m", "py_compile", "demo_agent_output.py"]},
                    },
                    {
                        "tool": "send_message",
                        "args": {"to": "Coordinator", "message": "The standalone demo module compiled successfully."},
                    },
                ],
                "final": None,
            },
            {
                "thought": "Implementation and independent verification are complete.",
                "status": "complete",
                "next_agent": "same",
                "reason": "The requested file exists and the syntax check passed.",
                "tool_calls": [],
                "final": "Created demo_agent_output.py and verified it with Python's bytecode compiler.",
            },
        ]

    def __call__(self, _prompt: str) -> str:
        if not self._responses:
            raise RuntimeError("Offline demo received more model turns than expected")
        return json.dumps(self._responses.pop(0))


def run_job(
    payload: dict[str, Any],
    *,
    log_root: Path,
    state_path: Path,
    model_callback=None,
) -> dict[str, Any]:
    """Run one task synchronously while publishing lifecycle state."""
    if model_callback is None:
        model_callback = _scripted_model_from_env()
    spec = agent_task_spec_from_dict(payload)
    _update_state(
        state_path,
        status="running",
        pid=os.getpid(),
        title=spec.title,
        scope_folder=spec.scope_folder,
        started_at=_now(),
    )
    try:
        runner = AgentTaskRunner(
            log_root=log_root,
            model_callback=model_callback,
            approval_callback=lambda _request: False,
        )
        run_dir = runner.run(spec, on_log=lambda line: _update_state(state_path, last_log=line))
        error_path = run_dir / "error.txt"
        error = error_path.read_text(encoding="utf-8", errors="replace") if error_path.exists() else ""
        status = "failed" if error else "completed"
        return _update_state(
            state_path,
            status=status,
            run_dir=str(run_dir),
            final_path=str(run_dir / "final.md"),
            error=error,
            finished_at=_now(),
        )
    except Exception as exc:
        return _update_state(
            state_path,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_now(),
        )


def _detached_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, "-m", "standalone.background_agents"]
    if args.command == "start-demo":
        command.extend(["demo", "--workspace", str(Path(args.workspace).resolve())])
    else:
        command.extend(["run", "--spec", str(Path(args.spec).resolve())])
    command.extend(["--log-root", str(Path(args.log_root).resolve()), "--state", str(Path(args.state).resolve())])
    return command


def start_detached(args: argparse.Namespace) -> dict[str, Any]:
    """Start a child runner that is not tied to the launching terminal."""
    state_path = Path(args.state).resolve()
    _update_state(state_path, status="queued", created_at=_now())
    stdout_path = state_path.with_suffix(".stdout.log")
    stderr_path = state_path.with_suffix(".stderr.log")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            _detached_command(args),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=str(Path(__file__).resolve().parents[1]),
            close_fds=True,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    return _update_state(
        state_path,
        pid=process.pid,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def start_payload_detached(
    payload: dict[str, Any],
    *,
    log_root: str | Path,
    state_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist and detach one task payload without importing any OpenWand UI code."""
    root = Path(log_root).expanduser().resolve()
    jobs_root = root / "background_jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    state = Path(state_path).expanduser().resolve() if state_path else jobs_root / f"{job_id}.json"
    spec_path = state.with_suffix(".spec.json")
    spec_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _update_state(
        state,
        job_id=job_id,
        spec_path=str(spec_path),
        **dict(metadata or {}),
    )
    args = argparse.Namespace(
        command="start",
        spec=str(spec_path),
        log_root=str(root),
        state=str(state),
    )
    result = start_detached(args)
    result["job_id"] = job_id
    result["state_path"] = str(state)
    return result


def _default_paths(args: argparse.Namespace) -> None:
    if not getattr(args, "log_root", None):
        args.log_root = str(Path.cwd() / "agent-runs")
    if not getattr(args, "state", None):
        args.state = str(Path(args.log_root) / f"job-{uuid.uuid4().hex[:10]}.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OpenWand's scoped Agent Team without launching the OpenWand UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run a task-spec JSON in this process.")
    run.add_argument("--spec", required=True)
    run.add_argument("--log-root")
    run.add_argument("--state")

    demo = subparsers.add_parser("demo", help="Run an offline Agent Team demo.")
    demo.add_argument("--workspace", required=True)
    demo.add_argument("--log-root")
    demo.add_argument("--state")

    start = subparsers.add_parser("start", help="Launch a task-spec JSON as a detached process.")
    start.add_argument("--spec", required=True)
    start.add_argument("--log-root")
    start.add_argument("--state")

    start_demo = subparsers.add_parser("start-demo", help="Launch the offline Agent Team demo as a detached process.")
    start_demo.add_argument("--workspace", required=True)
    start_demo.add_argument("--log-root")
    start_demo.add_argument("--state")

    status = subparsers.add_parser("status", help="Print a previously launched job state.")
    status.add_argument("--state", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "status":
        print(json.dumps(_read_json(Path(args.state)), indent=2, ensure_ascii=False))
        return 0

    _default_paths(args)
    state_path = Path(args.state).resolve()
    log_root = Path(args.log_root).resolve()
    if args.command in {"start", "start-demo"}:
        print(json.dumps(start_detached(args), indent=2, ensure_ascii=False))
        return 0

    if args.command == "demo":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        result = run_job(
            _demo_payload(workspace),
            log_root=log_root,
            state_path=state_path,
            model_callback=_OfflineDemoModel(),
        )
    else:
        result = run_job(
            _read_json(Path(args.spec).resolve()),
            log_root=log_root,
            state_path=state_path,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
