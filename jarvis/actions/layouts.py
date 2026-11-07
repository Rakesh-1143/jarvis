"""Save and restore window layouts (piece AH).

"save this layout as coding"  -> remembers every open window: program, title, position, size, state.
"restore coding layout"       -> starts missing programs, waits up to 10 s, moves windows back.
"list layouts", "delete layout coding" (delete asks to confirm).

Intent: layout {action: save|restore|list|delete, name?}

Settings (optional) in config.yaml:
  layouts:
    file: ~/.jarvis-layouts.json
    wait_seconds: 10      # how long restore waits for started programs
    start_missing: true   # false = only move windows that are already open

Windows only (plain ctypes, no extra packages). On other systems it says so.
Tests swap `_backend` for a fake.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

DEFAULTS = {"file": "~/.jarvis-layouts.json", "wait_seconds": 10, "start_missing": True}
DEFAULT_NAME = "default"
POLL = 0.5
MAX_NAME = 40

# Windows that are part of Windows itself, never saved.
_SKIP_EXES = {
    "textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe", "searchapp.exe",
    "startmenuexperiencehost.exe", "lockapp.exe", "systemsettingsbroker.exe",
}
_SKIP_TITLES = {"program manager", "windows input experience"}
# Programs that host other apps: we can move their windows but starting the exe does nothing useful.
_NO_START = {"applicationframehost.exe", "explorer.exe"}

_lock = threading.Lock()
_sleep = time.sleep
_now = time.monotonic


# ---------------- settings and storage ----------------

def settings(cfg: dict | None = None) -> dict:
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config()
        except Exception:
            cfg = {}
    user = (cfg or {}).get("layouts") or {}
    return {**DEFAULTS, **(user if isinstance(user, dict) else {})}


def _file() -> Path:
    return Path(os.path.expanduser(str(settings().get("file") or DEFAULTS["file"])))


def _load() -> dict:
    try:
        with open(_file(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def clean_name(name) -> str:
    """'the Coding layout' -> 'coding'. Empty -> ''."""
    s = str(name or "").lower()
    s = re.sub(r"[^a-z0-9 _-]+", " ", s)
    words = [w for w in s.split() if w not in ("the", "my", "a", "layout", "layouts", "window", "windows",
                                                "workspace", "setup", "called", "named", "as")]
    return " ".join(words)[:MAX_NAME].strip()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _exe_key(exe: str) -> str:
    return re.split(r"[\\/]", str(exe or ""))[-1].lower()  # works for Windows paths on any OS


# ---------------- Windows backend (ctypes) ----------------

class _WinBackend:
    """Real Windows calls. Each window: {hwnd, pid, exe, title, rect: [l, t, r, b], state}."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ct, self.wt = ctypes, wintypes
        self.user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        try:
            self.dwm = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        except Exception:
            self.dwm = None
        try:
            self.user32.SetProcessDPIAware()  # real pixels, so saved and restored numbers match
        except Exception:
            pass

        class WINDOWPLACEMENT(ctypes.Structure):
            _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                        ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                        ("rcNormalPosition", wintypes.RECT)]

        self.WINDOWPLACEMENT = WINDOWPLACEMENT

    def _cloaked(self, hwnd) -> bool:
        if not self.dwm:
            return False
        val = self.wt.DWORD(0)
        try:
            ok = self.dwm.DwmGetWindowAttribute(hwnd, 14, self.ct.byref(val), self.ct.sizeof(val))  # DWMWA_CLOAKED
            return ok == 0 and val.value != 0
        except Exception:
            return False

    def _exe(self, pid: int) -> str:
        try:
            import psutil

            p = psutil.Process(pid)
            try:
                return p.exe()
            except Exception:
                return p.name()
        except Exception:
            return ""

    def list_windows(self) -> list[dict]:
        ct, wt, u = self.ct, self.wt, self.user32
        hwnds: list[int] = []
        proc = ct.WINFUNCTYPE(ct.c_bool, wt.HWND, wt.LPARAM)(lambda h, _l: hwnds.append(h) or True)
        u.EnumWindows(proc, 0)
        out = []
        for h in hwnds:
            if not u.IsWindowVisible(h) or u.GetWindow(h, 4):  # GW_OWNER: skip dialogs/popups
                continue
            if u.GetWindowLongW(h, -20) & 0x80:  # GWL_EXSTYLE & WS_EX_TOOLWINDOW
                continue
            n = u.GetWindowTextLengthW(h)
            if n <= 0 or self._cloaked(h):
                continue
            buf = ct.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            pid = wt.DWORD(0)
            u.GetWindowThreadProcessId(h, ct.byref(pid))
            if u.IsIconic(h):
                wp = self.WINDOWPLACEMENT()
                wp.length = ct.sizeof(wp)
                u.GetWindowPlacement(h, ct.byref(wp))
                r = wp.rcNormalPosition
                state = "minimized"
            else:
                r = wt.RECT()
                u.GetWindowRect(h, ct.byref(r))
                state = "maximized" if u.IsZoomed(h) else "normal"
            out.append({"hwnd": h, "pid": pid.value, "exe": self._exe(pid.value), "title": buf.value,
                        "rect": [r.left, r.top, r.right, r.bottom], "state": state})
        return out

    def on_screen(self, rect) -> bool:
        r = self.wt.RECT(*rect)
        return bool(self.user32.MonitorFromRect(self.ct.byref(r), 0))  # MONITOR_DEFAULTTONULL

    def place(self, hwnd, rect, state: str) -> bool:
        u = self.user32
        l, t, r, b = (int(x) for x in rect)
        w, h = max(100, r - l), max(60, b - t)
        if state == "minimized":
            wp = self.WINDOWPLACEMENT()
            wp.length = self.ct.sizeof(wp)
            u.GetWindowPlacement(hwnd, self.ct.byref(wp))
            wp.showCmd = 7  # SW_SHOWMINNOACTIVE
            wp.rcNormalPosition = self.wt.RECT(l, t, l + w, t + h)
            return bool(u.SetWindowPlacement(hwnd, self.ct.byref(wp)))
        if u.IsIconic(hwnd) or u.IsZoomed(hwnd):
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
        if state == "maximized":
            # Put a smaller window on the right screen first, then maximize it there.
            dx, dy = w // 8, h // 8
            ok = u.SetWindowPos(hwnd, 0, l + dx, t + dy, w - 2 * dx, h - 2 * dy, 0x0014)
            u.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return bool(ok)
        return bool(u.SetWindowPos(hwnd, 0, l, t, w, h, 0x0014))  # SWP_NOZORDER | SWP_NOACTIVATE

    def start(self, exe: str) -> bool:
        try:
            os.startfile(exe)  # type: ignore[attr-defined]  # Windows only
            return True
        except Exception:
            return False


_backend = None


def _get_backend():
    global _backend
    if _backend is None and sys.platform == "win32":
        try:
            _backend = _WinBackend()
        except Exception:
            _backend = None
    return _backend


def _windows(be) -> list[dict]:
    """Open app windows worth saving (not Windows itself, not Jarvis)."""
    me = os.getpid()
    out = []
    for w in be.list_windows():
        title = str(w.get("title") or "").strip()
        if not title or title.lower() in _SKIP_TITLES:
            continue
        if _exe_key(w.get("exe")) in _SKIP_EXES or w.get("pid") == me:
            continue
        out.append(w)
    return out


# ---------------- matching ----------------

def _score(saved: dict, cur: dict) -> int:
    """How well an open window matches a saved one (0 = not the same program)."""
    if _exe_key(saved.get("exe")) != _exe_key(cur.get("exe")):
        return 0
    a, b = str(saved.get("title") or "").lower(), str(cur.get("title") or "").lower()
    if a == b:
        return 100
    wa, wb = set(re.findall(r"\w+", a)), set(re.findall(r"\w+", b))
    return 1 + len(wa & wb)


def _match(saved: list[dict], current: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair each saved window with one open window (best title match first)."""
    pairs = sorted(((_score(s, c), i, j) for i, s in enumerate(saved) for j, c in enumerate(current)),
                   key=lambda x: -x[0])
    got: dict[int, dict] = {}
    used: set[int] = set()
    for score, i, j in pairs:
        if score and i not in got and j not in used:
            got[i] = current[j]
            used.add(j)
    return [(s, got.get(i)) for i, s in enumerate(saved)]


# ---------------- actions ----------------

def _not_windows() -> str:
    return "Window layouts only work on Windows."


def save(name: str) -> str:
    be = _get_backend()
    if be is None:
        return _not_windows()
    try:
        wins = _windows(be)
    except Exception:
        return "Sorry, I couldn't read the open windows."
    if not wins:
        return "There are no open windows to save."
    name = name or DEFAULT_NAME
    entry = [{"exe": w.get("exe") or "", "title": w.get("title") or "",
              "rect": [int(x) for x in w.get("rect") or [0, 0, 0, 0]], "state": w.get("state") or "normal"}
             for w in wins]
    with _lock:
        data = _load()
        existed = name in data
        data[name] = {"saved": time.strftime("%Y-%m-%d %H:%M"), "windows": entry}
        try:
            _save(data)
        except OSError:
            return "Sorry, I couldn't save the layout file."
    verb = "Updated" if existed else "Saved"
    return f"{verb} the {name} layout with {_plural(len(entry), 'window')}."


def _pick_name(name: str, data: dict) -> str | None:
    if name:
        return name if name in data else None
    if len(data) == 1:
        return next(iter(data))
    return DEFAULT_NAME if DEFAULT_NAME in data else None


def restore(name: str) -> str:
    be = _get_backend()
    if be is None:
        return _not_windows()
    with _lock:
        data = _load()
    if not data:
        return "You have no saved layouts. Say 'save this layout as' and a name."
    real = _pick_name(name, data)
    if real is None:
        if name:
            return f"I don't have a layout called {name}. You have: {', '.join(sorted(data))}."
        return f"Which layout? You have: {', '.join(sorted(data))}."
    saved = [w for w in (data[real].get("windows") or []) if isinstance(w, dict)]
    if not saved:
        return f"The {real} layout is empty."
    s = settings()
    try:
        pairs = _match(saved, _windows(be))
    except Exception:
        return "Sorry, I couldn't read the open windows."

    # Start programs that have no open window (once per program).
    not_started: list[str] = []
    started: set[str] = set()
    if s.get("start_missing", True):
        for sw, cur in pairs:
            exe = str(sw.get("exe") or "")
            key = _exe_key(exe)
            if cur is not None or not key or key in started or key in _NO_START:
                continue
            if not (key.endswith(".exe") and os.path.isabs(exe) and os.path.isfile(exe) and be.start(exe)):
                not_started.append(os.path.splitext(key)[0])
                continue
            started.add(key)

    if started:
        try:
            wait = max(0.0, float(s.get("wait_seconds", DEFAULTS["wait_seconds"])))
        except (TypeError, ValueError):
            wait = float(DEFAULTS["wait_seconds"])
        end = _now() + wait
        while True:
            try:
                pairs = _match(saved, _windows(be))
            except Exception:
                break
            missing = {_exe_key(sw.get("exe")) for sw, cur in pairs if cur is None} & started
            if not missing or _now() >= end:
                break
            _sleep(POLL)

    moved = off = failed = 0
    missing_names: list[str] = []
    for sw, cur in pairs:
        if cur is None:
            nm = os.path.splitext(_exe_key(sw.get("exe")))[0] or "a window"
            if nm not in missing_names and nm not in not_started:
                missing_names.append(nm)
            continue
        rect = list(sw.get("rect") or [])
        if len(rect) != 4:
            failed += 1
            continue
        try:
            if not be.on_screen(rect):  # that screen is unplugged: keep size, put on main screen
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                rect = [50, 50, 50 + w, 50 + h]
                off += 1
            ok = be.place(cur.get("hwnd"), rect, str(sw.get("state") or "normal"))
        except Exception:
            ok = False
        if ok:
            moved += 1
        else:
            failed += 1

    parts = [f"Restored the {real} layout: moved {_plural(moved, 'window')}."]
    if off:
        parts.append(f"{_plural(off, 'window')} went to the main screen because the other screen is missing.")
    if failed:
        parts.append(f"I couldn't move {_plural(failed, 'window')}; it may be running as admin.")
    if not_started:
        parts.append(f"I couldn't start {', '.join(not_started[:3])}.")
    if missing_names:
        parts.append(f"Still not open: {', '.join(missing_names[:3])}.")
    return " ".join(parts)


def list_layouts() -> str:
    with _lock:
        data = _load()
    if not data:
        return "You have no saved layouts."
    parts = [f"{n} ({_plural(len(v.get('windows') or []), 'window')})" for n, v in sorted(data.items())]
    return "Your layouts: " + ", ".join(parts) + "."


def delete(name: str, confirm: bool = False) -> str:
    with _lock:
        data = _load()
        if not name:
            if not data:
                return "You have no saved layouts."
            return f"Which layout should I delete? You have: {', '.join(sorted(data))}."
        if name not in data:
            return f"I don't have a layout called {name}."
        if not confirm:
            return f"Are you sure you want to delete the {name} layout?"
        del data[name]
        try:
            _save(data)
        except OSError:
            return "Sorry, I couldn't update the layout file."
    return f"Deleted the {name} layout."


# ---------------- intent glue ----------------

_ACTIONS = {"save": "save", "store": "save", "remember": "save", "restore": "restore", "load": "restore",
            "open": "restore", "apply": "restore", "list": "list", "show": "list", "delete": "delete",
            "remove": "delete", "forget": "delete"}


def _action(args: dict) -> str:
    return _ACTIONS.get(str((args or {}).get("action") or "").lower().strip(), "")


def layout(args: dict) -> str:
    args = args or {}
    act = _action(args)
    name = clean_name(args.get("name"))
    if act == "save":
        return save(name)
    if act == "restore":
        return restore(name)
    if act == "list":
        return list_layouts()
    if act == "delete":
        return delete(name, confirm=args.get("confirm") is True)
    return "I can save, restore, list or delete window layouts."


def needs_confirm(args: dict) -> bool:
    """Only delete of an existing layout asks first."""
    if _action(args) != "delete":
        return False
    name = clean_name((args or {}).get("name"))
    return bool(name) and name in _load()


def risky_text(args: dict) -> str | None:
    """Words for 'are you sure you want to ...?' (delete only), else None."""
    if not needs_confirm(args):
        return None
    return f"delete the {clean_name(args.get('name'))} window layout"


CATALOG: dict[str, dict] = {
    "layout": {
        "description": ("Save, restore, list or delete named window layouts (which programs are open and where "
                        "their windows are). Restore starts missing programs and moves windows back. "
                        "Delete asks the user to confirm."),
        "properties": {
            "action": {"type": "string", "enum": ["save", "restore", "list", "delete"]},
            "name": {"type": "string", "description": "Layout name, e.g. coding, study, meeting. Default 'default'."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"layout": layout}
