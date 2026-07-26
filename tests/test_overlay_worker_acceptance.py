"""Real-worker acceptance for the floating overlay and tray shell."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.workflow


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


def _run_real_worker_shell_case(
    case_root: Path,
    execution_mode: str,
    *,
    tray_expectations: tuple[tuple[str, str, str], ...] = (),
    provider_title: str = "",
) -> None:
    """Run one provider's shell workflow in its own worker-process tree."""
    from runtime.supervisor.flows import FlowController
    from runtime.supervisor.ipc import WispSupervisor, default_specs

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

    case_root.mkdir(parents=True, exist_ok=True)
    (case_root / ".env").write_text(
        f"WISP_ONBOARDING_COMPLETE=True\nCHAT_EXECUTION_MODE={execution_mode}\nTTS_PROVIDER=none\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    shared_env = {
        "PYTHONPATH": os.pathsep.join([str(repo_root), str(repo_root / "runtime" / "brain")]),
        # Authentication is outside this shell test. Never let isolated hosted
        # workers query the runner's real OS credential store while Settings is
        # populating its connection rows.
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "QT_QPA_PLATFORM": "offscreen",
        "CHAT_EXECUTION_MODE": execution_mode,
        "WISP_ADDONS_DIR": str(case_root / "addons"),
        "WISP_BRAIN_FAKE_LLM": "1",
        "WISP_REPO_ROOT": str(case_root),
        "WISP_RUN_LOG_DIR": str(case_root / "logs"),
        "WISP_UI_DEBUG_METHODS": "1",
        "WISP_ONBOARDING_COMPLETE": "True",
    }
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
    ui.on_stderr_line(
        lambda line: progress(f"UI {line}")
        if line.startswith("[settings debug]")
        else None
    )
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
) -> None:
    """Open each lightweight tray surface sequentially in one real worker tree."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / "tray-surfaces",
            "codex",
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
) -> None:
    """Require the real Settings dialog to finish deferred loading before success."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / "settings",
            "codex",
            tray_expectations=(("Settings", "settings_ready", "ready"),),
        )


@pytest.mark.parametrize(
    ("execution_mode", "provider_title"),
    (("codex", "ChatGPT"), ("claude", "Claude")),
)
def test_real_worker_provider_action_opens_matching_controls_then_quit(
    tmp_path: Path,
    capfd,
    execution_mode: str,
    provider_title: str,
) -> None:
    """Open each provider's controls in its own sequential real worker tree."""
    with capfd.disabled():
        _run_real_worker_shell_case(
            tmp_path / execution_mode,
            execution_mode,
            provider_title=provider_title,
        )
