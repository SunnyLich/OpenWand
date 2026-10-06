from __future__ import annotations

from pathlib import Path

import pytest

from scripts import make_release_manifest


def test_release_manifest_accepts_minor_only_v_tag(tmp_path: Path) -> None:
    asset = tmp_path / "OpenWand-v0.6-linux-x64.tar.gz"
    asset.write_bytes(b"release")

    manifest = make_release_manifest.build_manifest(
        [asset],
        repo="SunnyLich/Python-AI-assistant-overlay",
        tag="v0.6",
    )

    assert manifest["version"] == "0.6"
    assert manifest["notes_url"].endswith("/releases/tag/v0.6")
    assert manifest["assets"]["linux-x64"]["name"] == asset.name


def test_release_manifest_accepts_patch_v_tag(tmp_path: Path) -> None:
    asset = tmp_path / "OpenWand-v0.6.1-windows-x64.zip"
    asset.write_bytes(b"release")

    manifest = make_release_manifest.build_manifest(
        [asset],
        repo="SunnyLich/Python-AI-assistant-overlay",
        tag="v0.6.1",
    )

    assert manifest["version"] == "0.6.1"
    assert manifest["assets"]["windows-x64"]["sha256"] == make_release_manifest._sha256(asset)


def test_release_manifest_keeps_legacy_zip_and_installer_separate(tmp_path: Path) -> None:
    archive = tmp_path / "OpenWand-v0.12.0-windows-x64.zip"
    installer = tmp_path / "OpenWand-v0.12.0-windows-x64-setup.exe"
    archive.write_bytes(b"bridge")
    installer.write_bytes(b"installer")

    manifest = make_release_manifest.build_manifest(
        [installer, archive], repo="SunnyLich/OpenWand", tag="v0.12.0"
    )

    assert manifest["assets"]["windows-x64"]["name"] == archive.name
    assert manifest["assets"]["windows-x64-installer"]["name"] == installer.name


def test_release_manifest_can_pin_old_windows_client_to_transition_zip(tmp_path: Path) -> None:
    installer = tmp_path / "OpenWand-v0.13.0-windows-x64-setup.exe"
    installer.write_bytes(b"new installer")
    bridge = {
        "name": "OpenWand-v0.12.0-windows-x64.zip",
        "url": "https://github.com/SunnyLich/OpenWand/releases/download/v0.12.0/OpenWand-v0.12.0-windows-x64.zip",
        "sha256": "a" * 64,
        "size": 123,
    }

    manifest = make_release_manifest.build_manifest(
        [installer], repo="SunnyLich/OpenWand", tag="v0.13.0", legacy_windows_asset=bridge
    )

    assert manifest["version"] == "0.13.0"
    assert manifest["assets"]["windows-x64"] == bridge
    assert manifest["assets"]["windows-x64-installer"]["name"] == installer.name

    remote = {
        "tag_name": "v0.12.0",
        "assets": [{"name": bridge["name"], "size": bridge["size"], "digest": "sha256:" + bridge["sha256"]}],
    }
    make_release_manifest.verify_legacy_release_asset(bridge, remote, "SunnyLich/OpenWand")
    remote["assets"][0]["digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="digest changed"):
        make_release_manifest.verify_legacy_release_asset(bridge, remote, "SunnyLich/OpenWand")


def test_release_manifest_rejects_windows_asset_collision(tmp_path: Path) -> None:
    archive = tmp_path / "OpenWand-v0.12.0-windows-x64.zip"
    archive.write_bytes(b"bridge")
    with pytest.raises(ValueError, match="pinned transition ZIP cannot be combined"):
        make_release_manifest.build_manifest(
            [archive], repo="SunnyLich/OpenWand", tag="v0.12.0",
            legacy_windows_asset={"name": archive.name, "url": "https://example.test/bridge.zip", "sha256": "abc", "size": 6},
        )


def test_release_manifest_rejects_non_version_tag(tmp_path: Path) -> None:
    asset = tmp_path / "OpenWand-latest-linux-x64.tar.gz"
    asset.write_bytes(b"release")

    with pytest.raises(ValueError, match="Release tag does not look like a version"):
        make_release_manifest.build_manifest(
            [asset],
            repo="SunnyLich/Python-AI-assistant-overlay",
            tag="latest",
        )


def test_build_checksums_lists_release_assets_by_name(tmp_path: Path) -> None:
    windows_asset = tmp_path / "OpenWand-v0.6.1-windows-x64.zip"
    linux_asset = tmp_path / "OpenWand-v0.6.1-linux-x64.tar.gz"
    windows_asset.write_bytes(b"windows")
    linux_asset.write_bytes(b"linux")

    checksums = make_release_manifest.build_checksums([windows_asset, linux_asset])

    assert checksums == (
        f"{make_release_manifest._sha256(linux_asset)}  {linux_asset.name}\n"
        f"{make_release_manifest._sha256(windows_asset)}  {windows_asset.name}\n"
    )
