"""Focus-free, deliberately limited checks for Virtual Workspace files.

This module is *not* a security sandbox.  It avoids executing generated source
code and does not accept arbitrary commands.  The supported operations only
parse or compile workspace-owned files:

* Python syntax compilation (``py_compile`` in isolated interpreter mode)
* JavaScript syntax checking (``node --check`` when Node.js is installed)
* JSON parsing (a fixed isolated-Python helper)

Processes have no console window, receive no stdin, use a reduced environment,
and are stopped on cancellation, timeout, or excessive output.  A VM/container
is still required before Wisp can honestly offer arbitrary untrusted program
execution with host and network isolation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SECURITY_NOTICE = (
    "Limited validation only; this is not a security sandbox and does not run "
    "generated source code. Arbitrary execution requires a VM or container."
)


class LimitedCheck(StrEnum):
    """Checks that cannot be replaced with an arbitrary command."""

    PYTHON_SYNTAX = "python_syntax"
    JAVASCRIPT_SYNTAX = "javascript_syntax"
    JSON = "json"


@dataclass(frozen=True)
class CheckRequest:
    """A typed request for one or more files inside the workspace."""

    check: LimitedCheck
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    """Result returned by :class:`LimitedWorkspaceRunner`."""

    check: LimitedCheck
    paths: tuple[str, ...]
    ok: bool
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False
    cancelled: bool = False
    output_limit_exceeded: bool = False
    unavailable: bool = False
    security_notice: str = SECURITY_NOTICE

    @property
    def summary(self) -> str:
        """Return a concise, user-facing outcome."""
        if self.unavailable:
            return f"{self.check.value} checker is unavailable"
        if self.cancelled:
            return f"{self.check.value} check cancelled"
        if self.timed_out:
            return f"{self.check.value} check timed out"
        if self.output_limit_exceeded:
            return f"{self.check.value} check stopped: output limit exceeded"
        return f"{self.check.value} check {'passed' if self.ok else 'failed'}"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable result for the authenticated viewer."""
        return {
            "check": self.check.value,
            "paths": list(self.paths),
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "output_limit_exceeded": self.output_limit_exceeded,
            "unavailable": self.unavailable,
            "summary": self.summary,
            "security_notice": self.security_notice,
        }


class LimitedRunHandle:
    """Handle for a non-blocking check started with ``submit``."""

    def __init__(self, cancel_event: threading.Event):
        self._cancel_event = cancel_event
        self._done = threading.Event()
        self._result: CheckResult | None = None
        self._error: BaseException | None = None

    def cancel(self) -> None:
        """Request cancellation; a running checker is terminated promptly."""
        self._cancel_event.set()

    @property
    def done(self) -> bool:
        """Return whether the background check finished."""
        return self._done.is_set()

    def result(self, timeout: float | None = None) -> CheckResult:
        """Wait for and return the check result."""
        if not self._done.wait(timeout):
            raise TimeoutError("The workspace check is still running.")
        if self._error is not None:
            raise self._error
        if self._result is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("The workspace check ended without a result.")
        return self._result

    def _finish(self, result: CheckResult) -> None:
        self._result = result
        self._done.set()

    def _fail(self, error: BaseException) -> None:
        self._error = error
        self._done.set()


class LimitedWorkspaceRunner:
    """Run syntax/data checks without using the user's terminal or focus.

    The runner deliberately exposes typed checks instead of a command string or
    argv API.  Resolved inputs must be regular, non-symlink files underneath
    ``workspace_root``.  This prevents path escape but is not process isolation.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 64 * 1024,
        max_file_bytes: int = 8 * 1024 * 1024,
        max_files: int = 50,
    ):
        self.root = Path(workspace_root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        if max_output_bytes < 1024 or max_output_bytes > 1024 * 1024:
            raise ValueError("max_output_bytes must be between 1 KiB and 1 MiB")
        if max_file_bytes < 1024 or max_file_bytes > 64 * 1024 * 1024:
            raise ValueError("max_file_bytes must be between 1 KiB and 64 MiB")
        if max_files < 1 or max_files > 100:
            raise ValueError("max_files must be between 1 and 100")
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = int(max_output_bytes)
        self.max_file_bytes = int(max_file_bytes)
        self.max_files = int(max_files)

    def run(
        self,
        request: CheckRequest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> CheckResult:
        """Run one typed check and block only the calling/background thread."""
        started = time.monotonic()
        paths = self._validate_request(request)
        display_paths = tuple(path.relative_to(self.root).as_posix() for path in paths)
        command = self._build_command(request.check, paths)
        if command is None:
            return CheckResult(
                check=request.check,
                paths=display_paths,
                ok=False,
                returncode=None,
                stdout="",
                stderr="Required checker is not installed.",
                elapsed_seconds=time.monotonic() - started,
                unavailable=True,
            )
        return self._run_process(
            request.check,
            display_paths,
            command,
            cancel_event=cancel_event or threading.Event(),
            started=started,
        )

    def submit(
        self,
        request: CheckRequest,
        *,
        callback: Callable[[CheckResult], None] | None = None,
    ) -> LimitedRunHandle:
        """Start a check on a daemon thread and return immediately."""
        cancel_event = threading.Event()
        handle = LimitedRunHandle(cancel_event)

        def worker() -> None:
            try:
                result = self.run(request, cancel_event=cancel_event)
                handle._finish(result)
                if callback is not None:
                    callback(result)
            except BaseException as exc:  # preserve validation failures for caller
                handle._fail(exc)

        threading.Thread(
            target=worker,
            name=f"wisp-workspace-check-{request.check.value}",
            daemon=True,
        ).start()
        return handle

    def _validate_request(self, request: CheckRequest) -> tuple[Path, ...]:
        if not isinstance(request.check, LimitedCheck):
            raise ValueError("Unsupported workspace check")
        if not request.paths:
            raise ValueError("At least one file is required")
        if len(request.paths) > self.max_files:
            raise ValueError(f"At most {self.max_files} files may be checked at once")
        expected_suffix = {
            LimitedCheck.PYTHON_SYNTAX: ".py",
            LimitedCheck.JAVASCRIPT_SYNTAX: (".js", ".cjs", ".mjs"),
            LimitedCheck.JSON: ".json",
        }[request.check]
        resolved: list[Path] = []
        seen: set[Path] = set()
        for raw_path in request.paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError("Workspace file paths must be non-empty strings")
            candidate = Path(raw_path)
            if candidate.is_absolute():
                raise ValueError("Workspace file paths must be relative")
            unresolved = self.root / candidate
            if self._contains_symlink(unresolved):
                raise ValueError(f"Symlink paths are not allowed: {raw_path}")
            try:
                path = unresolved.resolve(strict=True)
                path.relative_to(self.root)
            except (OSError, ValueError) as exc:
                raise ValueError(f"File is outside the workspace or missing: {raw_path}") from exc
            if not path.is_file():
                raise ValueError(f"Not a regular file: {raw_path}")
            if path.suffix.lower() not in (
                (expected_suffix,) if isinstance(expected_suffix, str) else expected_suffix
            ):
                raise ValueError(f"Wrong file type for {request.check.value}: {raw_path}")
            if path.stat().st_size > self.max_file_bytes:
                raise ValueError(f"File exceeds the {self.max_file_bytes}-byte limit: {raw_path}")
            if path not in seen:
                resolved.append(path)
                seen.add(path)
        return tuple(resolved)

    def _contains_symlink(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return True
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False

    def _build_command(self, check: LimitedCheck, paths: tuple[Path, ...]) -> list[str] | None:
        if check is LimitedCheck.PYTHON_SYNTAX:
            return [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-m",
                "py_compile",
                *(str(path) for path in paths),
            ]
        if check is LimitedCheck.JSON:
            helper = (
                "import json,sys; "
                "[(json.load(open(p, encoding='utf-8'))) for p in sys.argv[1:]]"
            )
            return [sys.executable, "-I", "-S", "-B", "-c", helper, *(str(path) for path in paths)]
        node = shutil.which("node")
        if not node:
            return None
        # Node accepts one input per --check call, so multiple files are checked
        # sequentially by fixed invocations in order.
        if len(paths) > 1:
            raise ValueError("JavaScript syntax checks currently accept one file at a time")
        return [node, "--check", str(paths[0])]

    def _run_process(
        self,
        check: LimitedCheck,
        display_paths: tuple[str, ...],
        command: list[str],
        *,
        cancel_event: threading.Event,
        started: float,
    ) -> CheckResult:
        startupinfo = None
        creationflags = 0
        popen_kwargs: dict[str, object] = {}
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(
            command,
            cwd=str(self.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=self._reduced_environment(),
            startupinfo=startupinfo,
            creationflags=creationflags,
            **popen_kwargs,
        )
        chunks = {"stdout": bytearray(), "stderr": bytearray()}
        output_limit = threading.Event()
        chunk_lock = threading.Lock()

        def drain(name: str, stream: object) -> None:
            if stream is None:
                return
            while True:
                data = stream.read(4096)  # type: ignore[attr-defined]
                if not data:
                    break
                with chunk_lock:
                    used = len(chunks["stdout"]) + len(chunks["stderr"])
                    remaining = max(0, self.max_output_bytes - used)
                    if remaining:
                        chunks[name].extend(data[:remaining])
                    if len(data) > remaining:
                        output_limit.set()

        readers = [
            threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        cancelled = False
        while process.poll() is None:
            if cancel_event.is_set():
                cancelled = True
                self._terminate(process)
                break
            if output_limit.is_set():
                self._terminate(process)
                break
            if time.monotonic() - started >= self.timeout_seconds:
                timed_out = True
                self._terminate(process)
                break
            time.sleep(0.02)
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)
        for reader in readers:
            reader.join(timeout=1.0)

        stdout = bytes(chunks["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(chunks["stderr"]).decode("utf-8", errors="replace")
        limit_exceeded = output_limit.is_set()
        return CheckResult(
            check=check,
            paths=display_paths,
            ok=process.returncode == 0 and not (timed_out or cancelled or limit_exceeded),
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=time.monotonic() - started,
            timed_out=timed_out,
            cancelled=cancelled,
            output_limit_exceeded=limit_exceeded,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        try:
            process.terminate()
            process.wait(timeout=0.4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    @staticmethod
    def _reduced_environment() -> dict[str, str]:
        env = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        if os.name == "nt":
            for name in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
                value = os.environ.get(name)
                if value:
                    env[name] = value
        else:
            env["PATH"] = "/usr/bin:/bin"
        return env
