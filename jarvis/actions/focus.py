"""Focus (Pomodoro) sessions and Do Not Disturb.

"start focus for 25 minutes" -> work / break rounds, spoken at each change.
"stop focus", "how long left". "turn on do not disturb" / "turn it off".

Settings (optional) in config.yaml:
  focus:
    work: 25          # minutes of work per round
    short_break: 5
    long_break: 15
    long_every: 4     # every 4th break is long
    rounds: 4         # rounds before the session ends (0 = until "stop focus")
    dnd: true         # turn on Do Not Disturb while focusing

Do Not Disturb is best effort (Windows only): it sets the Windows "quiet hours"
state and turns off notification banners in the registry. If both fail, it
opens the notification settings page so the user can switch it by hand.

Wiring: set `focus.notify = io.say` (or call set_notifier). After a "start"
reply, main can call take_routine() and run that routine if it is not empty.
"""
from __future__ import annotations

import os
import threading
import time

# Called with the text to announce. Core sets it (like timers.notify).
notify = print
TICK = 0.5

DEFAULTS = {"work": 25, "short_break": 5, "long_break": 15, "long_every": 4, "rounds": 4, "dnd": True}

_lock = threading.Lock()
_session: dict | None = None  # {"phase", "ends", "round", "work", "settings"}
_thread: threading.Thread | None = None
_routine = ""
_dnd_on = False          # what we last set
_dnd_by_focus = False    # True = focus turned DND on, so focus turns it off again
_saved_toasts: int | None = None  # registry value before we changed it

# Windows "quiet hours" state (WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED).
# Data: 0 = off, 1 = priority only, 2 = alarms only.
_WNF_QUIET_HOURS = 0x0D83063EA3BF1C75
_TOASTS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
_TOASTS_VALUE = "NOC_GLOBAL_SETTING_TOASTS_ENABLED"
# The banner setting from before DND, kept on disk so a crash during focus can't leave banners off forever.
SAVED_FILE = os.path.join(os.path.expanduser("~"), ".jarvis-dnd-saved")


def set_notifier(fn) -> None:
    global notify
    notify = fn
    restore_after_crash()  # main calls this once at start


def _write_saved(value: int | None) -> None:
    try:
        if value is None:
            if os.path.exists(SAVED_FILE):
                os.remove(SAVED_FILE)
        else:
            with open(SAVED_FILE, "w", encoding="utf-8") as f:
                f.write(str(value))
    except OSError:
        pass


def restore_after_crash() -> bool:
    """If Jarvis stopped while DND was on, put notification banners back. True if something was restored."""
    global _saved_toasts
    try:
        with open(SAVED_FILE, encoding="utf-8") as f:
            value = int(f.read().strip())
    except (OSError, ValueError):
        return False
    _saved_toasts = value
    ok = _registry_toasts(False)
    if ok:
        _write_saved(None)
    return ok


def _settings() -> dict:
    out = dict(DEFAULTS)
    try:
        from jarvis.config import load_config

        out.update((load_config().get("focus") or {}))
    except Exception:
        pass
    return out


def _routines() -> dict:
    try:
        from jarvis.config import load_config

        return load_config().get("routines") or {}
    except Exception:
        return {}


def _mins(seconds: float) -> str:
    m = max(1, int(round(seconds / 60)))
    return f"{m} minute{'s' if m != 1 else ''}"


def _say(text: str) -> None:
    try:
        notify(text)
    except Exception:
        pass


# ---------------- Do Not Disturb (Windows, best effort) ----------------

def _wnf_quiet_hours(on: bool) -> bool:
    try:
        import ctypes

        ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]  # Windows only
        name = ctypes.c_ulonglong(_WNF_QUIET_HOURS)
        data = ctypes.c_uint32(2 if on else 0)
        status = ntdll.NtUpdateWnfStateData(ctypes.byref(name), ctypes.byref(data), ctypes.sizeof(data),
                                            None, None, 0, 0)
        return status == 0
    except Exception:
        return False


def _registry_toasts(on: bool) -> bool:
    """Turn notification banners off (DND on) or back to how they were."""
    global _saved_toasts
    try:
        import winreg  # Windows only

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _TOASTS_KEY, 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            if on:
                if _saved_toasts is None:
                    try:
                        _saved_toasts = int(winreg.QueryValueEx(key, _TOASTS_VALUE)[0])
                    except OSError:
                        _saved_toasts = 1
                    _write_saved(_saved_toasts)
                value = 0
            else:
                value = 1 if _saved_toasts is None else _saved_toasts
                _saved_toasts = None
            winreg.SetValueEx(key, _TOASTS_VALUE, 0, winreg.REG_DWORD, value)
        if not on:
            _write_saved(None)
        return True
    except Exception:
        return False


def _open_settings() -> bool:
    try:
        os.startfile("ms-settings:notifications")  # type: ignore[attr-defined]  # Windows only
        return True
    except Exception:
        return False


def _set_dnd(on: bool) -> str:
    """Returns 'done', 'settings' (opened the page) or 'failed'."""
    global _dnd_on
    ok_wnf = _wnf_quiet_hours(on)
    ok_reg = _registry_toasts(on)
    if ok_wnf or ok_reg:
        _dnd_on = on
        return "done"
    return "settings" if _open_settings() else "failed"


def dnd(args: dict) -> str:
    global _dnd_by_focus
    state = str(args.get("state", "on")).lower()
    if state == "status":
        return "Do not disturb is on." if _dnd_on else "Do not disturb is off."
    on = state != "off"
    result = _set_dnd(on)
    _dnd_by_focus = False
    if result == "done":
        return "Do not disturb is on. Notifications are hidden." if on else "Do not disturb is off."
    if result == "settings":
        return f"I couldn't switch it myself, so I opened notification settings. Turn do not disturb {'on' if on else 'off'} there."
    return "Sorry, I couldn't change do not disturb on this computer."


# ---------------- Focus sessions ----------------

def _break_minutes(s: dict, round_no: int) -> float:
    every = int(s.get("long_every") or 0)
    return float(s["long_break"] if every and round_no % every == 0 else s["short_break"])


def _end_session() -> None:
    """Call with _lock held. Clears the session and undoes DND if focus set it."""
    global _session, _dnd_by_focus
    _session = None
    if _dnd_by_focus:
        _dnd_by_focus = False
        _set_dnd(False)


def _tick(now: float | None = None) -> None:
    """Move to the next phase when the current one is over."""
    global _session
    now = time.time() if now is None else now
    with _lock:
        s = _session
        if not s or now < s["ends"]:
            return
        cfg = s["settings"]
        if s["phase"] == "work":
            rounds = int(cfg.get("rounds") or 0)
            if rounds and s["round"] >= rounds:
                _end_session()
                n = s["round"]
                msg = f"Focus session done. You finished {n} round{'s' if n != 1 else ''}. Great work!"
            else:
                brk = _break_minutes(cfg, s["round"])
                s.update(phase="break", ends=now + brk * 60)
                msg = f"Time for a {_mins(brk * 60)} break."
        else:
            s.update(phase="work", ends=now + s["work"] * 60, round=s["round"] + 1)
            msg = f"Break is over. Focus round {s['round']} for {_mins(s['work'] * 60)}."
    _say(msg)  # outside the lock: speaking can take a while


def _loop() -> None:
    while True:
        time.sleep(TICK)
        with _lock:
            if _session is None:
                return
        _tick()


def _ensure_thread() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-focus", daemon=True)
        _thread.start()


def take_routine() -> str:
    """Name of the routine to run after focus starts ('' = none). Cleared after reading."""
    global _routine
    name, _routine = _routine, ""
    return name


def _start(args: dict) -> str:
    global _session, _routine, _dnd_by_focus
    cfg = _settings()
    try:
        m = args.get("minutes")
        work = float(cfg["work"] if m is None or m == "" else m)
    except (TypeError, ValueError):
        work = float(DEFAULTS["work"])
    if work <= 0:
        return "For how many minutes should I start focus?"
    with _lock:
        _session = {"phase": "work", "ends": time.time() + work * 60, "round": 1, "work": work, "settings": cfg}
    extra = ""
    if cfg.get("dnd") and not _dnd_on:
        if _set_dnd(True) == "done":
            _dnd_by_focus = True
            extra = " Do not disturb is on."
    _routine = "focus" if "focus" in _routines() else ""
    _ensure_thread()
    return f"Focus started for {_mins(work * 60)}. I'll tell you when it's break time.{extra}"


def _stop() -> str:
    with _lock:
        s = _session
        if not s:
            return "No focus session is running."
        done = s["round"] - (1 if s["phase"] == "work" else 0)
        _end_session()
    if done:
        return f"Focus stopped. You did {done} full round{'s' if done != 1 else ''}."
    return "Focus stopped."


def _status() -> str:
    with _lock:
        s = dict(_session) if _session else None
    if not s:
        return "No focus session is running."
    left = max(1, s["ends"] - time.time())
    if s["phase"] == "work":
        return f"{_mins(left)} left in focus round {s['round']}."
    return f"{_mins(left)} left in your break."


def focus(args: dict) -> str:
    action = str(args.get("action") or "start").lower()
    if action == "stop":
        return _stop()
    if action == "status":
        return _status()
    return _start(args)


def is_active() -> bool:
    return _session is not None


_ACTION = {"type": "string", "enum": ["start", "stop", "status"]}

CATALOG: dict[str, dict] = {
    "focus": {"description": "Pomodoro focus session: start (work/break rounds, spoken at each change), "
                             "stop, or status (how long is left).",
              "properties": {"action": _ACTION,
                             "minutes": {"description": "Work minutes per round (start only, default 25).",
                                         "type": "integer"}},
              "required": ["action"]},
    "dnd": {"description": "Turn Windows Do Not Disturb (hide notifications) on or off.",
            "properties": {"state": {"type": "string", "enum": ["on", "off"]}}, "required": ["state"]},
}

HANDLERS = {"focus": focus, "dnd": dnd}
