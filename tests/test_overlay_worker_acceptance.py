"""Real-worker acceptance for the floating overlay and tray shell."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.workflow

_AUXILIARY_VISIBILITY_KEYS = (
    "chat_visible",
    "memory_visible",
    "addons_visible",
    "runtime_status_visible",
    "settings_visible",
    "provider_controls_visible",
)
_AUXILIARY_LABEL_BY_READY_KEY = {
    "chat_visible": "chat",
    "memory_visible": "memory",
    "addons_visible": "addons",
    "runtime_status_visible": "runtime_status",
    "settings_ready": "settings",
}


def _wait_snapshot(ui, key: str, *, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    snapshot = {}
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        snapshot = ui.call("ui.debug.shell.snapshot", timeout=remaining)
        if snapshot.get(key) is True:
            return snapshot
        time.sleep(1.0)
    pytest.fail(f"UI shell did not reach {key}: {snapshot}")


def _close_aux_windows(ui, expected: str, *, timeout: float = 15.0) -> dict:
    result = ui.call("ui.debug.shell.close_aux_windows", timeout=10)
    assert expected in result.get("closed", [])
    deadline = time.monotonic() + timeout
    snapshot = {}
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        snapshot = ui.call("ui.debug.shell.snapshot", timeout=remaining)
        if not any(snapshot.get(key) for key in _AUXILIARY_VISIBILITY_KEYS):
            assert snapshot["icon_visible"] is True
            return snapshot
        time.sleep(0.1)
    pytest.fail(f"Auxiliary UI windows did not close: {snapshot}")


def _run_real_worker_shell_case(
    case_root: Path,
    execution_mode: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tray_expectations: tuple[tuple[str, str, str], ...] = (),
    provider_title: str = "",
) -> None:
    """Run one provider's shell workflow in its own worker-process tree."""
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True, exist_ok=True)
    assert not any(case_root.iterdir()), f"Test root was not empty after reset: {case_root}"

    run_log_dir = case_root / "logs"
    user_data_dir = case_root / "user-data"
    addons_dir = case_root / "addons"
    chats_dir = case_root / "chats"
    memory_dir = case_root / "memory"
    model_files_dir = case_root / "model_files"
    model_tools_dir = case_root / "model_tools"
    tools_installed_dir = case_root / "tools" / "installed"
    optional_packages_dir = user_data_dir / "python_packages"
    privacy_model_dir = user_data_dir / "models" / "openai-privacy-filter"
    env_path = case_root / ".env"
    isolated_paths = {
        "WISP_DATA_ROOT": case_root,
        "WISP_REPO_ROOT": case_root,
        "WISP_RUN_LOG_DIR": run_log_dir,
        "WISP_USER_DATA_DIR": user_data_dir,
        "WISP_ADDONS_DIR": addons_dir,
        "WISP_OPTIONAL_PACKAGES_DIR": optional_packages_dir,
        "WISP_PRIVACY_MODEL_DIR": privacy_model_dir,
        "WISP_SETTINGS_ENV_PATH": env_path,
    }
    assert all(path == case_root or case_root in path.parents for path in isolated_paths.values())

    env_path.write_text(
        f"WISP_ONBOARDING_COMPLETE=True\nCHAT_EXECUTION_MODE={execution_mode}\nTTS_PROVIDER=none\n",
        encoding="utf-8",
    )
    assert {path.name for path in case_root.iterdir()} == {".env"}
    assert all(
        not path.exists()
        for path in (
            run_log_dir,
            user_data_dir,
            addons_dir,
            chats_dir,
            memory_dir,
            model_files_dir,
            model_tools_dir,
            tools_installed_dir,
            optional_packages_dir,
            privacy_model_dir,
        )
    ), f"Prior Wisp history survived the test-root reset: {case_root}"

    isolated_env = {
        name: str(path)
        for name, path in isolated_paths.items()
    }
    parent_env = {
        **isolated_env,
        "CHAT_EXECUTION_MODE": execution_mode,
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "TTS_PROVIDER": "none",
        "WISP_ONBOARDING_COMPLETE": "True",
    }
    for name, value in parent_env.items():
        monkeypatch.setenv(name, value)

    # Some parent-process modules cache their paths at import time. Patch those
    # canonical locations too, so a combined local pytest run is as isolated as
    # CI's fresh per-file pytest process.
    from core.system import paths as system_paths

    canonical_parent_paths = {
        "REPO_ROOT": case_root,
        "USER_DATA_DIR": user_data_dir,
        "UPDATE_DOWNLOAD_DIR": user_data_dir / "updates",
        "SINGLE_INSTANCE_LOCK": user_data_dir / "wisp.lock",
        "MEMORY_DIR": memory_dir,
        "AGENT_RUNS_DIR": memory_dir / "agent_runs",
        "CHATS_DIR": chats_dir,
        "PROJECTS_FILE": chats_dir / "projects.json",
        "CONVERSATIONS_FILE": chats_dir / "conversations.json",
        "CHAT_ATTACHMENTS_DIR": chats_dir / "attachments",
        "TOOLS_INSTALLED_DIR": tools_installed_dir,
        "MODEL_TOOLS_DIR": model_tools_dir,
        "MODEL_FILE_ACCESS_DIR": model_files_dir,
        "ADDONS_DIR": addons_dir,
    }
    for name, path in canonical_parent_paths.items():
        monkeypatch.setattr(system_paths, name, path)

    import config
    from core import optional_deps, privacy_model
    from core.conversation_store import store as conversation_store
    from core.memory_store import store as memory_store

    monkeypatch.setattr(config, "_ENV_FILE", env_path)
    monkeypatch.setattr(config, "BASE_DIR", str(case_root))
    monkeypatch.setattr(optional_deps, "OPTIONAL_PACKAGES_DIR", optional_packages_dir)
    for name in ("CHATS_DIR", "PROJECTS_FILE", "CONVERSATIONS_FILE", "CHAT_ATTACHMENTS_DIR"):
        monkeypatch.setattr(conversation_store, name, canonical_parent_paths[name])
    monkeypatch.setattr(memory_store, "_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_store, "_FALLBACK_PATH", str(memory_dir / "facts_fallback.json"))

    from runtime.supervisor.flows import FlowController
    from runtime.supervisor.ipc import WispSupervisor, default_specs

    # Confirm the parent process sees only this case's paths before any UI or
    # worker is started. Runtime Status uses these parent-side locations.
    assert Path(os.environ["WISP_RUN_LOG_DIR"]).resolve() == run_log_dir.resolve()
    assert optional_deps.OPTIONAL_PACKAGES_DIR.resolve() == optional_packages_dir.resolve()
    assert conversation_store.CONVERSATIONS_FILE.resolve() == (
        chats_dir / "conversations.json"
    ).resolve()
    assert Path(memory_store._FALLBACK_PATH).resolve() == (
        memory_dir / "facts_fallback.json"
    ).resolve()
    installer_scan_roots = (
        run_log_dir / "installers",
        optional_deps.OPTIONAL_PACKAGES_DIR.parent / "installers",
        privacy_model.model_dir().parent / "installers",
    )
    assert all(root == case_root or case_root in root.parents for root in installer_scan_roots)
    assert all(not root.exists() for root in installer_scan_roots)

    started_at = time.monotonic()
    last_progress_at = started_at

    def progress(message: str) -> None:
        nonlocal last_progress_at
        now = time.monotonic()
        print(
            f"=== overlay shell [{execution_mode}]: {message} "
            f"(+{now - last_progress_at:.1f}s, total {now - started_at:.1f}s) ===",
            flush=True,
        )
        last_progress_at = now

    repo_root = Path(__file__).resolve().parents[1]
    shared_env = {
        **parent_env,
        "PYTHONPATH": os.pathsep.join([str(repo_root), str(repo_root / "runtime" / "brain")]),
        "QT_QPA_PLATFORM": "offscreen",
        "WISP_BRAIN_FAKE_LLM": "1",
        "WISP_UI_DEBUG_METHODS": "1",
    }
    assert all(shared_env[name] == str(path) for name, path in isolated_paths.items())
    specs = default_specs()
    for spec in specs.values():
        spec.env = {**spec.env, **shared_env}
    supervisor = WispSupervisor(specs)
    flow = FlowController(
        native=supervisor.workers["native"],
        ui=supervisor.workers["ui"],
        brain=supervisor.workers["brain"],
        audio=supervisor.workers["audio"],
    )
    ui = supervisor.workers["ui"]
    # WorkerClient already persists stderr and keeps a bounded in-memory tail.
    # Re-emitting every settings-debug line with a flushed print can backpressure
    # a hosted Windows runner and makes diagnostic chatter look like test progress
    # to the per-file inactivity watchdog.
    try:
        progress("starting isolated UI flow")
        # This acceptance path only exercises UI-shell IPC. Keep the real flow
        # wiring, but do not launch unrelated brain/audio prewarms.
        flow.start(prewarm=False)
        progress("overlay visible")

        for label, ready_key, reached_state in tray_expectations:
            progress(f"triggering {label}")
            result = ui.call("ui.debug.tray.trigger", {"label": label}, timeout=15)
            assert result == {"triggered": True, "label": label}
            _wait_snapshot(ui, ready_key)
            progress(f"{label} {reached_state}")
            _close_aux_windows(ui, _AUXILIARY_LABEL_BY_READY_KEY[ready_key])
            progress(f"{label} closed")

        if provider_title:
            progress("clicking provider badge")
            assert ui.call("ui.debug.provider_badge.click", timeout=10) == {
                "clicked": True,
                "provider": execution_mode,
            }
            progress("provider badge click returned")
            provider = _wait_snapshot(ui, "provider_controls_visible")
            assert any(provider_title in title for title in provider["visible_window_titles"])
            progress(f"{provider_title} controls visible")
            _close_aux_windows(ui, "provider_controls")
            progress(f"{provider_title} controls closed")

        progress("triggering Quit")
        assert ui.call("ui.debug.tray.trigger", {"label": "Quit"}, timeout=10)["triggered"] is True
        progress("Quit trigger returned")
        deadline = time.monotonic() + 10
        while ui.alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not ui.alive()
        progress("quit complete")
    finally:
        progress("stopping flow")
        flow.stop()
        progress("flow stopped; shutting down workers")
        worker_states = ", ".join(
            f"{name}=pid:{worker.pid},alive:{worker.alive()}"
            for name, worker in supervisor.workers.items()
        )
        progress(f"worker states before shutdown: {worker_states}")
        # Windows psutil process-tree discovery can block inside native process
        # enumeration on a busy hosted runner. This isolated fixture cannot have
        # addon hosts, and Windows uses in-process hotkeys, so stop each real
        # worker without the unrelated OS-wide survivor audit. Keep the existing
        # audit on macOS (where the hotkey helper is a child process) and Linux.
        audit_managed_processes = os.name != "nt"
        progress(f"managed process audit enabled: {audit_managed_processes}")
        supervisor.shutdown(
            audit_managed_processes=audit_managed_processes,
            progress=lambda phase: progress(f"worker shutdown: {phase}"),
        )
        progress("worker shutdown complete")


def test_real_worker_tray_actions_open_each_shared_surface_then_quit(
    tmp_path: Path,
    capfd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open each lightweight tray surface sequentially in one real worker tree."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / "tray-surfaces",
            "codex",
            monkeypatch,
            tray_expectations=(
                ("Last chat", "chat_visible", "visible"),
                ("Memory", "memory_visible", "visible"),
                ("Addon Manager", "addons_visible", "visible"),
                ("Runtime Status", "runtime_status_visible", "visible"),
            ),
        )


def test_real_worker_settings_action_finishes_loading_then_quit(
    tmp_path: Path,
    capfd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the real Settings dialog to finish deferred loading before success."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / "settings",
            "codex",
            monkeypatch,
            tray_expectations=(("Settings", "settings_ready", "ready"),),
        )


@pytest.mark.parametrize(
    ("execution_mode", "provider_title"),
    (("codex", "ChatGPT"), ("claude", "Claude")),
)
def test_real_worker_provider_action_opens_matching_controls_then_quit(
    tmp_path: Path,
    capfd,
    monkeypatch: pytest.MonkeyPatch,
    execution_mode: str,
    provider_title: str,
) -> None:
    """Open each provider's controls in its own sequential real worker tree."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / execution_mode,
            execution_mode,
            monkeypatch,
            provider_title=provider_title,
        )
