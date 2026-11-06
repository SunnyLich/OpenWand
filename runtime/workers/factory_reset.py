"""Run factory reset after the UI and supervisor have fully shut down."""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def run(*, wait_pid: int, settings_path: Path, log_path: Path, ready_path: Path | None = None) -> int:
    from core import factory_reset, updater
    from core.system import single_instance

    try:
        if ready_path is not None:
            ready_path.write_text("ready", encoding="utf-8")
            deadline = time.monotonic() + 15
            while not ready_path.with_name("proceed").exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Factory reset was not scheduled; no data was removed.")
                time.sleep(0.05)
        while updater._process_exists(wait_pid):
            time.sleep(0.25)
        if not single_instance.acquire(lock_file=False):
            raise RuntimeError("Another OpenWand process is running. Close it and retry Reset All.")
        plan = factory_reset.build_reset_plan(settings_path=settings_path)
        factory_reset.execute_reset(plan)
    except Exception as exc:  # noqa: BLE001 - detached failures must be visible
        try:
            log_path.write_text(str(exc), encoding="utf-8")
        except OSError:
            pass
        _show_failure(str(exc), log_path)
        return 1
    log_path.unlink(missing_ok=True)
    if ready_path is not None:
        ready_path.unlink(missing_ok=True)
        ready_path.with_name("proceed").unlink(missing_ok=True)
    log_path.parent.rmdir()
    return 0


def _show_failure(message: str, log_path: Path) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    QMessageBox.warning(None, "OpenWand reset could not finish", f"{message}\n\nDetails: {log_path}")
    del app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--settings-path", type=Path, required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument("--ready-path", type=Path, required=True)
    args = parser.parse_args()
    return run(wait_pid=args.wait_pid, settings_path=args.settings_path, log_path=args.log_path, ready_path=args.ready_path)


if __name__ == "__main__":
    raise SystemExit(main())
