"""Canonical, side-effect-free speech capability status.

This module owns the vocabulary used by Settings, Setup Check, and the audio
worker.  It deliberately separates configuration, package installation,
runtime importability, local assets, and live warmup readiness; those are
different facts and must not be flattened into one ``installed`` boolean.
"""
from __future__ import annotations

import sys
from typing import Any

SCHEMA_VERSION = 1


def _text(config: Any, name: str, default: str = "") -> str:
    return str(getattr(config, name, default) or default).strip()


def _package_status(key: str, *, device: str | None = None) -> dict[str, object]:
    from core import optional_deps

    try:
        return dict(optional_deps.optional_package_runtime_status(key, device=device))
    except Exception as exc:  # noqa: BLE001 - status must remain reportable
        return {
            "key": key,
            "installed": False,
            "valid": False,
            "message": f"Package status check failed: {type(exc).__name__}: {exc}",
        }


def _runtime_failure(status: dict[str, object]) -> str:
    if status.get("valid") is True:
        return ""
    return str(status.get("error") or "runtime import verification failed").strip()


def _installer_status(config: Any, key: str, *, device: str | None = None) -> dict[str, object]:
    """Return the newest non-stale individual/combined speech install status."""
    from core import optional_deps, updater

    display_names = {"stt": "STT", "elevenlabs": "ElevenLabs", "kokoro": "Kokoro"}
    candidates: list[tuple[dict[str, object], str]] = []
    expected = optional_deps.optional_package_contract(key, device=device)
    candidates.append((optional_deps.read_optional_install_status(display_names[key]), expected))
    if key in {"stt", "kokoro"}:
        stt_device = _text(config, "STT_DEVICE", "auto").lower()
        kokoro_requested = _text(config, "KOKORO_DEVICE", "auto").lower()
        kokoro_device = (
            "cuda" if optional_deps.kokoro_install_mode_for_device(kokoro_requested) == "gpu" else "cpu"
        )
        combined_contract = optional_deps.local_speech_install_contract(
            kokoro_device=kokoro_device,
            stt_device=stt_device,
        )
        candidates.append((optional_deps.read_optional_install_status("Local speech"), combined_contract))
    current_version = updater.current_version()
    valid = [
        status
        for status, contract in candidates
        if status
        and str(status.get("install_contract") or "") == contract
        and str(status.get("app_version") or "") == current_version
    ]
    return max(valid, key=lambda item: float(item.get("updated_at") or 0.0), default={})


def _apply_installer_overlay(result: dict[str, object], installer: dict[str, object]) -> bool:
    """Apply an active/failed installer phase; return whether it is authoritative."""
    result["installer"] = installer
    if not installer or installer.get("ok") is True:
        return False
    message = str(installer.get("message") or "Speech installation status is unavailable.").strip()
    # Package metadata alone is not proof that native imports or assets work.
    # Active installer phases therefore stay conservative until verification.
    current_usable = bool(result.get("usable"))
    if installer.get("restart_apply"):
        result.update(
            state="restart_required",
            usable=current_usable,
            summary=message,
            action="Restart OpenWand to apply and verify the staged speech packages.",
        )
    elif installer.get("ok") is None:
        result.update(
            state="installing",
            usable=current_usable,
            summary=message,
            action="Wait for the speech package download to finish.",
        )
    else:
        result.update(
            state="install_failed",
            usable=current_usable,
            summary=message,
            error=message,
            action="Review the installer message and retry the speech installation.",
        )
    return True


def stt_status(
    config: Any,
    *,
    verify_runtime: bool = False,
    live: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return local speech-recognition status without loading a Whisper model."""
    provider = _text(config, "STT_PROVIDER", "local").lower()
    if provider == "none":
        model = ""
    else:
        model = (
            _text(config, "STT_CLOUDFLARE_MODEL", "@cf/openai/whisper-large-v3-turbo")
            if provider == "cloudflare"
            else _text(config, "STT_MODEL")
        )
    device = _text(config, "STT_DEVICE", "auto").lower()
    compute = _text(config, "STT_COMPUTE_TYPE", "int8").lower()
    result: dict[str, object] = {
        "component": "stt",
        "provider": provider,
        "configured": bool(model),
        "model": model,
        "requested_device": device,
        "requested_compute": compute,
        "active_device": "",
        "active_compute": "",
        "installed": False,
        "usable": False,
        "ready": None,
        "warming": False,
        "state": "disabled" if not model else "checking",
        "summary": (
            "Speech to text is disabled."
            if provider == "none"
            else "STT is not configured; voice and dictation can stay off."
        ),
        "error": "",
        "action": "",
        "package": {},
        "runtime": {},
        "installer": {},
    }
    if not model:
        return result

    if provider == "cloudflare":
        missing: list[str] = []
        if not _text(config, "STT_CLOUDFLARE_ACCOUNT_ID"):
            missing.append("Cloudflare Account ID")
        if not _text(config, "CLOUDFLARE_API_TOKEN"):
            missing.append("Cloudflare Workers AI API token")
        result["installed"] = None
        if missing:
            detail = f"Missing {', '.join(missing)}."
            result.update(
                state="not_configured",
                usable=False,
                summary=f"Cloudflare STT is incomplete: {detail}",
                error=detail,
                action="Complete the Cloudflare fields in Settings > Voice.",
            )
        else:
            result.update(
                state="configured",
                usable=True,
                ready=True,
                summary=f"Cloudflare STT is configured: {model}; connection has not been tested.",
            )
        return result
    if provider != "local":
        detail = f"Unknown STT provider: {provider}"
        result.update(
            state="invalid_configuration",
            usable=False,
            summary=detail,
            error=detail,
            action="Choose a supported STT provider.",
        )
        return result

    package = _package_status("stt", device=device)
    result["package"] = package
    result["installed"] = bool(package.get("installed"))
    installer = _installer_status(config, "stt", device=device)
    if _apply_installer_overlay(result, installer):
        return result
    if package.get("valid") is not True:
        detail = str(package.get("message") or "STT packages are missing or invalid").strip()
        result.update(
            state="repair_required" if package.get("installed") else "not_installed",
            summary=f"STT is not usable: {detail}",
            error=detail,
            action="STT support is not working. Open Settings > Voice and click Install STT.",
        )
        return result

    runtime: dict[str, object] = {}
    if verify_runtime:
        from core import optional_deps

        runtime = dict(optional_deps.stt_runtime_import_status_subprocess())
        result["runtime"] = runtime
        failure = _runtime_failure(runtime)
        if failure:
            runtime_installed = bool(runtime.get("installed"))
            result.update(
                state="repair_required" if runtime_installed else "not_installed",
                installed=runtime_installed,
                summary=(
                    f"STT model configured: {model}, but STT verification failed: {failure}"
                    if runtime_installed
                    else f"STT model configured: {model}, but faster-whisper is not installed."
                ),
                error=failure,
                action="STT support is not working. Open Settings > Voice and click Install STT.",
            )
            return result
        if sys.platform == "win32" and device == "cuda":
            from core.stt_device import windows_cuda_runtime_status

            cuda = dict(windows_cuda_runtime_status())
            result["cuda_runtime"] = cuda
            if cuda.get("checked") and not cuda.get("valid"):
                names = ", ".join(sorted(str(name) for name in dict(cuda.get("errors") or {})))
                failure = "Windows CUDA runtime is incomplete or unloadable" + (f": {names}" if names else "")
                result.update(
                    state="repair_required",
                    summary=f"STT model configured: {model}, but STT verification failed: {failure}",
                    error=failure,
                    action="STT support is not working. Open Settings > Voice and click Install STT.",
                )
                return result

    live = dict(live or {})
    ready = live.get("ready") if "ready" in live else None
    warming = bool(live.get("warming"))
    live_error = str(live.get("error") or "").strip()
    active_device = str(live.get("device") or "")
    active_compute = str(live.get("compute") or "")
    result.update(
        installed=True,
        usable=True,
        ready=ready,
        warming=warming,
        active_device=active_device,
        active_compute=active_compute,
    )
    if live_error:
        result.update(
            state="failed",
            usable=False,
            summary=f"STT model failed to load: {live_error}",
            error=live_error,
            action="Review the speech error, then repair STT if it persists.",
        )
    elif ready is True:
        backend = " / ".join(part for part in (active_device, active_compute) if part) or "active backend"
        result.update(state="ready", summary=f"STT is ready: {model} on {backend}.")
    elif warming:
        result.update(state="warming", summary=f"STT is warming up: {model}.")
    else:
        result.update(
            state="installed",
            summary=f"STT packages and runtime are verified for {model}; the model loads on first use.",
        )
    return result


def _tts_requirements(config: Any, provider: str) -> tuple[list[str], list[str]]:
    """Return (missing setting labels, configured values) for a TTS provider."""
    names: dict[str, tuple[tuple[str, str], ...]] = {
        "cartesia": (("CARTESIA_API_KEY", "Cartesia API key"), ("CARTESIA_VOICE_ID", "Cartesia voice ID")),
        "elevenlabs": (("ELEVENLABS_API_KEY", "ElevenLabs API key"),),
        "openai": (("OPENAI_API_KEY", "OpenAI API key"),),
        "openai_compatible": (("TTS_CUSTOM_BASE_URL", "custom TTS base URL"),),
        "gpt_sovits": (
            ("GPT_SOVITS_URL", "GPT-SoVITS URL"),
            ("GPT_SOVITS_REF_AUDIO_PATH", "GPT-SoVITS reference audio"),
        ),
        "kokoro": (("KOKORO_VOICE", "Kokoro voice"), ("KOKORO_LANG_CODE", "Kokoro language")),
    }
    required = names.get(provider, ())
    missing = [label for name, label in required if not _text(config, name)]
    values = [_text(config, name) for name, _label in required]
    return missing, values


def tts_status(
    config: Any,
    *,
    verify_runtime: bool = False,
    live: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return configured TTS route status without making a provider request."""
    provider = _text(config, "TTS_PROVIDER", "none").lower()
    result: dict[str, object] = {
        "component": "tts",
        "provider": provider,
        "configured": provider not in {"", "none"},
        "installed": None,
        "usable": False,
        "ready": None,
        "warming": False,
        "state": "disabled",
        "summary": "TTS is off; replies will stay text-only.",
        "error": "",
        "action": "",
        "package": {},
        "runtime": {},
        "assets": {},
        "installer": {},
    }
    if provider in {"", "none"}:
        return result
    supported = {"cartesia", "elevenlabs", "openai", "openai_compatible", "gpt_sovits", "kokoro"}
    if provider not in supported:
        detail = f"Unknown TTS provider: {provider}"
        result.update(state="invalid_configuration", summary=detail, error=detail, action="Choose a supported TTS provider.")
        return result

    missing, _values = _tts_requirements(config, provider)
    if missing:
        detail = f"Missing {', '.join(missing)}."
        result.update(
            state="not_configured",
            summary=f"TTS provider {provider} is incomplete: {detail}",
            error=detail,
            action="Complete the provider settings in Settings > Voice.",
        )
        return result

    if provider == "elevenlabs":
        package = _package_status("elevenlabs")
        result["package"] = package
        result["installed"] = bool(package.get("installed"))
        if _apply_installer_overlay(result, _installer_status(config, "elevenlabs")):
            return result
        if package.get("valid") is not True:
            detail = str(package.get("message") or "ElevenLabs SDK is missing or invalid").strip()
            result.update(
                state="repair_required" if package.get("installed") else "not_installed",
                summary=f"ElevenLabs is not usable: {detail}",
                error=detail,
                action="ElevenLabs support is not installed. Open Settings > Voice and click Install ElevenLabs.",
            )
            return result
        if verify_runtime:
            from core import optional_deps

            runtime = dict(optional_deps.elevenlabs_runtime_import_status_subprocess())
            result["runtime"] = runtime
            failure = _runtime_failure(runtime)
            if failure:
                result.update(
                    state="repair_required",
                    summary=f"ElevenLabs is installed, but its SDK cannot load: {failure}",
                    error=failure,
                    action="ElevenLabs support is not working. Open Settings > Voice and click Install ElevenLabs.",
                )
                return result
        result["installed"] = True

    if provider == "kokoro":
        from core import optional_deps, tts_assets

        requested_device = _text(config, "KOKORO_DEVICE", "auto").lower()
        install_device = "cuda" if optional_deps.kokoro_install_mode_for_device(requested_device) == "gpu" else "cpu"
        package = _package_status("kokoro", device=install_device)
        result["package"] = package
        result["installed"] = bool(package.get("installed"))
        if _apply_installer_overlay(
            result,
            _installer_status(config, "kokoro", device=install_device),
        ):
            return result
        runtime: dict[str, object] = {}
        package_usable = package.get("valid") is True
        installed_candidate = bool(package.get("installed"))
        if not package_usable and installed_candidate:
            if verify_runtime:
                # Package pins can move while the installed Kokoro entry point
                # stays compatible. Verify the runtime before asking for a
                # needless repair.
                runtime = dict(optional_deps.kokoro_runtime_import_status_subprocess())
                result["runtime"] = runtime
                package_usable = runtime.get("valid") is True
            else:
                # Lightweight/live status must not disable an existing Kokoro
                # layer just because the checked-in lock changed. Startup and
                # synthesis import the real entry point and report actual errors.
                package_usable = True
                result["version_drift"] = True
        if not package_usable:
            detail = str(package.get("message") or "Kokoro packages are missing or invalid").strip()
            result.update(
                state="repair_required" if package.get("installed") else "not_installed",
                summary=f"Kokoro is not usable: {detail}",
                error=detail,
                action="Open Settings > Voice and install or repair Kokoro.",
            )
            return result
        try:
            assets = tts_assets.verify(
                tts_assets.KOKORO,
                voices=tts_assets.parse_voices(_text(config, "KOKORO_VOICE", "af_heart")),
            )
            result["assets"] = {
                "state": assets.state,
                "problems": list(assets.problems),
                "missing_voices": list(assets.missing_voices),
            }
            if assets.state != "ok" or assets.missing_voices:
                problems = list(assets.problems) or [
                    f"missing voice files: {', '.join(assets.missing_voices)}"
                ]
                detail = "; ".join(problems)
                result.update(
                    state="assets_required",
                    summary=f"Kokoro packages are installed, but local voice files are incomplete: {detail}",
                    error=detail,
                    action="Open Settings > Voice and repair the Kokoro voice files.",
                )
                return result
        except Exception as exc:  # noqa: BLE001
            detail = f"Kokoro asset verification failed: {type(exc).__name__}: {exc}"
            result.update(state="repair_required", summary=detail, error=detail, action="Repair the Kokoro voice files.")
            return result
        if verify_runtime:
            if not runtime:
                runtime = dict(optional_deps.kokoro_runtime_import_status_subprocess())
                result["runtime"] = runtime
            failure = _runtime_failure(runtime)
            if not failure:
                torch = dict(optional_deps.kokoro_torch_status_subprocess())
                result["torch"] = torch
                failure = _runtime_failure(torch)
                if not failure and requested_device == "cuda" and not torch.get("cuda_available"):
                    failure = optional_deps.kokoro_cuda_failure_detail(torch)
            if failure:
                result.update(
                    state="repair_required",
                    summary=f"Kokoro is installed, but its runtime is broken: {failure}",
                    error=failure,
                    action="Open Settings > Voice and repair Kokoro.",
                )
                return result
        result["installed"] = True

    live = dict(live or {})
    ready = live.get("ready") if "ready" in live else None
    warming = bool(live.get("warming"))
    live_error = str(live.get("error") or "").strip()
    result.update(usable=True, ready=ready, warming=warming)
    if live_error:
        result.update(state="failed", usable=False, summary=f"TTS failed: {live_error}", error=live_error)
    elif ready is True:
        result.update(state="ready", summary=f"TTS is ready: {provider}.")
    elif warming:
        result.update(state="warming", summary=f"TTS is warming up: {provider}.")
    elif provider == "kokoro":
        result.update(
            state="installed",
            summary="TTS provider kokoro: packages, runtime, and selected voice files are verified.",
        )
    else:
        result.update(state="configured", summary=f"TTS provider {provider} is configured; connection has not been tested.")
    return result


def speech_status(
    config: Any,
    *,
    verify_runtime: bool = False,
    stt_live: dict[str, object] | None = None,
    tts_live: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the stable combined status document consumed by UI and IPC."""
    return {
        "schema": SCHEMA_VERSION,
        "stt": stt_status(config, verify_runtime=verify_runtime, live=stt_live),
        "tts": tts_status(config, verify_runtime=verify_runtime, live=tts_live),
    }
