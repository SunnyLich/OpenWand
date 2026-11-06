"""Safety and platform coverage for OpenWand's self-uninstaller."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import uninstaller


def _source_checkout(root: Path) -> Path:
    (root / "runtime" / "supervisor").mkdir(parents=True)
    (root / "core" / "system").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='openwand'\n", encoding="utf-8")
    (root / "runtime" / "supervisor" / "app.py").write_text("", encoding="utf-8")
    (root / "core" / "system" / "paths.py").write_text("", encoding="utf-8")
    return root


def test_linux_source_plan_removes_only_exact_openwand_owned_paths(tmp_path):
    """Source uninstall includes its checkout/data/models/integrations, not shared caches."""
    home = tmp_path / "home"
    source = _source_checkout(tmp_path / "src" / "OpenWand")
    data_root = home / ".config" / "openwand"
    optional_root = data_root / "python_packages"
    optional_root.mkdir(parents=True)
    hub = home / ".cache" / "huggingface" / "hub"
    owned_model = hub / "models--Systran--faster-whisper-base"
    owned_lock = hub / ".locks" / owned_model.name
    unrelated_model = hub / "models--Qwen--Qwen3.5-9B"
    for path in (owned_model, owned_lock, unrelated_model):
        path.mkdir(parents=True)

    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True,
        platform="linux",
        frozen=False,
        source_root=source,
        user_data_root=data_root,
        optional_packages_root=optional_root,
        home=home,
        environ={},
    )

    targets = set(plan.targets)
    assert plan.source_checkout is True
    assert source in targets
    assert data_root in targets
    assert home / ".config" / "wisp" in targets
    assert owned_model not in targets  # Shared cache ownership cannot be inferred from a repo name.
    assert owned_lock not in targets
    assert home / ".config" / "autostart" / "openwand.desktop" in targets
    assert home / ".config" / "autostart" / "wisp.desktop" in targets
    assert home / ".local" / "share" / "applications" / "openwand.desktop" in targets
    assert unrelated_model not in targets
    assert home / ".cache" / "huggingface" / "hub" not in targets
    assert home / ".cache" / "uv" not in targets


def test_packaged_macos_plan_targets_app_bundle_and_launch_agent(tmp_path):
    """macOS release uninstall removes the current app bundle, not /Applications."""
    home = tmp_path / "Users" / "person"
    app_root = tmp_path / "Applications" / "OpenWand.app"
    executable = app_root / "Contents" / "MacOS" / "OpenWand"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    data_root = home / "Library" / "Application Support" / "OpenWand"
    optional_root = data_root / "python_packages"

    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True,
        platform="darwin",
        frozen=True,
        executable=executable,
        user_data_root=data_root,
        optional_packages_root=optional_root,
        home=home,
        environ={},
    )

    targets = set(plan.targets)
    assert plan.source_checkout is False
    assert plan.app_root == app_root
    assert app_root in targets
    assert app_root.with_name("OpenWand.app.previous-update") in targets
    assert data_root in targets
    assert home / "Library" / "Application Support" / "Wisp" in targets
    assert home / "Library" / "LaunchAgents" / "com.openwand.launcher.plist" in targets
    assert home / "Library" / "LaunchAgents" / "com.wisp.launcher.plist" in targets
    assert tmp_path / "Applications" not in targets


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_packaged_onedir_plan_targets_only_current_release_root(tmp_path, platform):
    """Windows and Linux portable releases remove their current onedir folder."""
    home = tmp_path / "home"
    app_root = tmp_path / "portable" / "OpenWand"
    executable = app_root / ("OpenWand.exe" if platform == "win32" else "OpenWand")
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    data_root = (home / "AppData" / "Roaming" / "OpenWand") if platform == "win32" else (home / ".config" / "openwand")

    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True,
        platform=platform,
        frozen=True,
        executable=executable,
        user_data_root=data_root,
        optional_packages_root=data_root / "python_packages",
        home=home,
        environ={},
    )

    assert plan.app_root == app_root
    assert app_root in plan.targets
    assert app_root.with_name("OpenWand.previous-update") in plan.targets
    assert app_root.parent not in plan.targets
    if platform == "linux":
        assert home / ".local" / "share" / "applications" / "openwand.desktop" in plan.targets


def test_windows_script_uses_only_literal_manifest_targets(tmp_path):
    """Windows helper has no discovery wildcard and removes only the validated list."""
    app_root = tmp_path / "OpenWand's release"
    data_root = tmp_path / "OpenWand"
    plan = uninstaller.UninstallPlan(
        platform="win32",
        source_checkout=False,
        app_root=app_root,
        user_data_root=data_root,
        targets=(app_root, data_root),
    )

    script = uninstaller.render_windows_uninstall_script(
        plan,
        wait_pid=4242,
        log_path=tmp_path / "uninstall.log",
    )

    assert "$waitPid = 4242" in script
    assert "OpenWand''s release" in script
    assert "Remove-Item -LiteralPath $target" in script
    assert "Remove-ItemProperty -LiteralPath" in script
    assert "Get-ChildItem" not in script
    assert "-Filter" not in script


def test_installed_windows_uninstall_runs_registered_uninstaller_first(monkeypatch, tmp_path):
    home = tmp_path / "home"
    app_root = tmp_path / "installed" / "OpenWand"
    app_root.mkdir(parents=True)
    exe = app_root / "OpenWand.exe"
    exe.write_bytes(b"app")
    (app_root / uninstaller.INSTALLED_MARKER_NAME).write_text("installer", encoding="utf-8")
    registered = app_root / "unins000.exe"
    registered.write_bytes(b"uninstaller")
    monkeypatch.setattr(uninstaller, "_registered_windows_uninstaller", lambda _root: registered)
    data_root = home / "AppData" / "Roaming" / "OpenWand"
    plan = uninstaller.build_uninstall_plan(
        platform="win32", frozen=True, executable=exe, home=home,
        user_data_root=data_root, optional_packages_root=data_root / "python_packages", environ={},
    )
    assert plan.registered_uninstaller == registered
    script = uninstaller.render_windows_uninstall_script(plan, wait_pid=123, log_path=tmp_path / "log.txt")
    assert str(registered) in script
    assert script.index("Start-Process -FilePath $registeredUninstaller") < script.index("foreach ($target in $targets)")
    assert "user data was kept" in script


def test_migrated_portable_backup_cannot_remove_shared_user_data(tmp_path):
    home = tmp_path / "home"
    app_root = tmp_path / "portable" / "OpenWand"
    app_root.mkdir(parents=True)
    exe = app_root / "OpenWand.exe"
    exe.write_bytes(b"app")
    (app_root / uninstaller.MIGRATED_PORTABLE_MARKER_NAME).write_text("installed", encoding="utf-8")
    data_root = home / "AppData" / "Roaming" / "OpenWand"
    with pytest.raises(uninstaller.UninstallError, match="portable backup was migrated"):
        uninstaller.build_uninstall_plan(
            platform="win32", frozen=True, executable=exe, home=home,
            user_data_root=data_root, optional_packages_root=data_root / "python_packages", environ={},
        )


def test_posix_script_uses_literal_targets_and_self_cleans(tmp_path):
    """POSIX helper quotes paths, waits for OpenWand, and removes its temp directory."""
    target = tmp_path / "OpenWand release"
    plan = uninstaller.UninstallPlan(
        platform="linux",
        source_checkout=False,
        app_root=target,
        user_data_root=tmp_path / "openwand",
        targets=(target,),
    )

    script = uninstaller.render_posix_uninstall_script(
        plan,
        wait_pid=99,
        log_path=tmp_path / "uninstall.log",
    )

    assert "kill -0 \"$wait_pid\"" in script
    assert f"'{target}'" in script
    assert "rm -rf -- \"$target\"" in script
    assert "rmdir -- \"$helper_dir\"" in script
    assert "find " not in script


def test_source_plan_refuses_unrecognized_or_overbroad_roots(tmp_path):
    """A source directory must carry OpenWand identity markers and cannot be the home directory."""
    home = tmp_path / "home"
    data_root = home / ".config" / "openwand"

    with pytest.raises(uninstaller.UninstallError, match="unrecognized source"):
        uninstaller.build_uninstall_plan(
            platform="linux",
            frozen=False,
            source_root=tmp_path / "not-openwand",
            user_data_root=data_root,
            optional_packages_root=data_root / "python_packages",
            home=home,
            environ={},
        )

    source = _source_checkout(home)
    with pytest.raises(uninstaller.UninstallError, match="home directory"):
        uninstaller.build_uninstall_plan(
            platform="linux",
            frozen=False,
            source_root=source,
            user_data_root=data_root,
            optional_packages_root=data_root / "python_packages",
            home=home,
            environ={},
        )


def test_keychain_cleanup_removes_consolidated_oauth_and_legacy_accounts(monkeypatch):
    """Complete uninstall attempts every keychain account created by OpenWand."""
    from core import secret_store

    deleted: list[tuple[str, str]] = []

    class PasswordDeleteError(Exception):
        pass

    fake_keyring = SimpleNamespace(
        errors=SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
        get_password=lambda service, account: None if (service, account) in deleted else "stored",
        delete_password=lambda service, account: deleted.append((service, account)),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    assert uninstaller.remove_openwand_keychain_entries() == []

    accounts = {account for _service, account in deleted}
    assert {
        "__openwand_secrets__",
        "__wisp_secrets__",
        "chatgpt-oauth",
        "github-oauth",
        "github-copilot-token",
    } <= accounts
    assert {"chatgpt-oauth-chunk-0", "chatgpt-oauth-chunk-31"} <= accounts
    assert {name.lower() for name in secret_store.API_KEY_NAMES} <= accounts


def test_standalone_worker_refuses_while_another_openwand_process_is_running(monkeypatch):
    """The batch launcher cannot race a still-running OpenWand process during removal."""
    from PySide6.QtWidgets import QMessageBox

    from core.system import single_instance
    from runtime.workers import uninstall_openwand
    from ui import uninstall_dialog

    warnings: list[tuple] = []
    dialog_calls: list[object] = []
    monkeypatch.setattr(single_instance, "acquire", lambda: False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(uninstall_dialog, "run_uninstall_dialog", dialog_calls.append)

    assert uninstall_openwand._run_uninstaller_dialog() == 1
    assert len(warnings) == 1
    assert "Close OpenWand" in warnings[0][2]
    assert dialog_calls == []


def test_standalone_worker_uses_shared_confirmed_uninstall_flow(monkeypatch):
    """The batch entrypoint delegates to the exact UI flow used by Settings."""
    from core.system import single_instance
    from runtime.workers import uninstall_openwand
    from ui import uninstall_dialog

    dialog_calls: list[object] = []
    monkeypatch.setattr(single_instance, "acquire", lambda: True)
    monkeypatch.setattr(uninstall_dialog, "run_uninstall_dialog", dialog_calls.append)

    assert uninstall_openwand._run_uninstaller_dialog() == 0
    assert dialog_calls == [None]


def test_uninstall_confirmation_is_yes_no_without_typed_phrase(monkeypatch, tmp_path):
    """One native Yes/No decision follows the deletion preview; no text challenge remains."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ui import uninstall_dialog

    app = QApplication.instance() or QApplication([])
    plan = uninstaller.UninstallPlan(
        platform="win32",
        source_checkout=False,
        app_root=tmp_path / "OpenWand",
        user_data_root=tmp_path / "data" / "OpenWand",
        targets=(tmp_path / "OpenWand", tmp_path / "data" / "OpenWand"),
    )
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    launches: list[uninstaller.UninstallPlan] = []
    monkeypatch.setattr(uninstall_dialog.uninstaller, "build_uninstall_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(
        uninstall_dialog.uninstaller, "launch_uninstaller",
        lambda plan: launches.append(plan) or uninstaller.UninstallLaunch(tmp_path / "helper", tmp_path / "failures.log"),
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: next(answers))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)

    assert uninstall_dialog.run_uninstall_dialog() is False
    assert launches == []
    assert uninstall_dialog.run_uninstall_dialog() is True
    assert launches == [plan]
    app.processEvents()


def test_uninstall_runtime_failure_matrix_is_controlled_and_leak_free(monkeypatch, tmp_path):
    """Every pre-launch uninstall failure keeps OpenWand alive and removes its helper."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from core import updater
    from ui import uninstall_dialog

    app = QApplication.instance() or QApplication([])
    helper_parent = tmp_path / "helpers"
    helper_parent.mkdir()
    plans = (
        uninstaller.UninstallPlan(
            platform="win32",
            source_checkout=False,
            app_root=tmp_path / "missing-release" / "OpenWand",
            user_data_root=tmp_path / "missing-release-data" / "OpenWand",
            targets=(tmp_path / "missing-release" / "OpenWand",),
        ),
        uninstaller.UninstallPlan(
            platform="linux",
            source_checkout=True,
            app_root=tmp_path / "missing-source" / "OpenWand",
            user_data_root=tmp_path / "missing-source-data" / "openwand",
            targets=(tmp_path / "missing-source" / "OpenWand",),
        ),
    )
    failures = (
        PermissionError("target is locked"),
        PermissionError("required elevation is denied"),
        PermissionError("storage access is denied"),
        OSError("another process is using the files"),
        OSError("cleanup only partly completes"),
    )
    warnings: list[str] = []
    monkeypatch.setattr(uninstaller.tempfile, "gettempdir", lambda: str(helper_parent))
    monkeypatch.setattr(uninstaller, "remove_openwand_keychain_entries", lambda: [])
    monkeypatch.setattr(updater, "openwand_wait_pid", lambda _pid=None: 123)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, message: warnings.append(message))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QTimer, "singleShot", lambda *_args: None)

    for plan in plans:
        monkeypatch.setattr(uninstall_dialog.uninstaller, "build_uninstall_plan", lambda p=plan, **_kwargs: p)
        for failure in failures:
            monkeypatch.setattr(
                updater,
                "launch_detached_helper",
                lambda *_args, error=failure, **_kwargs: (_ for _ in ()).throw(error),
            )
            before = set(helper_parent.iterdir())
            assert uninstall_dialog.run_uninstall_dialog() is False
            assert set(helper_parent.iterdir()) == before
            assert str(failure) in warnings[-1]

    # Cancelling at the confirmation boundary must never create a helper.
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.StandardButton.No)
    before = set(helper_parent.iterdir())
    assert uninstall_dialog.run_uninstall_dialog() is False
    assert set(helper_parent.iterdir()) == before
    app.processEvents()


def test_uninstall_renderers_retry_missing_locked_and_partial_targets(tmp_path):
    """Both detached removers encode missing-target, retry, logging, and self-cleanup."""
    targets = (tmp_path / "missing", tmp_path / "locked", tmp_path / "partial")
    for platform in ("win32", "linux"):
        plan = uninstaller.UninstallPlan(
            platform=platform,
            source_checkout=platform != "win32",
            app_root=targets[0],
            user_data_root=tmp_path / "data" / "openwand",
            targets=targets,
        )
        log = tmp_path / f"{platform}-failures.log"
        if platform == "win32":
            script = uninstaller.render_windows_uninstall_script(plan, wait_pid=123, log_path=log)
            assert "for ($attempt = 0; $attempt -lt 30; $attempt++)" in script
            assert "Test-Path -LiteralPath" in script
            assert "Could not remove:" in script
            assert "Remove-Item -LiteralPath $PSCommandPath" in script
        else:
            script = uninstaller.render_posix_uninstall_script(plan, wait_pid=123, log_path=log)
            assert "[ -e \"$target\" ] || [ -L \"$target\" ]" in script
            assert "if ! rm -rf -- \"$target\"" in script
            assert "Could not remove:" in script
            assert "rm -f -- \"$0\"" in script
        for target in targets:
            assert str(target) in script


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_default_uninstall_preserves_saved_data_models_and_credentials(monkeypatch, tmp_path, platform):
    from core import updater

    home = tmp_path / "home"
    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = home / "data" / "OpenWand"
    optional = data / "python_packages"
    model = home / ".cache" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"
    model.mkdir(parents=True)
    plan = uninstaller.build_uninstall_plan(
        platform=platform, frozen=False, source_root=source, user_data_root=data,
        optional_packages_root=optional, home=home, environ={},
    )
    assert plan.remove_user_data is False
    assert source in plan.targets
    for kept in (data, optional, model, data.with_name("Wisp" if platform != "linux" else "wisp")):
        assert not any(kept == target or kept.is_relative_to(target) for target in plan.targets)
    monkeypatch.setattr(
        uninstaller, "remove_openwand_keychain_entries",
        lambda: pytest.fail("Keeping settings must not delete saved credentials"),
    )
    monkeypatch.setattr(uninstaller.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "launch_detached_helper", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(updater, "openwand_wait_pid", lambda _pid=None: 123)
    launch = uninstaller.launch_uninstaller(plan)
    script = launch.script_path.read_text(encoding="utf-8")
    assert str(data) not in script
    assert str(model) not in script


@pytest.mark.parametrize("remove_data", [False, True])
def test_uninstall_checkbox_controls_preview_plan_and_keychain_cleanup(monkeypatch, tmp_path, remove_data):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from core import updater
    from ui import uninstall_dialog

    app = QApplication.instance() or QApplication([])
    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = tmp_path / "home" / "data" / "OpenWand"
    build_plan = uninstaller.build_uninstall_plan
    monkeypatch.setattr(
        uninstaller, "build_uninstall_plan",
        lambda **kwargs: build_plan(
            platform="win32", frozen=False, source_root=source, user_data_root=data,
            optional_packages_root=data / "python_packages", home=tmp_path / "home", environ={}, **kwargs,
        ),
    )
    credential_calls = []
    monkeypatch.setattr(uninstaller, "remove_openwand_keychain_entries", lambda: credential_calls.append(True) or [])
    monkeypatch.setattr(uninstaller.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "launch_detached_helper", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(updater, "openwand_wait_pid", lambda _pid=None: 123)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QTimer, "singleShot", lambda *_args: None)

    def confirm(box):
        assert not box.checkBox().isChecked()
        assert "Keep saved settings" in box.informativeText()
        box.checkBox().setChecked(remove_data)
        assert (str(data) in box.informativeText().split("Exact paths scheduled for deletion:")[1]) == remove_data
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", confirm)
    assert uninstall_dialog.run_uninstall_dialog() is True
    assert credential_calls == []  # Cleanup is deferred until every worker exits.
    app.processEvents()


def test_native_data_cleanup_removes_only_data_and_keeps_app(monkeypatch, tmp_path):
    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = tmp_path / "home" / "data" / "OpenWand"
    data.mkdir(parents=True)
    (data / "settings.json").write_text("{}", encoding="utf-8")
    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True, platform="win32", frozen=False, source_root=source,
        user_data_root=data, optional_packages_root=data / "python_packages", home=tmp_path / "home", environ={},
    )
    calls = []
    monkeypatch.setattr(uninstaller, "remove_openwand_keychain_entries", lambda: calls.append(True) or [])
    uninstaller.remove_user_data_files(plan)
    assert calls == [True]
    assert not data.exists()
    assert (source / "pyproject.toml").exists()


def test_native_cleanup_worker_requires_installed_copy_and_exclusive_access(monkeypatch):
    from core.system import paths, single_instance
    from runtime.workers import uninstall_openwand

    monkeypatch.setattr(paths, "is_installed_release", lambda: False)
    monkeypatch.setattr(single_instance, "acquire", lambda **_kwargs: pytest.fail("Not an installed copy"))
    assert uninstall_openwand._remove_installed_user_data() == 1
    monkeypatch.setattr(paths, "is_installed_release", lambda: True)
    monkeypatch.setattr(single_instance, "acquire", lambda **kwargs: False if kwargs == {"lock_file": False} else True)
    assert uninstall_openwand._remove_installed_user_data() == 2


def test_native_cleanup_worker_runs_without_gui_or_recursive_uninstall(monkeypatch, tmp_path):
    from core.system import paths, single_instance
    from runtime.workers import uninstall_openwand

    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = tmp_path / "home" / "data" / "OpenWand"
    data.mkdir(parents=True)
    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True, platform="win32", frozen=False, source_root=source,
        user_data_root=data, optional_packages_root=data / "python_packages", home=tmp_path / "home", environ={},
    )
    monkeypatch.setattr(paths, "is_installed_release", lambda: True)
    monkeypatch.setattr(single_instance, "acquire", lambda **kwargs: kwargs == {"lock_file": False})
    monkeypatch.setattr(uninstaller, "build_uninstall_plan", lambda **kwargs: plan if kwargs["remove_user_data"] else None)
    monkeypatch.setattr(uninstaller, "remove_openwand_keychain_entries", lambda: [])
    monkeypatch.setattr(uninstaller, "launch_uninstaller", lambda *_args: pytest.fail("Must not recurse into Inno"))
    monkeypatch.setattr(sys, "argv", ["uninstall_openwand", "--remove-user-data"])
    assert uninstall_openwand.main() == 0
    assert not data.exists()
    assert source.is_dir()


def test_native_cleanup_keeps_files_when_credential_cleanup_fails(monkeypatch, tmp_path):
    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = tmp_path / "home" / "data" / "OpenWand"
    data.mkdir(parents=True)
    plan = uninstaller.build_uninstall_plan(
        remove_user_data=True, platform="win32", frozen=False, source_root=source,
        user_data_root=data, optional_packages_root=data / "python_packages", home=tmp_path / "home", environ={},
    )
    monkeypatch.setattr(uninstaller, "remove_openwand_keychain_entries", lambda: ["keychain locked"])
    with pytest.raises(uninstaller.UninstallError, match="keychain locked"):
        uninstaller.remove_user_data_files(plan)
    assert data.is_dir()
    assert source.is_dir()


def test_keep_data_refuses_app_folder_containing_settings(tmp_path):
    source = _source_checkout(tmp_path / "checkout" / "OpenWand")
    data = source / "saved" / "OpenWand"
    with pytest.raises(uninstaller.UninstallError, match="Cannot keep settings"):
        uninstaller.build_uninstall_plan(
            platform="win32", frozen=False, source_root=source, user_data_root=data,
            optional_packages_root=data / "python_packages", home=tmp_path / "home", environ={},
        )


def test_factory_reset_removes_owned_state_and_preserves_external_providers(monkeypatch, tmp_path):
    from core import factory_reset, optional_deps, secret_store
    from core.system import autostart, paths

    source = tmp_path / 'checkout'
    data = tmp_path / 'data' / 'OpenWand'
    legacy = data.with_name('Wisp' if sys.platform != 'linux' else 'wisp')
    monkeypatch.setattr(paths, 'REPO_ROOT', source)
    monkeypatch.setattr(paths, 'USER_DATA_DIR', data)
    monkeypatch.setattr(paths, 'ADDONS_DIR', source / 'addons')
    monkeypatch.setattr(paths, 'SINGLE_INSTANCE_LOCK', data / 'openwand.lock')
    monkeypatch.setattr(optional_deps, 'OPTIONAL_PACKAGES_DIR', data / 'python_packages')
    monkeypatch.setattr(secret_store, '_META_FILE', source / 'private' / '.secret_status.json')
    # Legacy tokens must also be isolated from the real checkout in this test.
    monkeypatch.setattr(factory_reset, '__file__', str(source / 'core' / 'factory_reset.py'))
    tracked = source / 'addons' / 'bundled' / '__init__.py'
    monkeypatch.setattr(factory_reset, '_tracked_source_files', lambda: frozenset({tracked}))
    owned = [
        source / '.env', source / 'settings_profiles' / 'personal.env',
        source / 'chats' / 'chat.json', source / 'memory' / 'memory.db',
        source / 'addons' / 'downloaded' / 'addon.toml', source / 'callers' / 'custom.toml',
        source / 'addon_data' / 'tokens.json', source / 'tools' / 'installed' / 'tool.exe',
        source / 'core' / 'private' / '.chatgpt_tokens.json',
        data / 'models' / 'privacy' / 'model.bin', data / 'python_packages' / 'package.py',
        data / 'logs' / 'app.log', legacy / '.env',
    ]
    external = [
        tmp_path / 'ollama' / 'models' / 'model.bin',
        tmp_path / '.codex' / 'auth.json', tmp_path / 'browser' / 'cookies',
        tmp_path / '.cache' / 'huggingface' / 'hub' / 'models--Systran--faster-whisper-base' / 'model.bin',
        source / 'core' / 'app.py', tracked,
    ]
    for file in owned + external:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('keep-or-remove', encoding='utf-8')
    removed = []
    monkeypatch.setattr(autostart, 'sync_start_on_login', lambda enabled: removed.append(('autostart', enabled)))
    monkeypatch.setattr(uninstaller, 'remove_openwand_keychain_entries', lambda: removed.append(True) or [])
    plan = factory_reset.build_reset_plan(settings_path=source / '.env')
    factory_reset.execute_reset(plan)
    assert removed == [True, ('autostart', False)]
    assert all(not file.exists() for file in owned)
    assert all(file.read_text(encoding='utf-8') == 'keep-or-remove' for file in external)
    # Installed releases put state and stable user data in the same directory.
    with monkeypatch.context() as scoped:
        executable = tmp_path / 'installed' / 'OpenWand' / 'OpenWand.exe'
        scoped.setattr(sys, 'frozen', True, raising=False)
        scoped.setattr(sys, 'executable', str(executable))
        scoped.setattr(paths, 'REPO_ROOT', data)
        packaged = factory_reset.build_reset_plan(settings_path=data / '.env')
        assert data in packaged.targets
        assert executable.parent not in packaged.targets
        assert executable.parent.with_name('OpenWand.previous-update') in packaged.targets


def test_factory_reset_keeps_data_when_keychain_cannot_be_verified(monkeypatch, tmp_path):
    from core import factory_reset

    target = tmp_path / 'chats.json'
    target.write_text('personal-data', encoding='utf-8')
    monkeypatch.setattr(uninstaller, 'remove_openwand_keychain_entries', lambda: ['OAuth keychain locked'])
    with pytest.raises(uninstaller.UninstallError, match='OAuth keychain locked'):
        factory_reset.execute_reset(factory_reset.ResetPlan((target,)))
    assert target.read_text(encoding='utf-8') == 'personal-data'


@pytest.mark.parametrize('delete_error', [False, True])
def test_credential_cleanup_detects_silent_delete_failure(monkeypatch, delete_error):
    class PasswordDeleteError(Exception):
        pass

    def delete(*_args):
        if delete_error:
            raise PasswordDeleteError('not removed')
    fake = SimpleNamespace(
        errors=SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
        get_password=lambda _service, account: 'token' if account == 'chatgpt-oauth' else None,
        delete_password=delete,
    )
    monkeypatch.setitem(sys.modules, 'keyring', fake)
    failures = uninstaller.remove_openwand_keychain_entries()
    assert failures == ['chatgpt-oauth: credential still exists after deletion']


def test_factory_reset_worker_waits_for_shutdown_and_requires_exclusive_access(monkeypatch, tmp_path):
    from core import factory_reset, updater
    from core.system import single_instance
    from runtime.workers import factory_reset as worker

    events = []
    states = iter([True, True, False])
    monkeypatch.setattr(updater, '_process_exists', lambda _pid: next(states))
    monkeypatch.setattr(worker.time, 'sleep', lambda _delay: events.append('waiting'))
    monkeypatch.setattr(single_instance, 'acquire', lambda **kwargs: events.append(('lock', kwargs)) or True)
    plan = factory_reset.ResetPlan((tmp_path / '.env',))
    monkeypatch.setattr(factory_reset, 'build_reset_plan', lambda **_kw: plan)
    monkeypatch.setattr(factory_reset, 'execute_reset', lambda p: events.append(('reset', p)))
    log = tmp_path / 'helper' / 'failures.log'
    log.parent.mkdir()
    assert worker.run(wait_pid=123, settings_path=tmp_path / '.env', log_path=log) == 0
    assert events == ['waiting', 'waiting', ('lock', {'lock_file': False}), ('reset', plan)]
    assert not log.parent.exists()

    monkeypatch.setattr(updater, '_process_exists', lambda _pid: False)
    monkeypatch.setattr(single_instance, 'acquire', lambda **_kw: False)
    monkeypatch.setattr(factory_reset, 'execute_reset', lambda _p: pytest.fail('Lock was not acquired'))
    shown = []
    monkeypatch.setattr(worker, '_show_failure', lambda *args: shown.append(args))
    log.parent.mkdir()
    assert worker.run(wait_pid=123, settings_path=tmp_path / '.env', log_path=log) == 1
    assert 'Another OpenWand process' in log.read_text(encoding='utf-8')
    assert shown


def test_factory_reset_launch_failure_keeps_data_and_removes_helper(monkeypatch, tmp_path):
    from core import factory_reset, updater

    target = tmp_path / '.env'
    target.write_text('saved', encoding='utf-8')
    monkeypatch.setattr(factory_reset, 'build_reset_plan', lambda **_kw: factory_reset.ResetPlan((target,)))
    monkeypatch.setattr(factory_reset.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setenv('OPENWAND_SUPERVISOR_PID', '123')
    launches = []
    def start(command, **kwargs):
        launches.append((command, kwargs))
        Path(command[command.index('--ready-path') + 1]).write_text('ready', encoding='utf-8')
    monkeypatch.setattr(updater, 'launch_detached_helper', start)
    log = factory_reset.launch_reset(settings_path=target)
    assert (log.parent / 'proceed').exists()
    assert 'OPENWAND_SUPERVISOR_PID' not in launches[0][1]['env']
    assert target.read_text(encoding='utf-8') == 'saved'
    (log.parent / 'ready').unlink()
    (log.parent / 'proceed').unlink()
    log.parent.rmdir()
    monkeypatch.setattr(updater, 'launch_detached_helper', lambda *_a, **_kw: (_ for _ in ()).throw(OSError('launch failed')))
    with pytest.raises(OSError, match='launch failed'):
        factory_reset.launch_reset(settings_path=target)
    assert target.read_text(encoding='utf-8') == 'saved'
    assert not list(tmp_path.glob('openwand-reset-*'))
    monkeypatch.setattr(updater, 'launch_detached_helper', lambda *_a, **_kw: None)
    clock = iter([0, 11])
    monkeypatch.setattr(factory_reset.time, 'monotonic', lambda: next(clock))
    with pytest.raises(RuntimeError, match='worker did not start'):
        factory_reset.launch_reset(settings_path=target)
    assert target.read_text(encoding='utf-8') == 'saved'


def test_factory_reset_does_not_follow_directory_links(monkeypatch, tmp_path):
    import subprocess

    from core import factory_reset
    from core.system import autostart

    external = tmp_path / 'external-provider'
    external.mkdir()
    model = external / 'model.bin'
    model.write_text('external', encoding='utf-8')
    link = tmp_path / 'OpenWand-addon-data'
    if sys.platform == 'win32':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(external)], check=True, capture_output=True)
    else:
        link.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(uninstaller, 'remove_openwand_keychain_entries', lambda: [])
    monkeypatch.setattr(autostart, 'sync_start_on_login', lambda _enabled: None)
    factory_reset.execute_reset(factory_reset.ResetPlan((link,)))
    assert not link.exists()
    assert model.read_text(encoding='utf-8') == 'external'


def test_factory_reset_reports_partial_cleanup_without_hiding_failures(monkeypatch, tmp_path):
    from core import factory_reset, updater
    from core.system import autostart, single_instance
    from runtime.workers import factory_reset as worker

    locked = tmp_path / 'locked-chats.json'
    other = tmp_path / 'settings.env'
    for path in (locked, other):
        path.write_text('saved', encoding='utf-8')
    monkeypatch.setattr(uninstaller, 'remove_openwand_keychain_entries', lambda: [])
    monkeypatch.setattr(autostart, 'sync_start_on_login', lambda _enabled: None)
    monkeypatch.setattr(updater, '_process_exists', lambda _pid: False)
    monkeypatch.setattr(single_instance, 'acquire', lambda **_kw: True)
    monkeypatch.setattr(factory_reset, 'build_reset_plan', lambda **_kw: factory_reset.ResetPlan((locked, other)))
    remove = factory_reset._remove_target
    attempts = []
    def fail_locked(path, protected):
        if path == locked:
            attempts.append(path)
            raise PermissionError('file is locked')
        return remove(path, protected)
    monkeypatch.setattr(factory_reset, '_remove_target', fail_locked)
    monkeypatch.setattr(factory_reset.time, 'sleep', lambda _delay: None)
    shown = []
    monkeypatch.setattr(worker, '_show_failure', lambda *args: shown.append(args))
    log = tmp_path / 'failures.log'
    assert worker.run(wait_pid=123, settings_path=other, log_path=log) == 1
    assert len(attempts) == 3
    assert locked.exists() and not other.exists()
    assert 'partly complete' in log.read_text(encoding='utf-8')
    assert 'file is locked' in shown[0][0]
