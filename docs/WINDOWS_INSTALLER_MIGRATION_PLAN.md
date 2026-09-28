# Windows installer and portable migration

Status: Inno Setup smoke test complete on the `dev` branch. The OpenWand installer, Azure signing integration, and migration flow remain to be implemented.

## Proven with a disposable app

`tools/test_inno_smoke.ps1` compiles a one-file installer with Inno Setup 6.7.3. On Windows, it verifies a silent per-user install, the Programs and Features entry, an in-place upgrade using the same `AppId`, and silent uninstall. It uses a unique temporary app ID and install path on each run. This does not yet test signing or package the OpenWand bundle.

## Existing release behavior

- The released Windows updater reads `assets["windows-x64"]` from `openwand-release-manifest.json` and expects a ZIP. It always extracts the downloaded file and replaces the portable app folder. Pointing that key at an EXE would break released clients.
- Settings offers Check, Download, and Apply in separate steps. It offers an update only when the manifest version exceeds the running app version.
- Settings and most writable state already live in `%APPDATA%\OpenWand`. A portable Windows build puts user add-ons next to `OpenWand.exe` when that folder is writable. A per-user installer will also be writable, so installed mode must explicitly place add-ons in `%APPDATA%\OpenWand\addons`.
- The existing portable uninstaller deletes the app folder and user data. An installed copy must invoke its registered Windows uninstaller; full data removal needs a separate, explicit user choice.

## Migration for users on the current ZIP release

1. The first installer-capable release publishes both the legacy ZIP and the new EXE. Keep `assets["windows-x64"]` mapped to the ZIP so every existing updater can reach this bridge release. Add a distinct `assets["windows-x64-installer"]` entry for the EXE. The manifest generator must reject collisions rather than silently overwrite either artifact.
2. Current portable users apply the bridge ZIP through Settings as they do today. The bridge app then offers **Switch to installed OpenWand** even when its version equals the EXE version; this is a change of install type, not a version update. The action includes a clear explanation of the new install location and the portable copy that will remain as backup.
3. The bridge app copies user add-ons from the portable `addons` folder to `%APPDATA%\OpenWand\addons` without overwriting conflicts. Existing settings, chats, models, and credentials stay in their current user-data locations. The installed app uses the user-data add-on folder, while portable mode retains its present behavior.
4. The bridge app downloads the versioned EXE, checks its manifest SHA-256 and Authenticode signature, then starts a detached helper. After OpenWand exits, the helper runs the installer silently, checks its exit code and registration, and opens the installed executable. On failure, the original portable copy remains usable.
5. Leave the old portable folder in place after migration. Offer explicit cleanup after the installed app has opened and its add-ons and settings have been checked. Never remove an arbitrary folder merely because it once contained OpenWand.

This gives existing users an in-app path with no manual download: one normal ZIP update, then one explicit switch to the installer. The first EXE release must retain the compatibility ZIP while old clients are supported. A direct one-click handoff from the old updater is technically possible through its new-version PowerShell helper hook, but it would download both the ZIP and EXE and change install type without the old UI explaining it. The bridge prompt is safer and clearer.

## Installed release behavior

- Use a stable Inno `AppId`, per-user x64 installation, one Programs entry, Start Menu shortcut, and a fixed default location under `%LOCALAPPDATA%\Programs\OpenWand`.
- Sign the bundled PE files first, then sign Inno's generated uninstaller and final setup EXE with the existing Azure Artifact Signing account. Verify every signature before publishing.
- Installed copies select the installer manifest entry. Their updater verifies the download and runs the next installer after OpenWand exits. It must never use the portable folder-replacement helper.
- In-app Uninstall invokes the registered uninstaller. Windows uninstall removes installer-owned files and registration. Removal of settings, credentials, add-ons, and models remains a separate explicit action.
- Upload each versioned installer without `--clobber`. Once its URL is submitted to Microsoft Store, the bytes at that URL must stay unchanged.

## Release gates

- Build and sign the real offline installer on a Windows CI runner.
- Verify silent fresh install, in-place upgrade, Programs entry, launch, Windows uninstall, and no leftover installer registration.
- Verify a current released ZIP can update to the bridge ZIP, switch to the EXE, retain settings and user add-ons, and recover cleanly from an installer failure.
- Verify installer updates do not invoke ZIP folder replacement, and portable updates still do.
