"""Stage immutable, verified Store installers into the existing Pages deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stage(site: Path) -> None:
    manifest = json.loads((ROOT / "packaging/microsoft-store/downloads.json").read_text(encoding="utf-8"))
    for item in manifest["installers"]:
        version, filename = item["version"], item["filename"]
        if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("Store installer must have a fixed release version")
        if filename != f"OpenWand-{version}-windows-x64-setup.exe":
            raise ValueError("Unexpected Store installer filename")
        expected_url = f"https://github.com/SunnyLich/OpenWand/releases/download/{version}/{filename}"
        if item["url"] != expected_url or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ValueError("Invalid Store installer source or digest")
        target = site / "downloads" / version / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        digest, size = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(expected_url, timeout=120) as source, partial.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"Store installer integrity check failed: {filename}")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        print(f"Verified {filename}: {size} bytes, SHA256 {digest.hexdigest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    stage(parser.parse_args().site)
