"""Start Jarvis automatically when you log in to Windows (no admin needed).

    python packaging/autostart.py install     # turn auto-start on
    python packaging/autostart.py uninstall   # turn auto-start off
    python packaging/autostart.py status      # show if it is on

It adds one value named "Jarvis" under
HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
that runs packaging/start_jarvis.pyw with pythonw.exe (no console window).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Jarvis"


def pythonw_path() -> Path:
    """pythonw.exe next to the running python (inside .venv after install)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def command() -> str:
    return f'"{pythonw_path()}" "{ROOT / "packaging" / "start_jarvis.pyw"}"'


def _winreg():
    import winreg  # Windows only

    return winreg


def install() -> None:
    wr = _winreg()
    with wr.OpenKey(wr.HKEY_CURRENT_USER, RUN_KEY, 0, wr.KEY_SET_VALUE) as key:
        wr.SetValueEx(key, NAME, 0, wr.REG_SZ, command())


def uninstall() -> None:
    wr = _winreg()
    with wr.OpenKey(wr.HKEY_CURRENT_USER, RUN_KEY, 0, wr.KEY_SET_VALUE) as key:
        try:
            wr.DeleteValue(key, NAME)
        except FileNotFoundError:
            pass  # already off


def is_installed() -> bool:
    wr = _winreg()
    with wr.OpenKey(wr.HKEY_CURRENT_USER, RUN_KEY, 0, wr.KEY_READ) as key:
        try:
            wr.QueryValueEx(key, NAME)
            return True
        except FileNotFoundError:
            return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    action = args[0] if args else "status"
    if sys.platform != "win32":
        print("Auto-start only works on Windows.")
        return 1
    if action == "install":
        install()
        print("Auto-start is ON. Jarvis will start when you log in.")
    elif action == "uninstall":
        uninstall()
        print("Auto-start is OFF.")
    elif action == "status":
        print("Auto-start is", "ON" if is_installed() else "OFF")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
