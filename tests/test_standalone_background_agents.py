"""Acceptance tests for the UI-independent background-agent entry point."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from standalone.background_agents import _read_json, quick_task_payload, start_payload_detached


def test_quick_task_payload_is_scoped_and_has_real_subagents(tmp_path: Path) -> None:
    payload = quick_task_payload("Fix the parser and run its tests.", tmp_path)

    assert payload["scope_folder"] == str(tmp_path.resolve())
    assert payload["allow_network"] is False
    assert payload["allow_file_delete"] is False
    assert [agent["role"] for agent in payload["agents"]] == ["Coordinator", "Implementer", "Reviewer"]
    assert payload["communications"]


def test_payload_launcher_persists_a_detachable_job_contract(tmp_path: Path) -> None:
    payload = quick_task_payload("Check the project.", tmp_path)
    with patch(
        "standalone.background_agents.start_detached",
        return_value={"status": "queued", "pid": 123},
    ) as start:
        result = start_payload_detached(
            payload,
            log_root=tmp_path / "runs",
            metadata={"source": "chat_model"},
        )

    assert result["job_id"].startswith("job-")
    assert Path(result["state_path"]).parent == (tmp_path / "runs" / "background_jobs").resolve()
    state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
    assert state["source"] == "chat_model"
    assert Path(state["spec_path"]).is_file()
    assert start.call_count == 1


def test_standalone_offline_demo_runs_agents_code_and_test(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state = tmp_path / "demo-state.json"
    logs = tmp_path / "runs"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "standalone.background_agents",
            "demo",
            "--workspace",
            str(workspace),
            "--log-root",
            str(logs),
            "--state",
            str(state),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    status = json.loads(state.read_text(encoding="utf-8"))
    run_dir = Path(status["run_dir"])
    turns = json.loads((run_dir / "turns.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert (workspace / "demo_agent_output.py").exists()
    assert [turn["agent"] for turn in turns] == ["Coordinator", "Builder", "Reviewer", "Coordinator"]
    assert "verified" in (run_dir / "final.md").read_text(encoding="utf-8").lower()


def test_detached_offline_demo_finishes_after_launcher_exits(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state = tmp_path / "detached-state.json"
    logs = tmp_path / "runs"

    launcher = subprocess.run(
        [
            sys.executable,
            "-m",
            "standalone.background_agents",
            "start-demo",
            "--workspace",
            str(workspace),
            "--log-root",
            str(logs),
            "--state",
            str(state),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert launcher.returncode == 0, launcher.stderr or launcher.stdout

    deadline = time.monotonic() + 20
    status: dict = {}
    while time.monotonic() < deadline:
        if state.exists():
            status = _read_json(state)
            if status.get("status") in {"completed", "failed"}:
                break
        time.sleep(0.05)

    assert status.get("status") == "completed", status
    assert Path(status["final_path"]).exists()
    assert (workspace / "demo_agent_output.py").exists()
