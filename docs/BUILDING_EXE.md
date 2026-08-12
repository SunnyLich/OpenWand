# Building The Windows EXE

This project includes a PyInstaller build path for the supervisor runtime
(`runtime.supervisor.app`).

From PowerShell in the project root:

```powershell
.\tools\build_exe.ps1 -Clean
```

The script uses a dedicated `.venv-build` environment by default. If
`.venv-build` does not exist, it creates it automatically. The script first
looks for a local Python matching `.python-version`; if none is available, it
installs/uses `uv` to provision that Python for `.venv-build`, seeding `pip` in
the new environment. If an existing `.venv-build` is missing `pip`, the script
bootstraps it with `ensurepip` before installing dependencies. It then checks
dependencies and installs anything that is missing or out of date — no prompts.
Already-satisfied packages are skipped. Builds must use Python `3.12`, matching
`.python-version`; the script stops with a clear message if the selected build
environment or global Python does not match that Python minor line.

Keep the normal `.venv` for development and tests. The separate build
environment keeps local experiments, optional GPU packages, and developer tools
out of portable release bundles unless you intentionally opt into them.

(`-Yes` is still accepted for backward compatibility but no longer does anything,
since auto-install is now the default.)

The built app lands at:

```text
dist\OpenWand\OpenWand.exe
```

Use `-SkipInstall` if dependencies are already installed:

```powershell
.\tools\build_exe.ps1 -Clean -SkipInstall
```

Use `-UseGlobalPython` only if you intentionally want to build outside the
build virtual environment. Use `-UseDevVenv` on Windows, or `--use-dev-venv` on
Linux/macOS, only when you intentionally want PyInstaller to build from the
developer `.venv`.

Notes:

- API keys are not bundled. Users should enter them in Settings so they are saved to the OS keychain.
- `.env.example` is bundled as a template, but your local `.env` is not included.
- The MCP Bridge and UI Lab addons are bundled when present in the checkout and
  seeded into the writable `addons` folder on first launch. Existing addon
  folders are left untouched so user addon configuration, such as MCP Bridge
  `servers.json`, is preserved.
- Portable builds create an `addons` folder next to `OpenWand.exe` when that folder
  is writable. Drop addon folders there, or use **Addon Manager > Install
  archive/folder**. If the executable lives in a read-only install location,
  OpenWand falls back to the user data addon folder shown by **Open addons folder**.
- Windows builds place `Uninstall OpenWand.bat` beside `OpenWand.exe`. Double-click it
  after closing OpenWand to preview the exact OpenWand-owned paths that will be removed,
  confirm permanent removal, and run the same validated uninstaller available in
  **Settings > App > Uninstall OpenWand**.
- The packaged executable starts the same supervisor worker runtime as the
  launchers.
- Packaged no-console runs keep runtime logs under `build_logs/`; the latest
  folder is written to `build_logs/latest_openwand_runtime.txt`. From the tray menu,
  open `Runtime Status` to see worker pids and running/stopped state plus the
  live aggregated event log: worker stderr (tracebacks grouped into one
  expandable "encountered an error" entry), supervisor logs, bubble notices,
  setup-check results, and optional-installer outcomes — all without launching
  from a terminal.
- Runtime package installs in packaged builds require `uv`. This includes addon
  dependency environments and Settings > Voice installs for optional speech
  packages such as STT/faster-whisper, Kokoro, or ElevenLabs. The Windows build script stages
  `uv.exe` into `tools\uv.exe` before PyInstaller runs, installing `uv` into the
  build Python first if needed, and PyInstaller bundles it with OpenWand. If you
  build without the script, place `uv.exe` at `bin\uv.exe` or `tools\uv.exe`
  before running PyInstaller.
- Packaged builds deliberately exclude faster-whisper, CTranslate2, PyAV,
  ONNX Runtime, and the ElevenLabs SDK. Releases therefore stay small; speech
  providers have one authoritative pinned installation under OpenWand's
  user-writable `python_packages` directory, created or repaired by
  Settings > Voice > Install STT; packages present in the build environment do
  not become a second bundled STT backend. The build scripts also filter the
  installer-owned native STT wheels from their temporary build requirements,
  avoiding downloads that PyInstaller would discard.
- `pip` is used in the build environment but is deliberately excluded from
  packaged OpenWand releases. Bundled `uv` is the only package installer used by a
  frozen app; source checkouts retain their normal `pip` fallback.
- If packaging fails on a missing required dependency, rerun without
  `-SkipInstall` so the build script can install it into `.venv-build`.
- ElevenLabs is deliberately installer-owned in packaged releases, like local
  STT. PyInstaller excludes its SDK so a bundled copy cannot enlarge the ZIP or disagree with the
  Settings status checker or the user-writable runtime layer. Settings > Voice
  installs the pinned ElevenLabs SDK and its exact dependency closure, verifies
  the real SDK import, and asks for a repair if any part is stale or broken.
  Source checkouts may instead use the pinned SDK installed in their Python
  environment; status and runtime checks explicitly report which layer won.

The complete source/release transaction and status-state contract is documented
in [SPEECH_INSTALLATION.md](SPEECH_INSTALLATION.md).

## Cross-Platform Portable Builds

Tagged releases are built by `.github/workflows/build.yml`.

Create a `v`-prefixed release tag that matches the current
`pyproject.toml` version:

```powershell
git tag v0.11
git push origin v0.11
```

Tags without the `v` prefix do not trigger release builds.

The workflow builds:

- Windows: `OpenWand-<tag>-windows-x64.zip`
- macOS: `OpenWand-<tag>-macos-<arch>.zip`
- Linux: `OpenWand-<tag>-linux-x64.tar.gz`

After all platform jobs finish, the workflow creates or updates a draft GitHub
Release and uploads `openwand-release-manifest.json` plus `SHA256SUMS.txt`. The
Settings update button uses the manifest to find the newest build for the
current platform, verify the SHA256 hash, download the matching artifact, and
then apply it through a small helper process when the user chooses **Apply
update**. Users can compare downloaded archives against `SHA256SUMS.txt` from
the release page before unpacking them.

Manual platform build entry points:

```powershell
.\tools\build_exe.ps1 -Clean
```

```bash
./tools/build_exe.sh --clean --yes
./tools/build_macos_app.sh --clean --yes
```

On Linux desktops, starting `tools/build_exe.sh` from a file manager
(double-click) opens a terminal window automatically so build progress stays
visible, and the window waits for Enter before closing so the result stays
readable. Terminal launches behave as before.

For the closest local match to GitHub release artifacts, use the same commands
the workflow uses:

```powershell
.\tools\build_exe.ps1 -Clean -Yes
```

```bash
./tools/build_exe.sh --clean --yes
./tools/build_macos_app.sh --clean --yes
```

The release workflow intentionally delegates to these scripts instead of
duplicating dependency installation or PyInstaller commands in YAML. The normal
CI workflow includes `.github/workflows/build.yml`, `.python-version`, and these
build scripts in its path filters, and the test suite asserts that the release
workflow still calls the local scripts. If someone changes the GitHub build path
without updating the shared scripts, CI should fail before a release artifact is
cut.
