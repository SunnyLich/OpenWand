"""Regression tests for the canonical STT/TTS status contract."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import optional_deps, speech_status, tts_assets
from runtime.workers import audio_host


@pytest.fixture(autouse=True)
def _no_persisted_installer_status(monkeypatch):
    monkeypatch.setattr(optional_deps, "read_optional_install_status", lambda _display_name: {})


def _config(**overrides):
    values = {
        "STT_MODEL": "base",
        "STT_DEVICE": "cpu",
        "STT_COMPUTE_TYPE": "int8",
        "TTS_PROVIDER": "none",
        "KOKORO_VOICE": "af_heart",
        "KOKORO_LANG_CODE": "a",
        "KOKORO_DEVICE": "cpu",
        "ELEVENLABS_API_KEY": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_stt_status_distinguishes_package_files_from_runtime_import(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True, "message": "files match"},
    )
    monkeypatch.setattr(
        optional_deps,
        "stt_runtime_import_status_subprocess",
        lambda: {"installed": True, "valid": False, "error": "ImportError: ctranslate2 DLL failed"},
    )

    status = speech_status.stt_status(_config(), verify_runtime=True)

    assert status["installed"] is True
    assert status["usable"] is False
    assert status["state"] == "repair_required"
    assert "ctranslate2" in status["error"]


def test_kokoro_status_rejects_missing_selected_voice_assets(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        tts_assets,
        "verify",
        lambda *_args, **_kwargs: tts_assets.AssetStatus(state="ok", missing_voices=["af_heart"]),
    )

    status = speech_status.tts_status(_config(TTS_PROVIDER="kokoro"))

    assert status["installed"] is True
    assert status["usable"] is False
    assert status["state"] == "assets_required"
    assert "af_heart" in status["error"]


def test_kokoro_status_requires_package_runtime_torch_and_assets(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        optional_deps,
        "kokoro_runtime_import_status_subprocess",
        lambda: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        optional_deps,
        "kokoro_torch_status_subprocess",
        lambda: {"installed": True, "valid": True, "cuda_available": False},
    )
    monkeypatch.setattr(
        tts_assets,
        "verify",
        lambda *_args, **_kwargs: tts_assets.AssetStatus(state="ok"),
    )

    status = speech_status.tts_status(_config(TTS_PROVIDER="kokoro"), verify_runtime=True)

    assert status["installed"] is True
    assert status["usable"] is True
    assert status["state"] == "installed"


def test_elevenlabs_status_reports_broken_sdk_separately(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        optional_deps,
        "elevenlabs_runtime_import_status_subprocess",
        lambda: {"installed": True, "valid": False, "error": "ImportError: broken pydantic"},
    )

    status = speech_status.tts_status(
        _config(TTS_PROVIDER="elevenlabs", ELEVENLABS_API_KEY="secret"),
        verify_runtime=True,
    )

    assert status["installed"] is True
    assert status["usable"] is False
    assert status["state"] == "repair_required"
    assert "pydantic" in status["error"]


def test_audio_speech_status_combines_install_and_live_warmup(monkeypatch):
    import config
    from core.macos_helper import handlers as stt_handlers

    monkeypatch.setattr(config, "STT_MODEL", "base", raising=False)
    monkeypatch.setattr(config, "STT_DEVICE", "cpu", raising=False)
    monkeypatch.setattr(config, "STT_COMPUTE_TYPE", "int8", raising=False)
    monkeypatch.setattr(config, "TTS_PROVIDER", "none", raising=False)
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        stt_handlers,
        "stt_is_ready",
        lambda: {"ready": False, "warming": True, "error": "", "device": "cpu", "compute": "int8"},
    )

    status = audio_host.speech_status()

    assert status["schema"] == speech_status.SCHEMA_VERSION
    assert status["stt"]["state"] == "warming"
    assert status["stt"]["installed"] is True
    assert status["stt"]["active_device"] == "cpu"
    assert status["tts"]["state"] == "disabled"
    assert "audio.speech.status" in audio_host.HANDLERS


def test_tts_runtime_refuses_unmanaged_elevenlabs_package(monkeypatch):
    from core import tts

    monkeypatch.setattr(
        optional_deps,
        "require_optional_package_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("release contract mismatch")),
    )

    with pytest.raises(RuntimeError, match="release contract mismatch"):
        list(tts._stream_elevenlabs("hello"))


def test_stt_status_reports_staged_restart_before_package_failure(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": False, "valid": False, "message": "not installed"},
    )
    monkeypatch.setattr(
        speech_status,
        "_installer_status",
        lambda *_args, **_kwargs: {
            "ok": None,
            "restart_apply": True,
            "message": "STT packages are staged. Restart Wisp to apply them.",
        },
    )

    status = speech_status.stt_status(_config())

    assert status["state"] == "restart_required"
    assert status["usable"] is False
    assert "Restart Wisp" in status["summary"]


def test_elevenlabs_status_does_not_call_metadata_only_package_usable_after_failed_repair(monkeypatch):
    monkeypatch.setattr(
        optional_deps,
        "optional_package_runtime_status",
        lambda *_args, **_kwargs: {"installed": True, "valid": True},
    )
    monkeypatch.setattr(
        speech_status,
        "_installer_status",
        lambda *_args, **_kwargs: {"ok": False, "message": "Download failed: disk full."},
    )

    status = speech_status.tts_status(
        _config(TTS_PROVIDER="elevenlabs", ELEVENLABS_API_KEY="secret")
    )

    assert status["state"] == "install_failed"
    assert status["usable"] is False
    assert "disk full" in status["error"]
