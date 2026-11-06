"""Factory reset of OpenWand-owned state, without removing the application."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from core import uninstaller
from core.system import paths


@dataclass(frozen=True)
class ResetPlan:
    targets: tuple[Path, ...]
    protected: frozenset[Path] = frozenset()


# These are writable application state, not provider installations or workspaces.
_STATE_NAMES = (
    ".env", "settings_profiles", "chats", "memory", "callers", "addons.json",
    "addon_data", "addon_envs", "addons", "model_tools", "model_files",
    "tools/installed", "private", "core/private", "outputs", "logs", "build_logs",
)


def _tracked_source_files() -> frozenset[Path]:
    checkout = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "-C", str(checkout), "ls-files", "-z"],
        check=True, capture_output=True, timeout=15,
    )
    return frozenset(checkout / os.fsdecode(name) for name in result.stdout.split(b"\0") if name)


def build_reset_plan(*, settings_path: Path | None = None) -> ResetPlan:
    """Enumerate owned state; protect source files even inside writable folders."""
    from core import optional_deps, secret_store

    root = paths.REPO_ROOT.absolute()
    data = paths.USER_DATA_DIR.absolute()
    home = Path.home().absolute()
    uninstaller._assert_safe_root(root, label="OpenWand state root", home=home)
    uninstaller._assert_safe_root(data, label="OpenWand user-data root", home=home)
    if data.name.casefold() != "openwand":
        raise uninstaller.UninstallError(f"Unexpected OpenWand user-data directory: {data}")
    frozen = bool(getattr(sys, "frozen", False))
    protected: frozenset[Path] = frozenset()
    if not frozen:
        # A reset in a development checkout must preserve tracked source and edits.
        protected = _tracked_source_files()
    settings = Path(settings_path or os.environ.get("OPENWAND_SETTINGS_ENV_PATH") or root / ".env").absolute()
    targets = [root / name for name in _STATE_NAMES]
    targets.extend([
        data, data.with_name("wisp" if sys.platform.startswith("linux") else "Wisp"),
        settings, settings.parent / "settings_profiles", settings.parent / "callers",
        paths.ADDONS_DIR.absolute(), optional_deps.OPTIONAL_PACKAGES_DIR.absolute(),
        secret_store._META_FILE.absolute(),
        Path(__file__).parent / "private" / ".chatgpt_tokens.json",
        Path(__file__).parent / "private" / ".github_tokens.json",
        optional_deps.OPTIONAL_PACKAGES_DIR.absolute().parent / "tts_assets.json",
    ])
    if addon_store := os.environ.get("OPENWAND_ADDON_STORE"):
        targets.append(Path(addon_store).expanduser().absolute())
    app_root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    if frozen:
        targets.append(app_root.with_name(f"{app_root.name}.previous-update"))
    for target in targets:
        uninstaller._assert_safe_root(target, label="OpenWand reset target", home=home)
        if target == app_root or app_root.is_relative_to(target):
            raise uninstaller.UninstallError(f"Reset target overlaps application source: {target}")
    return ResetPlan(uninstaller._collapse_targets(targets, platform=sys.platform), protected)


def _remove_target(target: Path, protected: frozenset[Path]) -> None:
    """Never follow directory links or erase a protected source/lock file."""
    if target in protected:
        return
    if target.is_symlink():
        target.unlink()
    elif target.is_junction():
        target.rmdir()
    elif target.is_dir():
        if any(path.is_relative_to(target) for path in protected):
            for child in target.iterdir():
                _remove_target(child, protected)
        else:
            shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)


def execute_reset(plan: ResetPlan) -> None:
    """Called only with exclusive access after all application workers exit."""
    from core.system.autostart import sync_start_on_login

    failures = uninstaller.remove_openwand_keychain_entries()
    if failures:
        raise uninstaller.UninstallError("Could not clear OpenWand sign-ins: " + "; ".join(failures))
    try:
        sync_start_on_login(False)
    except Exception as exc:  # noqa: BLE001 - include OS integration failures in the result
        failures.append(f"Start on login: {exc}")
    protected = plan.protected
    if sys.platform != "win32":
        # Keep the locked inode until this process exits, preventing a second app
        # from locking a newly created file while cleanup is still in progress.
        protected |= frozenset({paths.SINGLE_INSTANCE_LOCK.absolute()})
    for target in plan.targets:
        for attempt in range(3):
            try:
                _remove_target(target, protected)
                break
            except OSError as exc:
                if attempt == 2:
                    failures.append(f"{target}: {exc}")
                else:
                    time.sleep(0.25)
    if failures:
        raise uninstaller.UninstallError("Factory reset partly complete: " + "; ".join(failures))


def launch_reset(*, settings_path: Path) -> Path:
    """Launch a worker which waits for shutdown before clearing saved state."""
    from core import updater

    build_reset_plan(settings_path=settings_path)  # Fail before asking the app to exit.
    helper_root = Path(tempfile.gettempdir()) / f"openwand-reset-{uuid.uuid4().hex}"
    helper_root.mkdir()
    log_path = helper_root / "reset-failures.log"
    ready_path = helper_root / "ready"
    command = [
        sys.executable, "-m", "runtime.workers.factory_reset",
        "--wait-pid", str(updater.openwand_wait_pid()),
        "--settings-path", str(settings_path.absolute()), "--log-path", str(log_path),
        "--ready-path", str(ready_path),
    ]
    try:
        # Source module imports need the checkout; packaged dispatch uses its exe.
        cwd = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        for key in ("OPENWAND_SUPERVISOR_PID", "OPENWAND_SUPERVISOR_CREATE_TIME"):
            env.pop(key, None)
        updater.launch_detached_helper(command, cwd=cwd, env=env)
        deadline = time.monotonic() + 10
        while not ready_path.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("The factory reset worker did not start. OpenWand has been kept open.")
            time.sleep(0.05)
        # The worker must not erase anything if scheduling timed out in the UI.
        ready_path.with_name("proceed").write_text("confirmed", encoding="utf-8")
    except Exception:
        try:
            helper_root.rmdir()
        except OSError:
            pass  # Preserve a worker's failure report if it already wrote one.
        raise
    return log_path
