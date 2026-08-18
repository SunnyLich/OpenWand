"""Runtime-installable optional Python dependencies."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import site
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.system.paths import REPO_ROOT, USER_DATA_DIR


def _optional_packages_dir() -> Path:
    """Return the shared user-writable optional dependency install directory."""
    override = os.environ.get("OPENWAND_OPTIONAL_PACKAGES_DIR")
    if override:
        return Path(override).expanduser()
    return USER_DATA_DIR / "python_packages"


OPTIONAL_PACKAGES_DIR = _optional_packages_dir()
KOKORO_EN_MODEL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)
PYTORCH_CUDA_WHEEL_INDEX = "https://download.pytorch.org/whl/cu128"
PYPI_WHEEL_INDEX = "https://pypi.org/simple"
KOKORO_CUDA_TORCH_PACKAGE = "torch==2.11.0+cu128"
KOKORO_PACKAGE = "kokoro==0.9.4"
SOUNDFILE_PACKAGE = "soundfile==0.14.0"
KOKORO_TRANSFORMERS_PACKAGE = "transformers==5.13.1"
KOKORO_MISAKI_PACKAGE = "misaki[en]==0.9.4"
KOKORO_LOGURU_PACKAGE = "loguru==0.7.3"
ELEVENLABS_PACKAGE = "elevenlabs==2.55.0"
# Live voice conversation (Gemini Live). Pin verified against the bundled
# locks: its httpx/pydantic/websockets/anyio/requests ranges all accept the
# lock versions, so pip --target won't vendor shadowing duplicates of bundled
# packages into the optional dir (google-auth/tenacity are not bundled and
# install fresh). No remove-artifacts list: the google/ namespace dir is
# shared with google-auth, so blind removal would break other packages.
GOOGLE_GENAI_PACKAGE = "google-genai==2.10.0"
STT_PACKAGE = "faster-whisper==1.2.1"
# Runtime optional installs cannot consume the build environment's monolithic
# requirements lock: installing that entire file into the shared optional
# directory would duplicate OpenWand itself and every provider.  Keep the exact
# faster-whisper dependency closure here instead.  These versions are copied
# from the platform release locks and are checked against them in CI.
_STT_LOCKED_VERSIONS = {
    "faster-whisper": "1.2.1",
    "av": "17.1.0",
    "ctranslate2": "4.8.0",
    "huggingface-hub": "1.21.0",
    "tokenizers": "0.22.2",
    "tqdm": "4.68.3",
    "numpy": "2.5.0",
    "pyyaml": "6.0.3",
    "setuptools": "81.0.0",
    "flatbuffers": "25.12.19",
    "packaging": "26.2",
    "protobuf": "6.33.2",
    "filelock": "3.29.4",
    "fsspec": "2026.6.0",
    "hf-xet": "1.5.1",
    "httpx": "0.28.1",
    "requests": "2.34.2",
    "typer": "0.25.1",
    "typing-extensions": "4.15.0",
    "anyio": "4.14.1",
    "certifi": "2026.6.17",
    "httpcore": "1.0.9",
    "idna": "3.18",
    "charset-normalizer": "3.4.7",
    "urllib3": "2.7.0",
    "annotated-doc": "0.0.4",
    "click": "8.4.2",
    "rich": "15.0.0",
    "shellingham": "1.5.4",
    "h11": "0.16.0",
    "sniffio": "1.3.1",
    "markdown-it-py": "4.2.0",
    "pygments": "2.20.0",
    "mdurl": "0.1.2",
}

# STT and Kokoro are installed into one optional-package directory. Any
# dependency that both stacks can resolve must therefore have one release-owned
# version, or installing one feature can silently change the other. Provider-
# specific native/model packages stay out of this shared set.
_STT_PROVIDER_ONLY_PACKAGES = {
    "faster-whisper",
    "av",
    "ctranslate2",
    "flatbuffers",
    "onnxruntime",
}
_OPTIONAL_AI_COMPAT_PACKAGE_NAMES = (
    "protobuf",
    "tokenizers",
    "setuptools",
)


def _stt_locked_versions(platform_name: str | None = None) -> dict[str, str]:
    """Return the platform release versions that own the speech shared layer."""
    platform_name = platform_name or sys.platform
    versions = dict(_STT_LOCKED_VERSIONS)
    versions["onnxruntime"] = "1.23.2" if platform_name == "darwin" else "1.27.0"
    if platform_name == "win32":
        versions["colorama"] = "0.4.6"
    return versions


def stt_locked_packages(platform_name: str | None = None) -> list[str]:
    """Return the exact faster-whisper closure from one platform release lock."""
    versions = _stt_locked_versions(platform_name)
    return [f"{name}=={version}" for name, version in versions.items()]


def speech_shared_locked_packages(platform_name: str | None = None) -> list[str]:
    """Return identical pins for every dependency shared by STT and Kokoro."""
    versions = _stt_locked_versions(platform_name)
    ordered_names = [
        *_OPTIONAL_AI_COMPAT_PACKAGE_NAMES,
        *(
            name
            for name in versions
            if name not in _STT_PROVIDER_ONLY_PACKAGES
            and name not in _OPTIONAL_AI_COMPAT_PACKAGE_NAMES
        ),
    ]
    return [f"{name}=={versions[name]}" for name in ordered_names]


STT_LOCKED_PACKAGES = stt_locked_packages()
SPEECH_SHARED_LOCKED_PACKAGES = speech_shared_locked_packages()
OPTIONAL_AI_COMPAT_PACKAGES = SPEECH_SHARED_LOCKED_PACKAGES[:len(_OPTIONAL_AI_COMPAT_PACKAGE_NAMES)]
_ELEVENLABS_LOCKED_VERSIONS = {
    "anyio": "4.14.1",
    "annotated-types": "0.7.0",
    "certifi": "2026.6.17",
    "charset-normalizer": "3.4.7",
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "idna": "3.18",
    "pydantic": "2.13.4",
    "pydantic-core": "2.46.4",
    "requests": "2.34.2",
    "sniffio": "1.3.1",
    "typing-extensions": "4.15.0",
    "typing-inspection": "0.4.2",
    "urllib3": "2.7.0",
    "websockets": "15.0.1",
}
ELEVENLABS_INSTALL_PACKAGES = [
    ELEVENLABS_PACKAGE,
    *(f"{name}=={version}" for name, version in _ELEVENLABS_LOCKED_VERSIONS.items()),
]
STT_WINDOWS_CUDA_PACKAGES = [
    "nvidia-cuda-runtime-cu12==12.8.90",
    "nvidia-cublas-cu12==12.8.4.1",
]
OPTIONAL_INSTALL_CONTRACT_SCHEMA = 5
OPTIONAL_LAYER_MANIFEST_SCHEMA = 1
OPTIONAL_LAYER_MANIFEST_NAME = ".openwand-contract.json"
_SUPPORTED_CONTRACT_TARGETS = {
    "win32": {"amd64", "x86_64"},
    "linux": {"amd64", "x86_64"},
    "darwin": {"arm64", "aarch64"},
}
_CONTRACT_TARGET_SLUGS = {
    "win32": "windows-x64",
    "linux": "linux-x64",
    "darwin": "macos-arm64",
}
KOKORO_BASE_INSTALL_PACKAGES = [
    KOKORO_PACKAGE,
    SOUNDFILE_PACKAGE,
    *SPEECH_SHARED_LOCKED_PACKAGES,
    KOKORO_TRANSFORMERS_PACKAGE,
    KOKORO_MISAKI_PACKAGE,
    KOKORO_LOGURU_PACKAGE,
    KOKORO_EN_MODEL_URL,
]
KOKORO_INSTALL_PACKAGES = list(KOKORO_BASE_INSTALL_PACKAGES)
# The compat pins only exist on PyPI; the cu128 index hosts torch wheels
# alone, so it needs PyPI as a fallback index or pip finds zero versions.
KOKORO_GPU_TORCH_INSTALL_PACKAGES = [
    "--index-url",
    PYTORCH_CUDA_WHEEL_INDEX,
    "--extra-index-url",
    PYPI_WHEEL_INDEX,
    KOKORO_CUDA_TORCH_PACKAGE,
    *SPEECH_SHARED_LOCKED_PACKAGES,
]
# pip --target cannot see packages already staged in the target dir, so the
# Kokoro phase re-resolves kokoro's torch dependency and would overwrite the
# staged CUDA build with PyPI's CPU wheel. Pin the exact +cu128 build here
# too; pip reuses the wheel cached during the Torch phase.
KOKORO_GPU_INSTALL_PACKAGES = [
    "--extra-index-url",
    PYTORCH_CUDA_WHEEL_INDEX,
    KOKORO_CUDA_TORCH_PACKAGE,
    *KOKORO_BASE_INSTALL_PACKAGES,
]
UV_UNSAFE_BEST_MATCH_INDEX_ARGS = ["--index-strategy", "unsafe-best-match"]
KOKORO_REMOVE_ARTIFACTS = [
    "kokoro",
    "kokoro-*.dist-info",
    "misaki",
    "misaki-*.dist-info",
    "soundfile.py",
    "soundfile-*.dist-info",
    "_soundfile.py",
    "_soundfile_data",
    "numpy",
    "numpy-*.dist-info",
    "numpy.libs",
    "huggingface_hub",
    "huggingface_hub-*.dist-info",
    "en_core_web_sm",
    "en_core_web_sm-*.dist-info",
]
STT_INSTALL_PACKAGES = list(STT_LOCKED_PACKAGES)
STT_REMOVE_ARTIFACTS = [
    "faster_whisper",
    "faster_whisper-*.dist-info",
    "ctranslate2",
    "ctranslate2-*.dist-info",
    "ctranslate2.libs",
    "av",
    "av-*.dist-info",
    "av.libs",
    "onnxruntime",
    "onnxruntime-*.dist-info",
    "onnxruntime.libs",
]
_DIST_INFO_SUFFIX = ".dist-info"


@dataclass(frozen=True)
class OptionalPackageSpec:
    """Release-owned optional package install contract."""

    key: str
    display_name: str
    packages: tuple[str, ...]
    required_modules: tuple[str, ...] = ()
    remove_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionalDependencyContract:
    """One complete, immutable dependency set accepted as a unit."""

    kind: str
    key: str
    device: str
    packages: tuple[str, ...]
    fingerprint: str


def _is_frozen() -> bool:
    """Return whether OpenWand is running from a packaged executable."""
    return bool(getattr(sys, "frozen", False))


def _normalized_machine(machine: str | None = None) -> str:
    value = str(machine if machine is not None else platform.machine()).strip().lower()
    aliases = {
        "x64": "amd64",
        "x86-64": "x86_64",
        "x86_64h": "x86_64",
        "arm64e": "arm64",
    }
    return aliases.get(value, value)


def optional_contract_target_supported(
    *,
    platform_name: str | None = None,
    machine: str | None = None,
) -> bool:
    """Return whether OpenWand builds and tests dependency contracts for a target."""
    selected_platform = str(platform_name or sys.platform).strip().lower()
    return _normalized_machine(machine) in _SUPPORTED_CONTRACT_TARGETS.get(selected_platform, set())


def _optional_contract_variant(key: str, device: str | None, platform_name: str) -> str:
    normalized = str(key or "").strip().lower().replace("_", "-")
    selected = str(device or "").strip().lower()
    if normalized == "stt":
        return "stt-cuda" if platform_name == "win32" and selected in {"auto", "cuda"} else "stt-cpu"
    if normalized == "kokoro":
        gpu = platform_name != "darwin" and selected in {"auto", "cuda"}
        return "kokoro-gpu" if gpu else "kokoro-cpu"
    if normalized == "elevenlabs":
        return "elevenlabs"
    if normalized in {"live-voice", "live_voice"}:
        return "live-voice"
    raise KeyError(f"Unknown optional package contract: {key}")


def optional_contract_lock_path(
    kind: str,
    key: str,
    *,
    device: str | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> Path | None:
    """Return the checked-in lock for one supported whole contract."""
    selected_platform = str(platform_name or sys.platform).strip().lower()
    if machine is not None and not optional_contract_target_supported(
        platform_name=selected_platform,
        machine=machine,
    ):
        return None
    target = _CONTRACT_TARGET_SLUGS.get(selected_platform)
    normalized_kind = str(kind or "").strip().lower()
    if not target or normalized_kind not in {"source", "release"}:
        return None
    variant = _optional_contract_variant(key, device, selected_platform)
    return REPO_ROOT / "requirements" / "optional" / normalized_kind / target / f"{variant}.lock"


def _optional_contract_lock_packages(
    kind: str,
    key: str,
    *,
    device: str | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, ...]:
    path = optional_contract_lock_path(
        kind,
        key,
        device=device,
        platform_name=platform_name,
        machine=machine,
    )
    if path is None:
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    packages: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        # uv emits requirements-file options as one textual line, while
        # subprocess argv requires the flag and value as separate items.
        if text.startswith("--") and " " in text:
            option, value = text.split(None, 1)
            packages.extend((option, value))
        else:
            packages.append(text)
    return tuple(packages)


def _runtime_lock_path(platform_name: str) -> Path | None:
    filenames = {
        "win32": "requirements-windows.lock",
        "linux": "requirements-linux.lock",
        "darwin": "requirements-macos.lock",
    }
    filename = filenames.get(str(platform_name).strip().lower())
    return REPO_ROOT / "requirements" / filename if filename else None


def _runtime_lock_versions(platform_name: str) -> dict[str, str]:
    """Read exact versions from one checked-in source runtime lock."""
    path = _runtime_lock_path(platform_name)
    if path is None:
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    versions: dict[str, str] = {}
    for line in lines:
        text = line.strip()
        if not text or text.startswith(("#", "-")) or "==" not in text:
            continue
        name, version = text.split("==", 1)
        version = version.split(";", 1)[0].strip()
        if name.strip() and version:
            versions[_canonical_package_name(name)] = version
    return versions


def _find_uv() -> str:
    """Find a uv executable usable for packaged optional dependency installs."""
    suffix = ".exe" if sys.platform == "win32" else ""
    candidates: list[Path] = []
    bundle_root = Path(getattr(sys, "_MEIPASS", REPO_ROOT))
    candidates.extend([
        bundle_root / "bin" / f"uv{suffix}",
        bundle_root / "uv" / f"uv{suffix}",
        bundle_root / f"uv{suffix}",
    ])
    if _is_frozen():
        exe_root = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_root / "bin" / f"uv{suffix}",
            exe_root / "_internal" / "bin" / f"uv{suffix}",
            exe_root / f"uv{suffix}",
        ])
    candidates.extend([
        REPO_ROOT / "bin" / f"uv{suffix}",
        REPO_ROOT / "tools" / f"uv{suffix}",
    ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("uv") or ""


def add_optional_packages_to_path(*, prepend: bool = False) -> None:
    """Add user packages, optionally preferring their dependency layer."""
    path = str(OPTIONAL_PACKAGES_DIR)
    try:
        OPTIONAL_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        if path not in sys.path:
            site.addsitedir(path)
    except Exception:
        pass

    if prepend:
        # ``site.addsitedir`` appends after PyInstaller's bundled importer. A
        # runtime-installed provider needs its matching dependency versions as
        # one layer, but only opt-in consumers should override bundled modules.
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def is_importable(module_name: str) -> bool:
    """Return whether an optional dependency exists in OpenWand's managed package dir."""
    add_optional_packages_to_path()
    importlib.invalidate_caches()
    try:
        return importlib.machinery.PathFinder.find_spec(module_name, [str(OPTIONAL_PACKAGES_DIR)]) is not None
    except Exception:
        return False


def stt_install_packages(device: str | None = None, *, platform_name: str | None = None) -> list[str]:
    """Return the exact packages for the selected STT platform/device."""
    platform_name = platform_name or sys.platform
    locked = _optional_contract_lock_packages(
        "release",
        "stt",
        device=device,
        platform_name=platform_name,
    )
    if locked:
        return list(locked)
    # Unsupported source targets do not have a release lock. Keep the old
    # source-install recipe available as best effort without calling it a
    # supported contract.
    packages = stt_locked_packages(platform_name)
    if platform_name == "win32" and str(device or "").strip().lower() in {"auto", "cuda"}:
        packages.extend(STT_WINDOWS_CUDA_PACKAGES)
    return packages


def stt_remove_artifacts() -> list[str]:
    """Return optional-package artifacts to clear before repairing STT."""
    return list(STT_REMOVE_ARTIFACTS)


def kokoro_remove_artifacts() -> list[str]:
    """Return optional-package artifacts to clear before repairing Kokoro."""
    return list(KOKORO_REMOVE_ARTIFACTS)


def optional_package_spec(key: str, *, device: str | None = None) -> OptionalPackageSpec:
    """Return the release spec for an optional package family."""
    normalized = str(key or "").strip().lower().replace("_", "-")
    if normalized == "stt":
        return OptionalPackageSpec(
            key="stt",
            display_name="STT",
            packages=tuple(stt_install_packages(device)),
            required_modules=("faster_whisper", "av.about", "ctranslate2"),
            remove_artifacts=tuple(stt_remove_artifacts()),
        )
    if normalized == "kokoro":
        packages = kokoro_install_packages(device)
        return OptionalPackageSpec(
            key="kokoro",
            display_name="Kokoro",
            packages=tuple(packages),
            required_modules=("kokoro", "en_core_web_sm"),
            remove_artifacts=tuple(kokoro_remove_artifacts()),
        )
    if normalized == "elevenlabs":
        packages = _optional_contract_lock_packages("release", "elevenlabs")
        return OptionalPackageSpec(
            key="elevenlabs",
            display_name="ElevenLabs",
            packages=packages or tuple(ELEVENLABS_INSTALL_PACKAGES),
            required_modules=("elevenlabs",),
        )
    if normalized in {"live-voice", "live_voice"}:
        packages = _optional_contract_lock_packages("release", "live_voice")
        return OptionalPackageSpec(
            key="live_voice",
            display_name="Live voice",
            packages=packages or (GOOGLE_GENAI_PACKAGE,),
            required_modules=("google.genai",),
        )
    raise KeyError(f"Unknown optional package spec: {key}")


def _dependency_contract_fingerprint(
    *,
    kind: str,
    key: str,
    device: str,
    packages: tuple[str, ...],
    platform_name: str,
    machine: str,
) -> str:
    payload = {
        "schema": OPTIONAL_INSTALL_CONTRACT_SCHEMA,
        "kind": kind,
        "key": key,
        "device": device,
        "platform": platform_name,
        "machine": machine,
        "python_implementation": sys.implementation.name,
        "python_cache_tag": str(getattr(sys.implementation, "cache_tag", "") or ""),
        "packages": list(packages),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{OPTIONAL_INSTALL_CONTRACT_SCHEMA}:{kind}:{digest[:24]}"


def optional_dependency_contracts(
    key: str,
    *,
    device: str | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> tuple[OptionalDependencyContract, ...]:
    """Return the whole Source and Release contracts accepted for one feature.

    Contracts exist only for OpenWand's supported release targets. Unsupported
    operating-system/architecture combinations remain source-only best effort
    and deliberately do not acquire an implied compatibility promise.
    """
    selected_platform = str(platform_name or sys.platform).strip().lower()
    selected_machine = _normalized_machine(machine)
    if not optional_contract_target_supported(
        platform_name=selected_platform,
        machine=selected_machine,
    ):
        return ()
    spec = optional_package_spec(key, device=device)
    selected_device = str(device or "").strip().lower()
    contracts: list[OptionalDependencyContract] = []
    source_packages = _optional_contract_lock_packages(
        "source",
        spec.key,
        device=device,
        platform_name=selected_platform,
        machine=selected_machine,
    )
    if source_packages:
        contracts.append(
            OptionalDependencyContract(
                kind="source",
                key=spec.key,
                device=selected_device,
                packages=source_packages,
                fingerprint=_dependency_contract_fingerprint(
                    kind="source",
                    key=spec.key,
                    device=selected_device,
                    packages=source_packages,
                    platform_name=selected_platform,
                    machine=selected_machine,
                ),
            )
        )
    release_packages = _optional_contract_lock_packages(
        "release",
        spec.key,
        device=device,
        platform_name=selected_platform,
        machine=selected_machine,
    )
    if not release_packages:
        return tuple(contracts)
    contracts.append(
        OptionalDependencyContract(
            kind="release",
            key=spec.key,
            device=selected_device,
            packages=release_packages,
            fingerprint=_dependency_contract_fingerprint(
                kind="release",
                key=spec.key,
                device=selected_device,
                packages=release_packages,
                platform_name=selected_platform,
                machine=selected_machine,
            ),
        )
    )
    return tuple(contracts)


def optional_dependency_contract_record(
    key: str,
    *,
    device: str | None = None,
    kind: str = "release",
) -> dict[str, object]:
    """Return atomic provenance data for a selected complete contract."""
    contracts = optional_dependency_contracts(key, device=device)
    contract = next((item for item in contracts if item.kind == kind), None)
    if contract is None:
        return {}
    return {
        "schema": OPTIONAL_LAYER_MANIFEST_SCHEMA,
        "kind": contract.kind,
        "key": contract.key,
        "device": contract.device,
        "fingerprint": contract.fingerprint,
        "packages": _expected_package_versions(contract.packages),
        "platform": sys.platform,
        "machine": _normalized_machine(),
        "python_implementation": sys.implementation.name,
        "python_cache_tag": str(getattr(sys.implementation, "cache_tag", "") or ""),
    }


def optional_package_contract(key: str, *, device: str | None = None) -> str:
    """Return a stable fingerprint for an optional install and its checker.

    Persisted success statuses and staged downloads are only reusable while
    this fingerprint matches.  Changing package pins or checker semantics then
    makes an application update revalidate instead of trusting stale state.
    """
    contracts = optional_dependency_contracts(key, device=device)
    release = next((contract for contract in contracts if contract.kind == "release"), None)
    if release is not None:
        return release.fingerprint
    # Unsupported source-only targets do not gain a release contract. Return a
    # stable unsupported marker so installer plans cannot masquerade as supported.
    spec = optional_package_spec(key, device=device)
    payload = {
        "schema": OPTIONAL_INSTALL_CONTRACT_SCHEMA,
        "kind": "unsupported",
        "platform": sys.platform,
        "machine": _normalized_machine(),
        "key": spec.key,
        "packages": list(spec.packages),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{OPTIONAL_INSTALL_CONTRACT_SCHEMA}:unsupported:{digest[:24]}"


def local_speech_install_contract(*, kokoro_device: str, stt_device: str) -> str:
    """Return one fingerprint for the wizard's combined TTS and STT install."""
    payload = {
        "schema": OPTIONAL_INSTALL_CONTRACT_SCHEMA,
        "platform": sys.platform,
        "machine": platform.machine().lower(),
        "python_implementation": sys.implementation.name,
        "python_cache_tag": str(getattr(sys.implementation, "cache_tag", "") or ""),
        "key": "local-speech",
        "kokoro": optional_package_contract("kokoro", device=kokoro_device),
        "stt": optional_package_contract("stt", device=stt_device),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{OPTIONAL_INSTALL_CONTRACT_SCHEMA}:{digest[:24]}"


def optional_installer_dir() -> Path:
    """Return the durable control/log directory for optional installs.

    Installer plans must survive a OpenWand restart. Per-run diagnostic directories
    deliberately do not, so they can never own apply plans or status files.
    """
    return OPTIONAL_PACKAGES_DIR.parent / "installers"


def optional_layer_manifest_path(target_dir: Path | str | None = None) -> Path:
    target = Path(target_dir) if target_dir is not None else OPTIONAL_PACKAGES_DIR
    return target / OPTIONAL_LAYER_MANIFEST_NAME


def read_optional_layer_manifest(target_dir: Path | str | None = None) -> dict[str, object]:
    """Read optional-layer provenance without treating it as package evidence."""
    try:
        data = json.loads(optional_layer_manifest_path(target_dir).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict) or int(data.get("schema") or 0) != OPTIONAL_LAYER_MANIFEST_SCHEMA:
        return {}
    return data


def write_optional_layer_contracts(
    target_dir: Path | str,
    records: list[dict[str, object]],
) -> Path:
    """Atomically merge verified contract provenance into an inactive layer."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    existing = read_optional_layer_manifest(target)
    existing_contracts = existing.get("contracts")
    contracts = dict(existing_contracts) if isinstance(existing_contracts, dict) else {}
    for record in records:
        key = str(record.get("key") or "").strip()
        if key:
            contracts[key] = dict(record)
    payload = {
        "schema": OPTIONAL_LAYER_MANIFEST_SCHEMA,
        "contracts": contracts,
    }
    path = optional_layer_manifest_path(target)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def optional_install_log_path(display_name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", str(display_name).lower()).strip("-") or "optional-package"
    return optional_installer_dir() / f"{slug}-install.log"


def optional_install_status_path(display_name: str) -> Path:
    return optional_install_log_path(display_name).with_suffix(".status.json")


def read_optional_install_status(display_name: str) -> dict[str, object]:
    """Read one durable installer status document without trusting its result."""
    try:
        data = json.loads(optional_install_status_path(display_name).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def current_optional_install_status(
    display_name: str,
    key: str,
    *,
    device: str | None = None,
) -> dict[str, object]:
    """Return installer state only when it belongs to the current contract."""
    from core import updater

    status = read_optional_install_status(display_name)
    if (
        str(status.get("install_contract") or "") != optional_package_contract(key, device=device)
        or str(status.get("app_version") or "") != updater.current_version()
    ):
        return {}
    return status


def current_local_speech_install_status(
    *,
    kokoro_device: str,
    stt_device: str,
) -> dict[str, object]:
    """Return the setup wizard's combined status for the current contract."""
    from core import updater

    status = read_optional_install_status("Local speech")
    if (
        str(status.get("install_contract") or "")
        != local_speech_install_contract(kokoro_device=kokoro_device, stt_device=stt_device)
        or str(status.get("app_version") or "") != updater.current_version()
    ):
        return {}
    return status


def _expected_package_versions(packages: list[str] | tuple[str, ...]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for item in packages:
        parsed = _install_requirement_name_version(item)
        if parsed is None:
            continue
        name, version = parsed
        expected[name] = version
    return expected


def _primary_package_name(key: str) -> str:
    normalized = str(key or "").strip().lower().replace("_", "-")
    return {
        "stt": "faster-whisper",
        "kokoro": "kokoro",
        "elevenlabs": "elevenlabs",
        "live-voice": "google-genai",
    }.get(normalized, normalized)


def _dist_info_groups_for_root(root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    if not root.exists():
        return groups
    try:
        candidates = list(root.iterdir())
    except Exception:
        return groups
    for path in candidates:
        if not path.is_dir() or not path.name.endswith(_DIST_INFO_SUFFIX):
            continue
        name, _version = _dist_info_metadata(path)
        canonical = _canonical_package_name(name)
        if canonical:
            groups.setdefault(canonical, []).append(path)
    return groups


def _installed_versions_from_groups(groups: dict[str, list[Path]]) -> dict[str, list[str]]:
    return {
        package: sorted({(_dist_info_metadata(path)[1] or "") for path in paths})
        for package, paths in groups.items()
    }


def _installed_versions_from_distributions(paths: list[str]) -> dict[str, list[str]]:
    # Import resolution uses the first matching sys.path root. Compare the
    # contract with that active layer and ignore shadowed user/global installs
    # from later roots; duplicate metadata inside the selected root still fails.
    versions: dict[str, set[str]] = {}
    selected_root: dict[str, str] = {}
    for raw_path in paths:
        try:
            root = str(Path(raw_path).resolve())
            distributions = importlib.metadata.distributions(path=[raw_path])
            for distribution in distributions:
                name = _canonical_package_name(str(distribution.metadata.get("Name") or ""))
                if not name:
                    continue
                if name in selected_root and selected_root[name] != root:
                    continue
                selected_root.setdefault(name, root)
                versions.setdefault(name, set()).add(str(distribution.version or ""))
        except Exception:
            continue
    return {name: sorted(found) for name, found in versions.items()}


def _dependency_contract_result(
    contract: OptionalDependencyContract,
    installed_versions: dict[str, list[str]],
) -> dict[str, object]:
    """Compare one installed layer with one complete contract, without mixing."""
    expected = _expected_package_versions(contract.packages)
    missing: list[str] = []
    mismatched: dict[str, object] = {}
    duplicates: dict[str, list[str]] = {}
    for package, expected_version in expected.items():
        found = installed_versions.get(package) or []
        if not found:
            missing.append(package)
            continue
        if len(found) > 1:
            duplicates[package] = list(found)
        if found != [expected_version]:
            mismatched[package] = {
                "expected": expected_version,
                "installed": list(found),
            }
    return {
        "kind": contract.kind,
        "fingerprint": contract.fingerprint,
        "expected": expected,
        "missing": missing,
        "mismatched": mismatched,
        "duplicates": duplicates,
        "valid": bool(expected) and not missing and not mismatched and not duplicates,
    }


def optional_dependency_record_status(
    record: dict[str, object],
    target_dir: Path | str,
) -> dict[str, object]:
    """Validate an inactive layer against one serialized whole contract.

    Installer helpers use this immediately before activation so a damaged,
    partial, or subsequently modified staging directory can never receive
    valid provenance or replace the active dependency layer.
    """
    raw_packages = record.get("packages")
    packages = dict(raw_packages) if isinstance(raw_packages, dict) else {}
    expected = {
        _canonical_package_name(str(name)): str(version)
        for name, version in packages.items()
        if str(name).strip() and str(version).strip()
    }
    synthetic = OptionalDependencyContract(
        kind=str(record.get("kind") or "release"),
        key=str(record.get("key") or ""),
        device=str(record.get("device") or ""),
        packages=tuple(f"{name}=={version}" for name, version in expected.items()),
        fingerprint=str(record.get("fingerprint") or ""),
    )
    groups = _dist_info_groups_for_root(Path(target_dir))
    result = _dependency_contract_result(synthetic, _installed_versions_from_groups(groups))
    result["key"] = synthetic.key
    return result


def _matching_dependency_contract(
    contracts: tuple[OptionalDependencyContract, ...],
    installed_versions: dict[str, list[str]],
    *,
    preferred_kind: str,
) -> tuple[OptionalDependencyContract | None, list[dict[str, object]]]:
    results = [_dependency_contract_result(contract, installed_versions) for contract in contracts]
    ordered_kinds = (preferred_kind, *(kind for kind in ("source", "release") if kind != preferred_kind))
    for kind in ordered_kinds:
        for contract, result in zip(contracts, results, strict=True):
            if contract.kind == kind and result["valid"]:
                return contract, results
    return None, results


def optional_package_spec_status(
    key: str,
    *,
    device: str | None = None,
    target_dir: Path | str | None = None,
) -> dict[str, object]:
    """Return whether the managed layer matches a whole Source or Release contract."""
    spec = optional_package_spec(key, device=device)
    target = Path(target_dir) if target_dir is not None else OPTIONAL_PACKAGES_DIR
    expected = _expected_package_versions(spec.packages)
    contracts = optional_dependency_contracts(key, device=device)
    status: dict[str, object] = {
        "key": spec.key,
        "display_name": spec.display_name,
        "installed": False,
        "valid": False,
        "expected": dict(expected),
        "missing": [],
        "mismatched": {},
        "duplicates": {},
        "contract_kind": "",
        "contract_fingerprint": "",
        "contract_results": [],
        "supported_target": bool(contracts),
        "provenance": {},
        "message": "",
    }
    try:
        root = target.resolve()
    except Exception:
        root = target
    groups = _dist_info_groups_for_root(root)
    installed_versions = _installed_versions_from_groups(groups)
    manifest = read_optional_layer_manifest(root)
    manifest_contracts = manifest.get("contracts")
    provenance = (
        dict(manifest_contracts.get(spec.key) or {})
        if isinstance(manifest_contracts, dict)
        else {}
    )
    status["provenance"] = provenance
    match, results = _matching_dependency_contract(
        contracts,
        installed_versions,
        preferred_kind="release",
    )
    status["contract_results"] = results
    primary_name = _primary_package_name(spec.key)
    status["installed"] = bool(primary_name and installed_versions.get(primary_name))
    if match is not None:
        matched_result = next(result for result in results if result["fingerprint"] == match.fingerprint)
        recorded_fingerprint = str(provenance.get("fingerprint") or "")
        provenance_valid = not recorded_fingerprint or recorded_fingerprint == match.fingerprint
        status["valid"] = provenance_valid
        status["expected"] = dict(matched_result["expected"])
        status["contract_kind"] = match.kind
        status["contract_fingerprint"] = match.fingerprint
        status["message"] = (
            f"{spec.display_name} package files match the complete {match.kind} contract."
            if provenance_valid
            else f"{spec.display_name} package versions match, but recorded contract provenance differs. Repair it."
        )
    else:
        preferred_result = next(
            (result for result in results if result["kind"] == "release"),
            results[0] if results else None,
        )
        missing = list(preferred_result["missing"]) if preferred_result else list(expected)
        mismatched = dict(preferred_result["mismatched"]) if preferred_result else {}
        duplicates = dict(preferred_result["duplicates"]) if preferred_result else {}
        status["missing"] = missing
        status["mismatched"] = mismatched
        status["duplicates"] = duplicates
        parts: list[str] = []
        if not contracts:
            parts.append("unsupported operating-system or architecture target")
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if mismatched:
            parts.append(f"version mismatch for {', '.join(sorted(mismatched))}")
        if duplicates:
            parts.append(f"duplicate metadata for {', '.join(sorted(duplicates))}")
        status["message"] = (
            f"{spec.display_name} package files do not match a complete Source or Release contract: "
            f"{'; '.join(parts)}."
        )
    return status


def _source_environment_paths() -> list[str]:
    """Return import paths for a source checkout, excluding the managed layer."""
    try:
        optional_root = OPTIONAL_PACKAGES_DIR.resolve()
    except Exception:
        optional_root = OPTIONAL_PACKAGES_DIR
    paths: list[str] = []
    for raw_path in sys.path:
        if not raw_path:
            raw_path = os.getcwd()
        try:
            if Path(raw_path).resolve() == optional_root:
                continue
        except Exception:
            pass
        paths.append(raw_path)
    return paths


def _find_module_spec(module_name: str, search_paths: list[str]):
    """Find a top-level or dotted module without importing its parent package."""
    parts = [part for part in str(module_name or "").split(".") if part]
    if not parts:
        return None
    fullname = parts[0]
    spec = importlib.machinery.PathFinder.find_spec(fullname, search_paths)
    for part in parts[1:]:
        if spec is None:
            return None
        locations = getattr(spec, "submodule_search_locations", None)
        if locations is None:
            return None
        fullname = f"{fullname}.{part}"
        spec = importlib.machinery.PathFinder.find_spec(fullname, list(locations))
    return spec


def _source_environment_spec_status(key: str, *, device: str | None = None) -> dict[str, object]:
    """Check the provider installed by a source checkout's Python environment.

    Supported targets must match one complete Source or Release dependency
    contract. Unsupported targets are explicitly source-only best effort: the
    provider and required imports must work, but OpenWand makes no version promise.
    """
    spec = optional_package_spec(key, device=device)
    paths = _source_environment_paths()
    installed = _installed_versions_from_distributions(paths)
    primary_name = _primary_package_name(spec.key)
    primary_versions = installed.get(primary_name) or []
    contracts = optional_dependency_contracts(key, device=device)
    match, contract_results = _matching_dependency_contract(
        contracts,
        installed,
        preferred_kind="source",
    )
    missing_modules = []
    for module_name in spec.required_modules:
        try:
            found = _find_module_spec(module_name, paths) is not None
        except Exception:
            found = False
        if not found:
            missing_modules.append(module_name)
    supported_target = bool(contracts)
    # Unsupported platforms/architectures are source-only and intentionally
    # best effort. Do not manufacture or persist a compatibility contract.
    valid = bool(match) and not missing_modules if supported_target else bool(primary_versions) and not missing_modules
    detail: list[str] = []
    if not primary_versions:
        detail.append(f"missing {primary_name}")
    elif supported_target and match is None:
        detail.append("installed versions mix or differ from the complete Source and Release contracts")
    if missing_modules:
        detail.append(f"missing import {', '.join(missing_modules)}")
    if not supported_target:
        detail.append("unsupported target; source dependencies are best effort")
    matched_result = (
        next(result for result in contract_results if result["fingerprint"] == match.fingerprint)
        if match is not None
        else None
    )
    preferred_result = next(
        (result for result in contract_results if result["kind"] == "source"),
        contract_results[0] if contract_results else None,
    )
    return {
        "key": spec.key,
        "display_name": spec.display_name,
        "source": "environment",
        "installed": bool(primary_versions),
        "valid": valid,
        "expected": dict(
            matched_result["expected"]
            if matched_result is not None
            else preferred_result["expected"]
            if preferred_result is not None
            else {}
        ),
        "missing": list(preferred_result["missing"]) if preferred_result is not None else [],
        "mismatched": dict(preferred_result["mismatched"]) if preferred_result is not None else {},
        "duplicates": dict(preferred_result["duplicates"]) if preferred_result is not None else {},
        "contract_kind": match.kind if match is not None else "unsupported-source" if not supported_target else "",
        "contract_fingerprint": match.fingerprint if match is not None else "",
        "contract_results": contract_results,
        "supported_target": supported_target,
        "message": (
            f"{spec.display_name} is provided by the complete {match.kind} contract in the source environment."
            if valid and match is not None
            else f"{spec.display_name} is usable from an unsupported source target without a support contract."
            if valid
            else f"{spec.display_name} is not usable from the source Python environment: {'; '.join(detail)}."
        ),
    }


def optional_package_runtime_status(key: str, *, device: str | None = None) -> dict[str, object]:
    """Return the dependency layer the current source/release runtime can use."""
    managed = dict(optional_package_spec_status(key, device=device))
    managed["source"] = "managed"
    if managed.get("valid") or _is_frozen():
        return managed

    environment = _source_environment_spec_status(key, device=device)
    if environment.get("valid"):
        environment["managed"] = managed
        return environment
    if managed.get("installed"):
        managed["environment"] = environment
        return managed
    environment["managed"] = managed
    return environment


def require_optional_package_runtime(
    key: str,
    *,
    device: str | None = None,
    allow_version_drift: bool = False,
) -> dict[str, object]:
    """Prepare one valid dependency layer for runtime use.

    Frozen releases must use the installer-owned layer because speech SDKs are
    deliberately excluded from the ZIP. Source checkouts may use the provider
    installed by their locked Python environment, while a valid managed repair
    install still takes precedence.
    """
    status = optional_package_runtime_status(key, device=device)
    # Kokoro has had compatible transitive dependency updates between app
    # releases.  Synthesis imports the real entry point immediately after this
    # check, so it is both safer and more useful to let that import decide than
    # to reject an otherwise complete layer solely because metadata pins moved.
    # Install/repair verification remains strict unless the caller explicitly
    # opts into this runtime-only compatibility path.
    compatible_managed_drift = bool(
        allow_version_drift
        and str(key or "").strip().lower().replace("_", "-") == "kokoro"
        and str(status.get("source") or "managed") == "managed"
        and status.get("installed")
    )
    if not status.get("valid") and not compatible_managed_drift:
        display_name = str(status.get("display_name") or key)
        detail = str(status.get("message") or "package files are missing or invalid")
        raise RuntimeError(
            f"{display_name} is not installed for this OpenWand release. "
            f"Open Settings > Voice and install it. {detail}"
        )

    source = str(status.get("source") or "managed")
    if source == "managed":
        add_optional_packages_to_path(prepend=True)
        search_paths = [str(OPTIONAL_PACKAGES_DIR)]
    else:
        optional_path = str(OPTIONAL_PACKAGES_DIR)
        while optional_path in sys.path:
            sys.path.remove(optional_path)
        search_paths = _source_environment_paths()
    importlib.invalidate_caches()
    spec = optional_package_spec(key, device=device)
    missing_modules = [
        module_name
        for module_name in spec.required_modules
        if _find_module_spec(module_name, search_paths) is None
    ]
    if missing_modules:
        raise RuntimeError(
            f"{spec.display_name} install is incomplete in the selected {source} dependency layer: "
            f"missing {', '.join(missing_modules)}. Open Settings > Voice and reinstall it."
        )
    if compatible_managed_drift:
        status["runtime_compatible"] = True
        status["version_drift"] = True
    return status


def remove_optional_package_artifacts(patterns: list[str]) -> list[str]:
    """Remove package files/directories from OpenWand's optional package layer.

    This is intentionally scoped to ``OPTIONAL_PACKAGES_DIR``. Runtime installs
    use ``pip --target``/``uv --target``, and a broken native wheel can survive a
    reinstall unless its old target directories are removed first.
    """
    removed: list[str] = []
    try:
        root = OPTIONAL_PACKAGES_DIR.resolve()
    except Exception:
        root = OPTIONAL_PACKAGES_DIR
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return removed
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip()
        if not pattern or any(sep in pattern for sep in ("/", "\\")):
            continue
        for path in root.glob(pattern):
            try:
                resolved = path.resolve()
                if resolved == root or root not in resolved.parents:
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(path.name)
            except FileNotFoundError:
                continue
            except Exception:
                continue
    return removed


def _canonical_package_name(name: str) -> str:
    """Return a PEP 503-ish normalized package name for grouping metadata."""
    return re.sub(r"[-_.]+", "-", name).lower().strip("-")


def _dist_info_metadata(path: Path) -> tuple[str, str]:
    """Return package name/version recorded by a ``.dist-info`` directory."""
    name = ""
    version = ""
    try:
        metadata = path / "METADATA"
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.lower().startswith("version:"):
                version = line.split(":", 1)[1].strip()
            if name and version:
                return name, version
    except Exception:
        pass

    stem = path.name[:-len(_DIST_INFO_SUFFIX)] if path.name.endswith(_DIST_INFO_SUFFIX) else path.name
    if "-" in stem:
        name, version = stem.rsplit("-", 1)
    else:
        name = stem
    return name, version


def _optional_dist_info_groups() -> dict[str, list[Path]]:
    """Return optional-package ``.dist-info`` directories grouped by package."""
    try:
        root = OPTIONAL_PACKAGES_DIR.resolve()
    except Exception:
        root = OPTIONAL_PACKAGES_DIR
    if not root.exists():
        return {}

    groups: dict[str, list[Path]] = {}
    try:
        candidates = list(root.iterdir())
    except Exception:
        return groups
    for path in candidates:
        if not path.is_dir() or not path.name.endswith(_DIST_INFO_SUFFIX):
            continue
        name, _version = _dist_info_metadata(path)
        canonical = _canonical_package_name(name)
        if canonical:
            groups.setdefault(canonical, []).append(path)
    return groups


def duplicate_optional_dist_infos() -> dict[str, list[str]]:
    """Return duplicate optional-package metadata directories by package name."""
    duplicates: dict[str, list[str]] = {}
    for package, paths in _optional_dist_info_groups().items():
        if len(paths) > 1:
            duplicates[package] = sorted(path.name for path in paths)
    return duplicates


def _dist_info_top_level_names(path: Path, package: str) -> list[str]:
    """Return top-level module/package artifacts described by a dist-info."""
    names: set[str] = set()
    try:
        for line in (path / "top_level.txt").read_text(encoding="utf-8", errors="replace").splitlines():
            name = line.strip()
            if name and not any(sep in name for sep in ("/", "\\")):
                names.add(name)
    except Exception:
        pass
    if not names:
        names.add(package.replace("-", "_"))
    return sorted(names)


def _namespace_owned_paths(root: Path, dist_info: Path, name: str) -> list[Path]:
    """Return the paths one distribution's RECORD owns inside a namespace dir."""
    try:
        record = (dist_info / "RECORD").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    members: set[str] = set()
    for line in record.splitlines():
        rel = line.split(",", 1)[0].strip().replace("\\", "/")
        if not rel.startswith(f"{name}/"):
            continue
        member = rel[len(name) + 1 :].split("/", 1)[0]
        if member:
            members.add(member)
    return [root / name / member for member in sorted(members)]


def _optional_package_artifact_paths(root: Path, package: str, dist_infos: list[Path]) -> list[Path]:
    """Return package artifacts associated with dist-info metadata."""
    paths: list[Path] = []
    seen: set[Path] = set()
    for dist_info in dist_infos:
        for name in _dist_info_top_level_names(dist_info, package):
            top = root / name
            if top.is_dir() and not (top / "__init__.py").exists():
                # Implicit namespace dir (google/, nvidia/, ...) shared by
                # several distributions: protobuf's top_level.txt says
                # "google", but deleting google/ wholesale would also remove
                # google-genai and google-auth. Remove only the members this
                # distribution's RECORD lists.
                owned = _namespace_owned_paths(root, dist_info, name)
                if owned:
                    for candidate in owned:
                        if candidate not in seen:
                            seen.add(candidate)
                            paths.append(candidate)
                    continue
            for candidate in (
                top,
                root / f"{name}.py",
                root / f"{name}.libs",
            ):
                if candidate not in seen:
                    seen.add(candidate)
                    paths.append(candidate)
        if dist_info not in seen:
            seen.add(dist_info)
            paths.append(dist_info)
    return paths


def _remove_optional_paths(
    paths: list[Path],
    *,
    root: Path | None = None,
) -> list[str]:
    """Remove resolved paths scoped to one optional-package directory."""
    selected_root = root or OPTIONAL_PACKAGES_DIR
    removed: list[str] = []
    try:
        resolved_root = selected_root.resolve()
    except Exception:
        resolved_root = selected_root
    for path in paths:
        try:
            resolved = path.resolve()
            if resolved == resolved_root or resolved_root not in resolved.parents:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path.name)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return removed


def _install_requirement_name_version(spec: str) -> tuple[str, str] | None:
    """Return normalized package name and exact version from an install spec."""
    text = str(spec or "").strip()
    if not text or text.startswith("-"):
        return None
    wheel_name = Path(text.split("?", 1)[0].rstrip("/")).name
    if wheel_name.endswith(".whl") and "-" in wheel_name:
        name, version, *_rest = wheel_name[:-4].split("-")
        return _canonical_package_name(name), version
    direct = re.match(
        r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?\s*@\s*(\S+)",
        text,
    )
    if direct:
        direct_wheel = Path(direct.group(2).split("?", 1)[0].rstrip("/")).name
        if direct_wheel.endswith(".whl") and "-" in direct_wheel:
            _wheel_package, version, *_rest = direct_wheel[:-4].split("-")
            return _canonical_package_name(direct.group(1)), version
    match = re.match(
        r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?\s*==\s*([^;,\s]+)",
        text,
    )
    if match:
        return _canonical_package_name(match.group(1)), match.group(2)
    return None


def remove_stale_optional_package_artifacts(
    packages: list[str],
    *,
    target_dir: Path | str | None = None,
) -> list[str]:
    """Remove target package artifacts that do not match pinned install specs."""
    requested = {
        name: version
        for item in packages
        if (parsed := _install_requirement_name_version(item))
        for name, version in [parsed]
    }
    if not requested:
        return []
    selected_root = Path(target_dir) if target_dir is not None else OPTIONAL_PACKAGES_DIR
    try:
        root = selected_root.resolve()
    except Exception:
        root = selected_root
    groups = _dist_info_groups_for_root(root)
    paths_to_remove: list[Path] = []
    for package, expected_version in requested.items():
        dist_infos = groups.get(package) or []
        if not dist_infos:
            continue
        installed_versions = {_dist_info_metadata(path)[1] for path in dist_infos}
        if len(dist_infos) > 1 or installed_versions != {expected_version}:
            paths_to_remove.extend(_optional_package_artifact_paths(root, package, dist_infos))
    return _remove_optional_paths(paths_to_remove, root=root)


def remove_duplicate_optional_package_artifacts(
    *,
    target_dir: Path | str | None = None,
) -> list[str]:
    """Remove package trees that have duplicate ``.dist-info`` metadata.

    ``pip install --target`` can leave old files behind during upgrades. When
    duplicate metadata already exists, remove the package tree and metadata so
    the next install recreates one coherent package version.
    """
    selected_root = Path(target_dir) if target_dir is not None else OPTIONAL_PACKAGES_DIR
    try:
        root = selected_root.resolve()
    except Exception:
        root = selected_root
    duplicates = {
        package: paths
        for package, paths in _dist_info_groups_for_root(root).items()
        if len(paths) > 1
    }
    paths_to_remove: list[Path] = []
    for package, paths in duplicates.items():
        paths_to_remove.extend(_optional_package_artifact_paths(root, package, paths))
    return _remove_optional_paths(paths_to_remove, root=root)


def subprocess_no_window_kwargs() -> dict[str, object]:
    """Return subprocess kwargs that suppress helper console windows on Windows."""
    if sys.platform != "win32":
        return {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    return {"creationflags": creationflags} if creationflags else {}


def system_cuda_available() -> bool:
    """Return whether the host appears to have an NVIDIA CUDA device."""
    if sys.platform == "darwin":
        return False
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        result = subprocess.run(
            [nvidia_smi, "-L"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            **subprocess_no_window_kwargs(),
        )
    except Exception:
        return False
    return result.returncode == 0 and "GPU" in (result.stdout or "")


def kokoro_install_mode_for_device(
    device: str | None,
    *,
    platform_name: str | None = None,
) -> str:
    """Return cpu/gpu install mode for the selected Kokoro device."""
    selected_platform = platform_name or sys.platform
    if selected_platform == "darwin":
        return "cpu"
    selected = "cpu" if device is None else str(device or "auto").strip().lower()
    if selected == "cpu":
        return "cpu"
    if selected in {"auto", "cuda"}:
        # A CUDA-enabled Torch wheel still supports CPU execution. Installing
        # it for Auto therefore provisions both runtime paths up front and
        # avoids making package selection depend on a fallible hardware probe.
        return "gpu"
    return "cpu"


def kokoro_install_packages(
    device: str | None,
    *,
    platform_name: str | None = None,
) -> list[str]:
    """Return packages/flags for the selected Kokoro device install."""
    selected_platform = platform_name or sys.platform
    locked = _optional_contract_lock_packages(
        "release",
        "kokoro",
        device=device,
        platform_name=selected_platform,
    )
    if locked:
        return list(locked)
    if kokoro_install_mode_for_device(device, platform_name=platform_name) == "gpu":
        return list(KOKORO_GPU_INSTALL_PACKAGES)
    return list(KOKORO_BASE_INSTALL_PACKAGES)


def kokoro_torch_install_packages(
    device: str | None,
    *,
    platform_name: str | None = None,
) -> list[str]:
    """Return an optional first install phase for Kokoro's Torch backend."""
    if kokoro_install_mode_for_device(device, platform_name=platform_name) == "gpu":
        return list(KOKORO_GPU_TORCH_INSTALL_PACKAGES)
    return []


def kokoro_torch_status() -> dict[str, object]:
    """Return installed Torch/Kokoro CUDA capability for Settings status."""
    add_optional_packages_to_path(prepend=True)
    importlib.invalidate_caches()
    status: dict[str, object] = {
        "installed": False,
        "version": "",
        "cuda_version": "",
        "cuda_available": False,
        "cuda_error": "",
        "device": "",
        "error": "",
        "valid": False,
    }
    try:
        if importlib.machinery.PathFinder.find_spec("torch", [str(OPTIONAL_PACKAGES_DIR)]) is None:
            return status
        import torch  # type: ignore

        status["installed"] = True
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
        else:
            # is_available() hides the reason (CPU-only wheel, driver too
            # old, ...); a forced init raises it so Settings can show it.
            try:
                torch.cuda.init()
            except Exception as exc:
                status["cuda_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def kokoro_cuda_failure_detail(status: dict[str, object]) -> str:
    """Describe a failed CUDA verification with the installed Torch's identity."""
    version = str(status.get("version") or "") or "unknown"
    cuda_version = str(status.get("cuda_version") or "")
    build = f"CUDA {cuda_version} build" if cuda_version else "CPU-only build"
    detail = f"torch {version} ({build})"
    cuda_error = str(status.get("cuda_error") or "")
    if cuda_error:
        detail = f"{detail}: {cuda_error}"
    return detail


def kokoro_torch_status_subprocess() -> dict[str, object]:
    """Return Torch status from a short-lived process so DLLs are not pinned."""
    return _optional_probe_status(
        "torch-status",
        {
            "installed": False,
            "version": "",
            "cuda_version": "",
            "cuda_available": False,
            "cuda_error": "",
            "device": "",
            "error": "",
            "valid": False,
            "subprocess": True,
        },
    )


def _optional_probe_status(
    probe: str,
    default: dict[str, object],
    *,
    extra_args: list[str] | None = None,
    dependency_source: str = "managed",
    timeout: float | None = 30,
    progress: Callable[[int], None] | None = None,
) -> dict[str, object]:
    """Run an optional dependency probe in a short-lived process."""
    try:
        command = [
            sys.executable,
            "-m",
            "runtime.workers.optional_deps_probe",
            probe,
            str(OPTIONAL_PACKAGES_DIR),
        ]
        if extra_args:
            command.extend(extra_args)
        probe_env = pip_install_env()
        probe_env["OPENWAND_OPTIONAL_PROBE_SOURCE"] = dependency_source
        common_kwargs = {
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "cwd": str(REPO_ROOT),
            "env": probe_env,
            **subprocess_no_window_kwargs(),
        }
        if progress is None:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
                **common_kwargs,
            )
        else:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **common_kwargs,
            )
            started_at = time.monotonic()
            while True:
                elapsed = time.monotonic() - started_at
                if timeout is not None and elapsed >= timeout:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                wait_for = 10.0 if timeout is None else max(0.1, min(10.0, timeout - elapsed))
                try:
                    stdout, stderr = process.communicate(timeout=wait_for)
                    result = subprocess.CompletedProcess(command, int(process.returncode or 0), stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    try:
                        progress(max(1, int(time.monotonic() - started_at)))
                    except Exception:
                        pass
        text = (result.stdout or "").strip().splitlines()
        if result.returncode != 0 or not text:
            detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
            status = dict(default)
            status["error"] = detail[:500] or f"{probe} subprocess failed."
            return status
        data = json.loads(text[-1])
        if isinstance(data, dict):
            data.setdefault("source", dependency_source)
            return data
        status = dict(default)
        status["error"] = f"{probe} subprocess returned invalid JSON."
        return status
    except subprocess.TimeoutExpired:
        status = dict(default)
        status["timed_out"] = True
        status["error"] = f"{probe} subprocess timed out after {timeout:g}s." if timeout else f"{probe} subprocess timed out."
        return status
    except Exception as exc:
        status = dict(default)
        status["error"] = f"{type(exc).__name__}: {exc}"
        return status


def stt_runtime_import_status_fast() -> dict[str, object]:
    """Return cheap faster-whisper package metadata without importing it."""
    add_optional_packages_to_path(prepend=True)
    importlib.invalidate_caches()
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "version": "",
        "origin": "",
        "error": "",
        "fast": True,
    }
    try:
        spec = importlib.machinery.PathFinder.find_spec("faster_whisper", [str(OPTIONAL_PACKAGES_DIR)])
        if spec is None:
            return status
        status["installed"] = True
        status["origin"] = str(getattr(spec, "origin", "") or "")
        dist_infos = _dist_info_groups_for_root(OPTIONAL_PACKAGES_DIR).get("faster-whisper") or []
        if len(dist_infos) == 1:
            status["version"] = _dist_info_metadata(dist_infos[0])[1]
        status["valid"] = bool(status["origin"])
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def stt_runtime_import_status_subprocess() -> dict[str, object]:
    """Return faster-whisper import status without pinning native modules."""
    return _optional_probe_status(
        "stt-runtime-status",
        {
            "installed": False,
            "valid": False,
            "version": "",
            "origin": "",
            "error": "",
            "subprocess": True,
        },
        dependency_source=str(optional_package_runtime_status("stt").get("source") or "managed"),
    )


def elevenlabs_runtime_import_status_subprocess() -> dict[str, object]:
    """Return ElevenLabs SDK import status without polluting the caller process."""
    return _optional_probe_status(
        "elevenlabs-runtime-status",
        {
            "installed": False,
            "valid": False,
            "version": "",
            "origin": "",
            "error": "",
            "subprocess": True,
        },
        dependency_source=str(optional_package_runtime_status("elevenlabs").get("source") or "managed"),
    )


def stt_model_status_subprocess(
    model: str,
    device: str,
    compute_type: str,
    *,
    progress: Callable[[int], None] | None = None,
) -> dict[str, object]:
    """Load a Whisper model in a subprocess to verify STT without freezing Settings."""
    timeout_text = os.environ.get("OPENWAND_STT_MODEL_VERIFY_TIMEOUT_SECONDS", "").strip()
    timeout: float | None = 60 * 60
    if timeout_text:
        try:
            timeout = max(1.0, float(timeout_text))
        except ValueError:
            timeout = 60 * 60
    return _optional_probe_status(
        "stt-model-status",
        {
            "installed": False,
            "valid": False,
            "model": model,
            "device": "",
            "compute": "",
            "requested_device": device,
            "requested_compute": compute_type,
            "diagnostics": [],
            "error": "",
            "subprocess": True,
        },
        extra_args=[model, device, compute_type],
        dependency_source=str(optional_package_runtime_status("stt", device=device).get("source") or "managed"),
        timeout=timeout,
        progress=progress,
    )


def _torch_version_from_package_files() -> str:
    """Return torch's version from version.py when dist-info metadata is missing."""
    try:
        text = (OPTIONAL_PACKAGES_DIR / "torch" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else ""


def kokoro_torch_status_fast() -> dict[str, object]:
    """Return cheap Torch package metadata for Settings without importing Torch."""
    add_optional_packages_to_path(prepend=True)
    importlib.invalidate_caches()
    status: dict[str, object] = {
        "installed": False,
        "version": "",
        "cuda_version": "",
        "cuda_available": False,
        "device": "",
        "error": "",
        "fast": True,
        "valid": False,
    }
    try:
        spec = importlib.machinery.PathFinder.find_spec("torch", [str(OPTIONAL_PACKAGES_DIR)])
        if spec is None:
            return status
        status["installed"] = True
        origin = str(getattr(spec, "origin", "") or "")
        status["origin"] = origin
        if not origin or not origin.replace("\\", "/").endswith("/torch/__init__.py"):
            status["error"] = "Torch install looks incomplete."
            return status
        try:
            from importlib import metadata

            status["version"] = metadata.version("torch")
        except Exception:
            # A failed pip --target upgrade can strip torch's dist-info while
            # leaving a working torch package behind; read the version from
            # the package files so Settings does not report a broken install.
            status["version"] = _torch_version_from_package_files()
        status["valid"] = bool(status["version"])
        version = str(status.get("version") or "").lower()
        status["cuda_version"] = "unknown" if any(marker in version for marker in ("+cu", "cuda", "cu12", "cu11")) else ""
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def kokoro_runtime_import_status() -> dict[str, object]:
    """Return whether Kokoro's runtime import path is usable."""
    add_optional_packages_to_path(prepend=True)
    importlib.invalidate_caches()
    status: dict[str, object] = {
        "installed": False,
        "valid": False,
        "origin": "",
        "error": "",
    }
    try:
        if (spec := importlib.machinery.PathFinder.find_spec("kokoro", [str(OPTIONAL_PACKAGES_DIR)])) is None:
            return status
        from kokoro import KPipeline  # type: ignore

        status["installed"] = True
        status["valid"] = KPipeline is not None
        status["origin"] = str(getattr(spec, "origin", "") or "")
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def kokoro_runtime_import_status_subprocess() -> dict[str, object]:
    """Return Kokoro runtime import status without pinning native modules."""
    return _optional_probe_status(
        "kokoro-runtime-status",
        {
            "installed": False,
            "valid": False,
            "origin": "",
            "error": "",
            "subprocess": True,
        },
        # Importing the CUDA-enabled Torch + Kokoro stack can legitimately take
        # around a minute on Windows after process start.  Thirty seconds caused
        # healthy installs to be reported as broken.
        timeout=90,
    )


def pip_install_command(
    packages: list[str],
    *,
    reinstall: bool = False,
    target_dir: Path | str | None = None,
) -> list[str]:
    """Return a command that installs packages into OpenWand's optional dir."""
    target = Path(target_dir) if target_dir is not None else OPTIONAL_PACKAGES_DIR
    if _is_frozen():
        uv = _find_uv()
        if not uv:
            suffix = ".exe" if sys.platform == "win32" else ""
            raise RuntimeError(
                "Packaged OpenWand installs optional packages with uv, but uv was not bundled. "
                f"Place uv{suffix} under bin/ or tools/ before building, then rebuild OpenWand."
            )
        index_args = _uv_index_strategy_args(packages)
        return [
            uv,
            "pip",
            "install",
            "--color",
            "never",
            "--link-mode",
            "copy",
            "--python-version",
            f"{sys.version_info.major}.{sys.version_info.minor}",
            "--target",
            str(target),
            *(["--reinstall"] if reinstall else []),
            *index_args,
            *packages,
        ]
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--progress-bar=raw",
        "--upgrade",
        "--target",
        str(target),
        *(["--force-reinstall"] if reinstall else []),
        *packages,
    ]


def _uv_index_strategy_args(packages: list[str]) -> list[str]:
    """Return uv-only index flags needed for mixed PyPI/PyTorch CUDA installs."""
    if PYTORCH_CUDA_WHEEL_INDEX in packages and KOKORO_CUDA_TORCH_PACKAGE in packages:
        return list(UV_UNSAFE_BEST_MATCH_INDEX_ARGS)
    return []


def ensure_pip_available() -> None:
    """Bootstrap pip for source-checkout optional package installs if needed."""
    if _is_frozen():
        return

    def run_python(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=pip_install_env(),
            **subprocess_no_window_kwargs(),
        )

    check = run_python(["-m", "pip", "--version"])
    if check.returncode == 0:
        return

    bootstrap = run_python(["-m", "ensurepip", "--upgrade"])
    if bootstrap.returncode != 0:
        detail = (bootstrap.stderr or bootstrap.stdout or "").strip()
        raise RuntimeError(
            "Python is missing pip, and ensurepip could not bootstrap it. "
            f"{detail or f'exit code {bootstrap.returncode}'}"
        )

    verify = run_python(["-m", "pip", "--version"])
    if verify.returncode != 0:
        detail = (verify.stderr or verify.stdout or "").strip()
        raise RuntimeError(
            "Python is missing pip even after ensurepip completed. "
            f"{detail or f'exit code {verify.returncode}'}"
        )


def pip_install_env() -> dict[str, str]:
    """Return an environment for optional dependency installs."""
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("UV_HTTP_TIMEOUT", "60")
    return env
