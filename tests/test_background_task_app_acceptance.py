"""Full-process acceptance coverage for model-delegated background work."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_chat_model_delegates_real_detached_work_and_result_returns(tmp_path: Path) -> None:
    runner = Path(__file__).parent / "support" / "background_task_app_runner.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--root", str(tmp_path / "acceptance")],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=75,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["job_status"] == "completed"
    assert result["delivered"] is True
    assert result["tool_offered"] is True
    assert result["provider_rounds"] >= 2
    assert "wisp-background-task-e2e" in result["chat_result"]
    assert Path(result["output_path"]).is_file()
