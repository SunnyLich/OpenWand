"""Remove repository-owned pytest basetemps after a test process exits.

Pytest intentionally retains an explicitly configured ``--basetemp`` after a
run. OpenWand uses repository-local basetemps for workflow and CI isolation, so
those retained trees otherwise accumulate indefinitely.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

KEEP_TEMP_ENV = "OPENWAND_KEEP_PYTEST_TEMP"
_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.2, 1.0, 2.0)
_OWNED_CHILD_PATTERN = re.compile(
    r"^(?P<kind>pytest|app_workflows|app_architecture|failure_evidence|workflow)_(?P<pid>\d+)(?:_|$)"
)
_OWNED_ROOT_PATTERN = re.compile(r"^\.pytest-tmp-pytest_(?P<pid>\d+)(?:_|$)")


def _is_truthy(value: str | None) -> bool:
    """Return whether an environment value explicitly enables an option."""

    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _owned_basetemp(config: object) -> Path | None:
    """Return the configured basetemp when it is safely owned by this repo."""

    option = getattr(config, "option", None)
    raw_basetemp = getattr(option, "basetemp", None)
    rootpath = getattr(config, "rootpath", None)
    if not raw_basetemp or rootpath is None:
        return None

    root = Path(rootpath).resolve()
    target = Path(raw_basetemp)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()

    pytest_temp_root = (root / ".tmp_pytest").resolve()
    try:
        relative = target.relative_to(pytest_temp_root)
    except ValueError:
        relative = None
    if relative is not None and relative.parts:
        return target

    if target.parent == root and target.name.startswith(".pytest-tmp-"):
        return target
    return None


def remove_owned_basetemp(
    root: Path,
    target: Path | str,
    *,
    defer_until_process_exit: bool = False,
) -> bool:
    """Remove one repository-owned pytest basetemp and nothing broader."""

    if _is_truthy(os.environ.get(KEEP_TEMP_ENV)):
        return False

    config = SimpleNamespace(
        rootpath=Path(root),
        option=SimpleNamespace(basetemp=target),
    )
    owned = _owned_basetemp(config)
    if owned is None:
        return False

    removed = _remove_tree_with_retries(
        owned,
        warn=not defer_until_process_exit,
    )
    if not removed and defer_until_process_exit:
        _schedule_deferred_removal(Path(root).resolve(), owned)
    return removed


def _remove_tree_with_retries(path: Path, *, warn: bool = True) -> bool:
    """Remove a temporary tree, retrying briefly for released Windows handles."""

    deletion_path = path
    if os.name == "nt":
        deletion_path = Path(f"\\\\?\\{path.resolve()}")

    def handle_error(function: Callable[[str], object], failed_path: str, error: BaseException) -> None:
        """Ignore vanished children and retry entries made read-only by tests."""

        if isinstance(error, FileNotFoundError):
            return
        try:
            os.chmod(failed_path, stat.S_IREAD | stat.S_IWRITE)
            function(failed_path)
        except FileNotFoundError:
            return
        except OSError:
            raise error from None

    last_error: OSError | None = None
    for delay in _RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(deletion_path, onexc=handle_error)
            return True
        except FileNotFoundError as exc:
            if not path.exists():
                return True
            last_error = exc
        except OSError as exc:
            last_error = exc

    if last_error is not None and warn:
        warnings.warn(
            f"Could not remove pytest temporary directory {path}: {last_error}",
            RuntimeWarning,
            stacklevel=2,
        )
    return not path.exists()


def _schedule_deferred_removal(root: Path, target: Path) -> None:
    """Launch a quiet reaper for handles released only during interpreter exit."""

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--reap",
        str(root),
        str(target),
        str(os.getpid()),
    ]
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(command, **kwargs)
    except OSError as exc:
        warnings.warn(
            f"Could not schedule deferred pytest cleanup for {target}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


def _reap_after_process_exit(root: Path, target: Path, owner_pid: int) -> int:
    """Wait for one runner to exit, then remove its validated basetemp."""

    config = SimpleNamespace(
        rootpath=root,
        option=SimpleNamespace(basetemp=target),
    )
    owned = _owned_basetemp(config)
    if owned is None:
        return 2

    while _process_is_running(owner_pid):
        time.sleep(0.1)

    deadline = time.monotonic() + 60.0
    while owned.exists() and time.monotonic() < deadline:
        if _remove_tree_with_retries(owned, warn=False):
            break
        time.sleep(0.5)
    return 0 if not owned.exists() else 1


def _process_is_running(pid: int) -> bool:
    """Return whether a process ID is still alive without mutating it."""

    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            try:
                exit_code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == still_active
                # A query failure must preserve the directory instead of
                # guessing that a possibly live process is dead.
                return True
            finally:
                kernel32.CloseHandle(handle)
        # Access denied means the process exists but cannot be queried.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cleanup_stale_owned_basetemps(root: Path, *, runner_pid: int | None = None) -> list[Path]:
    """Remove dead-process pytest trees and this runner's completed phase trees.

    Live sibling processes are deliberately preserved.  ``runner_pid`` is used
    only for the named phase directories created by ``run_app_workflow_tests``;
    by the time its finalizer calls this function, those child pytest processes
    have all exited even though their directory names contain the parent PID.
    """

    if _is_truthy(os.environ.get(KEEP_TEMP_ENV)):
        return []
    root = Path(root).resolve()
    temp_root = (root / ".tmp_pytest").resolve()

    removed: list[Path] = []
    if temp_root.is_dir():
        for child in list(temp_root.iterdir()):
            if not child.is_dir():
                continue
            match = _OWNED_CHILD_PATTERN.match(child.name)
            if match is None:
                continue
            owner_pid = int(match.group("pid"))
            is_runner_phase = match.group("kind") != "pytest"
            owned_by_finished_runner = bool(
                is_runner_phase and runner_pid is not None and owner_pid == runner_pid
            )
            if not owned_by_finished_runner and _process_is_running(owner_pid):
                continue
            _remove_tree_with_retries(child)
            if not child.exists():
                removed.append(child)
        try:
            temp_root.rmdir()
        except OSError:
            pass

    for child in list(root.iterdir()):
        if not child.is_dir():
            continue
        match = _OWNED_ROOT_PATTERN.match(child.name)
        if match is None or _process_is_running(int(match.group("pid"))):
            continue
        _remove_tree_with_retries(child)
        if not child.exists():
            removed.append(child)
    return removed


def pytest_configure(config: object) -> None:
    """Collect abandoned runs, then give plain pytest a unique basetemp."""

    option = getattr(config, "option", None)
    rootpath = getattr(config, "rootpath", None)
    if option is None or rootpath is None:
        return

    root = Path(rootpath).resolve()
    cleanup_stale_owned_basetemps(root)
    if getattr(option, "basetemp", None):
        return

    option.basetemp = str(
        root / f".pytest-tmp-pytest_{os.getpid()}_{time.time_ns()}"
    )


def pytest_unconfigure(config: object) -> None:
    """Delete this pytest process's owned basetemp after plugin teardown.

    Keep the shared ``.tmp_pytest`` parent in place.  Removing that parent is
    racy: a concurrent pytest process can observe it, then lose it immediately
    before creating its own child directory.  The master workflow runner's
    stale-temp pass removes the parent after it has checked all owned children.
    """

    if _is_truthy(os.environ.get(KEEP_TEMP_ENV)):
        return

    basetemp = _owned_basetemp(config)
    if basetemp is None:
        return

    remove_owned_basetemp(
        Path(config.rootpath),
        basetemp,
        defer_until_process_exit=True,
    )


def _main(argv: list[str]) -> int:
    """Run the private detached-reaper entry point."""

    if len(argv) != 5 or argv[1] != "--reap":
        return 2
    return _reap_after_process_exit(Path(argv[2]), Path(argv[3]), int(argv[4]))


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
