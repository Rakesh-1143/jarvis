"""Piece BR: second screen / projector modes and screen info.

"extend my screen", "duplicate screen", "second screen only", "laptop screen only",
"how many monitors", "what's my resolution", "open projection menu".

Intent: display {action: extend|duplicate|external_only|internal_only|info|menu}
  extend / duplicate / external_only / internal_only - DisplaySwitch.exe /extend /clone /external /internal
  info  - (info) how many screens, resolution and refresh rate of each
  menu  - open the Windows "Project" side menu (Win+P)

Screen info uses pywin32 (core package): EnumDisplayMonitors, GetMonitorInfo, EnumDisplaySettings.
Tests swap `_monitors()`, `_switch()` and `_menu()` for fakes.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ACTIONS = ("extend", "duplicate", "external_only", "internal_only", "info", "menu")
_SYNONYMS = {
    "clone": "duplicate", "mirror": "duplicate", "copy": "duplicate", "same": "duplicate",
    "external": "external_only", "second_only": "external_only", "second_screen_only": "external_only",
    "projector_only": "external_only", "monitor_only": "external_only",
    "internal": "internal_only", "pc_only": "internal_only", "laptop_only": "internal_only",
    "pc_screen_only": "internal_only", "laptop_screen_only": "internal_only", "disconnect": "internal_only",
    "resolution": "info", "monitors": "info", "status": "info", "count": "info", "how_many": "info",
    "project": "menu", "projection": "menu", "win_p": "menu", "options": "menu",
}
_SWITCH_ARGS = {"extend": "/extend", "duplicate": "/clone", "external_only": "/external", "internal_only": "/internal"}
_REPLIES = {
    "extend": "Extending your screen to the second display.",
    "duplicate": "Showing the same picture on both screens.",
    "external_only": "Switching to the second screen only. Your laptop screen will go dark.",
    "internal_only": "Switching to the laptop screen only.",
}
_GENERIC = re.compile(r"generic|pnp|default monitor", re.I)


def _on_windows() -> bool:
    return sys.platform == "win32"


def _displayswitch() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    # 32-bit Python on 64-bit Windows sees SysWOW64 as System32; Sysnative is the real one.
    for folder in ("Sysnative", "System32"):
        path = os.path.join(root, folder, "DisplaySwitch.exe")
        if os.path.exists(path):
            return path
    return "DisplaySwitch.exe"


def _switch(mode: str) -> None:
    from jarvis.winutil import NO_WINDOW

    subprocess.Popen([_displayswitch(), _SWITCH_ARGS[mode]], creationflags=NO_WINDOW)


def _menu() -> None:
    import pyautogui

    pyautogui.hotkey("win", "p")


def _monitors() -> list[dict]:
    """[{device, width, height, hz, primary, name}] for each active screen, primary first."""
    import win32api

    out = []
    for handle, _dc, _rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        device = info.get("Device", "")
        width = height = hz = 0
        try:
            mode = win32api.EnumDisplaySettings(device, -1)  # ENUM_CURRENT_SETTINGS: real pixels, not scaled
            width, height, hz = int(mode.PelsWidth), int(mode.PelsHeight), int(mode.DisplayFrequency)
        except Exception:
            left, top, right, bottom = info.get("Monitor", (0, 0, 0, 0))
            width, height = right - left, bottom - top
        name = ""
        try:
            name = str(win32api.EnumDisplayDevices(device, 0).DeviceString or "").strip()
        except Exception:
            pass
        out.append({"device": device, "width": width, "height": height, "hz": hz,
                    "primary": bool(info.get("Flags", 0) & 1), "name": name})
    return sorted(out, key=lambda m: not m["primary"])


def _screen_words(m: dict) -> str:
    text = f"{m['width']} by {m['height']}"
    if m.get("hz") and m["hz"] > 1:  # 0 or 1 mean "hardware default"
        text += f" at {m['hz']} hertz"
    return text


def _info() -> str:
    mons = _monitors()
    if not mons:
        return "I can't see any screens."
    if len(mons) == 1:
        return f"You have one screen. Its resolution is {_screen_words(mons[0])}."
    parts = []
    for i, m in enumerate(mons, 1):
        label = "main screen" if m["primary"] else f"screen {i}"
        if m.get("name") and not _GENERIC.search(m["name"]):
            label += f" ({m['name']})"
        parts.append(f"{label}: {_screen_words(m)}")
    return f"You have {len(mons)} screens. " + ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def display(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "").strip().lower().replace(" ", "_").replace("-", "_")
    action = _SYNONYMS.get(action, action)
    if action not in ACTIONS:
        return ("I can extend or duplicate your screen, use only the second screen or only the laptop screen, "
                "tell you your resolution, or open the projection menu.")
    if not _on_windows():
        return "Screen switching only works on Windows."
    try:
        if action == "info":
            return _info()
        if action == "menu":
            _menu()
            return "Here is the projection menu."
        _switch(action)
    except Exception as e:
        return f"I couldn't change the screens: {e}"
    return _REPLIES[action]


# ---------- phrases (for nlu_features) ----------

_SCR = r"(?:screens?|displays?|monitors?|desktop)"
_SECOND = r"(?:second|external|other|big|tv|projector|hdmi)(?: screen| display| monitor)?|projector|tv|hdmi"
_LAPTOP = r"(?:laptop|pc|computer|main|built-?in|internal)(?: screen| display| monitor)?"


def parse(text: str):
    """(intent, args) or None. Call before generic open_app / web_search."""
    t = re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip("?.! ")
    if not t:
        return None
    t = re.sub(r"^(?:please |can you |could you |jarvis )+", "", t)
    if re.fullmatch(rf"extend(?: my| the)? {_SCR}(?: to (?:the )?(?:{_SECOND}))?|extend mode|extend display mode", t):
        return "display", {"action": "extend"}
    if re.fullmatch(rf"(?:duplicate|mirror|clone)(?: my| the)? {_SCR}(?: on (?:the )?(?:{_SECOND}))?"
                    rf"|(?:duplicate|mirror) mode|same (?:picture|thing) on (?:both|all) {_SCR}"
                    rf"|show (?:my screen|this) on (?:the )?(?:{_SECOND})", t):
        return "display", {"action": "duplicate"}
    if re.fullmatch(rf"(?:(?:use|show)(?: the)? )?(?:{_SECOND}) only|only(?: use)?(?: the)? (?:{_SECOND})", t):
        return "display", {"action": "external_only"}
    if re.fullmatch(rf"(?:(?:use|show)(?: the)? )?(?:{_LAPTOP}) only|only(?: use)?(?: the)? (?:{_LAPTOP})"
                    rf"|(?:disconnect|stop)(?: the| my)? (?:projector|(?:second|external) (?:screen|display|monitor))"
                    rf"|stop (?:projecting|mirroring|duplicating|extending)(?: my screen)?", t):
        return "display", {"action": "internal_only"}
    if re.fullmatch(rf"(?:what(?:'s| is)) (?:my |the )?(?:screen |display |monitor )?resolution"
                    rf"|(?:screen|display|monitor) resolution|(?:how many) {_SCR}(?: do i have| are (?:connected|there))?"
                    rf"|(?:what(?:'s| is)) (?:my |the )?(?:screen|display|monitor) refresh rate|(?:my |the )?refresh rate", t):
        return "display", {"action": "info"}
    if re.fullmatch(r"(?:open|show)(?: the| me the)? (?:projection|project|projector|display mode|second screen) (?:menu|options|panel)"
                    r"|project (?:screen|menu)|projection (?:menu|options)", t):
        return "display", {"action": "menu"}
    return None


CATALOG: dict[str, dict] = {
    "display": {
        "description": ("Second screen / projector: extend the desktop, duplicate (mirror) it, use only the second "
                        "screen, or only the laptop screen (Windows DisplaySwitch); say how many screens and each "
                        "resolution and refresh rate; or open the Win+P projection menu."),
        "properties": {"action": {"type": "string", "enum": list(ACTIONS)}},
        "required": ["action"],
    },
}

HANDLERS = {"display": display}
