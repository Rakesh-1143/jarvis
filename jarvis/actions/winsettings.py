"""Windows settings: open any Settings page, dark mode, power plan, screen off."""
from __future__ import annotations

import os
import subprocess

from jarvis.winutil import NO_WINDOW

# spoken page -> Settings URI (or program). Longest match wins.
PAGES = {
    "display": "ms-settings:display", "screen": "ms-settings:display", "resolution": "ms-settings:display",
    "night light": "ms-settings:nightlight", "sound": "ms-settings:sound", "audio": "ms-settings:sound",
    "speaker": "ms-settings:sound", "microphone": "ms-settings:privacy-microphone", "mic": "ms-settings:privacy-microphone",
    "camera": "ms-settings:privacy-webcam", "bluetooth": "ms-settings:bluetooth", "devices": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi", "wi-fi": "ms-settings:network-wifi", "network": "ms-settings:network",
    "internet": "ms-settings:network", "vpn": "ms-settings:network-vpn", "hotspot": "ms-settings:network-mobilehotspot",
    "airplane mode": "ms-settings:network-airplanemode", "battery": "ms-settings:batterysaver",
    "battery saver": "ms-settings:batterysaver", "power": "ms-settings:powersleep", "sleep": "ms-settings:powersleep",
    "notifications": "ms-settings:notifications", "focus": "ms-settings:notifications",
    "do not disturb": "ms-settings:notifications", "apps": "ms-settings:appsfeatures",
    "installed apps": "ms-settings:appsfeatures", "default apps": "ms-settings:defaultapps",
    "startup": "ms-settings:startupapps", "startup apps": "ms-settings:startupapps", "storage": "ms-settings:storagesense",
    "update": "ms-settings:windowsupdate", "windows update": "ms-settings:windowsupdate", "updates": "ms-settings:windowsupdate",
    "privacy": "ms-settings:privacy", "location": "ms-settings:privacy-location", "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:devices-touchpad", "keyboard": "ms-settings:typing", "typing": "ms-settings:typing",
    "personalization": "ms-settings:personalization", "background": "ms-settings:personalization-background",
    "wallpaper": "ms-settings:personalization-background", "themes": "ms-settings:themes", "theme": "ms-settings:themes",
    "colors": "ms-settings:personalization-colors", "color": "ms-settings:personalization-colors",
    "lock screen": "ms-settings:lockscreen", "taskbar": "ms-settings:taskbar", "accounts": "ms-settings:yourinfo",
    "account": "ms-settings:yourinfo", "sign in": "ms-settings:signinoptions", "password": "ms-settings:signinoptions",
    "date": "ms-settings:dateandtime", "time": "ms-settings:dateandtime", "date and time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage", "region": "ms-settings:regionlanguage", "printers": "ms-settings:printers",
    "printer": "ms-settings:printers", "about": "ms-settings:about", "system": "ms-settings:about",
    "multitasking": "ms-settings:multitasking", "accessibility": "ms-settings:easeofaccess",
    "clipboard": "ms-settings:clipboard", "gaming": "ms-settings:gaming-gamebar", "recovery": "ms-settings:recovery",
    "activation": "ms-settings:activation", "remote desktop": "ms-settings:remotedesktop",
    "security": "windowsdefender:", "windows security": "windowsdefender:", "antivirus": "windowsdefender:",
    "control panel": "control", "device manager": "devmgmt.msc", "task manager": "taskmgr",
}


def _start(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # Windows only


def find_page(name: str) -> tuple[str, str]:
    """(spoken page, uri). Unknown -> ('', 'ms-settings:') = Settings home."""
    n = " ".join((name or "").lower().replace("settings", "").split())
    if n in PAGES:
        return n, PAGES[n]
    for key in sorted(PAGES, key=len, reverse=True):
        if key in n:
            return key, PAGES[key]
    return "", "ms-settings:"


def open_settings(args: dict) -> str:
    page, uri = find_page(args.get("page", ""))
    _start(uri)
    return f"Opening {page} settings." if page else "Opening settings."


# ---------- dark mode ----------
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _set_dark(on: bool) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE, 0, winreg.KEY_SET_VALUE) as k:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0 if on else 1)
    # tell open apps the theme changed (HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG)
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 3000,  # type: ignore[attr-defined]
                                             ctypes.byref(result))


def dark_mode(args: dict) -> str:
    state = args.get("state", "on")
    try:
        _set_dark(state != "off")
    except Exception:
        _start("ms-settings:personalization-colors")
        return "I couldn't switch the theme myself, so I opened the colors settings."
    return "Dark mode is on." if state != "off" else "Light mode is on."


# ---------- power plan ----------
_PLANS = {  # powercfg aliases (SCHEME_MIN = least power saving = high performance)
    "balanced": ("SCHEME_BALANCED", "balanced"),
    "power_saver": ("SCHEME_MAX", "power saver"),
    "high_performance": ("SCHEME_MIN", "high performance"),
}


def power_plan(args: dict) -> str:
    plan = args.get("plan", "balanced")
    if plan not in _PLANS:
        return "I can use balanced, power saver or high performance."
    alias, words = _PLANS[plan]
    r = subprocess.run(["powercfg", "/setactive", alias], capture_output=True, text=True, errors="replace",
                       creationflags=NO_WINDOW)
    if r.returncode == 0:
        return f"Power plan set to {words}."
    # Many new laptops only have "Balanced"; Windows 11 uses "Power mode" in Settings instead.
    _start("ms-settings:powersleep")
    return f"This laptop has no {words} plan, so I opened the power settings. Change Power mode there."


# ---------- screen off ----------
def screen_off(args: dict) -> str:
    import ctypes

    # WM_SYSCOMMAND / SC_MONITORPOWER / 2 = off. Moving the mouse turns it back on.
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # type: ignore[attr-defined]
    return "Turning the screen off. Move the mouse to turn it on."
