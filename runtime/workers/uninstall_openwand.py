"""Standalone GUI entrypoint used by ``Uninstall OpenWand.bat``."""
from __future__ import annotations

import sys
from pathlib import Path


def _remove_installed_user_data() -> int:
    """Synchronous, noninteractive cleanup called only by the native uninstaller."""
    from core import uninstaller
    from core.system import single_instance
    from core.system.paths import is_installed_release

    if not is_installed_release():
        return 1
    if not single_instance.acquire(lock_file=False):
        return 2
    try:
        plan = uninstaller.build_uninstall_plan(remove_user_data=True)
        uninstaller.remove_user_data_files(plan)
    except Exception as exc:  # noqa: BLE001 - return failures to Inno, never open a second UI
        import tempfile

        log = Path(tempfile.gettempdir()) / "openwand-uninstall-data-failures.log"
        try:
            log.write_text(str(exc), encoding="utf-8")
        except OSError:
            pass
        return 1
    return 0


def _run_uninstaller_dialog() -> int:
    """Open the shared uninstaller only when no other OpenWand process is active."""
    from PySide6.QtWidgets import QMessageBox

    from core.system import single_instance
    from ui.i18n import t
    from ui.uninstall_dialog import run_uninstall_dialog

    if not single_instance.acquire():
        QMessageBox.warning(
            None,
            t("Could not start uninstaller"),
            t("Another OpenWand process is still running. Close OpenWand, then run Uninstall OpenWand.bat again."),
        )
        return 1
    run_uninstall_dialog(None)
    return 0


def main() -> int:
    """Create a themed OpenWand application and show the complete-uninstall flow."""
    if "--clear-credentials" in sys.argv[1:]:
        from core import uninstaller

        failures = uninstaller.remove_openwand_keychain_entries()
        if failures:
            print("Could not clear OpenWand credentials: " + "; ".join(failures), file=sys.stderr)
            return 1
        return 0
    if "--remove-user-data" in sys.argv[1:]:
        return _remove_installed_user_data()

    from PySide6.QtWidgets import QApplication

    from ui import i18n
    from ui.shared.app_icon import install_app_icon
    from ui.shared.theme import apply_app_theme

    app = QApplication.instance() or QApplication(sys.argv[:1])
    install_app_icon(app)
    i18n.set_language(app=app)
    apply_app_theme(app)
    return _run_uninstaller_dialog()


if __name__ == "__main__":
    raise SystemExit(main())
