"""Process-level acceptance tests for source and packaged OpenWand launchers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.run_launcher_smoke import _packaged_executable, run_launcher_smoke

pytestmark = pytest.mark.workflow

ROOT = Path(__file__).resolve().parents[1]


def _source_python() -> Path:
    """Prefer the launcher's provisioned 3.12 environment when it exists."""
    venv_python = (
        ROOT / ".venv" / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else ROOT / ".venv" / "bin" / "python"
    )
    return venv_python if venv_python.is_file() else Path(sys.executable)


def test_source_development_launcher_starts_real_ui_workers_and_cleans_up() -> None:
    """The platform source launcher must reach real readiness and leave no process."""
    payload = run_launcher_smoke(
        "source",
        root=ROOT,
        source_python=_source_python(),
    )

    assert payload["launcher_kind"] == "source"
    assert payload["frozen"] is False
    assert payload["ui_overlay_shown"] is True
    assert payload["flows_started"] is True
    assert payload["clean_shutdown"] is True
    assert set(payload["workers"]) == {"native", "ui", "brain", "audio"}
    assert payload["supervisor_create_time"] > 0
    assert all(row["create_time"] > 0 for row in payload["workers"].values())


def test_real_app_settings_profiles_save_reopen_and_fetch_ollama_models() -> None:
    """The source app must drive real Settings widgets and isolated profile files."""
    payload = run_launcher_smoke(
        "source",
        root=ROOT,
        source_python=_source_python(),
        settings_profile_smoke=True,
    )

    settings = payload["settings_profile_smoke"]
    persisted = settings["persisted"]
    assert settings["real_process_ui"] is True
    assert settings["low_selected"]["profile_id"] == "low_setup"
    assert settings["low_selected"]["save_enabled"] is True
    assert not any(
        word in settings["low_selected"]["status"].casefold()
        for word in ("low setup", "selected", "detected", "profile")
    )
    assert settings["low_selected"]["status_tooltip"] == ""
    assert settings["low_selected"]["stt_beam_size"] == "1"
    assert settings["low_selected"]["memory_top_k"] == "2"
    assert settings["low_selected"]["context_browser_max_chars"] == "3000"
    staged = settings["staged_before_save"]
    assert staged["disk_active_profile"] == "a"
    assert staged["disk_settings_profile"] == "a"
    assert staged["disk_bubble_width"] == "340"
    assert staged["runtime_after_selection"] == staged["runtime_before_selection"]
    assert settings["ollama_loaded"]["provider"] == "ollama"
    assert {"llama3.2:3b", "qwen2.5:7b"} <= set(
        settings["ollama_loaded"]["model_choices"]
    )
    assert "ollama" not in settings["ollama_loaded"]["connection_providers"]
    assert settings["reopened_low"]["profile_id"] == "low_setup"
    assert settings["reopened_low"]["bubble_width"] == "222"
    assert settings["reopened_a"]["profile_id"] == "a"
    assert settings["reopened_a"]["bubble_width"] == "444"
    assert persisted == {
        "active_profile": "a",
        "settings_profile": "a",
        "a_bubble_width": "444",
        "low_setup_bubble_width": "222",
        "low_setup_provider": "ollama",
        "low_setup_model": "llama3.2:3b",
        "profile_files": ["a.env", "low_setup.env"],
    }
    assert payload["clean_shutdown"] is True


def test_packaged_launcher_starts_real_ui_workers_and_cleans_up() -> None:
    """A freshly built platform artifact must run the same real worker/UI stack."""
    executable = _packaged_executable(ROOT)
    if not executable.is_file():
        pytest.skip("build the platform artifact before running packaged acceptance")
    runtime_inputs = (
        ROOT / "runtime" / "supervisor" / "app.py",
        ROOT / "runtime" / "supervisor" / "ipc.py",
        ROOT / "core" / "system" / "paths.py",
    )
    if executable.stat().st_mtime < max(path.stat().st_mtime for path in runtime_inputs):
        pytest.skip("packaged artifact predates the runtime under test; rebuild it first")

    try:
        payload = run_launcher_smoke("packaged", root=ROOT, executable=executable)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 4551:
            pytest.skip("Windows Application Control blocked the packaged artifact")
        raise

    assert payload["launcher_kind"] == "packaged"
    assert payload["frozen"] is True
    assert payload["ui_overlay_shown"] is True
    assert payload["flows_started"] is True
    assert payload["clean_shutdown"] is True
    assert set(payload["workers"]) == {"native", "ui", "brain", "audio"}


def test_release_builds_gate_every_platform_artifact_on_packaged_smoke() -> None:
    """No release job may package an artifact before its real runtime smoke passes."""
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    for platform in ("Windows", "Linux", "macOS"):
        build = workflow.index(f"- name: Build {platform} artifact")
        smoke = workflow.index(f"- name: Smoke-test packaged {platform} runtime")
        package = workflow.index(f"- name: Package {platform} artifact")
        assert build < smoke < package
    assert workflow.count("python scripts/run_launcher_smoke.py --kind packaged --timeout 240") == 3
