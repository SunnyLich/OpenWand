"""Contracts for the complete GitHub-safe pytest chunk runner."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts import run_ci_pytest_chunk


def test_file_discovery_uses_the_single_canonical_tests_root(tmp_path: Path) -> None:
    canonical = tmp_path / "tests" / "integration" / "test_a.py"
    old_brain_location = tmp_path / "runtime" / "brain" / "tests" / "test_old.py"
    canonical.parent.mkdir(parents=True)
    old_brain_location.parent.mkdir(parents=True)
    canonical.write_text("def test_a(): pass\n", encoding="utf-8")
    old_brain_location.write_text("def test_old(): pass\n", encoding="utf-8")

    assert run_ci_pytest_chunk._test_files(tmp_path) == [canonical]


def test_github_runner_selects_only_github_safe_tests(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_example.py"
    command = run_ci_pytest_chunk._pytest_command(
        tmp_path, [test_file], tmp_path / ".pytest-tmp"
    )

    assert any(
        command[index : index + 2] == ["-m", "github_safe"]
        for index in range(len(command) - 1)
    )
    assert "-k" not in command
    timeout_option = command.index("-o")
    assert command[timeout_option + 1] == "faulthandler_timeout=60"


def test_chunks_partition_every_file_once() -> None:
    files = [Path(f"test_{index}.py") for index in range(11)]
    chunks = [
        run_ci_pytest_chunk._chunk_files(files, chunk_index, 4)
        for chunk_index in range(1, 5)
    ]

    flattened = [path for chunk in chunks for path in chunk]
    assert len(flattened) == len(files)
    assert set(flattened) == set(files)
    assert not any(
        set(left) & set(right)
        for left in chunks
        for right in chunks
        if left is not right
    )


def test_only_visible_output_counts_as_ci_progress() -> None:
    """Pipe control bytes cannot keep a silent test alive forever."""
    assert run_ci_pytest_chunk._contains_visible_progress(b". [42%]\n") is True
    assert run_ci_pytest_chunk._contains_visible_progress(b"\x00\r\n\t\x1f\x7f") is False
    assert run_ci_pytest_chunk._line_reports_progress(b"=== overlay shell: Settings visible ===") is True
    assert run_ci_pytest_chunk._line_reports_progress(b"Timeout (0:01:00)!") is False
    assert run_ci_pytest_chunk._line_reports_progress(
        b'  File "subprocess.py", line 1264 in wait'
    ) is False


def test_overlay_acceptance_has_a_focused_inactivity_ceiling(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_overlay_shell_acceptance.py"
    test_file.parent.mkdir(parents=True)
    test_file.touch()

    assert run_ci_pytest_chunk._file_inactivity_timeout(tmp_path, test_file, 300.0) == 90.0
    assert run_ci_pytest_chunk._file_inactivity_timeout(tmp_path, test_file, 30.0) == 30.0


def test_per_file_inactivity_timeout_stops_the_process_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A silent pytest process fails promptly instead of consuming the whole CI job."""
    test_file = tmp_path / "tests" / "test_slow.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_slow(): pass\n", encoding="utf-8")
    monkeypatch.setattr(
        run_ci_pytest_chunk,
        "_pytest_command",
        lambda *_args: [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    status = run_ci_pytest_chunk._run_file(
        tmp_path,
        test_file,
        tmp_path / ".pytest-tmp",
        0.5,
    )

    assert status == run_ci_pytest_chunk._FILE_TIMEOUT_EXIT_CODE


def test_per_file_inactivity_timeout_resets_when_output_arrives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A long-running file stays alive while it continues to report progress."""
    test_file = tmp_path / "tests" / "test_progress.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_progress(): pass\n", encoding="utf-8")
    script = (
        "import time\n"
        "for index in range(6):\n"
        "    print(index, flush=True)\n"
        "    time.sleep(0.4)\n"
    )
    monkeypatch.setattr(
        run_ci_pytest_chunk,
        "_pytest_command",
        lambda *_args: [sys.executable, "-c", script],
    )

    status = run_ci_pytest_chunk._run_file(
        tmp_path,
        test_file,
        tmp_path / ".pytest-tmp",
        1.0,
    )

    assert status == 0


def test_fault_handler_dumps_do_not_renew_file_inactivity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Repeated diagnostic stacks stay visible without keeping a hung file alive."""
    test_file = tmp_path / "tests" / "test_hung.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_hung(): pass\n", encoding="utf-8")
    script = (
        "import time\n"
        "for _ in range(20):\n"
        "    print('Timeout (0:01:00)!', flush=True)\n"
        "    print('Thread 0x123 (most recent call first):', flush=True)\n"
        "    print('  File \\\"subprocess.py\\\", line 1264 in wait', flush=True)\n"
        "    time.sleep(0.1)\n"
    )
    monkeypatch.setattr(
        run_ci_pytest_chunk,
        "_pytest_command",
        lambda *_args: [sys.executable, "-c", script],
    )

    status = run_ci_pytest_chunk._run_file(
        tmp_path,
        test_file,
        tmp_path / ".pytest-tmp",
        0.5,
    )

    assert status == run_ci_pytest_chunk._FILE_TIMEOUT_EXIT_CODE
