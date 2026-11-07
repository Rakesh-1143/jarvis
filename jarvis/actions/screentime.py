"""Screen time: how long each app was used, and app limits (piece AD).

A background thread checks the active window every 5 seconds and adds the time
to that app (process name, like "chrome") for today. Time is not counted when
there was no mouse/keyboard input for 2 minutes (idle), or when the screen is locked.

Limits: "warn me after 1 hour of YouTube". A limit matches the process name OR the
window title (so "youtube" works inside any browser). Jarvis speaks once per day
when a limit is reached.

Wiring:
- main.py: call `screentime.start(io.say)` once at start (`screentime.stop()` on exit saves the file).
- intents `screen_time {app?, period?: today|week}` (info) and `app_limit {app, minutes}`.

Config (all optional), in config.yaml:
    screentime_file: "~/.jarvis/screen time.json"
    screentime:
      enabled: true      # track at start
      interval: 5        # seconds between checks
      idle_minutes: 2    # no input this long = not counted
      keep_days: 60      # older days are deleted from the file
    app_limits:          # minutes per day
      youtube: 60
      chrome: 120
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from typing import Callable

DEFAULT_FILE = "~/.jarvis/screen time.json"
DEFAULTS: dict = {"enabled": True, "interval": 5, "idle_minutes": 2, "keep_days": 60}
SAVE_EVERY = 60.0  # seconds between file writes

# process name -> friendly spoken name
_FRIENDLY = {
    "msedge": "edge", "winword": "word", "excel": "excel", "powerpnt": "powerpoint",
    "code": "vs code", "explorer": "file explorer", "windowsterminal": "terminal",
    "applicationframehost": "windows app", "wwahost": "windows app", "acrord32": "acrobat",
    "notepad++": "notepad plus plus", "teams": "teams", "ms-teams": "teams",
}
# spoken name -> process name (the reverse, plus common extra words)
_ALIASES = {v: k for k, v in _FRIENDLY.items()}
_ALIASES.update({
    "google chrome": "chrome", "microsoft edge": "msedge", "visual studio code": "code",
    "vscode": "code", "microsoft word": "winword", "powerpoint": "powerpnt",
    "file manager": "explorer", "files": "explorer", "teams": "ms-teams",
})
# not real apps: the desktop, lock screen, task switcher
_SKIP = {"", "lockapp", "logonui", "searchhost", "shellexperiencehost", "startmenuexperiencehost",
         "screenclippinghost", "idle"}

_lock = threading.RLock()
_data: dict | None = None        # {"days": {date: {"apps": {proc: secs}, "limits": {key: secs}, "warned": [key]}},
                                 #  "limits": {key: minutes}}   (limits set by voice)
_settings: dict = dict(DEFAULTS)
_config_limits: dict[str, float] = {}
_on = True
_thread: threading.Thread | None = None
_stop = threading.Event()
_last_save = 0.0
SCREENTIME_FILE: str | None = None  # tests can set this


# ---------- config + storage ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        return load_config() or {}
    except Exception:
        return {}


def settings(cfg: dict | None = None) -> dict:
    cfg = _cfg() if cfg is None else cfg
    user = cfg.get("screentime") or {}
    return {**DEFAULTS, **(user if isinstance(user, dict) else {})}


def _limits_from(cfg: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    raw = cfg.get("app_limits") or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                if float(v) > 0:
                    out[norm(str(k))] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def _path() -> str:
    global SCREENTIME_FILE
    if not SCREENTIME_FILE:
        SCREENTIME_FILE = _cfg().get("screentime_file") or DEFAULT_FILE
    return os.path.expanduser(SCREENTIME_FILE)


def _load() -> dict:
    global _data
    with _lock:
        if _data is None:
            try:
                with open(_path(), encoding="utf-8") as f:
                    d = json.load(f)
                if not isinstance(d, dict):
                    raise ValueError
            except (OSError, ValueError):
                d = {}
            d.setdefault("days", {})
            d.setdefault("limits", {})
            _data = d
        return _data


def save() -> bool:
    """Write the data file (old days are dropped). Returns False on error."""
    global _last_save
    with _lock:
        d = _load()
        keep = int(_settings.get("keep_days") or 60)
        cutoff = (_dt.date.today() - _dt.timedelta(days=keep)).isoformat()
        for day in [k for k in d["days"] if k < cutoff]:
            del d["days"][day]
        path = _path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, path)
        except OSError:
            return False
        _last_save = _now_ts()
        return True


def reset() -> None:
    """Forget everything in memory (tests)."""
    global _data, _config_limits, _on, _last_save, SCREENTIME_FILE
    with _lock:
        _data = None
        _config_limits = {}
        _on = True
        _last_save = 0.0
        SCREENTIME_FILE = None


def _now_ts() -> float:
    import time

    return time.time()


# ---------- names ----------
def norm(name: str) -> str:
    """'Chrome.exe' -> 'chrome', 'Google Chrome' -> 'chrome', 'VS Code' -> 'code'."""
    n = str(name or "").strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    n = n.strip(" .")
    return _ALIASES.get(n, n)


def friendly(proc: str) -> str:
    return _FRIENDLY.get(proc, proc)


def _all_limits() -> dict[str, float]:
    with _lock:
        return {**_config_limits, **{k: float(v) for k, v in _load()["limits"].items()}}


# ---------- counting ----------
def _day(date: str) -> dict:
    d = _load()["days"].setdefault(date, {})
    d.setdefault("apps", {})
    d.setdefault("limits", {})
    d.setdefault("warned", [])
    return d


def tick(proc: str, title: str, idle_s: float, dt: float, date: str | None = None) -> list[str]:
    """Add `dt` seconds of use to the active app. Returns warnings to speak (limits just reached)."""
    proc = norm(proc)
    if idle_s >= float(_settings.get("idle_minutes") or 2) * 60 or proc in _SKIP or dt <= 0:
        return []
    dt = min(dt, 60.0)  # after sleep/hibernate the gap can be huge; never count it
    date = date or _dt.date.today().isoformat()
    title_l = str(title or "").lower()
    out: list[str] = []
    with _lock:
        day = _day(date)
        day["apps"][proc] = day["apps"].get(proc, 0.0) + dt
        for key, minutes in _all_limits().items():
            if key == proc or (key and key in title_l):
                used = day["limits"].get(key, 0.0) + dt
                day["limits"][key] = used
                if used >= minutes * 60 and key not in day["warned"]:
                    day["warned"].append(key)
                    out.append(f"You have used {friendly(key)} for {_fmt(used)} today. "
                               f"That is your limit of {_fmt(minutes * 60)}.")
    return out


def _fmt(secs: float) -> str:
    m = int(round(secs / 60))
    if m < 1:
        return "less than a minute"
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    return " and ".join(parts)


# ---------- reading the laptop (Windows) ----------
def probe() -> tuple[str, str, float]:
    """(process name, window title, idle seconds) of the active window. Windows only."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    idle = 0.0
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        idle = ((kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", "", idle
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proc = ""
    try:
        import psutil

        proc = psutil.Process(pid.value).name()
    except Exception:
        pass
    return proc, buf.value, idle


def _loop(say: Callable[[str], None], get: Callable[[], tuple[str, str, float]]) -> None:
    import time

    last = time.monotonic()
    interval = max(1.0, float(_settings.get("interval") or 5))
    while not _stop.wait(interval):
        now = time.monotonic()
        dt, last = now - last, now
        try:
            if _on:
                proc, title, idle = get()
                for msg in tick(proc, title, idle, dt):
                    say(msg)
            if _now_ts() - _last_save >= SAVE_EVERY:
                save()
        except Exception:
            pass  # never crash Jarvis because of screen time


def start(say: Callable[[str], None], cfg: dict | None = None,
          get: Callable[[], tuple[str, str, float]] | None = None) -> threading.Thread | None:
    """Start the tracking thread once. Returns None when not on Windows (and no `get` given)."""
    global _thread, _settings, _config_limits, _on, _last_save
    if _thread is not None and _thread.is_alive():
        return _thread
    cfg = _cfg() if cfg is None else cfg
    _settings = settings(cfg)
    _config_limits = _limits_from(cfg)
    _on = bool(_settings.get("enabled", True))
    if get is None:
        if os.name != "nt":
            return None
        get = probe
    _load()
    _last_save = _now_ts()
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(say, get), name="jarvis-screentime", daemon=True)
    _thread.start()
    return _thread


def stop() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
        save()
    _thread = None


# ---------- reports ----------
def _days(period: str, today: _dt.date | None = None) -> list[str]:
    today = today or _dt.date.today()
    n = 7 if period == "week" else 1
    return [(today - _dt.timedelta(days=i)).isoformat() for i in range(n)]


def usage(period: str = "today", today: _dt.date | None = None) -> tuple[dict[str, float], dict[str, float]]:
    """(seconds per app, seconds per limit key) summed over the period."""
    apps: dict[str, float] = {}
    lims: dict[str, float] = {}
    with _lock:
        days = _load()["days"]
        for date in _days(period, today):
            d = days.get(date) or {}
            for k, v in (d.get("apps") or {}).items():
                apps[k] = apps.get(k, 0.0) + float(v)
            for k, v in (d.get("limits") or {}).items():
                lims[k] = lims.get(k, 0.0) + float(v)
    return apps, lims


def screen_time(args: dict) -> str:
    """'how long did I use Chrome today', 'my screen time this week', 'top apps today'."""
    period = "week" if str(args.get("period") or "").lower() in ("week", "this week", "7 days") else "today"
    when = "this week" if period == "week" else "today"
    apps, lims = usage(period, args.get("_today"))
    app = norm(args.get("app") or "")
    if app:
        if app in apps:
            secs = apps[app]
        elif app in lims:
            secs = lims[app]
        else:
            hits = [k for k in apps if app in k]
            if not hits:
                if not apps:
                    return f"I have no screen time for {when} yet."
                return f"You did not use {app} {when}."
            secs = sum(apps[k] for k in hits)
        msg = f"You used {friendly(app)} for {_fmt(secs)} {when}."
        lim = _all_limits().get(app)
        if lim and period == "today":
            left = lim * 60 - secs
            msg += (f" Your limit is {_fmt(lim * 60)}, {_fmt(left)} left." if left > 0
                    else f" That is over your limit of {_fmt(lim * 60)}.")
        return msg
    total = sum(apps.values())
    if total < 60:
        return f"I have no screen time for {when} yet." + ("" if _on else " Tracking is off.")
    top = sorted(apps.items(), key=lambda kv: -kv[1])[:3]
    tops = ", ".join(f"{friendly(k)} {_fmt(v)}" for k, v in top if v >= 60)
    avg = f" That is about {_fmt(total / 7)} a day." if period == "week" else ""
    return f"Screen time {when}: {_fmt(total)}.{avg} Top apps: {tops}."


def app_limit(args: dict) -> str:
    """'warn me after 1 hour of YouTube', 'remove the Chrome limit', 'what are my app limits'."""
    app = norm(args.get("app") or "")
    if not app:
        lim = _all_limits()
        if not lim:
            return "You have no app limits. Say, for example, warn me after 1 hour of YouTube."
        return "Your daily limits: " + ", ".join(f"{friendly(k)} {_fmt(v * 60)}" for k, v in sorted(lim.items())) + "."
    raw = args.get("minutes")
    try:
        minutes = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        minutes = None
    if minutes is None:
        cur = _all_limits().get(app)
        return (f"Your {friendly(app)} limit is {_fmt(cur * 60)} a day." if cur
                else f"How many minutes a day for {friendly(app)}?")
    with _lock:
        d = _load()
        today = _dt.date.today().isoformat()
        if minutes <= 0:
            had = app in d["limits"] or app in _config_limits
            d["limits"].pop(app, None)
            _config_limits.pop(app, None)  # per session; config.yaml limit comes back on restart
            save()
            return f"Removed the {friendly(app)} limit." if had else f"There was no {friendly(app)} limit."
        minutes = min(minutes, 24 * 60)
        d["limits"][app] = minutes
        day = _day(today)
        if app in day["warned"]:
            day["warned"].remove(app)  # new limit: may warn again today
        save()
    return f"Okay. I will warn you after {_fmt(minutes * 60)} of {friendly(app)} each day."


def tracking(on: bool) -> None:
    """Pause or resume counting (not a voice intent; for tests or a future toggle)."""
    global _on
    _on = bool(on)


# ---------- for the AI brain ----------
CATALOG: dict[str, dict] = {
    "screen_time": {
        "description": "Say how long the user used the laptop or one app (today or this week), "
                       "and the top apps. Leave out app for the total.",
        "properties": {
            "app": {"type": "string", "description": "App or site name, lower case, e.g. chrome, youtube."},
            "period": {"type": "string", "enum": ["today", "week"], "description": "Default today."},
        },
        "required": [],
        "info": True,
    },
    "app_limit": {
        "description": "Set a daily time limit for an app or site; Jarvis warns once when it is reached. "
                       "minutes 0 removes the limit. Leave out app to list the limits.",
        "properties": {
            "app": {"type": "string", "description": "App or site name, lower case, e.g. youtube, chrome."},
            "minutes": {"type": "integer", "description": "Minutes per day. 0 = remove."},
        },
        "required": [],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"screen_time": screen_time, "app_limit": app_limit}
