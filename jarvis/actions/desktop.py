"""Media keys, music, and window control."""
from __future__ import annotations

import urllib.parse
import webbrowser

MUSIC_URL = "https://www.youtube.com/results?search_query={query}"

_MEDIA_KEYS = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack", "stop": "stop"}
_MEDIA_REPLY = {"play_pause": "Okay.", "next": "Next track.", "previous": "Previous track.", "stop": "Stopped."}


def media(args: dict) -> str:
    action = args.get("action", "play_pause")
    key = _MEDIA_KEYS.get(action)
    if not key:
        return "I can play, pause, skip, go back or stop."
    import pyautogui

    pyautogui.press(key)
    return _MEDIA_REPLY[action]


def play(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return media({"action": "play_pause"})
    webbrowser.open(MUSIC_URL.replace("{query}", urllib.parse.quote_plus(query)))
    return f"Playing {query}."


# ---------- windows ----------
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010

_HOTKEYS = {
    "switch": ("alt", "tab"),
    "show_desktop": ("win", "d"),
    "snap_left": ("win", "left"),
    "snap_right": ("win", "right"),
    "task_view": ("win", "tab"),
}
_WIN_REPLY = {
    "minimize": "Minimized.", "maximize": "Maximized.", "restore": "Restored.",
    "close": "Closed the window.", "switch": "Switched window.", "show_desktop": "Showing the desktop.",
    "snap_left": "Snapped left.", "snap_right": "Snapped right.", "task_view": "Here are your windows.",
}


def window(args: dict) -> str:
    action = args.get("action", "")
    if action not in _WIN_REPLY:
        return "I can minimize, maximize, restore, close, switch or snap windows, or show the desktop."
    if action in _HOTKEYS:
        import pyautogui

        pyautogui.hotkey(*_HOTKEYS[action])
    else:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "There is no active window."
        if action == "close":
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # app can still ask to save
        else:
            user32.ShowWindow(hwnd, {"minimize": SW_MINIMIZE, "maximize": SW_MAXIMIZE, "restore": SW_RESTORE}[action])
    return _WIN_REPLY[action]


# ---------- clipboard, selected text, screen ----------
def read_clipboard(args: dict) -> str:
    import pyperclip

    text = (pyperclip.paste() or "").strip()
    if not text:
        return "The clipboard is empty."
    if args.get("full"):
        return text[:20000]
    return text if len(text) <= 400 else text[:400].rsplit(" ", 1)[0] + "... and more."


def copy_text(args: dict) -> str:
    import pyperclip

    text = args.get("text") or ""
    if not text:
        return "What should I copy?"
    pyperclip.copy(text)
    return "Copied to the clipboard."


_CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "VirtualConsoleClass"}


def _foreground_is_console() -> bool:
    """True if the active window is a terminal. Ctrl+C there would stop the running program (or Jarvis)."""
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(user32.GetForegroundWindow(), buf, 256)
        return buf.value in _CONSOLE_CLASSES
    except Exception:  # not Windows
        return False


def get_selected_text(args: dict) -> str:
    """Copy whatever is selected in the active window (Ctrl+C) and return it. Keeps the old clipboard (text only)."""
    import time

    if _foreground_is_console():
        return "I can't read the selection in a terminal window."

    import pyautogui
    import pyperclip

    old = pyperclip.paste()
    pyperclip.copy("")
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.3)
    text = (pyperclip.paste() or "").strip()
    pyperclip.copy(old)
    return text[:20000] if text else "Nothing is selected."


def capture_screen_png(max_side: int = 1568) -> bytes:
    """Screenshot of the whole screen as PNG bytes, shrunk so the AI can read it fast."""
    import io

    import pyautogui

    img = pyautogui.screenshot()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
