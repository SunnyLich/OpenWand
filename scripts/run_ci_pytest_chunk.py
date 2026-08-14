"""Run one deterministic chunk of the CI pytest suite."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_PYTEST_NO_TESTS_COLLECTED = 5
_FILE_TIMEOUT_EXIT_CODE = 124
_DEFAULT_FILE_INACTIVITY_TIMEOUT_SECONDS = 300.0
_FAULT_HANDLER_TIMEOUT_SECONDS = 60
_PROCESS_POLL_SECONDS = 1.0
_IGNORED_ACTIVITY_BYTES = bytes(range(0x20)) + b"\x7f"
_PYTEST_PROGRESS_BYTES = frozenset(b".sFxXE")
_DIAGNOSTIC_LINE_PREFIXES = (
    b"Timeout (",
    b"Thread ",
    b"Current thread ",
    b"Stack (",
    b'File "',
    b"Fatal Python error:",
    b"Python runtime state:",
    b"Extension modules:",
)
_FILE_INACTIVITY_TIMEOUT_OVERRIDES = {
    "tests/test_overlay_shell_acceptance.py": 90.0,
    "tests/test_overlay_worker_acceptance.py": 90.0,
}


def _test_files(root: Path) -> list[Path]:
    return sorted(
        path for path in (root / "tests").rglob("test_*.py") if path.is_file()
    )


def _chunk_files(files: list[Path], chunk_index: int, chunk_total: int) -> list[Path]:
    return [
        path
        for index, path in enumerate(files)
        if index % chunk_total == chunk_index - 1
    ]


def _pytest_command(root: Path, files: list[Path], basetemp: Path) -> list[str]:
    return [
        sys.executable,
        "-X",
        "faulthandler",
        "-m",
        "pytest",
        "-ra",
        "--tb=short",
        "-o",
        f"faulthandler_timeout={_FAULT_HANDLER_TIMEOUT_SECONDS}",
        "-m",
        "github_safe",
        "--basetemp",
        str(basetemp),
        *(str(path.relative_to(root)) for path in files),
    ]


def _cleanup_basetemp(root: Path, basetemp: Path) -> None:
    """Remove a CI basetemp even when its pytest child timed out or failed."""

    if __package__:
        from scripts.pytest_temp_cleanup import remove_owned_basetemp
    else:
        from pytest_temp_cleanup import remove_owned_basetemp

    remove_owned_basetemp(root, basetemp, defer_until_process_exit=True)


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminate one timed-out pytest process and its worker descendants."""
    if os.name == "nt":
        # psutil's recursive process enumeration can itself block on a busy
        # hosted Windows runner. taskkill performs the native process-tree walk
        # and, crucially, closes descendant copies of pytest's output pipe.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
        return

    try:
        import psutil

        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        targets = [*reversed(descendants), parent]
        for target in targets:
            try:
                target.terminate()
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                pass
        _gone, alive = psutil.wait_procs(targets, timeout=3.0)
        for target in alive:
            try:
                target.kill()
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                pass
        psutil.wait_procs(alive, timeout=5.0)
    except Exception:
        if process.poll() is None:
            process.kill()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def _contains_visible_progress(chunk: bytes) -> bool:
    """Return whether output contains something a CI reader can actually see."""
    return bool(chunk.translate(None, _IGNORED_ACTIVITY_BYTES))


def _line_reports_progress(line: bytes) -> bool:
    """Distinguish test progress from repeated faulthandler diagnostics."""
    visible = line.translate(None, _IGNORED_ACTIVITY_BYTES).strip()
    if not visible:
        return False
    return not visible.startswith(_DIAGNOSTIC_LINE_PREFIXES)


def _is_pytest_progress_fragment(fragment: bytes) -> bool:
    """Recognize pytest's newline-free per-test progress characters."""
    return bool(fragment) and all(byte in _PYTEST_PROGRESS_BYTES for byte in fragment)


def _forward_process_output(
    process: subprocess.Popen,
    mark_activity,
) -> None:
    """Forward all output while only meaningful test progress renews the deadline."""
    stream = process.stdout
    if stream is None:
        return
    pending = b""
    while True:
        chunk = stream.read1(4096)
        if not chunk:
            if _line_reports_progress(pending):
                mark_activity()
            return
        binary_stdout = getattr(sys.stdout, "buffer", None)
        if binary_stdout is not None:
            binary_stdout.write(chunk)
            binary_stdout.flush()
        else:
            sys.stdout.write(chunk.decode(errors="replace"))
            sys.stdout.flush()
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if _line_reports_progress(line):
                mark_activity()
        if _is_pytest_progress_fragment(pending):
            mark_activity()
            pending = b""


def _file_inactivity_timeout(root: Path, path: Path, default: float) -> float:
    """Return a focused timeout without weakening a stricter caller deadline."""
    relative = path.relative_to(root).as_posix()
    override = _FILE_INACTIVITY_TIMEOUT_OVERRIDES.get(relative)
    return min(default, override) if override is not None else default


def _run_file(
    root: Path,
    path: Path,
    basetemp: Path,
    inactivity_timeout_seconds: float,
) -> int:
    """Run one pytest file until it exits or stops emitting output."""
    process = subprocess.Popen(
        _pytest_command(root, [path], basetemp),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    activity_lock = threading.Lock()
    last_activity_at = time.monotonic()

    def mark_activity() -> None:
        nonlocal last_activity_at
        with activity_lock:
            last_activity_at = time.monotonic()

    output_thread = threading.Thread(
        target=_forward_process_output,
        args=(process, mark_activity),
        name="openwand-ci-pytest-output",
        daemon=True,
    )
    output_thread.start()

    while True:
        with activity_lock:
            inactive_for = time.monotonic() - last_activity_at
        remaining = inactivity_timeout_seconds - inactive_for
        if remaining <= 0:
            print(
                "=== file stopped producing output for "
                f"{inactivity_timeout_seconds:g}s: {path.relative_to(root)} ===",
                flush=True,
            )
            _terminate_process_tree(process)
            output_thread.join(timeout=5.0)
            return _FILE_TIMEOUT_EXIT_CODE
        try:
            status = process.wait(timeout=min(_PROCESS_POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue
        output_thread.join(timeout=5.0)
        return status


def _run_per_file(
    root: Path,
    files: list[Path],
    chunk_index: int,
    *,
    inactivity_timeout_seconds: float = _DEFAULT_FILE_INACTIVITY_TIMEOUT_SECONDS,
) -> int:
    for index, path in enumerate(files, start=1):
        rel_path = path.relative_to(root)
        basetemp = root / (
            f".pytest-tmp-pytest_{os.getpid()}_ci_chunk_{chunk_index}_file_{index:03d}"
        )
        print(f"=== running file {index}/{len(files)}: {rel_path} ===", flush=True)
        file_timeout = _file_inactivity_timeout(
            root,
            path,
            inactivity_timeout_seconds,
        )
        try:
            status = _run_file(root, path, basetemp, file_timeout)
        except KeyboardInterrupt:
            print(f"=== runner interrupted while waiting for file {index}/{len(files)}: {rel_path} ===", flush=True)
            raise
        finally:
            _cleanup_basetemp(root, basetemp)
        print(f"=== file exit code {status}: {rel_path} ===", flush=True)
        if status == _PYTEST_NO_TESTS_COLLECTED:
            print(f"=== file skipped by selection: {rel_path} ===", flush=True)
            continue
        if status != 0:
            return status
    return 0


def _run_chunk(root: Path, files: list[Path], basetemp: Path) -> int:
    try:
        status = subprocess.run(_pytest_command(root, files, basetemp), cwd=root).returncode
    except KeyboardInterrupt:
        print("=== runner interrupted while waiting for pytest chunk ===", flush=True)
        raise
    finally:
        _cleanup_basetemp(root, basetemp)
    print(f"=== chunk exit code {status} ===", flush=True)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunk-total", type=int, default=4)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--per-file", action="store_true")
    parser.add_argument(
        "--per-file-inactivity-timeout-seconds",
        "--per-file-timeout-seconds",
        dest="per_file_inactivity_timeout_seconds",
        type=float,
        default=_DEFAULT_FILE_INACTIVITY_TIMEOUT_SECONDS,
    )
    args = parser.parse_args()

    if args.chunk_total < 1:
        parser.error("--chunk-total must be at least 1")
    if not 1 <= args.chunk_index <= args.chunk_total:
        parser.error("--chunk-index must be between 1 and --chunk-total")
    if args.per_file_inactivity_timeout_seconds <= 0:
        parser.error("--per-file-inactivity-timeout-seconds must be greater than zero")

    root = Path(__file__).resolve().parents[1]
    files = _chunk_files(_test_files(root), args.chunk_index, args.chunk_total)
    if not files:
        print(f"No test files selected for chunk {args.chunk_index}/{args.chunk_total}.")
        return 1

    print(f"CI pytest chunk {args.chunk_index}/{args.chunk_total}: {len(files)} files", flush=True)
    for path in files:
        print(f"  {path.relative_to(root)}", flush=True)

    if args.list_only:
        return 0

    if args.per_file:
        return _run_per_file(
            root,
            files,
            args.chunk_index,
            inactivity_timeout_seconds=args.per_file_inactivity_timeout_seconds,
        )

    basetemp = root / f".pytest-tmp-pytest_{os.getpid()}_ci_chunk_{args.chunk_index}"
    return _run_chunk(root, files, basetemp)


if __name__ == "__main__":
    raise SystemExit(main())
