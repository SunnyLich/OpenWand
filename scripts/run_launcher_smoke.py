"""Run a real OpenWand launcher until UI/workers are ready, then audit cleanup."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

EXPECTED_WORKERS = frozenset({"native", "ui", "brain", "audio"})
SETTINGS_SMOKE_OLLAMA_MODELS = ("qwen2.5:7b", "llama3.2:3b")


class _FakeOllamaServer:
    """Small local API used to prove Settings fetches Ollama models live."""

    def __init__(self) -> None:
        models = SETTINGS_SMOKE_OLLAMA_MODELS

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                if self.path.rstrip("/") == "/api/tags":
                    payload = {
                        "models": [{"name": model, "model": model} for model in models],
                    }
                elif self.path.rstrip("/") == "/v1/models":
                    payload = {
                        "object": "list",
                        "data": [
                            {
                                "id": model,
                                "object": "model",
                                "created": 0,
                                "owned_by": "ollama",
                            }
                            for model in models
                        ],
                    }
                else:
                    self.send_error(404)
                    return
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="launcher-smoke-fake-ollama",
        )

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _packaged_executable(root: Path) -> Path:
    if sys.platform == "win32":
        return root / "dist" / "OpenWand" / "OpenWand.exe"
    if sys.platform == "darwin":
        return root / "dist" / "OpenWand.app" / "Contents" / "MacOS" / "OpenWand"
    return root / "dist" / "OpenWand" / "OpenWand"


def _source_command(root: Path) -> list[str]:
    if sys.platform == "win32":
        return ["cmd.exe", "/d", "/c", str(root / "Start OpenWand.bat")]
    launcher = root / ("Start OpenWand.command" if sys.platform == "darwin" else "Start OpenWand.sh")
    return ["bash", str(launcher)]


def _process_identity_alive(pid: int, expected_create_time: float) -> bool:
    """Return whether the exact process recorded at readiness is still alive."""
    try:
        import psutil

        process = psutil.Process(pid)
        if abs(process.create_time() - expected_create_time) > 0.01:
            return False
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except ImportError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    except Exception:
        return False


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        import psutil

        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.terminate()
        parent.terminate()
        _gone, alive = psutil.wait_procs([*children, parent], timeout=5)
        for survivor in alive:
            survivor.kill()
        return
    except Exception:
        pass
    try:
        process.kill()
    except OSError:
        pass


def _validate_ready(payload: dict[str, Any], *, frozen: bool) -> dict[str, tuple[int, float]]:
    if payload.get("schema_version") != 1 or payload.get("ready") is not True:
        raise RuntimeError(f"invalid readiness payload: {payload!r}")
    if payload.get("frozen") is not frozen:
        raise RuntimeError(f"wrong runtime kind in readiness payload: {payload!r}")
    if payload.get("ui_overlay_shown") is not True or payload.get("flows_started") is not True:
        raise RuntimeError(f"UI/flow startup was not proven: {payload!r}")
    workers = payload.get("workers")
    if not isinstance(workers, dict) or set(workers) != EXPECTED_WORKERS:
        raise RuntimeError(f"expected all four workers, got: {workers!r}")
    identities: dict[str, tuple[int, float]] = {}
    for name in sorted(EXPECTED_WORKERS):
        row = workers[name]
        if not isinstance(row, dict) or row.get("ping_ok") is not True:
            raise RuntimeError(f"worker {name} did not answer its real ping: {row!r}")
        pid = row.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise RuntimeError(f"worker {name} has no real process id: {row!r}")
        create_time = row.get("create_time")
        if not isinstance(create_time, (int, float)) or create_time <= 0:
            raise RuntimeError(f"worker {name} has no process identity timestamp: {row!r}")
        identities[name] = (pid, float(create_time))
    supervisor_pid = payload.get("supervisor_pid")
    if not isinstance(supervisor_pid, int) or supervisor_pid <= 0:
        raise RuntimeError(f"supervisor has no real process id: {payload!r}")
    supervisor_create_time = payload.get("supervisor_create_time")
    if not isinstance(supervisor_create_time, (int, float)) or supervisor_create_time <= 0:
        raise RuntimeError(f"supervisor has no process identity timestamp: {payload!r}")
    pids = [pid for pid, _create_time in identities.values()]
    if len(set([supervisor_pid, *pids])) != len(pids) + 1:
        raise RuntimeError(f"launcher did not create distinct processes: {payload!r}")
    # communicate() already proved that the supervisor exited with code zero.
    # On Windows its kernel process object can remain queryable until Popen's
    # handle closes, so only the independently managed worker identities need
    # the post-exit survivor audit.
    return identities


def _state_diagnostics(state: Path) -> str:
    """Return bounded runtime artifacts before the temporary state is removed."""
    sections: list[str] = []
    for path in sorted((state / "data" / "build_logs").rglob("*.log")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sections.append(f"\n--- {path.relative_to(state)} ---\n{content[-12000:]}")
    return "".join(sections)[-30000:]


def run_launcher_smoke(
    kind: str,
    *,
    root: Path | None = None,
    executable: Path | None = None,
    source_python: Path | None = None,
    timeout: float = 180.0,
    settings_profile_smoke: bool = False,
) -> dict[str, Any]:
    """Run one real launcher in isolated state and return readiness evidence."""
    root = (root or _repo_root()).resolve()
    if kind not in {"source", "packaged"}:
        raise ValueError(f"unknown launcher kind: {kind}")
    if kind == "source":
        command = _source_command(root)
        frozen = False
    else:
        executable = (executable or _packaged_executable(root)).resolve()
        if not executable.is_file():
            raise FileNotFoundError(f"packaged OpenWand executable not found: {executable}")
        command = [str(executable)]
        frozen = True

    with tempfile.TemporaryDirectory(prefix=f"openwand-{kind}-smoke-") as temporary:
        state = Path(temporary)
        ready_file = state / "ready.json"
        settings_env_path = state / "config" / ".env"
        fake_ollama = _FakeOllamaServer() if settings_profile_smoke else None
        if fake_ollama is not None:
            fake_ollama.start()
            settings_env_path.parent.mkdir(parents=True, exist_ok=True)
            settings_env_path.write_text(
                "\n".join(
                    (
                        "OPENWAND_ONBOARDING_COMPLETE=True",
                        "START_ON_LOGIN=False",
                        "PROFILE_COUNT=1",
                        "PROFILE_1_ID=a",
                        "PROFILE_1_LABEL=A",
                        "PROFILE_1_LLM_PROVIDER=chatgpt",
                        "PROFILE_1_LLM_MODEL=gpt-5.5",
                        "PROFILE_1_BUBBLE_WIDTH=340",
                        "PROFILE_1_STT_BEAM_SIZE=4",
                        "PROFILE_1_MEMORY_TOP_K=9",
                        "PROFILE_1_CONTEXT_BROWSER_MAX_CHARS=9999",
                        "ACTIVE_PROFILE=a",
                        "SETTINGS_PROFILE=a",
                        "LLM_PROVIDER=chatgpt",
                        "LLM_MODEL=gpt-5.5",
                        "VISION_LLM_PROVIDER=chatgpt",
                        "VISION_LLM_MODEL=gpt-5.5",
                        "MEMORY_LLM_PROVIDER=chatgpt",
                        "MEMORY_LLM_MODEL=gpt-5.5",
                        "BUBBLE_WIDTH=340",
                        "STT_BEAM_SIZE=4",
                        "MEMORY_TOP_K=9",
                        "CONTEXT_BROWSER_MAX_CHARS=9999",
                        "",
                    )
                ),
                encoding="utf-8",
            )
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": str(root),
                "QT_QPA_PLATFORM": "offscreen",
                "OPENWAND_ADDONS_DIR": str(state / "addons"),
                "OPENWAND_BRAIN_FAKE_LLM": "1",
                "OPENWAND_LAUNCH_SMOKE_DISABLE_AUTOSTART_SYNC": "1",
                "OPENWAND_LAUNCH_SMOKE_EXIT_AFTER_READY": "1",
                "OPENWAND_LAUNCH_SMOKE_READY_FILE": str(ready_file),
                "OPENWAND_MACOS_SAFE_MODE": "1",
                "OPENWAND_DATA_ROOT": str(state / "data"),
                "OPENWAND_RUNTIME_LOG_MODE": "crash",
                "OPENWAND_USER_DATA_DIR": str(state / "user-data"),
            }
        )
        if fake_ollama is not None:
            env.update(
                {
                    "OLLAMA_HOST": fake_ollama.host,
                    "OPENWAND_LAUNCH_SMOKE_OLLAMA_MODELS": ",".join(SETTINGS_SMOKE_OLLAMA_MODELS),
                    "OPENWAND_LAUNCH_SMOKE_SETTINGS_PROFILE": "1",
                    "OPENWAND_SETTINGS_ENV_PATH": str(settings_env_path),
                    "OPENWAND_UI_DEBUG_METHODS": "1",
                }
            )
        if kind == "source":
            env["OPENWAND_LAUNCH_PYTHON"] = str((source_python or Path(sys.executable)).resolve())
        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            process = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=sys.platform != "win32",
            )
            try:
                output, _ = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                _stop_process_tree(process)
                output, _ = process.communicate(timeout=10)
                raise RuntimeError(
                    f"{kind} launcher did not reach readiness within {timeout:.0f}s\n{output[-8000:]}"
                ) from exc
            if process.returncode != 0:
                diagnostics = _state_diagnostics(state)
                raise RuntimeError(
                    f"{kind} launcher exited {process.returncode}\n{output[-8000:]}{diagnostics}"
                )
            if not ready_file.is_file():
                diagnostics = _state_diagnostics(state)
                raise RuntimeError(
                    f"{kind} launcher exited without readiness evidence\n{output[-8000:]}{diagnostics}"
                )
            payload = json.loads(ready_file.read_text(encoding="utf-8"))
            identities = _validate_ready(payload, frozen=frozen)
            deadline = time.monotonic() + 10.0
            survivors = {
                name: pid
                for name, (pid, create_time) in identities.items()
                if _process_identity_alive(pid, create_time)
            }
            while survivors and time.monotonic() < deadline:
                time.sleep(0.1)
                survivors = {
                    name: pid
                    for name, (pid, create_time) in identities.items()
                    if _process_identity_alive(pid, create_time)
                }
            if survivors:
                raise RuntimeError(f"{kind} launcher left managed processes running: {survivors}")
            payload["clean_shutdown"] = True
            payload["launcher_kind"] = kind
            return payload
        finally:
            if fake_ollama is not None:
                fake_ollama.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("source", "packaged"), required=True)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--source-python", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--settings-profile-smoke",
        action="store_true",
        help="Drive the real Settings dialog through profile save/reopen and Ollama model fetch.",
    )
    args = parser.parse_args(argv)
    payload = run_launcher_smoke(
        args.kind,
        executable=args.executable,
        source_python=args.source_python,
        timeout=args.timeout,
        settings_profile_smoke=args.settings_profile_smoke,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
