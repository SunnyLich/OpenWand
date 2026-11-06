"""Replay released 0.12.x updaters against the current Windows manifest format.

This checks manifest selection and hash-verified downloads using local fixture
bytes. It does not run an installer or claim to repair an old client's TLS trust.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.make_release_manifest import build_manifest

ROOT = Path(__file__).resolve().parents[1]
TAGS = ("v0.12.0", "v0.12.1", "v0.12.2")


def verify(*, fetch: bool = False) -> dict:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    bridge = json.loads((ROOT / "packaging/windows/transition-asset.json").read_text(encoding="utf-8"))
    results = []
    with TemporaryDirectory(prefix="openwand-legacy-compat-") as directory:
        temporary = Path(directory)
        installer = temporary / f"OpenWand-v{version}-windows-x64-setup.exe"
        installer.write_bytes(b"Compatibility fixture; not an executable installer.\n")
        manifest = build_manifest([installer], "SunnyLich/OpenWand", f"v{version}", bridge)
        assert manifest["assets"]["windows-x64"] == bridge
        # Use local fixture bytes to test the old download/hash code without
        # depending on a not-yet-published release or weakening TLS verification.
        manifest["assets"]["windows-x64-installer"]["url"] = installer.as_uri()
        manifest_file = temporary / "manifest.json"
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        for tag in TAGS:
            if fetch:
                subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", "tag", tag],
                               cwd=ROOT, check=True, capture_output=True)
            source = subprocess.check_output(["git", "show", f"{tag}:core/updater.py"], cwd=ROOT)
            module_name = "_legacy_updater_" + tag.replace(".", "_")
            legacy = types.ModuleType(module_name)
            legacy.__file__ = str(ROOT / "core/updater.py")
            sys.modules[module_name] = legacy
            try:
                exec(compile(source, f"{tag}:core/updater.py", "exec"), legacy.__dict__)
                for installed in (False, True):
                    with patch.object(sys, "frozen", True, create=True), patch.object(
                        legacy, "is_installed_release", return_value=installed
                    ):
                        result = legacy.check_for_updates(
                            url=manifest_file.as_uri(), platform_key="windows-x64", installed_version=tag[1:]
                        )
                        assert result.update_available and result.latest_version == version
                        assert result.asset is not None
                        assert result.asset.platform_key == "windows-x64-installer"
                        assert result.migration_available is (not installed)
                        downloaded = legacy.download_update(
                            result.asset, target_dir=temporary / f"{tag}-{installed}"
                        )
                        assert downloaded.read_bytes() == installer.read_bytes()
                        results.append({
                            "from_version": tag[1:], "to_version": version,
                            "mode": "installed" if installed else "portable-to-installer",
                            "legacy_updater_sha256": hashlib.sha256(source).hexdigest(),
                            "manifest_and_verified_download": "passed",
                        })
            finally:
                del sys.modules[module_name]
    return {"cases": results, "immutable_zip_bridge_preserved": True,
            "scope": "Released updater source, current manifest format and fixture-byte hash verification; actual installer upgrade and TLS recovery are separate checks."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Fetch released tags in a shallow CI checkout")
    parser.add_argument("--report", type=Path, default=Path("reports/legacy-updater-compatibility.json"))
    args = parser.parse_args()
    report = verify(fetch=args.fetch)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Released 0.12.x updater compatibility: {len(report['cases'])} cases passed. {args.report}")


if __name__ == "__main__":
    main()
