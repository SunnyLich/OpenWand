"""Reusable confirmation flow for a complete OpenWand uninstall."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QWidget

from core import uninstaller
from ui.i18n import t


def run_uninstall_dialog(parent: QWidget | None = None) -> bool:
    """Confirm and launch the detached, self-removing OpenWand uninstaller."""
    try:
        plan = uninstaller.build_uninstall_plan(remove_user_data=True)
    except Exception as exc:  # noqa: BLE001 - safety validation must be visible
        QMessageBox.warning(
            parent,
            t("Could not start uninstaller"),
            t("Could not build a safe uninstall plan: {error}").format(error=exc),
        )
        return False

    kind = t("source checkout") if plan.source_checkout else t("release installation")
    details = t(
        "This will permanently remove:\n"
        "• OpenWand's current {kind}: {app_root}\n"
        "• OpenWand login and desktop entries"
    ).format(kind=kind, app_root=plan.app_root)
    if plan.source_checkout:
        details += "\n\n" + t(
            "The source checkout will be deleted, including its Git history, uncommitted changes, "
            "and every file inside it."
        )

    confirm = QMessageBox(parent)
    confirm.setIcon(QMessageBox.Icon.Critical)
    confirm.setWindowTitle(t("Uninstall OpenWand?"))
    confirm.setText(t("This action cannot be undone."))
    remove_data = QCheckBox(t("Also remove all OpenWand data and sign-ins"), confirm)
    remove_data.setObjectName("uninstallRemoveUserData")
    confirm.setCheckBox(remove_data)
    plan_valid = True

    def update_preview() -> None:
        nonlocal plan, plan_valid
        try:
            plan = uninstaller.build_uninstall_plan(remove_user_data=remove_data.isChecked())
        except Exception as exc:  # noqa: BLE001 - never confirm an invalid plan
            plan_valid = False
            confirm.setInformativeText(str(exc))
            confirm.button(QMessageBox.StandardButton.Yes).setEnabled(False)
            return
        plan_valid = True
        confirm.button(QMessageBox.StandardButton.Yes).setEnabled(True)
        if remove_data.isChecked():
            data_details = t(
                "Also permanently remove settings, chats, memory, add-ons, tools, logs, updates, "
                "optional packages, saved API keys, OAuth sign-in tokens, and OpenWand-owned models.\n"
                "User data: {data_root}\n"
                "External providers, their models, other apps' sign-ins, browser sessions, "
                "and shared uv/pip and Hugging Face caches will be kept."
            ).format(data_root=plan.user_data_root)
        else:
            data_details = t("Keep saved settings and data for a future reinstall: {data_root}").format(
                data_root=plan.user_data_root,
            )
        exact_targets = "\n".join(f"• {path}" for path in plan.targets)
        confirm.setInformativeText(
            details + "\n\n" + data_details + "\n\n"
            + t("Exact paths scheduled for deletion:") + "\n" + exact_targets
        )
    confirm.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    confirm.setDefaultButton(QMessageBox.StandardButton.No)
    remove_data.toggled.connect(update_preview)
    update_preview()
    if confirm.exec() != QMessageBox.StandardButton.Yes or not plan_valid:
        return False

    try:
        launch = uninstaller.launch_uninstaller(plan)
    except Exception as exc:  # noqa: BLE001 - keep OpenWand open after a failed launch
        QMessageBox.warning(
            parent,
            t("Could not start uninstaller"),
            t("Could not start uninstaller: {error}").format(error=exc),
        )
        return False

    QMessageBox.information(
        parent,
        t("Uninstaller started"),
        t(
            "OpenWand will now close. The uninstaller will remove only the listed OpenWand-owned files "
            "after all OpenWand processes exit. If cleanup cannot finish, details will be saved here:\n{path}"
        ).format(path=launch.failure_log_path),
    )
    app = QApplication.instance()
    if app is not None:
        QTimer.singleShot(0, app.quit)
    return True
