# Windows installer and portable migration

Status: implemented on `dev` for the planned `v0.12.0` transition release. The [Windows-only development workflow](https://github.com/SunnyLich/OpenWand/actions/runs/36652788044) passed on code commit `87d57ca`: bundle signatures, signed uninstaller and setup, installed launcher and uninstall, plus a portable-to-installer handoff with add-on preservation and backup retention. Focused migration tests passed locally. The released `v0.11.1` updater source selected the pinned transition ZIP from a simulated later manifest. An interactive update from an actual `v0.11.1` ZIP and release publication remain.

## Proven with a disposable app

`tools/test_inno_smoke.ps1` compiles a one-file installer with Inno Setup 6.7.3. On Windows, it verifies a silent per-user install, the Programs and Features entry, an in-place upgrade using the same `AppId`, and silent uninstall. It uses a unique temporary app ID and install path on each run. The real `packaging/windows/OpenWand.iss` also reached Inno's expected request to sign its generated uninstaller with a mock bundle.

## Existing release behavior

- The released Windows updater reads `assets["windows-x64"]` from `openwand-release-manifest.json` and expects a ZIP. It always extracts the downloaded file and replaces the portable app folder. Pointing that key at an EXE would break released clients.
- Settings offers Check, Download, and Apply in separate steps. It offers an update only when the manifest version exceeds the running app version.
- Settings and most writable state already live in `%APPDATA%\OpenWand`. A portable Windows build puts user add-ons next to `OpenWand.exe` when that folder is writable. A per-user installer will also be writable, so installed mode must explicitly place add-ons in `%APPDATA%\OpenWand\addons`.
- The existing portable uninstaller deletes the app folder and user data. An installed copy must invoke its registered Windows uninstaller; full data removal needs a separate, explicit user choice.

## Migration for users on the current ZIP release

1. The first installer-capable release publishes both the transition ZIP and the new EXE. Keep `assets["windows-x64"]` mapped to the transition ZIP so every existing updater can reach it. Add a distinct `assets["windows-x64-installer"]` entry for the EXE. Every later published release manifest must continue to point `windows-x64` to that same immutable transition ZIP URL and SHA-256 while old clients are supported. The manifest generator must reject collisions rather than silently overwrite either artifact.
2. Current portable users apply the bridge ZIP through Settings as they do today. The bridge app then offers **Switch to installed OpenWand** even when its version equals the EXE version; this is a change of install type, not a version update. The action includes a clear explanation of the new install location and the portable copy that will remain as backup.
3. The bridge app copies user add-ons from the portable `addons` folder to `%APPDATA%\OpenWand\addons` without overwriting conflicts. Existing settings, chats, models, and credentials stay in their current user-data locations. The installed app uses the user-data add-on folder, while portable mode retains its present behavior.
4. The bridge app downloads the versioned EXE, checks its manifest SHA-256 and Authenticode signature, then starts a detached helper. After OpenWand exits, the helper runs the installer silently, checks its exit code and registration, and opens the installed executable. On failure, the original portable copy remains usable.
5. Leave the old portable folder in place after migration and mark it as a backup. Its transition-version in-app/batch uninstaller refuses to remove shared user data. The user can manually remove that folder after checking the installed copy. Never remove an arbitrary folder merely because it once contained OpenWand.

The old updater cannot be pinned to a specific release after it has shipped: it always reads the manifest attached to GitHub's current latest published release. Therefore, later manifests must retain the transition ZIP pointer even when their top-level `version` and installer asset advance. For example, a manifest for version `0.13.0` can point `windows-x64` to the version `0.12.0` transition ZIP and `windows-x64-installer` to the version `0.13.0` EXE. An old client sees `0.13.0` is newer and installs the bridge ZIP; the bridge's new logic must then offer installer migration rather than repeatedly applying that ZIP. Keep the transition ZIP asset hosted at its versioned URL.

This gives existing users an in-app path with no manual download: one normal ZIP update, then one explicit switch to the installer. A direct one-click handoff from the old updater is technically possible through its new-version PowerShell helper hook, but it would download both the ZIP and EXE and change install type without the old UI explaining it. The bridge prompt is safer and clearer.

## Installed release behavior

- Use a stable Inno `AppId`, per-user x64 installation, one Programs entry, Start Menu shortcut, and a fixed default location under `%LOCALAPPDATA%\Programs\OpenWand`.
- Sign the bundled PE files first, then sign Inno's generated uninstaller and final setup EXE with the existing Azure Artifact Signing account. Verify every signature before publishing.
- Installed copies select the installer manifest entry. Their updater verifies the download and runs the next installer after OpenWand exits. It must never use the portable folder-replacement helper.
- In-app **Uninstall OpenWand** invokes the registered uninstaller first, then removes the user data and model cache listed in its explicit confirmation. Windows Settings runs only the registered uninstaller and leaves user data in place.
- Upload each versioned installer without `--clobber`. Once its URL is submitted to Microsoft Store, the bytes at that URL must stay unchanged.

## Release gates

- Build and sign the real offline installer on a Windows CI runner.
- Verify silent fresh install, in-place upgrade, Programs entry, launch, Windows uninstall, and no leftover installer registration.
- Verify a current released ZIP can update to the bridge ZIP, switch to the EXE, retain settings and user add-ons, and recover cleanly from an installer failure.
- Test a pre-bridge updater against a simulated later latest manifest: it must still download the transition ZIP, and the bridge must migrate without looping back to that ZIP.
- Fail release publication if the legacy `windows-x64` entry loses its pinned transition URL or SHA-256, or if the transition release asset is unavailable.
- Verify installer updates do not invoke ZIP folder replacement, and portable updates still do.

## Release sequence

1. Run **Build Artifacts** manually on `dev` with `windows_only=true`. Inspect the signed EXE, signed uninstaller, installed launcher smoke result, and Windows uninstall result. This run creates an Actions artifact; it does not publish a GitHub release.
2. Once the full migration is tested from the current `v0.11.1` ZIP, tag the transition code as `v0.12.0`. The workflow uploads both `OpenWand-v0.12.0-windows-x64.zip` and `OpenWand-v0.12.0-windows-x64-setup.exe` to a draft release. Publish only after inspecting the release manifest and installer.
3. After publishing, copy the exact `assets.windows-x64` object from the `v0.12.0` manifest to `packaging/windows/transition-asset.json` on the development branch. Its versioned URL, SHA-256, and size stay fixed for subsequent releases. The build job then omits new Windows ZIPs, and the manifest generator rejects a collision with that pinned transition ZIP.
4. Keep the `v0.12.0` ZIP asset available while old updaters are supported. Verify its release URL still exists before every later release and check a pre-transition client against the latest manifest.
