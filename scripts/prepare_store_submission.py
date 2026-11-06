"""Prepare reviewable Store submission files from the final signed installer.

This generates metadata only. It does not sign, deploy Pages, submit to Partner
Center, or alter the tracked list of immutable Store downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"en", "zhHant", "zh", "es", "fr"}


def prepare(installer: Path, version: str, previous: dict[str, Any], notes: dict[str, str]) -> dict[str, Any]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a numeric major.minor.patch version")
    filename = f"OpenWand-v{version}-windows-x64-setup.exe"
    if installer.name != filename:
        raise ValueError("Installer filename does not match the release version")
    if set(notes) != LANGUAGES or any(not isinstance(text, str) or not text.strip() for text in notes.values()):
        raise ValueError("Store notes must cover all five installer languages")
    digest = hashlib.sha256()
    with installer.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    entry = {
        "version": f"v{version}", "filename": filename,
        "url": f"https://github.com/SunnyLich/OpenWand/releases/download/v{version}/{filename}",
        "sha256": digest.hexdigest(), "size": installer.stat().st_size,
    }
    entries = list(previous["installers"])
    matching = [item for item in entries if item["version"] == entry["version"]]
    if matching and matching != [entry]:
        raise ValueError("Refusing to change an immutable Store download entry")
    if not matching:
        entries.append(entry)
    return {
        "product_id": "XP99WCK9Q8WTG1",
        "version": version,
        "installer_url": f"https://sunnylich.github.io/OpenWand/downloads/v{version}/{filename}",
        "installer_parameters": "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART",
        "source": entry,
        "release_notes": notes,
        "downloads_manifest": {"installers": entries},
        "publication_order": [
            "Publish the GitHub release only after all artifact and upgrade checks pass.",
            "Copy downloads.json to packaging/microsoft-store/downloads.json and deploy Pages.",
            "Verify the public installer URL returns HTTP 200 without a redirect and matches the recorded hash and size.",
            "Submit the versioned URL, installer parameters and localized notes in Partner Center.",
            "Wait for Store certification/publication; test install and in-app update from the actual Store.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/store-submission"))
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    previous = json.loads((ROOT / "packaging/microsoft-store/downloads.json").read_text(encoding="utf-8"))
    notes = json.loads((ROOT / f"docs/releases/{version}-store.json").read_text(encoding="utf-8"))
    result = prepare(args.installer, version, previous, notes)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in (("submission.json", result), ("downloads.json", result["downloads_manifest"])):
        (args.output / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Store submission files prepared: {args.output}")


if __name__ == "__main__":
    main()
