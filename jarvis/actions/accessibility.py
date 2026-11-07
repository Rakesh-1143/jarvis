"""Piece BF: Windows accessibility by voice: Magnifier, Narrator, Live captions, colour filters,
text size and cursor size.

    "turn on the magnifier" / "magnify more" / "magnifier zoom out" / "close the magnifier"
    "turn on narrator" / "stop narrator"
    "turn on live captions" / "captions off"
    "turn on colour filter" / "grayscale off"
    "make text bigger" / "bigger cursor"   (opens the right Settings page)

Uses Windows' own shortcut keys through pyautogui.hotkey (not inputs.py). Narrator, captions and colour
filters are toggles, so "on"/"off" first check whether the feature is already running and do nothing then.
Wiring: merge CATALOG and HANDLERS; nlu_features can use accessibility.parse(text). Nothing risky.
"""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)

FEATURES = ("magnifier", "narrator", "captions", "color_filter", "text_size", "cursor")
ACTIONS = ("on", "off", "toggle", "zoom_in", "zoom_out")

# Windows shortcut keys (pyautogui names). "=" is the "+/=" key: Win+Plus in Microsoft's docs.
KEYS = {
    "magnifier_on": ("win", "="),
    "zoom_in": ("win", "="),
    "zoom_out": ("win", "-"),
    "magnifier_off": ("win", "esc"),
    "narrator": ("ctrl", "win", "enter"),
    "captions": ("win", "ctrl", "l"),
    "color_filter": ("win", "ctrl", "c"),
}

PAGES = {
    "magnifier": "ms-settings:easeofaccess-magnifier",
    "narrator": "ms-settings:easeofaccess-narrator",
    "captions": "ms-settings:easeofaccess-closedcaptioning",
    "color_filter": "ms-settings:easeofaccess-colorfilter",
    "text_size": "ms-settings:easeofaccess-display",
    "cursor": "ms-settings:easeofaccess-mousepointer",
}

PROCESSES = {"magnifier": "magnify.exe", "narrator": "narrator.exe", "captions": "livecaptions.exe"}
_COLOR_KEY = r"Software\Microsoft\ColorFiltering"

NAMES = {"magnifier": "Magnifier", "narrator": "Narrator", "captions": "Live captions",
         "color_filter": "Colour filter", "text_size": "text size", "cursor": "cursor size"}


# ---------- low level (patched in tests) ----------
def _hotkey(*keys: str) -> None:
    import pyautogui

    pyautogui.FAILSAFE = False  # a mouse in the corner must not break a voice command
    pyautogui.hotkey(*keys)


def _start(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # Windows only


def _running(feature: str) -> bool | None:
    """True/False if the feature's program is running; None if unknown."""
    exe = PROCESSES.get(feature)
    if not exe:
        return None
    try:
        import psutil

        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == exe:
                return True
        return False
    except Exception:
        log.debug("process check failed", exc_info=True)
        return None


def _color_state() -> tuple[bool | None, bool | None]:
    """(filter on?, shortcut enabled?) from the registry; None = unknown."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _COLOR_KEY) as k:
            def val(name):
                try:
                    return bool(winreg.QueryValueEx(k, name)[0])
                except OSError:
                    return False
            return val("Active"), val("HotkeyEnabled")
    except Exception:
        return None, None


# ---------- handler ----------
def _toggle_feature(feature: str, action: str, running: bool | None) -> str:
    name = NAMES[feature]
    if action == "on" and running is True:
        return f"{name} is already on."
    if action == "off" and running is False:
        return f"{name} is already off."
    _hotkey(*KEYS[feature])
    if action == "on" or (action == "toggle" and running is False):
        return f"{name} is on."
    if action == "off" or (action == "toggle" and running is True):
        return f"{name} is off."
    return f"Switched {name}."


def _magnifier(action: str) -> str:
    running = _running("magnifier")
    if action == "off" or (action == "toggle" and running):
        if running is False:
            return "Magnifier is already off."
        _hotkey(*KEYS["magnifier_off"])
        return "Magnifier closed."
    if action == "zoom_out":
        if running is False:
            return "Magnifier is not on. Say 'turn on the magnifier' first."
        _hotkey(*KEYS["zoom_out"])
        return "Zoomed out."
    if action == "on" and running:
        return "Magnifier is already on. Say 'zoom in' or 'zoom out'."
    _hotkey(*KEYS["zoom_in"])  # Win+Plus starts Magnifier, then zooms in
    if action == "zoom_in" and running is not False:
        return "Zoomed in."
    return "Magnifier is on. Say 'magnifier zoom in' or 'magnifier zoom out'."


def _color_filter(action: str) -> str:
    active, hotkey_ok = _color_state()
    if hotkey_ok is False:
        _start(PAGES["color_filter"])
        return ("The colour filter shortcut is turned off in Windows. I opened the settings: "
                "turn on 'Keyboard shortcut for color filters' once, then ask me again.")
    return _toggle_feature("color_filter", action, active)


def accessibility(args: dict) -> str:
    feature = str(args.get("feature") or "").lower().replace(" ", "_").replace("colour", "color")
    action = str(args.get("action") or "toggle").lower().replace(" ", "_")
    if feature not in FEATURES:
        return "I can control the magnifier, narrator, live captions, colour filter, text size and cursor size."
    if action not in ACTIONS:
        action = "toggle"
    if feature in ("text_size", "cursor"):
        _start(PAGES[feature])
        return f"Opening {NAMES[feature]} settings. Move the slider to change it."
    if action in ("zoom_in", "zoom_out") and feature != "magnifier":
        feature = "magnifier"
    try:
        if feature == "magnifier":
            return _magnifier(action)
        if feature == "color_filter":
            return _color_filter(action)
        return _toggle_feature(feature, action, _running(feature))
    except Exception:
        log.warning("accessibility %s %s failed", feature, action, exc_info=True)
        try:
            _start(PAGES[feature])
        except Exception:
            return f"Sorry, I couldn't change {NAMES[feature]}."
        tail = " Live captions need Windows 11 version 22H2 or newer." if feature == "captions" else ""
        return f"I couldn't switch {NAMES[feature]} myself, so I opened its settings.{tail}"


# ---------- phrases ----------
_ON = r"(?:turn on|switch on|start|open|enable|launch|show)"
_OFF = r"(?:turn off|switch off|stop|close|disable|exit|quit|hide)"
_FEAT = {
    "magnifier": r"(?:the )?(?:magnifier|magnify|screen magnifier)",
    "narrator": r"(?:the )?(?:narrator|screen reader)",
    "captions": r"(?:the )?(?:live captions?|live subtitles|captions)",
    "color_filter": r"(?:the )?(?:colou?r filters?|grayscale|greyscale|gray scale|grey scale|colou?r ?blind mode|"
                    r"inverted colou?rs|invert colou?rs)",
}


def _rules():
    rules = []
    for feat, f in _FEAT.items():
        rules += [
            (rf"{_ON} {f}(?: mode)?", feat, "on"),
            (rf"{f}(?: mode)? on", feat, "on"),
            (rf"{_OFF} {f}(?: mode)?", feat, "off"),
            (rf"{f}(?: mode)? off", feat, "off"),
            (rf"toggle {f}", feat, "toggle"),
        ]
    m = _FEAT["magnifier"]
    rules += [
        (rf"(?:{m} )?(?:zoom in|zoom more|more zoom)(?: (?:with|on) {m})?", "magnifier", "zoom_in"),
        (r"magnify(?: (?:more|the screen|screen|it))?", "magnifier", "zoom_in"),
        (rf"(?:{m} )?(?:zoom out|zoom less|less zoom)(?: (?:with|on) {m})?", "magnifier", "zoom_out"),
        (r"(?:make |set )?(?:the )?(?:text|font|letters?)(?: size)? (?:bigger|larger|smaller|size)|"
         r"(?:make )?(?:the )?(?:text|font|letters?) (?:bigger|larger|smaller)|"
         r"(?:bigger|larger|smaller) (?:text|font|letters)|change (?:the )?(?:text|font) size|text size(?: settings)?",
         "text_size", "toggle"),
        (r"(?:make |set )?(?:the )?(?:mouse )?(?:cursor|pointer|mouse)(?: size)? (?:bigger|larger|smaller)|"
         r"(?:bigger|larger|smaller) (?:mouse )?(?:cursor|pointer)|change (?:the )?(?:mouse )?(?:cursor|pointer)(?: size)?|"
         r"(?:cursor|pointer) size(?: settings)?",
         "cursor", "toggle"),
    ]
    return [(re.compile(rf"^{rx}$"), feat, act) for rx, feat, act in rules]


_RULES = _rules()


def parse(text: str) -> tuple[str, dict] | None:
    """Phrase -> ("accessibility", {feature, action}), or None. Bare "zoom in" is NOT caught
    (nlu_control uses it for Ctrl+Plus in the browser); magnifier zoom needs the word magnifier/magnify."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip().strip(" .!?"))
    t = re.sub(r"^(?:jarvis|hey jarvis|ok jarvis)[, ]+", "", t)
    t = re.sub(r"^(?:please|can you|could you)\s+", "", t)
    t = re.sub(r"\s+please$", "", t)
    for rx, feat, act in _RULES:
        if rx.match(t):
            if act in ("zoom_in", "zoom_out") and not re.search(r"magnif", t):
                return None
            return "accessibility", {"feature": feat, "action": act}
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "accessibility": {
        "description": "Windows accessibility: Magnifier (on/off/zoom_in/zoom_out), Narrator screen reader, "
                       "Live captions (Windows 11 22H2+), colour filters such as grayscale (on/off), or open "
                       "the text size / cursor size settings. Not for browser zoom.",
        "properties": {
            "feature": {"type": "string", "enum": list(FEATURES)},
            "action": {"type": "string", "enum": list(ACTIONS),
                       "description": "on, off, toggle (default), zoom_in, zoom_out (magnifier only)."},
        },
        "required": ["feature"]},
}

HANDLERS = {"accessibility": accessibility}
