"""Safely restart only this checkout's running Wisp development supervisor."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]


def _is_repo_supervisor(process: psutil.Process) -> bool:
    try:
        cmdline = process.cmdline()
        cwd = Path(process.cwd()).resolve()
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        return False
    return cwd == REPO_ROOT and "runtime.supervisor.app" in cmdline


def main() -> int:
    supervisors = [process for process in psutil.process_iter() if _is_repo_supervisor(process)]
    supervisor_pids = {process.pid for process in supervisors}
    roots = [
        process
        for process in supervisors
        if process.ppid() not in supervisor_pids
    ]
    stopped: set[int] = set()
    for root in roots:
        processes = root.children(recursive=True) + [root]
        for process in reversed(processes):
            if process.pid in stopped:
                continue
            stopped.add(process.pid)
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs(processes, timeout=4.0)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass

    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if not any(_is_repo_supervisor(process) for process in psutil.process_iter()):
            break
        time.sleep(0.1)

    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
    flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and module
        [sys.executable, "-m", "runtime.supervisor.app"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    print(f"stopped={sorted(stopped)} started={process.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
