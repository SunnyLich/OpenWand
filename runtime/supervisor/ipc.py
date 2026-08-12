"""Parent-side worker supervisor and JSON transport."""

from __future__ import annotations

import atexit
import itertools
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from runtime import protocol
from runtime.bootstrap import data_root, repo_root

log = logging.getLogger("openwand.runtime.supervisor")
# Worker stderr echoed into supervisor logging. Kept on its own logger so the
# runtime event log can skip it — stderr lines already reach the event log via
# on_stderr_line listeners, and double-ingesting them would duplicate entries.
stderr_echo_log = logging.getLogger("openwand.worker_stderr")

_STREAM_TOTAL_TIMEOUT_MULTIPLIER = 6.0

_MANAGED_CHILD_MODULES = frozenset(
    {
        # uv-managed Windows virtual environments can launch the real Python
        # interpreter as a child of the venv executable. Track that second
        # process node as part of the same logical worker.
        "runtime.workers.native_host",
        "runtime.workers.ui_host",
        "runtime.workers.brain_host",
        "runtime.workers.audio_host",
        "runtime.workers.hotkey_helper",
        "core.macos_helper.host",
        "core.addon_host",
    }
)


def _is_managed_child_process(process: psutil.Process) -> bool:
    """Return whether a worker child is an internal process that must die with OpenWand.

    Runtime installers, updater helpers, Ollama, and arbitrary addon-launched
    commands are intentionally absent: some of those are designed to survive an
    app restart or have an independent lifecycle.
    """
    try:
        command = tuple(str(part) for part in process.cmdline())
    except (psutil.Error, OSError):
        return False
    return any(module in command for module in _MANAGED_CHILD_MODULES)


def _snapshot_managed_processes(worker_pids: list[int]) -> list[psutil.Process]:
    """Snapshot direct workers and known internal descendants before shutdown.

    The snapshot must happen while parent/child relationships still exist. Once
    a worker exits, an orphaned helper may be re-parented and no longer be
    discoverable from the supervisor on any of the three desktop platforms.
    """
    found: dict[int, psutil.Process] = {}

    def add_internal_tree(process: psutil.Process, *, direct_worker: bool) -> None:
        if process.pid in found:
            return
        if not direct_worker and not _is_managed_child_process(process):
            return
        found[process.pid] = process
        try:
            children = process.children(recursive=False)
        except (psutil.Error, OSError):
            return
        for child in children:
            add_internal_tree(child, direct_worker=False)

    for pid in worker_pids:
        try:
            add_internal_tree(psutil.Process(pid), direct_worker=True)
        except (psutil.Error, OSError, ValueError):
            continue
    return list(found.values())


def _force_stop_managed_processes(
    processes: list[psutil.Process],
    *,
    terminate_timeout: float = 2.0,
    kill_timeout: float = 5.0,
) -> list[int]:
    """Stop survivors from a managed-process snapshot on Windows/macOS/Linux.

    Returns PIDs that were still alive after terminate + kill. ``psutil``
    validates process identity before signalling, which avoids killing an
    unrelated process if the operating system has already reused a PID.
    """
    candidates: list[psutil.Process] = []
    # Descendants were appended after their parent; signal them first so a
    # parent cannot keep a helper alive while it is itself being terminated.
    for process in reversed(processes):
        try:
            if not process.is_running():
                continue
            process.terminate()
            candidates.append(process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            log.warning("Could not terminate managed OpenWand process %s: %s", process.pid, exc)
            candidates.append(process)
    if not candidates:
        return []
    _gone, alive = psutil.wait_procs(candidates, timeout=terminate_timeout)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            log.error("Could not kill managed OpenWand process %s: %s", process.pid, exc)
    _gone, survivors = psutil.wait_procs(alive, timeout=kill_timeout)
    return [process.pid for process in survivors if process.is_running()]


class WorkerError(RuntimeError):
    """A worker call failed, timed out, or the worker is unavailable."""


@dataclass
class WorkerSpec:
    """Store worker spec configuration data."""
    name: str
    module: str
    role: str
    cwd: Path = field(default_factory=repo_root)
    env: dict[str, str] = field(default_factory=dict)
    restart_limit: int = 3
    shutdown_timeout: float = 2.0


class WorkerClient:
    """Spawn, monitor, and talk to one worker process."""

    def __init__(self, spec: WorkerSpec) -> None:
        """Initialize the worker client instance."""
        self.spec = spec
        self._proc: subprocess.Popen | None = None
        self._ids = itertools.count(1)
        self._spawn_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._event_handlers: dict[str, list[Callable[[Any, Any], None]]] = {}
        self._exit_handlers: list[Callable[[int | None], None]] = []
        self._scoped_event_lock = threading.Lock()
        self._scoped_event_handlers: dict[int, Callable[[str, Any, Any], None]] = {}
        self._stderr_tail: deque[str] = deque(maxlen=80)
        self._stderr_listeners: list[Callable[[str], None]] = []
        self._stderr_log_path: Path | None = None
        self._restart_count = 0
        self._shutting_down = False
        atexit.register(self.shutdown)

    def alive(self) -> bool:
        """Handle alive for worker client."""
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        """Handle pid for worker client."""
        return self._proc.pid if self._proc is not None else None

    def start(self) -> None:
        """Spawn the worker subprocess if it is not already running."""
        self._ensure_started()

    def begin_shutdown(self) -> None:
        """Prevent every future call from spawning or restarting this worker.

        This is deliberately a fast state change rather than a process wait.
        The supervisor uses it as an immediate barrier when the UI asks OpenWand to
        quit; the slower graceful termination still happens in ``shutdown``.
        """
        self._shutting_down = True

    def _ensure_started(self) -> None:
        """Ensure started."""
        if self.alive():
            return
        with self._spawn_lock:
            if self.alive():
                return
            if self._shutting_down:
                raise WorkerError(f"{self.spec.name} is shutting down")
            self._spawn()

    def _spawn(self) -> None:
        """Handle spawn for worker client."""
        env = os.environ.copy()
        env.update(self.spec.env)
        env.setdefault("PYTHONUNBUFFERED", "1")
        if "OPENWAND_DATA_ROOT" not in env and "OPENWAND_REPO_ROOT" not in env:
            env["OPENWAND_DATA_ROOT"] = str(data_root())
        env.setdefault("OPENWAND_SUPERVISOR_PID", str(os.getpid()))
        env.setdefault(
            "OPENWAND_SUPERVISOR_CREATE_TIME",
            str(psutil.Process(os.getpid()).create_time()),
        )
        self._stderr_log_path = self._worker_log_path(env)
        log.info("starting %s: %s", self.spec.name, self.spec.module)
        if self._stderr_log_path is not None:
            log.info("%s stderr log: %s", self.spec.name, self._stderr_log_path)
        self._proc = subprocess.Popen(
            [sys.executable, "-m", self.spec.module],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.spec.cwd),
            env=env,
            bufsize=0,
        )
        threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True).start()
        threading.Thread(target=self._stderr_loop, args=(self._proc,), daemon=True).start()

    def _read_loop(self, proc: subprocess.Popen) -> None:
        """Read loop."""
        stdout = proc.stdout
        assert stdout is not None
        while True:
            msg = protocol.read_message(stdout)
            if msg is None:
                break
            if msg.get("event") is not None:
                self._dispatch_event(msg["event"], msg.get("data"), msg.get("id"))
                continue
            rid = msg.get("id")
            if rid is None:
                continue
            with self._pending_lock:
                slot = self._pending.pop(rid, None)
            if slot is not None:
                slot["resp"] = msg
                slot["event"].set()
                wake = slot.get("wake")
                if wake is not None:
                    wake.set()
        with self._spawn_lock:
            if self._proc is proc:
                self._fail_pending("worker exited")
        # stdout EOF arrives before the OS publishes the exit code, so give the
        # process time to finish dying — this thread is dedicated to the worker,
        # so a bounded wait delays nothing. A short wait here used to race the
        # kernel and report exit code None for a process that had a real code.
        returncode = proc.poll()
        if returncode is None:
            try:
                returncode = proc.wait(timeout=10.0)
            except Exception:  # noqa: BLE001
                returncode = proc.poll()
        self._notify_exit(returncode)

    def _stderr_loop(self, proc: subprocess.Popen) -> None:
        """Handle stderr loop for worker client."""
        stderr = proc.stderr
        assert stderr is not None
        log_file = None
        if self._stderr_log_path is not None:
            try:
                self._stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = self._stderr_log_path.open("a", encoding="utf-8")
            except Exception:  # noqa: BLE001
                log.exception("could not open %s stderr log", self.spec.name)
        for raw in iter(stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self._stderr_tail.append(line)
                if log_file is not None:
                    try:
                        log_file.write(line + "\n")
                        log_file.flush()
                    except Exception:
                        pass
                for listener in list(self._stderr_listeners):
                    try:
                        listener(line)
                    except Exception:  # noqa: BLE001 - listener bugs must not kill the reader
                        pass
                if (
                    line.startswith("[plugin]")
                    or line.startswith("[plugin:")
                    or line.startswith("[kokoro install]")
                    or line.startswith("[tts] Kokoro")
                    or line.startswith("[tts] Building Kokoro")
                    or line.startswith("[tts] Installed Kokoro")
                    or line.startswith("[audio] Kokoro warmup")
                    or ("warmup exceeded" in line and line.startswith("[audio]"))
                ):
                    stderr_echo_log.info("[%s] %s", self.spec.name, line)
                else:
                    stderr_echo_log.debug("[%s] %s", self.spec.name, line)
        if log_file is not None:
            log_file.close()

    def _worker_log_path(self, env: dict[str, str]) -> Path | None:
        """Handle worker log path for worker client."""
        root = env.get("OPENWAND_RUN_LOG_DIR")
        if not root:
            return None
        safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in self.spec.name)
        return Path(root) / f"{safe_name}.stderr.log"

    def stderr_tail(self, max_lines: int = 20) -> str:
        """Handle stderr tail for worker client."""
        lines = list(self._stderr_tail)[-max_lines:]
        return "\n".join(lines)

    def _fail_pending(self, error: str) -> None:
        """Handle fail pending for worker client."""
        with self._pending_lock:
            for slot in self._pending.values():
                slot["resp"] = {"ok": False, "error": error}
                slot["event"].set()
                wake = slot.get("wake")
                if wake is not None:
                    wake.set()
            self._pending.clear()

    def _dispatch_event(self, event: str, data: Any, req_id: Any) -> None:
        """Dispatch event."""
        scoped = None
        if req_id is not None:
            with self._scoped_event_lock:
                scoped = self._scoped_event_handlers.get(req_id)
        if scoped is not None:
            try:
                scoped(event, data, req_id)
            except Exception:  # noqa: BLE001
                log.exception("%s scoped event handler failed for %s", self.spec.name, event)
            return
        for handler in list(self._event_handlers.get(event, ())):
            try:
                handler(data, req_id)
            except Exception:  # noqa: BLE001
                log.exception("%s event handler failed for %s", self.spec.name, event)

    def on_event(self, event: str, handler: Callable[[Any, Any], None]) -> None:
        """Handle event events."""
        self._event_handlers.setdefault(event, []).append(handler)

    def on_stderr_line(self, listener: Callable[[str], None]) -> None:
        """Register a callback invoked with every stderr line of this worker."""
        self._stderr_listeners.append(listener)

    def on_exit(self, handler: Callable[[int | None], None]) -> None:
        """Handle exit events."""
        self._exit_handlers.append(handler)

    def _notify_exit(self, returncode: int | None) -> None:
        """Handle notify exit for worker client."""
        for handler in list(self._exit_handlers):
            try:
                handler(returncode)
            except Exception:  # noqa: BLE001
                log.exception("%s exit handler failed", self.spec.name)

    def _write(self, req: dict[str, Any]) -> None:
        """Write a request to the worker's stdin (thread-safe)."""
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise WorkerError(f"{self.spec.name} is not running")
        with self._write_lock:
            try:
                protocol.write_message(proc.stdin, req)
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise WorkerError(f"{self.spec.name} write failed: {exc}") from exc

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        wait: bool = True,
    ) -> Any:
        """Send a request to the worker; await and return the response unless wait=False."""
        self._ensure_started()
        rid = next(self._ids)
        req = protocol.make_request(rid, method, params or {})
        if not wait:
            self._write(req)
            return None

        ev = threading.Event()
        slot: dict[str, Any] = {"event": ev, "resp": None}
        with self._pending_lock:
            self._pending[rid] = slot
        try:
            self._write(req)
        except WorkerError:
            with self._pending_lock:
                self._pending.pop(rid, None)
            raise

        if not ev.wait(timeout):
            with self._pending_lock:
                self._pending.pop(rid, None)
            tail = self.stderr_tail()
            detail = f"{self.spec.name} call {method!r} timed out after {timeout:.1f}s"
            if tail:
                detail += f"\nRecent {self.spec.name} stderr:\n{tail}"
            raise WorkerError(detail)
        resp = slot["resp"] or {"ok": False, "error": "missing response"}
        if not resp.get("ok"):
            raise WorkerError(str(resp.get("error") or f"{method!r} failed"))
        return resp.get("result")

    def call_with_events(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        total_timeout: float | None = None,
        on_event: Callable[[str, Any, Any], None],
        on_started: Callable[[Any], None] | None = None,
    ) -> Any:
        """Call a worker method and route events tagged with its request id.

        Streaming brain methods emit generic names like ``reply.chunk``. Scoped
        routing lets the supervisor decide whether those chunks belong to the
        overlay, chat, auth, or an agent run without changing the wire format.

        ``timeout`` is an inactivity limit: every scoped event renews it.
        ``total_timeout`` is an independent hard limit and defaults to six times
        the inactivity limit. Timed-out brain streams receive a cooperative
        cancellation request instead of being abandoned without notification.
        """
        self._ensure_started()
        rid = next(self._ids)
        req = protocol.make_request(rid, method, params or {})
        ev = threading.Event()
        wake = threading.Event()
        activity_lock = threading.Lock()
        last_activity = time.monotonic()
        idle_timeout = max(0.0, float(timeout))
        hard_timeout = (
            max(0.0, float(total_timeout))
            if total_timeout is not None
            else idle_timeout * _STREAM_TOTAL_TIMEOUT_MULTIPLIER
        )
        hard_timeout = max(idle_timeout, hard_timeout)
        hard_deadline = last_activity + hard_timeout
        slot: dict[str, Any] = {"event": ev, "resp": None, "wake": wake}

        def scoped_event(event: str, data: Any, req_id: Any) -> None:
            nonlocal last_activity
            with activity_lock:
                last_activity = time.monotonic()
            wake.set()
            on_event(event, data, req_id)

        with self._pending_lock:
            self._pending[rid] = slot
        with self._scoped_event_lock:
            self._scoped_event_handlers[rid] = scoped_event
        try:
            try:
                self._write(req)
            except WorkerError:
                with self._pending_lock:
                    self._pending.pop(rid, None)
                raise
            if on_started is not None:
                try:
                    # Publish the cancellable id only after the request is on the
                    # wire. The worker reads requests in order, so an immediate
                    # cancel can now target either its queued or active stream.
                    on_started(rid)
                except Exception:  # noqa: BLE001
                    log.exception("%s stream start callback failed for %s", self.spec.name, method)

            timeout_kind = ""
            while not ev.is_set():
                now = time.monotonic()
                with activity_lock:
                    idle_deadline = last_activity + idle_timeout
                deadline = min(idle_deadline, hard_deadline)
                remaining = deadline - now
                if remaining <= 0:
                    timeout_kind = "total" if hard_deadline <= idle_deadline else "idle"
                    break
                wake.wait(remaining)
                wake.clear()

            if timeout_kind:
                with self._pending_lock:
                    self._pending.pop(rid, None)
                if method.startswith("brain.") and method != "brain.cancel":
                    try:
                        self.call(
                            "brain.cancel",
                            {"target": rid},
                            timeout=5.0,
                        )
                    except Exception:  # noqa: BLE001 - timeout reporting must survive cancel failure
                        log.exception("could not cancel timed-out %s request %s", method, rid)
                tail = self.stderr_tail()
                elapsed_limit = hard_timeout if timeout_kind == "total" else idle_timeout
                detail = (
                    f"{self.spec.name} call {method!r} timed out after "
                    f"{elapsed_limit:.1f}s ({timeout_kind} timeout)"
                )
                if tail:
                    detail += f"\nRecent {self.spec.name} stderr:\n{tail}"
                raise WorkerError(detail)
            resp = slot["resp"] or {"ok": False, "error": "missing response"}
            if not resp.get("ok"):
                raise WorkerError(str(resp.get("error") or f"{method!r} failed"))
            return resp.get("result")
        finally:
            with self._scoped_event_lock:
                self._scoped_event_handlers.pop(rid, None)

    def restart(self) -> None:
        """Handle restart for worker client."""
        with self._spawn_lock:
            if self._shutting_down:
                raise WorkerError(f"{self.spec.name} is shutting down")
            if self._restart_count >= self.spec.restart_limit:
                raise WorkerError(f"{self.spec.name} restart limit exceeded")
            self._restart_count += 1
            self._terminate_locked()
            self._spawn()

    def shutdown(self, *, progress: Callable[[str], None] | None = None) -> None:
        """Handle shutdown for worker client."""
        if progress is not None:
            progress("waiting for spawn lock")
        with self._spawn_lock:
            if progress is not None:
                progress("acquired spawn lock")
            self._shutting_down = True
            self._terminate_locked(progress=progress)

    def _terminate_locked(self, *, progress: Callable[[str], None] | None = None) -> None:
        """Handle terminate locked for worker client."""
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            if progress is not None:
                progress("process already stopped")
            return
        try:
            if progress is not None:
                progress("waiting for write lock")
            with self._write_lock:
                if progress is not None:
                    progress("acquired write lock")
                if proc.stdin and not proc.stdin.closed:
                    if progress is not None:
                        progress("sending shutdown request and closing stdin")
                    protocol.write_message(proc.stdin, protocol.make_request(0, "__shutdown__"))
                    # EOF is the deterministic quit signal: worker stdin readers
                    # unblock on it even if the __shutdown__ request is missed.
                    proc.stdin.close()
                    if progress is not None:
                        progress("shutdown request sent and stdin closed")
        except Exception:  # noqa: BLE001
            pass
        try:
            if progress is not None:
                progress(f"waiting up to {self.spec.shutdown_timeout:g}s for graceful exit")
            proc.wait(timeout=self.spec.shutdown_timeout)
            if progress is not None:
                progress("graceful exit complete")
            return
        except Exception:  # noqa: BLE001 - escalate below, then let supervisor audit survivors
            if progress is not None:
                progress("graceful wait expired; terminating")
            pass
        try:
            proc.terminate()
            if progress is not None:
                progress("terminate sent; waiting up to 2s")
        except Exception:  # noqa: BLE001
            log.warning("Could not terminate %s pid=%s", self.spec.name, proc.pid, exc_info=True)
        try:
            proc.wait(timeout=2.0)
            if progress is not None:
                progress("terminate complete")
            return
        except Exception:  # noqa: BLE001
            if progress is not None:
                progress("terminate wait expired; killing")
            pass
        try:
            proc.kill()
            if progress is not None:
                progress("kill sent; waiting up to 5s")
            proc.wait(timeout=5.0)
            if progress is not None:
                progress("kill complete")
        except Exception:  # noqa: BLE001
            # Do not abort shutdown of the remaining workers. OpenWandSupervisor's
            # cross-platform psutil audit gets one final chance to stop this pid.
            log.error("Could not kill %s pid=%s", self.spec.name, proc.pid, exc_info=True)


def default_specs() -> dict[str, WorkerSpec]:
    """Handle default specs for runtime supervisor ipc."""
    return {
        "native": WorkerSpec("openwand-native", "runtime.workers.native_host", "native"),
        "ui": WorkerSpec("openwand-ui", "runtime.workers.ui_host", "ui"),
        "brain": WorkerSpec("openwand-brain", "runtime.workers.brain_host", "brain"),
        # The audio worker is the isolated subprocess whose whole purpose is to run
        # native CoreAudio/PortAudio off the Qt UI process, so audio must be enabled
        # here regardless of the global macOS safe-mode default — otherwise
        # core.tts.stream_audio drops every chunk and TTS plays silence even though
        # the brain's "Test TTS" (no device gate) reports OK. A crash in this worker
        # only restarts the worker, which is the point of the isolation.
        "audio": WorkerSpec(
            "openwand-audio",
            "runtime.workers.audio_host",
            "audio",
            env={"OPENWAND_MACOS_ENABLE_AUDIO": "1"},
            shutdown_timeout=40.0,
        ),
    }


class OpenWandSupervisor:
    """Owns all pure-Python workers."""

    def __init__(self, specs: dict[str, WorkerSpec] | None = None) -> None:
        """Initialize the openwand supervisor instance."""
        self.workers = {
            name: WorkerClient(spec)
            for name, spec in (specs or default_specs()).items()
        }
        self._managed_snapshot_lock = threading.Lock()
        self._managed_process_snapshot: list[psutil.Process] = []
        self._managed_snapshot_taken = False

    def start_all(self) -> dict[str, Any]:
        """Start all."""
        startup_timeouts = {
            "native": 20.0,
            "ui": 90.0,
            "brain": 90.0,
            "audio": 45.0,
        }
        results: dict[str, Any] = {}
        try:
            for name, worker in self.workers.items():
                results[name] = worker.call(
                    f"{name}.ping",
                    {"value": name},
                    timeout=startup_timeouts.get(name, 30.0),
                )
        except Exception:
            # A later worker may fail after earlier workers have spawned.  The
            # caller cannot safely use a partial process set, so contain the
            # startup transaction and leave no old workers or process locks.
            self.shutdown()
            raise
        return results

    def call(self, worker: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0) -> Any:
        """Call a method on the named worker and return its result."""
        return self.workers[worker].call(method, params, timeout=timeout)

    def begin_shutdown(self, *, capture_managed_processes: bool = True) -> None:
        """Close spawn gates and remember the live owned tree before it can orphan."""
        for worker in self.workers.values():
            begin = getattr(worker, "begin_shutdown", None)
            if callable(begin):
                begin()
        if not capture_managed_processes:
            return
        lock = getattr(self, "_managed_snapshot_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._managed_snapshot_lock = lock
        with lock:
            if getattr(self, "_managed_snapshot_taken", False):
                return
            worker_pids = [
                pid
                for worker in self.workers.values()
                if worker.alive() and (pid := worker.pid) is not None
            ]
            try:
                self._managed_process_snapshot = _snapshot_managed_processes(worker_pids)
            except Exception:  # noqa: BLE001 - worker shutdown must still proceed
                log.exception("Could not snapshot the managed OpenWand process tree during shutdown")
                return
            self._managed_snapshot_taken = True

    def shutdown(
        self,
        *,
        audit_managed_processes: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> list[int]:
        """Gracefully stop every worker, then optionally audit managed survivors."""
        self.begin_shutdown(capture_managed_processes=audit_managed_processes)
        managed_processes = (
            list(getattr(self, "_managed_process_snapshot", []))
            if audit_managed_processes
            else []
        )
        for name, worker in self.workers.items():
            try:
                if progress is None:
                    worker.shutdown()
                else:
                    worker.shutdown(
                        progress=lambda phase, worker_name=name: progress(
                            f"{worker_name}: {phase}"
                        )
                    )
            except Exception:  # noqa: BLE001 - one broken worker must not strand the rest
                log.exception("Worker %s raised during shutdown; continuing", name)
        survivors = (
            _force_stop_managed_processes(managed_processes)
            if audit_managed_processes
            else []
        )
        if survivors:
            log.error("Managed OpenWand processes survived shutdown: %s", ", ".join(map(str, survivors)))
        elif managed_processes:
            log.info("All managed OpenWand worker processes exited")
        return survivors
