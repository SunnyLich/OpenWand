"""Start an already-installed Ollama server when Wisp needs it.

This deliberately does not install Ollama, pull models, or stop a process.  It
only makes the existing local Ollama provider work without asking the user to
open the Ollama app first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
# How long one caller waits for a server it did not find running.
_START_TIMEOUT_SECONDS = 45.0
# A cold `ollama serve` on Windows regularly needs more than 15s before it binds
# its port, so the background watcher keeps waiting after a caller gives up: the
# retry the failure message asks for then meets a server that is already ready.
_READY_WATCH_SECONDS = 120.0
_PROBE_TIMEOUT_SECONDS = 0.75
_POLL_INTERVAL_SECONDS = 0.2
_start_lock = threading.Lock()
# Probe URL -> (ready event, watcher thread) for the launch currently in flight.
_pending_starts: dict[str, tuple[threading.Event, threading.Thread]] = {}


def resolve_ollama_base_url() -> str:
    """Resolve the OpenAI-compatible base URL of the Ollama server.

    Honors Ollama's own ``OLLAMA_HOST`` convention (host, host:port, or URL)
    so Wisp's requests, the readiness probe, and an auto-started ``ollama
    serve`` — which inherits the same environment — all agree on one endpoint.
    """
    raw = os.environ.get("OLLAMA_HOST", "").strip().rstrip("/")
    if not raw:
        return _DEFAULT_BASE_URL
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parts = urlsplit(raw)
        port = parts.port or 11434
    except ValueError:
        return _DEFAULT_BASE_URL
    host = parts.hostname or "localhost"
    if host in ("0.0.0.0", "::"):
        # A bind-everything server address; clients connect over loopback.
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme or 'http'}://{host}:{port}/v1"


OLLAMA_BASE_URL = resolve_ollama_base_url()


def _api_probe_url(base_url: str | None) -> str:
    """Map an OpenAI-compatible base URL onto Ollama's native tags endpoint."""
    base = (base_url or OLLAMA_BASE_URL).strip().rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/tags"


def _is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")


def ollama_is_running(base_url: str | None = None) -> bool:
    """Return whether the Ollama API server is accepting requests."""
    request = urllib.request.Request(_api_probe_url(base_url), method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def find_ollama_executable() -> Path | None:
    """Find a user-installed Ollama executable without requiring PATH setup."""
    configured = os.environ.get("OLLAMA_BIN", "").strip()
    candidates: list[Path] = [Path(configured).expanduser()] if configured else []

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
        candidates.extend(
            Path(folder) / subfolder / "Ollama" / "ollama.exe"
            for folder in (local_app_data, program_files, program_files_x86)
            if folder
            # The Windows installer puts Ollama under "Programs"; older and
            # system-wide installs sit directly in the parent folder.
            for subfolder in ("Programs", ".")
        )
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))

    on_path = shutil.which("ollama")
    if on_path:
        candidates.append(Path(on_path))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _start_ollama(executable: Path) -> None:
    """Launch Ollama's server with no visible console window."""
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(executable), "serve"], **kwargs)  # noqa: S603 -- executable is locally discovered.


def _watch_until_ready(base_url: str | None, ready: threading.Event) -> None:
    """Poll a just-launched server until it answers, off every caller's thread."""
    deadline = time.monotonic() + _READY_WATCH_SECONDS
    while time.monotonic() < deadline:
        if ollama_is_running(base_url):
            ready.set()
            return
        time.sleep(_POLL_INTERVAL_SECONDS)


def _begin_start(base_url: str | None) -> tuple[threading.Event, bool]:
    """Launch Ollama once and return the readiness event callers can wait on.

    The lock covers only the launch, never the wait, so a caller that waits out
    a slow start does not hold back other route probes or model listings.
    """
    key = _api_probe_url(base_url)
    with _start_lock:
        pending = _pending_starts.get(key)
        if pending is not None:
            event, watcher = pending
            if watcher.is_alive():
                # A concurrent caller already launched this server; join its wait
                # instead of starting a second one.
                return event, False
            # The previous watcher gave up, so this call may launch again.
            del _pending_starts[key]

        executable = find_ollama_executable()
        if executable is None:
            raise RuntimeError(
                "Ollama is not running and Wisp could not find an installed Ollama application. "
                "Install Ollama, then try again."
            )
        try:
            _start_ollama(executable)
        except OSError as exc:
            raise RuntimeError(f"Wisp could not start Ollama from {executable}: {exc}") from exc

        ready = threading.Event()
        watcher = threading.Thread(
            target=_watch_until_ready,
            args=(base_url, ready),
            name="ollama-start-watch",
            daemon=True,
        )
        _pending_starts[key] = (ready, watcher)
        watcher.start()
        return ready, True


def _reset_pending_starts() -> None:
    """Forget in-flight launches.  Test hook; production code never calls it."""
    with _start_lock:
        _pending_starts.clear()


def ensure_ollama_running(
    *,
    timeout_seconds: float = _START_TIMEOUT_SECONDS,
    base_url: str | None = None,
) -> bool:
    """Ensure the Ollama API is available, starting installed Ollama if needed.

    Returns ``True`` only when this call launched Ollama.  It never installs or
    terminates Ollama, so another application can keep using the shared server.
    Auto-start applies only to loopback endpoints — launching a local server
    cannot make a remote ``base_url`` reachable.
    """
    if ollama_is_running(base_url):
        return False

    if not _is_local_url(_api_probe_url(base_url)):
        raise RuntimeError(
            f"Ollama at {base_url} is not responding. Wisp only auto-starts a local "
            "Ollama server, so start or check that server, then try again."
        )

    ready, launched = _begin_start(base_url)
    if ready.wait(max(0.0, timeout_seconds)):
        return launched

    raise RuntimeError(
        "Wisp started Ollama, but its local server did not become ready in time. "
        "It may still be starting — try again in a moment, or open Ollama once to check it."
    )
