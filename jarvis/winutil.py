"""Small Windows helpers used by many modules. Every function is safe (does nothing) on other systems.

    com_init()            start COM on this thread (needed by pycaw, Outlook, WinRT, pywinauto in helper threads)
    NO_WINDOW             subprocess creationflags: no black console box when Jarvis runs hidden (pythonw)
    single_instance(name) False if another Jarvis is already running (so two copies don't both answer)
    fix_console()         print() never crashes on letters the console can't show (e.g. the rupee sign)
"""
from __future__ import annotations

import sys
import threading

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW

_local = threading.local()
_mutex = None  # keep the handle alive for the whole run


def com_init() -> None:
    """Start COM once on the calling thread. Windows only; never raises.

    Python's main thread gets COM from comtypes/pywin32 on import, but helper threads (triggers, tray,
    calendar alerts, notifications) don't, and then pycaw / Outlook / WinRT fail with
    "CoInitialize has not been called"."""
    if not IS_WINDOWS or getattr(_local, "com", False):
        return
    _local.com = True
    try:
        import ctypes

        # COINIT_APARTMENTTHREADED, like comtypes and pywin32 use. S_FALSE / RPC_E_CHANGED_MODE are fine:
        # both mean COM is already started on this thread.
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # type: ignore[attr-defined]
    except Exception:
        pass


def single_instance(name: str = "Local\\JarvisVoiceAssistant") -> bool:
    """True if this is the only running Jarvis. Uses a named Windows mutex, freed when the process ends."""
    global _mutex
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        handle = k32.CreateMutexW(None, False, name)
        if not handle:
            return True  # can't tell: don't block the start
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle(handle)
            return False
        _mutex = handle
        return True
    except Exception:
        return True


def fix_console() -> None:
    """Make print() replace letters the console can't show instead of crashing (UnicodeEncodeError).
    Under pythonw.exe there is no console at all (stdout is None); print() is then a no-op already."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass
