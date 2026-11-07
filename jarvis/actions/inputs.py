"""Mouse and keyboard control, and clicking buttons by their name (UI Automation).

Used by voice commands ("press control c", "scroll down", "click save")
and by the AI screen-control agent (jarvis/agent.py).
"""
from __future__ import annotations

import re
import time

# ---------- key names ----------
# spoken / xdotool-style name -> pyautogui key name
_KEYS = {
    "control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl", "alt": "alt", "shift": "shift",
    "windows": "win", "window": "win", "win": "win", "super": "win", "start": "win", "meta": "win", "cmd": "win",
    "enter": "enter", "return": "enter", "escape": "esc", "esc": "esc", "tab": "tab",
    "space": "space", "spacebar": "space", "space bar": "space",
    "backspace": "backspace", "back space": "backspace", "delete": "delete", "del": "delete", "insert": "insert",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "page up": "pageup", "pageup": "pageup", "prior": "pageup",
    "page down": "pagedown", "pagedown": "pagedown", "next": "pagedown",
    "caps lock": "capslock", "capslock": "capslock", "print screen": "printscreen", "printscreen": "printscreen",
    "print": "printscreen", "menu": "apps", "context menu": "apps",
    "minus": "-", "dash": "-", "hyphen": "-", "equals": "=", "equal": "=", "comma": ",", "period": ".",
    "dot": ".", "full stop": ".", "slash": "/", "backslash": "\\", "semicolon": ";", "quote": "'",
    "apostrophe": "'", "backtick": "`", "grave": "`",
    "volume up": "volumeup", "volume down": "volumedown", "volume mute": "volumemute", "mute": "volumemute",
}
# letters as Vosk often writes them
_LETTER_SOUNDS = {
    "see": "c", "sea": "c", "bee": "b", "be": "b", "dee": "d", "gee": "g", "jay": "j", "kay": "k",
    "pee": "p", "tea": "t", "tee": "t", "vee": "v", "why": "y", "ex": "x", "zed": "z", "zee": "z",
    "eye": "i", "oh": "o", "queue": "q", "cue": "q", "are": "r", "you": "u", "double you": "w",
    "ef": "f", "el": "l", "em": "m", "en": "n", "es": "s", "aitch": "h",
}
_NUMS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_MULTI = sorted([k for k in list(_KEYS) + list(_LETTER_SOUNDS) if " " in k], key=len, reverse=True)
_SKIP = {"key", "keys", "the", "and", "plus", "then", "button", "arrow", "together", "with"}


def parse_keys(text: str) -> list[str] | None:
    """'control shift t' / 'ctrl+s' / 'Return' / 'f five' -> ['ctrl', 'shift', 't']. None if a word is unknown."""
    t = text.lower().replace("+", " ").replace("_", " ").strip()
    t = re.sub(r"\s+", " ", t)
    for m in _MULTI:  # join multi-word names first
        t = re.sub(rf"\b{m}\b", m.replace(" ", "~"), t)
    words = [w.replace("~", " ") for w in t.split()]
    keys: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if w in _SKIP:
            continue
        if w in ("f", "ef") and i < len(words) and (words[i] in _NUMS or words[i].isdigit()):
            n = _NUMS[words[i]] if words[i] in _NUMS else int(words[i])  # "f zero" -> 0, not a crash
            i += 1
            if 1 <= n <= 12:
                keys.append(f"f{n}")
                continue
            return None
        if re.fullmatch(r"f([1-9]|1[0-2])", w):
            keys.append(w)
        elif w in _KEYS:
            keys.append(_KEYS[w])
        elif w in _LETTER_SOUNDS and len(words) > 1:  # "control see" -> ctrl c (only inside a combo)
            keys.append(_LETTER_SOUNDS[w])
        elif len(w) == 1:
            keys.append(w)
        elif w in _NUMS and _NUMS[w] < 10:
            keys.append(str(_NUMS[w]))
        else:
            return None
    return keys or None


def _int(value, default: int) -> int:
    """'3', 3 or 'three' -> 3. Anything else -> default (never raises)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return _NUMS.get(str(value).lower().strip(), default) or default


def _pg():
    import pyautogui

    return pyautogui


def press_keys(args: dict) -> str:
    """args: keys ('ctrl+c' or 'control c'), times (optional, 1-50)."""
    raw = str(args.get("keys") or "").strip()
    keys = parse_keys(raw)
    if not keys:
        return f"I don't know the key {raw}." if raw else "Which keys should I press?"
    times = max(1, min(50, _int(args.get("times"), 1)))
    pg = _pg()
    for _ in range(times):
        if len(keys) == 1:
            pg.press(keys[0])
        else:
            pg.hotkey(*keys)
        if times > 1:
            time.sleep(0.05)
    return "Done."


# ---------- mouse ----------
NOTCH = 120          # Windows wheel units per scroll "click"
_SCROLL = {"little": 3, "normal": 6, "lot": 15}
_MOVE = {"little": 40, "normal": 150, "lot": 400}


def _size(amount, table) -> int:
    if isinstance(amount, (int, float)) and amount > 0:
        return int(amount)
    a = str(amount or "").lower()
    if a.isdigit():
        return int(a)
    if "lot" in a or "more" in a or "far" in a:
        return table["lot"]
    if "little" in a or "bit" in a:
        return table["little"]
    return table["normal"]


def mouse(args: dict) -> str:
    """args: action click|double_click|right_click|middle_click|scroll|move|center, direction up|down|left|right, amount."""
    action = args.get("action", "click")
    direction = args.get("direction", "down")
    pg = _pg()
    if action in ("click", "left_click"):
        pg.click()
        return "Clicked."
    if action == "double_click":
        pg.doubleClick()
        return "Double clicked."
    if action == "right_click":
        pg.rightClick()
        return "Right clicked."
    if action == "middle_click":
        pg.middleClick()
        return "Middle clicked."
    if action == "scroll":
        n = _size(args.get("amount"), _SCROLL)
        if direction in ("left", "right"):
            pg.keyDown("shift")  # shift + wheel = sideways in most apps
            try:
                pg.scroll(n * NOTCH * (1 if direction == "left" else -1))
            finally:
                pg.keyUp("shift")
        else:
            pg.scroll(n * NOTCH * (1 if direction == "up" else -1))
        return f"Scrolled {direction}."
    if action == "move":
        n = _size(args.get("amount"), _MOVE)
        dx, dy = {"up": (0, -n), "down": (0, n), "left": (-n, 0), "right": (n, 0)}.get(direction, (0, 0))
        pg.moveRel(dx, dy, duration=0.15)
        return "Moved the mouse."
    if action == "center":
        w, h = pg.size()
        pg.moveTo(w // 2, h // 2, duration=0.15)
        return "Mouse is in the center."
    return "I can click, double click, right click, scroll or move the mouse."


# ---------- click a button / link by its name (UI Automation) ----------
_CLICKABLE = {"Button", "MenuItem", "Hyperlink", "TabItem", "ListItem", "CheckBox", "RadioButton",
              "TreeItem", "SplitButton", "ComboBox", "MenuBar", "DataItem"}
MAX_ELEMENTS = 3000


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def _score(want: str, name: str, ctype: str) -> int:
    n = _norm(name)
    if not n:
        return 0
    if n == want:
        s = 30
    elif n.startswith(want + " ") or n.startswith(want):
        s = 20
    elif re.search(rf"\b{re.escape(want)}\b", n):
        s = 10
    else:
        return 0
    return s + (5 if ctype in _CLICKABLE else 0) - min(len(n), 60) // 20


def find_element(text: str, elements) -> object | None:
    """Best match from (name, control_type, element) items. Separate for tests."""
    want = _norm(text)
    best, best_score = None, 0
    for name, ctype, el in elements:
        s = _score(want, name, ctype)
        if s > best_score:
            best, best_score = el, s
    return best


_SEARCH_TYPES = _CLICKABLE | {"Edit"}


class _Target:
    """Screen point of a found element. Plain data, so it can leave the helper thread safely."""

    def __init__(self, x: int, y: int):
        self.x, self.y = x, y

    def click_input(self, button: str = "left", double: bool = False) -> None:
        from pywinauto import mouse

        if double:
            mouse.double_click(button="left", coords=(self.x, self.y))
        else:
            mouse.click(button=button, coords=(self.x, self.y))


SEARCH_SECONDS = 5.0  # big windows (Chrome, Office) can have huge UI trees; never block the voice loop longer


def _collect_elements():
    import ctypes

    from pywinauto import Desktop

    try:
        import comtypes  # this runs in a helper thread, which needs its own COM start

        comtypes.CoInitialize()
    except Exception:
        pass
    hwnd = ctypes.windll.user32.GetForegroundWindow()  # type: ignore[attr-defined]
    if not hwnd:
        return []
    win = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
    out = []
    # Ask UI Automation only for clickable types (filtered search), not the whole tree.
    for ctype in sorted(_SEARCH_TYPES):
        try:
            found = win.descendants(control_type=ctype)
        except Exception:
            continue
        for el in found:
            if len(out) >= MAX_ELEMENTS:
                return out
            try:
                if el.is_visible():
                    r = el.rectangle()
                    out.append((el.window_text(), ctype, _Target((r.left + r.right) // 2, (r.top + r.bottom) // 2)))
            except Exception:
                continue
    return out


def _foreground_elements():
    """Clickable elements of the active window. Gives up after SEARCH_SECONDS (raises TimeoutError)."""
    import threading

    box: dict = {}

    def work():
        try:
            box["out"] = _collect_elements()
        except BaseException as e:  # passed back to the caller
            box["err"] = e

    t = threading.Thread(target=work, name="jarvis-click-search", daemon=True)
    t.start()
    t.join(SEARCH_SECONDS)
    if t.is_alive():
        raise TimeoutError("window search took too long")
    if "err" in box:
        raise box["err"]
    return box.get("out", [])


def click_text(args: dict) -> str:
    """Click a button, link, menu or tab in the active window by its visible name."""
    text = str(args.get("text") or "").strip()
    if not text:
        return "What should I click?"
    button = args.get("button", "left")
    try:
        elements = _foreground_elements()
    except ImportError:
        return "Clicking by name needs the pywinauto package. Run install.bat again."
    except TimeoutError:
        return "This window is too big to search quickly. Try a mouse command instead."
    el = find_element(text, elements)
    if el is None:
        return f"I couldn't find {text} on the screen."
    if button == "double":
        el.click_input(double=True)
    else:
        el.click_input(button="right" if button == "right" else "left")
    return f"Clicked {text}."
