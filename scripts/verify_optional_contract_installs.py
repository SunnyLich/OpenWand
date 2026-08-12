"""Install and import every CPU Release contract on the current native target."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FEATURES = ("stt", "kokoro", "elevenlabs", "live_voice")


def _verify_feature(uv: str, feature: str, root: Path) -> None:
    from core import optional_deps

    device = "cpu" if feature in {"stt", "kokoro"} else None
    contract = next(
        item
        for item in optional_deps.optional_dependency_contracts(feature, device=device)
        if item.kind == "release"
    )
    target = root / feature
    command = [
        uv,
        "pip",
        "install",
        "--python",
        sys.executable,
        "--link-mode",
        "copy",
        "--target",
        str(target),
        *contract.packages,
    ]
    print(f"Installing {feature} Release contract ({len(contract.packages)} lock entries).", flush=True)
    subprocess.run(command, check=True)

    record = optional_deps.optional_dependency_contract_record(feature, device=device, kind="release")
    status = optional_deps.optional_dependency_record_status(record, target)
    if not status.get("valid"):
        raise RuntimeError(f"{feature} install does not match its Release contract: {status}")

    modules = optional_deps.optional_package_spec(feature, device=device).required_modules
    code = "\n".join(
        [
            "import importlib, sys",
            f"sys.path.insert(0, {str(target)!r})",
            f"modules = {modules!r}",
            "for name in modules:",
            "    module = importlib.import_module(name)",
            "    print(name, getattr(module, '__file__', 'namespace'))",
        ]
    )
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    subprocess.run([sys.executable, "-I", "-c", code], check=True, env=env)
    print(f"Verified {feature} Release contract.", flush=True)


def _parse_features(argv: list[str] | None = None) -> list[str]:
    """Return explicitly requested features, or every feature when omitted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", nargs="*", choices=FEATURES)
    args = parser.parse_args(argv)
    return list(args.features or FEATURES)


def main() -> int:
    from core import optional_deps

    features = _parse_features()
    if not optional_deps.optional_contract_target_supported():
        raise SystemExit("This operating-system/architecture target has no supported Release contracts.")
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required to verify optional dependency contracts.")
    with tempfile.TemporaryDirectory(prefix="openwand-optional-contracts-") as raw_root:
        root = Path(raw_root)
        for feature in features:
            _verify_feature(uv, feature, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
