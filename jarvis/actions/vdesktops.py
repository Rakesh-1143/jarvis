"""Virtual desktops (piece BK).

"new desktop", "next desktop", "previous desktop", "go to desktop 2",
"move this window to desktop 3", "which desktop am I on", "close this desktop".

Intent: vdesktop {action: new|next|previous|go|move_window|close|which, number?}

Uses `pyvda` when installed (exact desktop numbers, move window, which/count).
Without it, falls back to Windows hotkeys:
  Win+Ctrl+D (new), Win+Ctrl+Left/Right (switch), Win+Ctrl+F4 (close).
  "go to desktop N" sweeps left to desktop 1, then right N-1 times.
  "move window" and "which" need pyvda (the reply says so).
Closing a desktop needs no confirm: Windows moves its windows to another desktop.
Tests swap `_backend()` for a fake.
"""
from __future__ import annotations

import re
import sys

ACTIONS = ("new", "next", "previous", "go", "move_window", "close", "which")
_SYNONYMS = {
    "create": "new", "add": "new", "open": "new",
    "prev": "previous", "back": "previous", "left": "previous",
    "right": "next", "forward": "next",
    "switch": "go", "goto": "go", "go_to": "go",
    "move": "move_window", "send": "move_window", "send_window": "move_window",
    "delete": "close", "remove": "close",
    "current": "which", "where": "which", "count": "which", "list": "which",
}
_WORDS = {
    "one": 1, "first": 1, "two": 2, "second": 2, "to": 2, "too": 2, "three": 3, "third": 3,
    "four": 4, "fourth": 4, "for": 4, "five": 5, "fifth": 5, "six": 6, "sixth": 6,
    "seven": 7, "seventh": 7, "eight": 8, "eighth": 8, "nine": 9, "ninth": 9, "ten": 10, "tenth": 10,
}
MAX_SWEEP = 20  # hotkey fallback: Left presses to be sure we are on desktop 1
NEED_PYVDA = "I need the pyvda package for that. Install it with: pip install pyvda"


def _number(value) -> int | None:
    """2, "2", "two", "second", "desktop 3" -> int. "last" -> -1. Else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if n >= 1 else None
    text = str(value).strip().lower()
    if not text:
        return None
    if "last" in text:
        return -1
    m = re.search(r"\d+", text)
    if m:
        n = int(m.group())
        return n if n >= 1 else None
    for word in re.findall(r"[a-z]+", text):
        if word in _WORDS and word not in ("to", "too", "for"):
            return _WORDS[word]
    return _WORDS.get(text)


# ---------------- backends ----------------

class PyvdaBackend:
    """Exact control through pyvda (Windows 10/11)."""

    exact = True

    def __init__(self, mod):
        self.m = mod

    def count(self) -> int:
        return len(self.m.get_virtual_desktops())

    def current(self) -> int:
        return int(self.m.VirtualDesktop.current().number)

    def name(self, n: int) -> str:
        try:
            return str(self.m.VirtualDesktop(n).name or "")
        except Exception:  # older Windows builds have no names
            return ""

    def go(self, n: int) -> None:
        self.m.VirtualDesktop(n).go()

    def new(self) -> int:
        self.m.VirtualDesktop.create()
        n = self.count()
        self.go(n)
        return n

    def move_window(self, n: int) -> bool:
        view = self.m.AppView.current()
        if not view or not getattr(view, "hwnd", 0):
            return False
        view.move(self.m.VirtualDesktop(n))
        return True

    def close(self, n: int, fallback: int) -> None:
        self.m.VirtualDesktop(n).remove(fallback=self.m.VirtualDesktop(fallback))


class HotkeyBackend:
    """Fallback with Win+Ctrl shortcuts. Does not know numbers or counts."""

    exact = False

    def _keys(self, *keys) -> None:
        import pyautogui

        pyautogui.hotkey(*keys)

    def new(self) -> None:
        self._keys("win", "ctrl", "d")

    def step(self, direction: str) -> None:
        self._keys("win", "ctrl", direction)

    def go(self, n: int) -> None:
        import time

        for _ in range(MAX_SWEEP):
            self.step("left")
            time.sleep(0.05)
        for _ in range(n - 1):
            self.step("right")
            time.sleep(0.05)

    def close(self) -> None:
        self._keys("win", "ctrl", "f4")


def _backend():
    if sys.platform != "win32":
        return None
    try:
        import pyvda  # needs comtypes; may raise on unsupported Windows builds

        return PyvdaBackend(pyvda)
    except Exception:
        pass
    try:
        import pyautogui  # noqa: F401

        return HotkeyBackend()
    except Exception:
        return None


# ---------------- handler ----------------

def _label(b, n: int) -> str:
    name = b.name(n) if hasattr(b, "name") else ""
    return f"desktop {n}" + (f" ({name})" if name and name.lower() != f"desktop {n}" else "")


def vdesktop(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "").strip().lower().replace(" ", "_")
    action = _SYNONYMS.get(action, action)
    if action not in ACTIONS:
        return ("I can make a new desktop, go to the next or previous one, go to desktop 2, "
                "move this window to desktop 3, tell you which desktop you are on, or close this desktop.")
    number = _number(args.get("number"))
    if action in ("go", "move_window") and number is None:
        return "Which desktop number?"

    b = _backend()
    if b is None:
        return "Virtual desktops only work on Windows."

    try:
        if not b.exact:
            return _hotkeys(b, action, number)
        return _exact(b, action, number)
    except Exception as e:  # COM errors from pyvda on odd Windows builds
        return f"I couldn't change desktops: {e}"


def _hotkeys(b: HotkeyBackend, action: str, number: int | None) -> str:
    if action == "new":
        b.new()
        return "New desktop made."
    if action == "next":
        b.step("right")
        return "Next desktop."
    if action == "previous":
        b.step("left")
        return "Previous desktop."
    if action == "close":
        b.close()
        return "Closed this desktop. Its windows moved to the next one."
    if action == "go":
        if number == -1:
            b.step("right")  # no count without pyvda; sweep right instead
            for _ in range(MAX_SWEEP - 1):
                b.step("right")
            return "Going to the last desktop."
        b.go(number)
        return f"Going to desktop {number}."
    return NEED_PYVDA  # move_window, which


def _exact(b: PyvdaBackend, action: str, number: int | None) -> str:
    count = b.count()
    cur = b.current()
    if number == -1:
        number = count
    if action == "which":
        return f"You are on {_label(b, cur)} of {count}."
    if action == "new":
        n = b.new()
        return f"New desktop made. You are on desktop {n}."
    if action in ("next", "previous"):
        target = cur + (1 if action == "next" else -1)
        if target < 1:
            return "You are already on the first desktop."
        if target > count:
            return "You are already on the last desktop. Say 'new desktop' to add one."
        b.go(target)
        return f"Desktop {target}."
    if action == "close":
        if count <= 1:
            return "This is your only desktop, so I can't close it."
        fallback = cur + 1 if cur < count else cur - 1
        b.close(cur, fallback)
        # Numbers shift down after removal when the fallback was to the right.
        landed = fallback - 1 if fallback > cur else fallback
        return f"Closed desktop {cur}. Its windows moved to desktop {landed}, where you are now."
    if number > count:
        return f"You have only {count} desktop{'s' if count != 1 else ''}."
    if action == "go":
        if number == cur:
            return f"You are already on desktop {number}."
        b.go(number)
        return f"Desktop {number}."
    # move_window
    if number == cur:
        return f"This window is already on desktop {number}."
    if not b.move_window(number):
        return "There is no active window to move."
    return f"Moved this window to desktop {number}."


CATALOG: dict[str, dict] = {
    "vdesktop": {
        "description": ("Windows virtual desktops: make a new desktop, go to the next/previous one, go to desktop "
                        "N, move the active window to desktop N, say which desktop is active (and how many), or "
                        "close the current desktop (its windows move to another desktop, nothing is lost)."),
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "number": {"type": "integer", "description": "Desktop number, starting at 1. Needed for go and move_window."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"vdesktop": vdesktop}
