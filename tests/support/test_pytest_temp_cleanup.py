"""Tests for repository-owned pytest basetemp cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import pytest_temp_cleanup


def test_child_process_recognizes_live_parent_pid():
    """The Windows handle check must not truncate a live 64-bit process handle."""

    root = Path(__file__).resolve().parents[2]
    code = (
        "from scripts.pytest_temp_cleanup import _process_is_running; "
        f"print(_process_is_running({os.getpid()}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "True"


def _config(root: Path, basetemp: Path | str | None) -> SimpleNamespace:
    """Build the minimal pytest config shape used by the cleanup plugin."""

    return SimpleNamespace(rootpath=root, option=SimpleNamespace(basetemp=basetemp))


def test_owned_basetemp_accepts_repo_pytest_temp_child(tmp_path):
    """A named child of .tmp_pytest is safe for automatic deletion."""

    target = tmp_path / ".tmp_pytest" / "focused-run"

    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, target)) == target.resolve()


def test_owned_basetemp_accepts_ci_temp_directory(tmp_path):
    """The CI runner's root-level basetemp naming contract is also owned."""

    target = tmp_path / ".pytest-tmp-ci-chunk-2"

    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, target)) == target.resolve()


def test_owned_basetemp_rejects_broad_or_external_paths(tmp_path):
    """Cleanup never removes the repository, temp root, or caller-owned path."""

    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, tmp_path)) is None
    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, tmp_path / ".tmp_pytest")) is None
    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, tmp_path / "custom-temp")) is None
    assert pytest_temp_cleanup._owned_basetemp(_config(tmp_path, tmp_path / ".tmp_pytest-escape")) is None


def test_pytest_configure_assigns_owned_temp_to_plain_run(tmp_path):
    """Direct pytest commands use an isolated, removable repository temp."""

    config = _config(tmp_path, None)

    pytest_temp_cleanup.pytest_configure(config)

    target = pytest_temp_cleanup._owned_basetemp(config)
    assert target is not None
    assert target.parent == tmp_path.resolve()
    assert target.name.startswith(f".pytest-tmp-pytest_{os.getpid()}_")


def test_pytest_configure_collects_abandoned_runs(tmp_path, monkeypatch):
    """Starting any later pytest run sweeps basetemps whose owners exited."""

    stale = tmp_path / ".tmp_pytest" / "pytest_1234_100"
    stale.mkdir(parents=True)
    (stale / "leftover.txt").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(pytest_temp_cleanup, "_process_is_running", lambda _pid: False)
    config = _config(tmp_path, None)

    pytest_temp_cleanup.pytest_configure(config)

    assert not stale.exists()
    assert pytest_temp_cleanup._owned_basetemp(config) is not None


def test_pytest_configure_preserves_caller_basetemp(tmp_path):
    """An explicit caller path remains unchanged and outside cleanup ownership."""

    config = _config(tmp_path, "custom-temp")

    pytest_temp_cleanup.pytest_configure(config)

    assert config.option.basetemp == "custom-temp"


def test_pytest_unconfigure_removes_only_current_owned_basetemp(tmp_path, monkeypatch):
    """One process cleans its own directory without touching shared run state."""

    monkeypatch.delenv(pytest_temp_cleanup.KEEP_TEMP_ENV, raising=False)
    current = tmp_path / ".tmp_pytest" / "current"
    sibling = tmp_path / ".tmp_pytest" / "other-process"
    current.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (current / "result.txt").write_text("temporary", encoding="utf-8")
    (sibling / "result.txt").write_text("keep", encoding="utf-8")

    pytest_temp_cleanup.pytest_unconfigure(_config(tmp_path, current))

    assert not current.exists()
    assert (tmp_path / ".tmp_pytest").is_dir()
    assert (sibling / "result.txt").read_text(encoding="utf-8") == "keep"


def test_pytest_unconfigure_keeps_empty_shared_parent_for_concurrent_runs(tmp_path, monkeypatch):
    """A finishing process cannot remove the parent another process is entering."""

    monkeypatch.delenv(pytest_temp_cleanup.KEEP_TEMP_ENV, raising=False)
    current = tmp_path / ".tmp_pytest" / "current"
    current.mkdir(parents=True)

    pytest_temp_cleanup.pytest_unconfigure(_config(tmp_path, current))

    assert not current.exists()
    assert (tmp_path / ".tmp_pytest").is_dir()


def test_pytest_unconfigure_preserves_temp_when_requested(tmp_path, monkeypatch):
    """Developers can retain a failing run's files through an environment flag."""

    monkeypatch.setenv(pytest_temp_cleanup.KEEP_TEMP_ENV, "1")
    target = tmp_path / ".tmp_pytest" / "debug-run"
    target.mkdir(parents=True)
    (target / "result.txt").write_text("keep", encoding="utf-8")

    pytest_temp_cleanup.pytest_unconfigure(_config(tmp_path, target))

    assert target.exists()


def test_remove_owned_basetemp_rejects_broad_path_and_removes_owned_child(tmp_path):
    """Runner finalizers can clean exact basetemps without broad deletion risk."""

    owned = tmp_path / ".pytest-tmp-ci-chunk-2"
    owned.mkdir()
    (owned / "result.txt").write_text("temporary", encoding="utf-8")

    assert pytest_temp_cleanup.remove_owned_basetemp(tmp_path, tmp_path) is False
    assert pytest_temp_cleanup.remove_owned_basetemp(tmp_path, owned) is True
    assert not owned.exists()


def test_remove_owned_basetemp_defers_locked_tree_until_process_exit(tmp_path, monkeypatch):
    """A Windows-style lingering handle schedules cleanup after runner exit."""

    owned = tmp_path / ".pytest-tmp-ci-chunk-2"
    owned.mkdir()
    scheduled: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        pytest_temp_cleanup,
        "_remove_tree_with_retries",
        lambda _path, **_kwargs: False,
    )
    monkeypatch.setattr(
        pytest_temp_cleanup,
        "_schedule_deferred_removal",
        lambda root, target: scheduled.append((root, target)),
    )

    assert (
        pytest_temp_cleanup.remove_owned_basetemp(
            tmp_path,
            owned,
            defer_until_process_exit=True,
        )
        is False
    )
    assert scheduled == [(tmp_path.resolve(), owned.resolve())]


def test_reaper_rejects_path_outside_owned_pytest_locations(tmp_path):
    """The detached process cannot be repurposed for arbitrary deletion."""

    outside = tmp_path / "ordinary-directory"
    outside.mkdir()

    assert pytest_temp_cleanup._reap_after_process_exit(tmp_path, outside, 1234) == 2
    assert outside.exists()


def test_remove_tree_ignores_a_child_that_vanished(tmp_path, monkeypatch):
    """A concurrently removed fixture does not leave its basetemp behind."""

    target = tmp_path / "run"
    target.mkdir()

    def fake_rmtree(path, *, onexc):
        onexc(Path.unlink, str(path / "already-gone.txt"), FileNotFoundError())
        path.rmdir()

    monkeypatch.setattr(pytest_temp_cleanup.shutil, "rmtree", fake_rmtree)

    pytest_temp_cleanup._remove_tree_with_retries(target)

    assert not target.exists()


def test_stale_cleanup_removes_dead_process_tree_but_preserves_live_sibling(tmp_path, monkeypatch):
    """A later workflow run collects abandoned temp without racing an active run."""

    dead = tmp_path / ".tmp_pytest" / "pytest_1234_100"
    live = tmp_path / ".tmp_pytest" / "pytest_5678_200"
    dead.mkdir(parents=True)
    live.mkdir(parents=True)
    (dead / "leftover.txt").write_text("stale", encoding="utf-8")
    (live / "active.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(pytest_temp_cleanup, "_process_is_running", lambda pid: pid == 5678)

    removed = pytest_temp_cleanup.cleanup_stale_owned_basetemps(tmp_path)

    assert dead in removed
    assert not dead.exists()
    assert (live / "active.txt").read_text(encoding="utf-8") == "keep"


def test_stale_cleanup_removes_dead_root_basetemp_but_preserves_live_sibling(
    tmp_path, monkeypatch
):
    """PID-labelled CI basetemps are recoverable after their runner is killed."""

    dead = tmp_path / ".pytest-tmp-pytest_1234_ci_chunk_1"
    live = tmp_path / ".pytest-tmp-pytest_5678_ci_chunk_2"
    dead.mkdir()
    live.mkdir()
    monkeypatch.setattr(pytest_temp_cleanup, "_process_is_running", lambda pid: pid == 5678)

    removed = pytest_temp_cleanup.cleanup_stale_owned_basetemps(tmp_path)

    assert dead in removed
    assert not dead.exists()
    assert live.exists()


def test_stale_cleanup_removes_completed_current_runner_phases(tmp_path, monkeypatch):
    """Named master-runner phases are owned by the runner after children exit."""

    phase = tmp_path / ".tmp_pytest" / "workflow_4321"
    phase.mkdir(parents=True)
    (phase / "result.txt").write_text("temporary", encoding="utf-8")
    monkeypatch.setattr(pytest_temp_cleanup, "_process_is_running", lambda _pid: True)

    removed = pytest_temp_cleanup.cleanup_stale_owned_basetemps(tmp_path, runner_pid=4321)

    assert phase in removed
    assert not (tmp_path / ".tmp_pytest").exists()


def test_stale_cleanup_honors_debug_retention_flag(tmp_path, monkeypatch):
    """Explicit retention keeps abandoned temp available for debugging."""

    stale = tmp_path / ".tmp_pytest" / "pytest_1234_100"
    stale.mkdir(parents=True)
    monkeypatch.setenv(pytest_temp_cleanup.KEEP_TEMP_ENV, "1")
    monkeypatch.setattr(pytest_temp_cleanup, "_process_is_running", lambda _pid: False)

    assert pytest_temp_cleanup.cleanup_stale_owned_basetemps(tmp_path) == []
    assert stale.exists()
