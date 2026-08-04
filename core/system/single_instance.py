"""Single-instance guard: ensure only one Wisp process runs at a time.

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

log = logging.getLogger("wisp")

# Kept alive for the whole process lifetime. If this handle is garbage-collected
# the OS releases the lock, so it must stay referenced at module scope.
_lock_handle = None
_mutex_handle = None
_WINDOWS_MUTEX_NAME = "Local\\Wisp.SingleInstance.v2"


def acquire() -> bool:
    """Try to become the single running instance.

    Returns True if this process now holds the lock (it is the only instance),
    or False if another Wisp instance already holds it. Fails open (returns
    True) if the lock file itself cannot be opened, so a filesystem hiccup never
    blocks the only instance from starting.
    """
    try:
        SINGLE_INSTANCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    if sys.platform == "win32":
        return _acquire_windows()
    return _acquire_posix()


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
        log.warning("Could not create the Wisp instance mutex; falling back to the file lock.")
    elif ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return False

    try:
        fh = open(SINGLE_INSTANCE_LOCK, "a+")
    except OSError:
        log.warning("Could not open single-instance lock file; skipping guard.")
        _mutex_handle = mutex
        return True  # fail open: never block the only instance over a fs error

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
        log.warning("Could not open single-instance lock file; skipping guard.")
        return True  # fail open: never block the only instance over a fs error

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False  # another instance holds the lock

    _lock_handle = fh
    return True
