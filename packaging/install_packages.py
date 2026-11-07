"""Install Jarvis's packages. Used by install.bat.

    python packaging/install_packages.py

1. Tries `pip install -r requirements.txt` (fast, one step).
2. If that fails (one package has no build for this Python, a network hiccup...), installs the packages
   one by one, so one broken OPTIONAL package (Spotify, OCR, tray icon...) does not stop the whole install.
3. Fails (exit code 1) only if a CORE package is missing: without those Jarvis can't hear or speak.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

# Jarvis can't run without these (config, mic, speech model, voice).
CORE = {"pyyaml", "vosk", "sounddevice", "pyttsx3", "comtypes", "pywin32"}


def requirement_lines(text: str) -> list[str]:
    """Package lines of requirements.txt, without comments and blank lines."""
    out = []
    for line in text.splitlines():
        line = line.split(" #", 1)[0].split("\t#", 1)[0].strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def package_name(line: str) -> str:
    """'winrt-Windows.Foundation>=2.0; sys_platform == "win32"' -> 'winrt-windows-foundation'."""
    name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _pip(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *args])


def main() -> int:
    if _pip("-r", str(REQUIREMENTS)) == 0:
        return 0
    print("\nOne package failed. Installing the packages one by one ...\n")
    failed = []
    for line in requirement_lines(REQUIREMENTS.read_text(encoding="utf-8")):
        if _pip(line) != 0:
            failed.append(line)
    if not failed:
        return 0
    core = [f for f in failed if package_name(f) in CORE]
    print("\nThese packages could not be installed:")
    for f in failed:
        print("   ", f, "(needed!)" if f in core else "(optional: only that feature won't work)")
    if core:
        print("\nJarvis needs the packages marked 'needed'. Check your internet and run install.bat again.")
        return 1
    print("\nJarvis will still work. Run 'python main.py --doctor' later to see what is missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
