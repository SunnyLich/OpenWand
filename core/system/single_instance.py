"""Single-instance guard: ensure only one OpenWand process runs at a time.

Uses an OS-level advisory lock on a file in the user-data dir. The lock is held
for the lifetime of the process and released automatically by the OS on exit or
crash, so there are no stale lock files to clean up.

The lock lives in the user-data dir (see paths.SINGLE_INSTANCE_LOCK), so a dev
run (`python -m runtime.supervisor.app`) and an installed build contend for the same lock.
"""
from __future__ import annotations

import logging
import sys

from core.system.paths import SINGLE_INSTANCE_LOCK

log = logging.getLogger("openwand")

# Kept alive for the whole process lifetime. If this handle is garbage-collected
# the OS releases the lock, so it must stay referenced at module scope.
_lock_handle = None
_mutex_handle = None
_WINDOWS_MUTEX_NAME = "Local\\OpenWand.SingleInstance.v2"


def acquire() -> bool:
    """Try to become the single running instance.

    Returns True if this process now holds the lock (it is the only instance),
    or False if another OpenWand instance already holds it or exclusivity cannot be
    proven. The guard fails closed: starting no OpenWand is safer than starting two
    supervisors with competing global hotkeys and UI workers.
    """
    try:
        SINGLE_INSTANCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.exception("Could not prepare the OpenWand single-instance lock directory; refusing startup.")
        return False

    try:
        if sys.platform == "win32":
            return _acquire_windows()
        return _acquire_posix()
    except Exception:  # noqa: BLE001 - an uncertain guard must never permit a second instance
        log.exception("Could not establish the OpenWand single-instance guard; refusing startup.")
        return False


def _acquire_windows() -> bool:
    """Handle acquire windows for system single instance."""
    global _lock_handle, _mutex_handle
    import ctypes
    import msvcrt

    # The named kernel mutex is the authoritative Windows guard.  The byte-range
    # file lock remains in place for updater compatibility, but msvcrt locking
    # alone has allowed two uv/python launcher trees to coexist in production.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    mutex = kernel32.CreateMutexW(None, True, _WINDOWS_MUTEX_NAME)
    if not mutex:
        log.error("Could not create the OpenWand instance mutex; refusing startup.")
        return False
    elif ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return False

    try:
        fh = open(SINGLE_INSTANCE_LOCK, "a+")
    except OSError:
        # The kernel mutex is the authoritative Windows guard. Keep its handle
        # alive even when the compatibility lock used by the updater is absent.
        log.warning("Could not open the compatibility instance lock; the kernel mutex remains active.")
        _mutex_handle = mutex
        return True

    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        if mutex:
            kernel32.CloseHandle(mutex)
        return False  # another instance holds the lock

    _lock_handle = fh
    _mutex_handle = mutex
    return True


def _acquire_posix() -> bool:
    """Handle acquire posix for system single instance."""
    global _lock_handle
    import fcntl

    try:
        fh = open(SINGLE_INSTANCE_LOCK, "a+")
    except OSError:
        log.error("Could not open the OpenWand instance lock; refusing startup.")
        return False

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False  # another instance holds the lock

    _lock_handle = fh
    return True
