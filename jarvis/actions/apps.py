"""Open and close apps."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser

from jarvis.winutil import NO_WINDOW

# spoken name -> command or full path. Extend via actions.configure(app_paths=...).
APP_PATHS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "command prompt": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "spotify": "spotify:",
    "camera": "microsoft.windows.camera:",
}

# spoken name -> process image name for closing (when it differs from APP_PATHS).
PROCESS_NAMES: dict[str, str] = {
    "calculator": "CalculatorApp.exe",
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "spotify": "Spotify.exe",
    "settings": "SystemSettings.exe",
    "terminal": "WindowsTerminal.exe",
    "camera": "WindowsCamera.exe",
}


# spoken name -> web address. "open youtube" opens the site when no app has that name.
WEBSITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google drive": "https://drive.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "whatsapp web": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "wikipedia": "https://www.wikipedia.org",
}
_DOMAIN = re.compile(r"^[a-z0-9-]+(?:\s*dot\s*|\.)(?:com|org|net|in|io|ai|dev|co|edu|gov)(?:\.[a-z]{2})?$")


def _website(name: str) -> str | None:
    if name in WEBSITES:
        return WEBSITES[name]
    if _DOMAIN.match(name):
        return "https://" + re.sub(r"\s*dot\s*", ".", name)
    return None


def _clean(name: str) -> str:
    return " ".join(name.lower().strip().split())


def open_app(name: str) -> str:
    name = re.sub(r"\s+(?:website|web site|site|page|dot com)$", lambda m: ".com" if "dot" in m.group(0) else "", _clean(name))
    if not name:
        return "Which app should I open?"
    url = None if name in APP_PATHS else _website(name)
    if url:
        webbrowser.open(url)
        return f"Opening {name}."
    if _BAD_CHARS.search(name):
        return "I can't open that name."
    target = APP_PATHS.get(name, name)
    try:
        _launch(target)
    except OSError:
        hit = find_start_app(name)  # Store and per-user apps: WhatsApp, Zoom, Discord...
        if hit:
            try:
                os.startfile("shell:AppsFolder\\" + hit[1])  # type: ignore[attr-defined]
                return f"Opening {hit[0]}."
            except OSError:
                pass
        from . import fuzzy  # only after the exact name failed: "crome" -> chrome

        key = fuzzy.app(name)
        if not key or key == name:
            return f"I couldn't find {name}."
        url = None if key in APP_PATHS else _website(key)
        if url:
            webbrowser.open(url)
            return f"Opening {key}."
        try:
            _launch(APP_PATHS[key])
        except (OSError, KeyError):
            return f"I couldn't find {key}."
        return f"Opening {key}."
    return f"Opening {name}."


# Characters that have a special meaning to the Windows shell. Never allowed in a spoken app name.
_BAD_CHARS = re.compile(r'["&|<>^%`;\r\n]')


def _launch(target: str) -> None:
    """Start an app without a shell, so a name can never run extra commands."""
    if os.path.isfile(target) or target.endswith(":"):
        os.startfile(target)  # type: ignore[attr-defined]  # Windows only
        return
    path = shutil.which(target)
    if path:
        subprocess.Popen([path])
    else:
        # ShellExecute also finds apps in the Windows "App Paths" registry. No shell is used.
        os.startfile(target)  # type: ignore[attr-defined]


# ---------- Start menu apps (Windows) ----------
_start_cache: list[tuple[str, str]] | None = None
_start_time = 0.0
START_CACHE_SECONDS = 1800


def start_menu_apps() -> list[tuple[str, str]]:
    """(name, AppID) of every app in the Start menu, from PowerShell Get-StartApps. Windows only.
    Cached for 30 minutes (PowerShell takes about a second). [] if it fails."""
    global _start_cache, _start_time
    if _start_cache is not None and time.monotonic() - _start_time < START_CACHE_SECONDS:
        return _start_cache
    if sys.platform != "win32":
        return []
    out: list[tuple[str, str]] = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW)
        data = json.loads(r.stdout or "[]")
        if isinstance(data, dict):  # only one app
            data = [data]
        out = [(str(d.get("Name")), str(d.get("AppID"))) for d in data
               if isinstance(d, dict) and d.get("Name") and d.get("AppID")]
    except Exception:
        out = []
    _start_cache, _start_time = out, time.monotonic()
    return out


def find_start_app(name: str, apps: list[tuple[str, str]] | None = None) -> tuple[str, str] | None:
    """Best Start menu app for a spoken name: exact, then first word ("zoom" -> "Zoom Workplace"),
    then a whole word in the name, then a close spelling. Never an uninstaller."""
    apps = start_menu_apps() if apps is None else apps
    want = _clean(name)
    if not want or not apps:
        return None
    usable = [(n, a) for n, a in apps if "uninstall" not in n.lower()]
    by_name = {_clean(n): (n, a) for n, a in usable}
    if want in by_name:
        return by_name[want]
    word = re.compile(r"\b" + re.escape(want) + r"\b")
    for test in (lambda k: k.startswith(want + " "), lambda k: bool(word.search(k))):
        hits = sorted((k for k in by_name if test(k)), key=len)
        if hits:
            return by_name[hits[0]]
    try:
        from . import fuzzy

        key = fuzzy.best(want, list(by_name))
        return by_name[key] if key else None
    except Exception:
        return None


def close_app(name: str) -> str:
    from .processes import PROTECTED, _base

    name = _clean(name)
    if not name:
        return "Which app should I close?"
    if _BAD_CHARS.search(name):
        return "I can't close that name."
    if name not in APP_PATHS and name not in PROCESS_NAMES:
        from . import fuzzy

        name = fuzzy.app(name, {**APP_PATHS, **PROCESS_NAMES}) or name
    proc = PROCESS_NAMES.get(name) or os.path.basename(APP_PATHS.get(name, name))
    if not proc.lower().endswith(".exe"):
        proc += ".exe"
    if _base(proc) in PROTECTED:
        return f"I won't close {name}. Windows or Jarvis needs it."
    # No /F: the app closes normally and can ask to save your work. Force close is "kill <name>", which asks first.
    r = subprocess.run(["taskkill", "/IM", proc], capture_output=True, text=True, errors="replace",
                       creationflags=NO_WINDOW)
    if r.returncode == 0:
        return f"Closing {name}."
    return f"I couldn't find {name} running."
