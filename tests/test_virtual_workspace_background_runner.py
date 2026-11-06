from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from addons.virtual_workspace.background_runner import (
    SECURITY_NOTICE,
    CheckRequest,
    LimitedCheck,
    LimitedWorkspaceRunner,
)


def test_python_syntax_check_passes_without_executing_source(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist.txt"
    (tmp_path / "demo.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    result = LimitedWorkspaceRunner(tmp_path).run(
        CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("demo.py",))
    )

    assert result.ok is True
    assert result.paths == ("demo.py",)
    assert result.summary == "python_syntax check passed"
    assert result.security_notice == SECURITY_NOTICE
    assert not marker.exists()
    assert not (tmp_path / "__pycache__").exists()


def test_python_syntax_check_reports_invalid_file(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def nope(:\n", encoding="utf-8")

    result = LimitedWorkspaceRunner(tmp_path).run(
        CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("broken.py",))
    )

    assert result.ok is False
    assert result.returncode
    assert "SyntaxError" in result.stderr


@pytest.mark.parametrize("check", [LimitedCheck.PYTHON_SYNTAX, LimitedCheck.JSON])
def test_frozen_checks_use_the_supported_module_entrypoint(tmp_path: Path, monkeypatch, check: LimitedCheck) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    path = tmp_path / ("source.py" if check is LimitedCheck.PYTHON_SYNTAX else "data.json")
    command = LimitedWorkspaceRunner(tmp_path)._build_command(check, (path,))
    assert command == [sys.executable, "-m", "runtime.workers.workspace_check", check.value, str(path)]


def test_packaged_check_worker_validates_without_executing_or_writing(tmp_path: Path, capsys) -> None:
    from runtime.workers.workspace_check import main

    source = tmp_path / "source.py"
    source.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    assert main(["python_syntax", str(source)]) == 0
    assert not (tmp_path / "__pycache__").exists()
    source.write_text("def broken(:\n", encoding="utf-8")
    assert main(["python_syntax", str(source)]) == 1
    assert "SyntaxError" in capsys.readouterr().err


def test_packaged_json_check_returns_a_controlled_error(tmp_path: Path, capsys) -> None:
    from runtime.workers.workspace_check import main

    source = tmp_path / "data.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    assert main(["json", str(source)]) == 0
    source.write_text('{"broken": }', encoding="utf-8")
    assert main(["json", str(source)]) == 1
    assert "JSONDecodeError" in capsys.readouterr().err


def test_json_check_accepts_valid_and_rejects_invalid_data(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text('{"working": true}', encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"working": }', encoding="utf-8")
    runner = LimitedWorkspaceRunner(tmp_path)

    good = runner.run(CheckRequest(LimitedCheck.JSON, ("good.json",)))
    bad = runner.run(CheckRequest(LimitedCheck.JSON, ("bad.json",)))

    assert good.ok is True
    assert bad.ok is False
    assert "JSONDecodeError" in bad.stderr


@pytest.mark.parametrize(
    ("check_request", "message"),
    [
        (CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("../outside.py",)), "outside the workspace"),
        (CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("note.txt",)), "Wrong file type"),
        (CheckRequest(LimitedCheck.JSON, ()), "At least one file"),
    ],
)
def test_request_rejects_unsafe_or_wrong_paths(
    tmp_path: Path,
    check_request: CheckRequest,
    message: str,
) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        LimitedWorkspaceRunner(tmp_path).run(check_request)


def test_request_rejects_symlink_even_when_target_is_inside_workspace(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("pass\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable on this platform")

    with pytest.raises(ValueError, match="Symlink paths are not allowed"):
        LimitedWorkspaceRunner(tmp_path).run(
            CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("link.py",))
        )


class _CommandTestRunner(LimitedWorkspaceRunner):
    command: list[str]

    def _build_command(self, check: LimitedCheck, paths: tuple[Path, ...]) -> list[str]:
        del check, paths
        return self.command


def test_hard_timeout_stops_checker(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("pass\n", encoding="utf-8")
    runner = _CommandTestRunner(tmp_path, timeout_seconds=0.15)
    runner.command = [sys.executable, "-I", "-S", "-c", "import time; time.sleep(5)"]

    result = runner.run(CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("demo.py",)))

    assert result.ok is False
    assert result.timed_out is True
    assert result.elapsed_seconds < 2


def test_hard_output_limit_stops_checker_and_caps_capture(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("pass\n", encoding="utf-8")
    runner = _CommandTestRunner(tmp_path, max_output_bytes=1024)
    runner.command = [
        sys.executable,
        "-I",
        "-S",
        "-c",
        "import os; os.write(1, b'x' * 100000)",
    ]

    result = runner.run(CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("demo.py",)))

    assert result.ok is False
    assert result.output_limit_exceeded is True
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 1024


def test_submit_returns_immediately_and_can_cancel(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("pass\n", encoding="utf-8")
    runner = _CommandTestRunner(tmp_path, timeout_seconds=5)
    runner.command = [sys.executable, "-I", "-S", "-c", "import time; time.sleep(5)"]
    started = time.monotonic()

    handle = runner.submit(CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("demo.py",)))
    assert time.monotonic() - started < 0.5
    handle.cancel()
    result = handle.result(timeout=2)

    assert result.ok is False
    assert result.cancelled is True
    assert handle.done is True


def test_callback_runs_after_background_check(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("pass\n", encoding="utf-8")
    called = threading.Event()
    observed = []

    def callback(result: object) -> None:
        observed.append(result)
        called.set()

    handle = LimitedWorkspaceRunner(tmp_path).submit(
        CheckRequest(LimitedCheck.PYTHON_SYNTAX, ("demo.py",)),
        callback=callback,
    )
    result = handle.result(timeout=3)

    assert called.wait(1)
    assert observed == [result]


def test_reduced_environment_drops_python_and_home_overrides() -> None:
    env = LimitedWorkspaceRunner._reduced_environment()

    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "HOME" not in env
    if os.name == "nt":
        assert "SystemRoot" in env or "WINDIR" in env
