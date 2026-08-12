"""Short-lived optional dependency probes.

Run via ``python -m runtime.workers.optional_deps_probe`` or, in frozen builds,
``OpenWand.exe -m runtime.workers.optional_deps_probe``. Keeping these checks in a
separate process prevents native libraries from staying loaded in the Settings
process after install verification.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

_USE_MANAGED_LAYER = True


def _configure_dependency_path(path: str) -> None:
    global _USE_MANAGED_LAYER
    optional_dir = str(Path(path).expanduser())
    while optional_dir in sys.path:
        sys.path.remove(optional_dir)
    _USE_MANAGED_LAYER = os.environ.get("OPENWAND_OPTIONAL_PROBE_SOURCE", "managed") != "environment"
    if _USE_MANAGED_LAYER:
        sys.path.insert(0, optional_dir)
    importlib.invalidate_caches()


def _distribution_version(package_name: str) -> str:
    """Read a version from the dependency layer selected by the parent."""
    if not _USE_MANAGED_LAYER:
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            return ""
    wanted = package_name.casefold().replace("_", "-")
    try:
        candidates = Path(sys.path[0]).glob("*.dist-info")
        for dist_info in candidates:
            name = ""
            version = ""
            for line in (dist_info / "METADATA").read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines():
                if line.casefold().startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.casefold().startswith("version:"):
                    version = line.split(":", 1)[1].strip()
                if name and version:
                    break
            if name.casefold().replace("_", "-") == wanted:
                return version
    except OSError:
        pass
    return ""


def _find_spec(module_name: str):
    if _USE_MANAGED_LAYER:
        return importlib.machinery.PathFinder.find_spec(module_name, [sys.path[0]])
    return importlib.util.find_spec(module_name)


def _torch_status() -> dict[str, object]:
    status: dict[str, object] = {
        "installed": False,
        "version": "",
        "cuda_version": "",
        "cuda_available": False,
        "device": "",
        "error": "",
        "valid": False,
        "subprocess": True,
    }
    try:
        if (spec := _find_spec("torch")) is None:
            return status
        status["installed"] = True
        status["origin"] = str(getattr(spec, "origin", "") or "")
        import torch  # type: ignore

        status["origin"] = str(getattr(torch, "__file__", "") or "")
        version = str(getattr(torch, "__version__", "") or "")
        if not version or not hasattr(torch, "cuda"):
            status["error"] = "Torch import is incomplete."
            return status
        try:
            from torch.amp import autocast  # type: ignore  # noqa: F401
        except Exception as exc:
            status["error"] = f"Torch import is incomplete for Kokoro: {type(exc).__name__}: {exc}"
            return status
        status["valid"] = True
        status["version"] = version
        status["cuda_version"] = str(getattr(getattr(torch, "version", None), "cuda", "") or "")
        cuda_available = bool(torch.cuda.is_available())
        status["cuda_available"] = cuda_available
        if cuda_available:
            try:
                status["device"] = str(torch.cuda.get_device_name(0))
            except Exception:
                status["device"] = "CUDA device"
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def _kokoro_runtime_status() -> dict[str, object]:
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "origin": "",
        "error": "",
        "subprocess": True,
    }
    try:
        if (spec := _find_spec("kokoro")) is None:
            return status
        status["installed"] = True
        status["origin"] = str(getattr(spec, "origin", "") or "")
        from kokoro import KPipeline  # type: ignore

        status["valid"] = KPipeline is not None
        status["origin"] = str(getattr(spec, "origin", "") or "")
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def _stt_runtime_status() -> dict[str, object]:
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "version": "",
        "origin": "",
        "error": "",
        "subprocess": True,
    }
    try:
        if (spec := _find_spec("faster_whisper")) is None:
            return status
        status["installed"] = True
        status["origin"] = str(getattr(spec, "origin", "") or "")
        status["version"] = _distribution_version("faster-whisper")
        from faster_whisper import WhisperModel  # type: ignore

        status["valid"] = WhisperModel is not None
        status["origin"] = str(getattr(spec, "origin", "") or "")
        status["version"] = _distribution_version("faster-whisper")
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def _elevenlabs_runtime_status() -> dict[str, object]:
    """Verify the SDK entry point used by OpenWand, not merely its package folder."""
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "version": "",
        "origin": "",
        "error": "",
        "subprocess": True,
    }
    try:
        if (spec := _find_spec("elevenlabs")) is None:
            return status
        status["installed"] = True
        status["origin"] = str(getattr(spec, "origin", "") or "")
        status["version"] = _distribution_version("elevenlabs")
        from elevenlabs.client import ElevenLabs  # type: ignore

        status["valid"] = ElevenLabs is not None
        status["origin"] = str(getattr(spec, "origin", "") or "")
        status["version"] = _distribution_version("elevenlabs")
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def _stt_model_status(model_name: str, requested_device: str, requested_compute: str) -> dict[str, object]:
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "model": model_name,
        "device": "",
        "compute": "",
        "requested_device": requested_device,
        "requested_compute": requested_compute,
        "diagnostics": [],
        "error": "",
        "subprocess": True,
    }
    diagnostics: list[str] = []
    try:
        if _find_spec("faster_whisper") is None:
            status["error"] = "faster_whisper was not found in OpenWand's selected dependency layer"
            status["diagnostics"] = [str(status["error"])]
            return status
        status["installed"] = True
        from faster_whisper import WhisperModel  # type: ignore

        from core.stt_device import build_model, resolve_compute_type, resolve_device

        def _log(message: str) -> None:
            diagnostics.append(str(message))
            print(f"[stt probe] {message}", file=sys.stderr, flush=True)

        _log(
            f"Model verification requested model={model_name!r}, "
            f"device={requested_device!r}, compute={requested_compute!r}."
        )
        device = resolve_device(requested_device, log=_log)
        compute = resolve_compute_type(device, requested_compute, log=_log)
        status["device"] = device
        status["compute"] = compute
        _log(f"Model verification resolved device={device!r}, compute={compute!r} before model construction.")
        if requested_device.strip().lower() == "cuda" and device != "cuda":
            raise RuntimeError(
                "CUDA was explicitly requested, but the NVIDIA/CUDA runtime could not be verified. "
                "The STT installer will not report a successful CPU fallback for an explicit GPU request."
            )
        _model, device, compute = build_model(WhisperModel, model_name, device, compute, log=_log)
        status["device"] = device
        status["compute"] = compute
        status["valid"] = True
        _log(f"Model verification succeeded with effective device={device!r}, compute={compute!r}.")
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
        diagnostics.append(f"Model verification failed: {type(exc).__name__}: {exc}")
    status["diagnostics"] = diagnostics
    return status


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    valid_probes = {
        "torch-status",
        "kokoro-runtime-status",
        "stt-runtime-status",
        "stt-model-status",
        "elevenlabs-runtime-status",
    }
    if len(args) < 2 or args[0] not in valid_probes:
        print(json.dumps({"error": "usage: optional_deps_probe <probe> <optional-packages-dir> [args...]"}))
        return 2
    probe, optional_dir = args[:2]
    _configure_dependency_path(optional_dir)
    if probe == "torch-status":
        status = _torch_status()
    elif probe == "kokoro-runtime-status":
        status = _kokoro_runtime_status()
    elif probe == "stt-runtime-status":
        status = _stt_runtime_status()
    elif probe == "elevenlabs-runtime-status":
        status = _elevenlabs_runtime_status()
    else:
        if len(args) != 5:
            print(json.dumps({"error": "usage: optional_deps_probe stt-model-status <optional-packages-dir> <model> <device> <compute>"}))
            return 2
        status = _stt_model_status(args[2], args[3], args[4])
    print(json.dumps(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
