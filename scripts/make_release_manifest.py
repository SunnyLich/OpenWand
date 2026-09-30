"""Generate the OpenWand release manifest consumed by the in-app updater."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _platform_key(name: str) -> str:
    lowered = name.lower()
    arch = "arm64" if "arm64" in lowered or "aarch64" in lowered else "x64"
    if "windows" in lowered:
        if lowered.endswith(".exe"):
            return f"windows-{arch}-installer"
        if not lowered.endswith(".zip"):
            raise ValueError(f"Unsupported Windows release asset: {name}")
        return f"windows-{arch}"
    if "macos" in lowered or "darwin" in lowered:
        return f"macos-{arch}"
    if "linux" in lowered:
        return f"linux-{arch}"
    raise ValueError(f"Cannot infer platform key from asset name: {name}")


def _version_from_tag(tag: str) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    if not re.match(r"^\d+\.\d+(?:\.\d+)?(?:[.+-][0-9A-Za-z.-]+)?$", version):
        raise ValueError(f"Release tag does not look like a version: {tag}")
    return version


def verify_legacy_release_asset(legacy_asset: dict, release_metadata: dict, repo: str) -> None:
    """Fail publication if GitHub no longer hosts the immutable transition ZIP."""
    name = legacy_asset["name"]
    url = legacy_asset["url"]
    prefix = f"https://github.com/{repo}/releases/download/"
    if not url.startswith(prefix):
        raise ValueError("Pinned transition ZIP URL is outside this repository.")
    tag = url[len(prefix):].split("/", 1)[0]
    if not tag.startswith("v") or release_metadata.get("tag_name") != tag:
        raise ValueError("Pinned transition ZIP release tag does not match GitHub.")
    matching = [asset for asset in release_metadata.get("assets", []) if asset.get("name") == name]
    if len(matching) != 1 or matching[0].get("size") != legacy_asset["size"]:
        raise ValueError("Pinned transition ZIP is missing or changed on GitHub.")
    remote_digest = matching[0].get("digest")
    if remote_digest and remote_digest.lower() != f"sha256:{legacy_asset['sha256'].lower()}":
        raise ValueError("Pinned transition ZIP digest changed on GitHub.")


def build_manifest(
    asset_paths: list[Path], repo: str, tag: str, legacy_windows_asset: dict | None = None
) -> dict:
    """Build the manifest object for release assets."""
    version = _version_from_tag(tag)
    base_url = f"https://github.com/{repo}/releases/download/{tag}"
    assets = {}
    for path in asset_paths:
        key = _platform_key(path.name)
        if key in assets:
            raise ValueError(f"Multiple release assets map to {key}: {assets[key]['name']}, {path.name}")
        assets[key] = {
            "name": path.name,
            "url": f"{base_url}/{path.name}",
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    if legacy_windows_asset is not None:
        if "windows-x64" in assets:
            raise ValueError("A pinned transition ZIP cannot be combined with a new Windows ZIP.")
        required = ("name", "url", "sha256", "size")
        if any(field not in legacy_windows_asset for field in required):
            raise ValueError("Pinned transition ZIP metadata is incomplete.")
        name = legacy_windows_asset["name"]
        url = legacy_windows_asset["url"]
        digest = legacy_windows_asset["sha256"]
        size = legacy_windows_asset["size"]
        if not isinstance(name, str) or not name.lower().endswith("-windows-x64.zip"):
            raise ValueError("Pinned transition asset must be a ZIP.")
        if not isinstance(url, str) or not url.startswith(f"https://github.com/{repo}/releases/download/v") or not url.endswith(f"/{name}"):
            raise ValueError("Pinned transition ZIP must use its versioned GitHub release URL.")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("Pinned transition ZIP SHA256 is invalid.")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("Pinned transition ZIP size is invalid.")
        assets["windows-x64"] = {field: legacy_windows_asset[field] for field in required}
    return {
        "version": version,
        "notes_url": f"https://github.com/{repo}/releases/tag/{tag}",
        "assets": assets,
    }


def build_checksums(asset_paths: list[Path]) -> str:
    """Build a sha256sum-compatible checksum listing for release assets."""
    lines = [f"{_sha256(path)}  {path.name}" for path in sorted(asset_paths, key=lambda item: item.name)]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repository, e.g. owner/name")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v0.6 or v0.6.1")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--checksums-out", type=Path, help="Optional SHA256SUMS.txt output path")
    parser.add_argument("--legacy-windows-asset", type=Path, help="Pinned transition ZIP metadata JSON")
    parser.add_argument("--legacy-release-metadata", type=Path, help="GitHub API metadata for the pinned ZIP release")
    parser.add_argument("assets", nargs="+", type=Path)
    args = parser.parse_args()

    legacy_windows_asset = None
    if args.legacy_windows_asset:
        legacy_windows_asset = json.loads(args.legacy_windows_asset.read_text(encoding="utf-8"))
        if not isinstance(legacy_windows_asset, dict):
            raise ValueError("Pinned transition ZIP metadata must be a JSON object.")
    if args.legacy_release_metadata:
        if legacy_windows_asset is None:
            raise ValueError("GitHub release metadata requires a pinned transition ZIP.")
        remote = json.loads(args.legacy_release_metadata.read_text(encoding="utf-8"))
        if not isinstance(remote, dict):
            raise ValueError("GitHub release metadata must be a JSON object.")
        verify_legacy_release_asset(legacy_windows_asset, remote, args.repo)
    manifest = build_manifest(args.assets, repo=args.repo, tag=args.tag, legacy_windows_asset=legacy_windows_asset)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.checksums_out:
        args.checksums_out.parent.mkdir(parents=True, exist_ok=True)
        args.checksums_out.write_text(build_checksums(args.assets), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
