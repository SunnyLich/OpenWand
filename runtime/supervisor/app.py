"""Pure-Python app supervisor entrypoint."""

from __future__ import annotations

import json
import logging
import os
import runpy
import shutil
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

import psutil

from core.system import single_instance
from runtime.bootstrap import (
    data_root,
    install_crash_diagnostics,
    suppress_console_ctrl_c,
)
from runtime.supervisor.flows import FlowController
from runtime.supervisor.ipc import OpenWandSupervisor
from runtime.supervisor.runtime_log import RuntimeEventLog, RuntimeLogHandler

RUNTIME_LOG_RETENTION_DAYS = 7
_RUNTIME_LOG_DIR_PREFIXES = ("openwand_runtime_", "openwand_crash_")


def _run_real_settings_smoke(supervisor: OpenWandSupervisor) -> dict[str, object] | None:
    """Exercise the production Settings dialog when launcher acceptance opts in."""
    if os.environ.get("OPENWAND_LAUNCH_SMOKE_SETTINGS_PROFILE") != "1":
        return None

    def call(action: str, **params: str) -> dict[str, object]:
        result = supervisor.call(
            "ui",
            "ui.debug.settings.action",
            {"action": action, **params},
            timeout=45.0,
        )
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError(f"real Settings action {action!r} failed: {result!r}")
        return result

    def wait_open(expected: bool, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last: object = None
        while time.monotonic() < deadline:
            last = supervisor.call("ui", "ui.settings.is_open", timeout=10.0)
            if isinstance(last, dict) and bool(last.get("open")) is expected:
                return
            time.sleep(0.05)
        raise RuntimeError(f"real Settings open state did not become {expected}: {last!r}")

    def open_settings() -> dict[str, object]:
        supervisor.call("ui", "ui.show_settings", timeout=10.0)
        wait_open(True)
        return call("snapshot")

    def close_settings() -> None:
        call("close")
        wait_open(False)

    def require(condition: bool, message: str, evidence: object) -> None:
        if not condition:
            raise RuntimeError(f"{message}: {evidence!r}")

    initial = open_settings()
    require(initial.get("profile_id") == "a", "Settings did not open on profile A", initial)
    require(initial.get("save_enabled") is False, "clean profile A unexpectedly enabled Save", initial)

    import config as runtime_config

    runtime_before_selection = {
        "active_profile": str(getattr(runtime_config, "ACTIVE_PROFILE", "")),
        "bubble_width": str(getattr(runtime_config, "BUBBLE_WIDTH", "")),
    }
    low_selected = call("select_profile", profile_id="low_setup")
    require(
        low_selected.get("profile_id") == "low_setup",
        "Low setup selection did not become active in Settings",
        low_selected,
    )
    require(
        low_selected.get("save_enabled") is True,
        "profile-only selection did not enable Save",
        low_selected,
    )
    forbidden_status_words = ("low setup", "selected", "detected", "profile")
    require(
        not any(
            word in str(low_selected.get("status") or "").casefold()
            for word in forbidden_status_words
        )
        and not str(low_selected.get("status_tooltip") or ""),
        "Settings displayed redundant profile-selection status",
        low_selected,
    )
    require(
        low_selected.get("stt_beam_size") == "1"
        and low_selected.get("memory_top_k") == "2"
        and low_selected.get("context_browser_max_chars") == "3000",
        "Low setup did not repopulate Settings fields across pages",
        low_selected,
    )

    from core.system.env_utils import read_env_file

    env_path = Path(str(os.environ["OPENWAND_SETTINGS_ENV_PATH"])).resolve()
    staged_root_values = read_env_file(env_path)
    staged_before_save = {
        "disk_active_profile": staged_root_values.get("ACTIVE_PROFILE"),
        "disk_settings_profile": staged_root_values.get("SETTINGS_PROFILE"),
        "disk_bubble_width": staged_root_values.get("BUBBLE_WIDTH"),
        "runtime_before_selection": runtime_before_selection,
        "runtime_after_selection": {
            "active_profile": str(getattr(runtime_config, "ACTIVE_PROFILE", "")),
            "bubble_width": str(getattr(runtime_config, "BUBBLE_WIDTH", "")),
        },
    }
    require(
        staged_before_save["disk_active_profile"] == "a"
        and staged_before_save["disk_settings_profile"] == "a"
        and staged_before_save["disk_bubble_width"] == "340"
        and staged_before_save["runtime_after_selection"] == runtime_before_selection,
        "selecting a profile applied it before Save changes",
        staged_before_save,
    )

    call("select_provider", provider="ollama")
    expected_models = {
        item.strip()
        for item in str(os.environ.get("OPENWAND_LAUNCH_SMOKE_OLLAMA_MODELS") or "").split(",")
        if item.strip()
    }
    deadline = time.monotonic() + 30.0
    ollama_loaded: dict[str, object] = {}
    while time.monotonic() < deadline:
        ollama_loaded = call("snapshot")
        choices = {str(item) for item in ollama_loaded.get("model_choices") or []}
        if (
            ollama_loaded.get("provider") == "ollama"
            and not ollama_loaded.get("model_refresh_busy")
            and expected_models.issubset(choices)
        ):
            break
        time.sleep(0.05)
    choices = {str(item) for item in ollama_loaded.get("model_choices") or []}
    require(
        bool(expected_models) and expected_models.issubset(choices),
        "real Settings did not fetch the installed Ollama model list",
        ollama_loaded,
    )
    require(
        "ollama" not in set(ollama_loaded.get("connection_providers") or []),
        "Ollama was incorrectly represented as a credential connection",
        ollama_loaded,
    )

    selected_model = sorted(expected_models)[0]
    call("select_model", model=selected_model)
    call("set_bubble_width", value="222")
    low_saved = call("save")
    require(
        low_saved.get("save_was_enabled") is True and low_saved.get("save_enabled") is False,
        "Save did not persist and clear the Low setup dirty state",
        low_saved,
    )

    close_settings()
    reopened_low = open_settings()
    require(
        reopened_low.get("profile_id") == "low_setup",
        "Settings bounced back to profile A after saving Low setup",
        reopened_low,
    )
    require(
        reopened_low.get("provider") == "ollama"
        and reopened_low.get("model") == selected_model
        and reopened_low.get("bubble_width") == "222",
        "saved Low setup values did not survive a real dialog reopen",
        reopened_low,
    )

    profile_a = call("select_profile", profile_id="a")
    require(
        profile_a.get("bubble_width") == "340",
        "profile A did not retain its isolated value",
        profile_a,
    )
    call("set_bubble_width", value="444")
    profile_a_saved = call("save")
    require(
        profile_a_saved.get("profile_id") == "a"
        and profile_a_saved.get("save_enabled") is False,
        "profile A did not save as the active profile",
        profile_a_saved,
    )

    close_settings()
    reopened_a = open_settings()
    require(
        reopened_a.get("profile_id") == "a"
        and reopened_a.get("bubble_width") == "444",
        "profile A did not survive a real dialog reopen",
        reopened_a,
    )
    low_again = call("select_profile", profile_id="low_setup")
    require(
        low_again.get("bubble_width") == "222"
        and low_again.get("provider") == "ollama"
        and low_again.get("model") == selected_model,
        "Low setup was contaminated by profile A",
        low_again,
    )
    a_again = call("select_profile", profile_id="a")
    from core import settings_profiles

    final_profile_files = {
        "a": settings_profiles.read_profile(env_path, "a"),
        "low_setup": settings_profiles.read_profile(env_path, "low_setup"),
    }
    require(
        a_again.get("bubble_width") == "444",
        "profile A was contaminated by Low setup",
        {"ui": a_again, "disk": final_profile_files},
    )

    root_values = read_env_file(env_path)
    a_values = final_profile_files["a"]
    low_values = final_profile_files["low_setup"]
    require(
        root_values.get("ACTIVE_PROFILE") == "a"
        and root_values.get("SETTINGS_PROFILE") == "a",
        "root config did not persist profile A as active",
        root_values,
    )
    require(
        a_values.get("BUBBLE_WIDTH") == "444"
        and low_values.get("BUBBLE_WIDTH") == "222",
        "profile files did not remain isolated",
        {"a": a_values, "low_setup": low_values},
    )
    close_settings()
    return {
        "real_process_ui": True,
        "initial": initial,
        "low_selected": low_selected,
        "staged_before_save": staged_before_save,
        "ollama_loaded": ollama_loaded,
        "low_saved": low_saved,
        "reopened_low": reopened_low,
        "profile_a_saved": profile_a_saved,
        "reopened_a": reopened_a,
        "low_again": low_again,
        "a_again": a_again,
        "persisted": {
            "active_profile": root_values.get("ACTIVE_PROFILE"),
            "settings_profile": root_values.get("SETTINGS_PROFILE"),
            "a_bubble_width": a_values.get("BUBBLE_WIDTH"),
            "low_setup_bubble_width": low_values.get("BUBBLE_WIDTH"),
            "low_setup_provider": low_values.get("LLM_PROVIDER"),
            "low_setup_model": low_values.get("LLM_MODEL"),
            "profile_files": sorted(
                path.name
                for path in settings_profiles.profiles_directory(env_path).glob("*.env")
            ),
        },
    }


def _write_launch_smoke_ready(
    supervisor: OpenWandSupervisor,
    startup_results: dict[str, object],
    hotkey_result: dict[str, object],
) -> bool:
    """Publish opt-in process-level startup evidence for launcher smoke tests."""
    configured = str(os.environ.get("OPENWAND_LAUNCH_SMOKE_READY_FILE") or "").strip()
    if not configured:
        return False
    path = Path(configured).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings_smoke = _run_real_settings_smoke(supervisor)
    supervisor_process = psutil.Process(os.getpid())
    payload = {
        "schema_version": 1,
        "ready": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "supervisor_pid": os.getpid(),
        "supervisor_create_time": supervisor_process.create_time(),
        "ui_overlay_shown": True,
        "flows_started": True,
        "hotkeys": hotkey_result,
        "workers": {
            name: {
                "pid": worker.pid,
                "create_time": psutil.Process(worker.pid).create_time(),
                "ping_ok": bool(startup_results.get(name)),
            }
            for name, worker in supervisor.workers.items()
        },
    }
    if settings_smoke is not None:
        payload["settings_profile_smoke"] = settings_smoke
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)
    logging.info("OpenWand launch smoke reached real UI/worker readiness: %s", path)
    return True


def _dispatch_module_mode() -> None:
    """Let a frozen supervisor executable emulate ``python -m module`` workers."""
    if len(sys.argv) >= 3 and sys.argv[1] == "-m":
        module = sys.argv[2]
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        raise SystemExit(0)


def _runtime_log_mode() -> str:
    """Return the supervisor log mode: debug keeps logs, crash writes on failure."""
    mode = str(os.environ.get("OPENWAND_RUNTIME_LOG_MODE") or "").strip().lower()
    if mode in {"debug", "always", "logs", "log"}:
        return "debug"
    if mode in {"crash", "off", "none", "0", "false"}:
        return "crash"
    if os.environ.get("OPENWAND_RUN_LOG_DIR"):
        return "debug"
    if getattr(sys, "frozen", False):
        return "debug"
    return "crash"


def _prune_runtime_logs(log_root: Path | None = None, *, now: float | None = None) -> int:
    """Remove OpenWand runtime log artifacts older than the retention window."""
    root = log_root if log_root is not None else data_root() / "build_logs"
    if not root.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - (RUNTIME_LOG_RETENTION_DAYS * 24 * 60 * 60)
    removed = 0

    def expired(path: Path) -> bool:
        """Return True when *path* is older than the retention cutoff."""
        try:
            return path.stat().st_mtime < cutoff
        except OSError:
            return False

    try:
        children = list(root.iterdir())
    except OSError:
        return 0

    for child in children:
        try:
            if child.is_dir() and child.name.startswith(_RUNTIME_LOG_DIR_PREFIXES) and expired(child):
                shutil.rmtree(child)
                removed += 1
        except OSError:
            continue

    ui_root = root / "ui_runtime"
    if ui_root.is_dir():
        try:
            ui_children = list(ui_root.iterdir())
        except OSError:
            ui_children = []
        for child in ui_children:
            try:
                if expired(child):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    removed += 1
            except OSError:
                continue
        try:
            ui_root.rmdir()
        except OSError:
            pass

    return removed


def _prepare_run_log_dir(*, reason: str = "runtime", expose_to_workers: bool = True) -> Path:
    """Create a runtime log directory when debug logs or crash logs are needed."""
    configured = os.environ.get("OPENWAND_RUN_LOG_DIR")
    if configured:
        path = Path(configured)
    else:
        root = data_root()
        _prune_runtime_logs(root / "build_logs")
        prefix = "openwand_runtime" if reason == "runtime" else "openwand_crash"
        path = root / "build_logs" / f"{prefix}_{time.strftime('%Y%m%d-%H%M%S')}"
        if expose_to_workers:
            os.environ["OPENWAND_RUN_LOG_DIR"] = str(path)
        latest = root / "build_logs" / "latest_openwand_runtime.txt"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(str(path), encoding="utf-8")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configure_logging(log_dir: Path | None) -> None:
    """Configure supervisor logging, optionally mirrored to a file."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        handlers.append(logging.FileHandler(log_dir / "supervisor.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def _write_abrupt_log(reason: str, supervisor: OpenWandSupervisor | None, exc_info=None) -> Path | None:
    """Best-effort crash-only log writer for normal launcher runs."""
    try:
        log_dir = _prepare_run_log_dir(reason="crash", expose_to_workers=False)
        report = log_dir / "supervisor-crash.log"
        lines = [
            f"OpenWand ended abruptly: {reason}",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        if exc_info is not None:
            lines.append("Exception:")
            lines.extend(traceback.format_exception(*exc_info))
            lines.append("")
        if supervisor is not None:
            lines.append("Worker stderr tails:")
            for name, worker in supervisor.workers.items():
                tail = worker.stderr_tail(80) if hasattr(worker, "stderr_tail") else ""
                lines.append(f"\n[{name}]")
                lines.append(tail or "(no recent stderr)")
        report.write_text("\n".join(lines), encoding="utf-8")
        return log_dir
    except Exception:  # noqa: BLE001
        return None


def _resume_staged_optional_installs() -> None:
    """Resume staged installs and prune inactive package-swap leftovers."""
    try:
        from scripts.optional_tts_installer import (
            cleanup_stale_optional_package_swaps,
            resume_pending_staged_applies,
        )

        resumed = resume_pending_staged_applies()
        if resumed:
            logging.info("Re-armed %d staged optional package install(s)", resumed)
        removed, failed = cleanup_stale_optional_package_swaps()
        if removed:
            logging.info(
                "Removed %d stale optional package swap folder(s): %s",
                len(removed),
                ", ".join(path.name for path in removed),
            )
        for path, error in failed.items():
            logging.warning("Could not remove stale optional package swap folder %s: %s", path, error)
    except Exception:
        logging.warning("Could not maintain staged optional package installs", exc_info=True)


def main() -> int:
    # Synthetic copy-Ctrl+C (selected-text capture) reaches the whole console
    # process group; without this the supervisor's SIGINT handler would treat it
    # as a quit and tear the app down. Workers are guarded via configure_paths().
    """Handle main for runtime supervisor app."""
    suppress_console_ctrl_c()
    install_crash_diagnostics()
    # Claim process ownership before log pruning, autostart synchronization, or
    # worker construction. A duplicate launcher exits without changing shared
    # state or briefly creating a second OpenWand worker tree.
    if not single_instance.acquire():
        logging.warning(
            "Another OpenWand instance is already running, or exclusivity could not be established; exiting."
        )
        return 2
    from core.system.paths import USER_DATA_DIR

    os.environ.setdefault(
        "OPENWAND_ACTION_TRACE_PATH",
        str(USER_DATA_DIR / "logs" / "action-timings.jsonl"),
    )
    log_mode = _runtime_log_mode()
    _prune_runtime_logs()
    log_dir = _prepare_run_log_dir() if log_mode == "debug" else None
    _configure_logging(log_dir)
    # Every log surface funnels into one runtime event log so the Runtime
    # Status window can show all of it: supervisor logging (via the handler
    # below), worker stderr (via on_stderr_line), bubble notices, installer
    # statuses, and setup-check results (via FlowController).
    runtime_log = RuntimeEventLog()
    logging.getLogger().addHandler(RuntimeLogHandler(runtime_log))
    if log_dir is not None:
        logging.info("OpenWand runtime logs: %s", log_dir)
    else:
        logging.info("OpenWand runtime logs are off; crash logs will be written only if startup ends abruptly.")
    try:
        import config
        from core.system.autostart import sync_start_on_login

        if os.environ.get("OPENWAND_LAUNCH_SMOKE_DISABLE_AUTOSTART_SYNC") != "1":
            sync_start_on_login(bool(getattr(config, "START_ON_LOGIN", False)))
    except Exception:
        logging.warning("Could not sync launch-at-login setting", exc_info=True)
    _resume_staged_optional_installs()
    supervisor = OpenWandSupervisor()
    for worker_name, worker in supervisor.workers.items():
        if hasattr(worker, "on_stderr_line"):
            worker.on_stderr_line(runtime_log.stderr_sink(worker_name))
    flows: FlowController | None = None
    stop = threading.Event()
    ui_quit_requested = threading.Event()
    abrupt_reason = ""

    def _close_worker_spawn_gate() -> None:
        """Prevent late startup/background calls from recreating workers."""
        begin_shutdown = getattr(supervisor, "begin_shutdown", None)
        if callable(begin_shutdown):
            begin_shutdown()

    def _stop(_signum=None, _frame=None) -> None:
        """Signal handler: set the stop event to trigger shutdown."""
        _close_worker_spawn_gate()
        stop.set()

    def _stop_when_ui_exits(returncode=None) -> None:
        """Stop when ui exits."""
        nonlocal abrupt_reason
        logging.info("UI worker exited with code %s", returncode)
        if returncode in (0, None) or ui_quit_requested.is_set():
            logging.info("UI worker exited cleanly; shutting down OpenWand")
            _close_worker_spawn_gate()
            stop.set()
            return
        logging.warning("UI worker exited unexpectedly; shutting down OpenWand")
        abrupt_reason = f"UI worker exited with code {returncode}"
        _close_worker_spawn_gate()
        stop.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            signal.signal(sig, _stop)

    ui_worker = supervisor.workers.get("ui")
    if ui_worker is not None and hasattr(ui_worker, "on_exit"):
        ui_worker.on_exit(_stop_when_ui_exits)
    if ui_worker is not None and hasattr(ui_worker, "on_event"):
        def _on_ui_quit_requested(_data=None, _req_id=None) -> None:
            logging.info("UI worker requested OpenWand shutdown")
            ui_quit_requested.set()
            _close_worker_spawn_gate()
            stop.set()

        ui_worker.on_event("ui.quit_requested", _on_ui_quit_requested)

    def _restart_audio_on_exit(returncode=None) -> None:
        """Restart the isolated audio worker after an unexpected exit."""
        if stop.is_set():
            return
        audio_worker = supervisor.workers.get("audio")
        logging.warning("Audio worker exited with code %s; restarting it", returncode)
        if audio_worker is None or not hasattr(audio_worker, "restart"):
            return
        try:
            audio_worker.restart()
            audio_worker.call("audio.ping", timeout=30.0)
            logging.info("Audio worker restarted after exit")
        except Exception:
            logging.exception("Audio worker restart failed")

    audio_worker = supervisor.workers.get("audio")
    if audio_worker is not None and hasattr(audio_worker, "on_exit"):
        audio_worker.on_exit(_restart_audio_on_exit)

    try:
        startup_results = supervisor.start_all()
        flows = FlowController(
            native=supervisor.workers["native"],
            ui=supervisor.workers["ui"],
            brain=supervisor.workers["brain"],
            audio=supervisor.workers["audio"],
            runtime_log=runtime_log,
        )
        flows.start()
        hotkey_result: dict[str, object] = {}
        if not stop.is_set():
            try:
                hotkey_result = flows.start_hotkeys()
            except Exception:
                logging.exception("native hotkeys did not start")
        if (
            _write_launch_smoke_ready(supervisor, startup_results, hotkey_result)
            and os.environ.get("OPENWAND_LAUNCH_SMOKE_EXIT_AFTER_READY") == "1"
        ):
            _close_worker_spawn_gate()
            stop.set()
        if not stop.is_set():
            stop.wait()
    except BaseException:
        if log_mode != "debug":
            crash_dir = _write_abrupt_log("supervisor exception", supervisor, sys.exc_info())
            if crash_dir is not None:
                logging.error("Wrote OpenWand crash log: %s", crash_dir)
        raise
    finally:
        _close_worker_spawn_gate()
        if flows is not None:
            flow_stop = getattr(flows, "stop", None)
            if callable(flow_stop):
                flow_stop()
        runtime_log.close()
        supervisor.shutdown()
    if abrupt_reason and log_mode != "debug":
        crash_dir = _write_abrupt_log(abrupt_reason, supervisor)
        if crash_dir is not None:
            logging.error("Wrote OpenWand crash log: %s", crash_dir)
    return 0


if __name__ == "__main__":
    _dispatch_module_mode()
    raise SystemExit(main())
