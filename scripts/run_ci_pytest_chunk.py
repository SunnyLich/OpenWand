"""Run one deterministic chunk of the CI pytest suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_PYTEST_NO_TESTS_COLLECTED = 5
_FILE_TIMEOUT_EXIT_CODE = 124
_DEFAULT_FILE_TIMEOUT_SECONDS = 300.0
_FAULT_HANDLER_TIMEOUT_SECONDS = 60


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


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminate one timed-out pytest process and its worker descendants."""
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


def _run_file(root: Path, path: Path, basetemp: Path, timeout_seconds: float) -> int:
    """Run one pytest file with a hard process-tree deadline."""
    process = subprocess.Popen(_pytest_command(root, [path], basetemp), cwd=root)
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"=== file timed out after {timeout_seconds:g}s: {path.relative_to(root)} ===",
            flush=True,
        )
        _terminate_process_tree(process)
        return _FILE_TIMEOUT_EXIT_CODE


def _run_per_file(
    root: Path,
    files: list[Path],
    chunk_index: int,
    *,
    timeout_seconds: float = _DEFAULT_FILE_TIMEOUT_SECONDS,
) -> int:
    for index, path in enumerate(files, start=1):
        rel_path = path.relative_to(root)
        basetemp = root / f".pytest-tmp-ci-chunk-{chunk_index}-file-{index:03d}"
        print(f"=== running file {index}/{len(files)}: {rel_path} ===", flush=True)
        try:
            status = _run_file(root, path, basetemp, timeout_seconds)
        except KeyboardInterrupt:
            print(f"=== runner interrupted while waiting for file {index}/{len(files)}: {rel_path} ===", flush=True)
            raise
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
    print(f"=== chunk exit code {status} ===", flush=True)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunk-total", type=int, default=4)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--per-file", action="store_true")
    parser.add_argument(
        "--per-file-timeout-seconds",
        type=float,
        default=_DEFAULT_FILE_TIMEOUT_SECONDS,
    )
    args = parser.parse_args()

    if args.chunk_total < 1:
        parser.error("--chunk-total must be at least 1")
    if not 1 <= args.chunk_index <= args.chunk_total:
        parser.error("--chunk-index must be between 1 and --chunk-total")
    if args.per_file_timeout_seconds <= 0:
        parser.error("--per-file-timeout-seconds must be greater than zero")

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
            timeout_seconds=args.per_file_timeout_seconds,
        )

    basetemp = root / f".pytest-tmp-ci-chunk-{args.chunk_index}"
    return _run_chunk(root, files, basetemp)


if __name__ == "__main__":
    raise SystemExit(main())
