from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCKS = (
    "requirements/requirements-windows.lock",
    "requirements/requirements-linux.lock",
    "requirements/requirements-macos.lock",
)
COMBINED_INSTALL_LOCK_GROUPS = tuple(
    (runtime_lock, companion_lock)
    for runtime_lock in RUNTIME_LOCKS
    for companion_lock in ("requirements/requirements-build.lock", "requirements/requirements-dev.lock")
)


def test_optional_contract_verifier_defaults_to_every_feature() -> None:
    """The CI verifier accepts no positional arguments and checks the full matrix."""
    from scripts.verify_optional_contract_installs import FEATURES, _parse_features

    assert _parse_features([]) == list(FEATURES)
    assert _parse_features(["stt", "kokoro"]) == ["stt", "kokoro"]


def test_optional_contract_lock_matrix_is_complete() -> None:
    """Every supported feature/platform/variant has independent Source and Release locks."""
    variants = {
        "windows-x64": {"stt-cpu", "stt-cuda", "kokoro-cpu", "kokoro-gpu", "elevenlabs", "live-voice"},
        "linux-x64": {"stt-cpu", "kokoro-cpu", "kokoro-gpu", "elevenlabs", "live-voice"},
        "macos-arm64": {"stt-cpu", "kokoro-cpu", "elevenlabs", "live-voice"},
    }
    expected = {
        ROOT / "requirements" / "optional" / kind / target / f"{variant}.lock"
        for kind in ("source", "release")
        for target, target_variants in variants.items()
        for variant in target_variants
    }
    actual = set((ROOT / "requirements" / "optional").glob("*/*/*.lock"))

    assert actual == expected
    assert len(actual) == 30
    for path in actual:
        text = path.read_text(encoding="utf-8")
        assert "==" in text
        assert not any(
            line and not line.startswith(("#", " ", "--")) and "==" not in line and " @ " not in line
            for line in text.splitlines()
        ), path


def test_release_contracts_agree_on_every_cross_feature_overlap() -> None:
    """Installing another feature must not change a dependency owned by the first."""
    from core import optional_deps

    matrix = {
        ("win32", "AMD64"): (
            ("stt", "cpu"),
            ("stt", "cuda"),
            ("kokoro", "cpu"),
            ("kokoro", "cuda"),
            ("elevenlabs", None),
            ("live_voice", None),
        ),
        ("linux", "x86_64"): (
            ("stt", "cpu"),
            ("kokoro", "cpu"),
            ("kokoro", "cuda"),
            ("elevenlabs", None),
            ("live_voice", None),
        ),
        ("darwin", "arm64"): (
            ("stt", "cpu"),
            ("kokoro", "cpu"),
            ("elevenlabs", None),
            ("live_voice", None),
        ),
    }
    for (platform_name, machine), variants in matrix.items():
        contracts: list[tuple[str, dict[str, str]]] = []
        for key, device in variants:
            release = next(
                contract
                for contract in optional_deps.optional_dependency_contracts(
                    key,
                    device=device,
                    platform_name=platform_name,
                    machine=machine,
                )
                if contract.kind == "release"
            )
            contracts.append(
                (key, optional_deps._expected_package_versions(release.packages))  # type: ignore[attr-defined]
            )
        for index, (left_key, left) in enumerate(contracts):
            for right_key, right in contracts[index + 1 :]:
                if left_key == right_key:
                    continue
                conflicts = {
                    name: (left[name], right[name])
                    for name in left.keys() & right.keys()
                    if left[name] != right[name]
                }
                assert conflicts == {}, (platform_name, left_key, right_key)


def _locked_version(lock_name: str, package: str) -> str:
    prefix = f"{package}=="
    for line in (ROOT / lock_name).read_text(encoding="utf-8").splitlines():
        if line.lower().startswith(prefix):
            return line.split("==", 1)[1].strip()
    raise AssertionError(f"{lock_name} does not pin {package}")


def test_runtime_manifest_pins_optional_ai_shared_dependencies() -> None:
    """Keep source checkout installs compatible with optional local AI packages."""
    manifest = (ROOT / "requirements/requirements.txt").read_text(encoding="utf-8")

    assert "protobuf==6.33.2" in manifest
    assert "tokenizers==0.22.2" in manifest
    assert "setuptools==81.0.0" in manifest
    assert "elevenlabs==2.55.0" in manifest


def test_runtime_locks_keep_optional_ai_shared_dependencies_compatible() -> None:
    """Avoid pip warnings from optional torch/transformers/opentelemetry installs."""
    for lock_name in RUNTIME_LOCKS:
        assert _locked_version(lock_name, "protobuf").startswith("6.")
        assert _locked_version(lock_name, "tokenizers") == "0.22.2"
        assert _locked_version(lock_name, "setuptools") == "81.0.0"
        assert _locked_version(lock_name, "elevenlabs") == "2.55.0"


def test_combined_lock_installs_do_not_pin_conflicting_versions() -> None:
    """Packaging/dev installs combine locks, so shared pins must agree."""
    for lock_group in COMBINED_INSTALL_LOCK_GROUPS:
        package_versions: dict[str, dict[str, str]] = {}
        for lock_name in lock_group:
            for line in (ROOT / lock_name).read_text(encoding="utf-8").splitlines():
                if "==" not in line or line.startswith((" ", "#")):
                    continue
                package, version = line.split("==", 1)
                package = package.lower()
                version = version.split(";", 1)[0].strip()
                package_versions.setdefault(package, {})[lock_name] = version

        conflicts = {
            package: versions
            for package, versions in package_versions.items()
            if len(set(versions.values())) > 1
        }
        assert conflicts == {}


def test_optional_installer_uses_exact_known_compatible_package_specs(monkeypatch) -> None:
    """Optional package installs should not float into runtime-lock conflicts."""
    from core import optional_deps

    assert optional_deps.ELEVENLABS_PACKAGE == "elevenlabs==2.55.0"
    assert optional_deps.STT_PACKAGE == "faster-whisper==1.2.1"
    assert optional_deps.KOKORO_PACKAGE == "kokoro==0.9.4"
    assert optional_deps.SOUNDFILE_PACKAGE == "soundfile==0.14.0"
    assert optional_deps.KOKORO_TRANSFORMERS_PACKAGE == "transformers==5.13.1"
    assert optional_deps.KOKORO_MISAKI_PACKAGE == "misaki[en]==0.9.4"
    assert optional_deps.KOKORO_LOGURU_PACKAGE == "loguru==0.7.3"
    assert optional_deps.stt_install_packages() == list(
        optional_deps._optional_contract_lock_packages("release", "stt")  # type: ignore[attr-defined]
    )
    windows_cuda = optional_deps.stt_install_packages("cuda", platform_name="win32")
    assert windows_cuda == optional_deps.stt_install_packages("auto", platform_name="win32")
    assert "nvidia-cuda-runtime-cu12==12.8.90" in windows_cuda
    assert "nvidia-cublas-cu12==12.8.4.1" in windows_cuda
    assert "nvidia-cuda-runtime-cu12==12.8.90" not in optional_deps.stt_install_packages(
        "cuda", platform_name="linux"
    )
    assert "nvidia-cuda-runtime-cu12==12.8.90" not in optional_deps.stt_install_packages(
        "cuda", platform_name="darwin"
    )
    platform_locks = {
        "win32": "requirements/requirements-windows.lock",
        "linux": "requirements/requirements-linux.lock",
        "darwin": "requirements/requirements-macos.lock",
    }
    for platform_name, lock_name in platform_locks.items():
        for requirement in optional_deps.stt_locked_packages(platform_name):
            package, expected = requirement.split("==", 1)
            assert _locked_version(lock_name, package) == expected
    assert optional_deps.stt_remove_artifacts() == [
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
    assert optional_deps.kokoro_remove_artifacts() == [
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
    assert optional_deps.KOKORO_INSTALL_PACKAGES[:5] == [
        "kokoro==0.9.4",
        "soundfile==0.14.0",
        "protobuf==6.33.2",
        "tokenizers==0.22.2",
        "setuptools==81.0.0",
    ]
    monkeypatch.setattr(optional_deps.sys, "platform", "win32")
    assert optional_deps.kokoro_torch_install_packages("cuda") == [
        "--index-url",
        optional_deps.PYTORCH_CUDA_WHEEL_INDEX,
        "--extra-index-url",
        optional_deps.PYPI_WHEEL_INDEX,
        "torch==2.11.0+cu128",
        *optional_deps.SPEECH_SHARED_LOCKED_PACKAGES,
    ]
    assert optional_deps.kokoro_install_packages("cuda") == list(
        optional_deps._optional_contract_lock_packages(  # type: ignore[attr-defined]
            "release", "kokoro", device="cuda", platform_name="win32"
        )
    )


def test_stt_and_kokoro_use_one_order_independent_shared_dependency_lock(monkeypatch) -> None:
    """Installing either speech stack cannot replace the other's shared versions."""
    from core import optional_deps

    monkeypatch.setattr(optional_deps.sys, "platform", "win32")

    def pinned(requirements: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for requirement in requirements:
            if requirement.startswith("-") or "==" not in requirement:
                continue
            name, version = requirement.split("==", 1)
            result[name.split("[", 1)[0].lower()] = version
        return result

    stt = pinned(optional_deps.stt_install_packages("cuda", platform_name=optional_deps.sys.platform))
    kokoro = pinned(optional_deps.kokoro_install_packages("cuda"))
    kokoro_torch = pinned(optional_deps.kokoro_torch_install_packages("cuda"))

    shared_names = set(stt) & set(kokoro)
    assert {"tokenizers", "setuptools"} <= shared_names
    assert {name: stt[name] for name in shared_names} == {
        name: kokoro[name] for name in shared_names
    }
    torch_shared_names = set(kokoro_torch) & set(kokoro)
    assert torch_shared_names
    assert {name: kokoro_torch[name] for name in torch_shared_names} == {
        name: kokoro[name] for name in torch_shared_names
    }

    stt_then_kokoro = {**stt, **kokoro}
    kokoro_then_stt = {**kokoro, **stt}
    assert {name: stt_then_kokoro[name] for name in shared_names} == {
        name: kokoro_then_stt[name] for name in shared_names
    }
