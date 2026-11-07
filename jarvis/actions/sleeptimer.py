"""Sleep timer for bedtime.

"stop the music in 30 minutes": near the end the master volume fades down
(FADE_SECONDS), then media is paused and the old volume level is put back.
"sleep the laptop in 1 hour" / "shut down in 2 hours": asks yes first (risky,
see risky_text), speaks a 1-minute warning, then sleeps / shuts down.
"cancel sleep timer", "how long is left on the sleep timer".

Only one sleep timer runs at a time; a new one replaces the old one.
The timer uses the wall clock, so it still works after the laptop wakes. If the
laptop was asleep long past the end time (LATE_SECONDS), the timer is dropped
instead of acting: shutting down right after the user opens the lid would be a
nasty surprise.

Wiring: main calls sleeptimer.set_notifier(io.say) once at start.
"""
from __future__ import annotations

import threading
import time

# Called with the text to announce. Core sets it with set_notifier().
notify = print
TICK = 0.5
FADE_SECONDS = 30
WARN_SECONDS = 60
LATE_SECONDS = 10 * 60
MAX_MINUTES = 24 * 60

ACTIONS = ("stop_media", "sleep", "shutdown")

_lock = threading.Lock()
# {"action", "ends", "minutes", "warned", "fade_from" (volume before fade or None)}
_timer: dict | None = None
_thread: threading.Thread | None = None


def set_notifier(fn) -> None:
    global notify
    notify = fn


def _say(text: str) -> None:
    try:
        notify(text)
    except Exception:
        pass


# ---------- system helpers (replaced in tests) ----------
def _get_volume() -> int:
    from . import system

    return system.get_volume()


def _set_volume(level: int) -> None:
    from . import system

    system.set_volume(level)


async def _pause_async() -> bool:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    mgr = await Manager.request_async()
    paused = False
    for s in mgr.get_sessions():
        try:
            if int(s.get_playback_info().playback_status) == 4:  # 4 = PLAYING
                await s.try_pause_async()
                paused = True
        except Exception:
            pass
    return paused


def _pause_media() -> None:
    """Pause every playing app (WinRT). Fallback: the media Stop key (never starts playback)."""
    try:
        import asyncio

        asyncio.run(_pause_async())
        return
    except Exception:
        pass
    try:
        from . import desktop

        desktop.media({"action": "stop"})
    except Exception:
        pass


def _do_sleep() -> None:
    from . import system

    system.sleep()


def _do_shutdown() -> None:
    from . import system

    system.shutdown()


# ---------- words ----------
def _spoken(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{max(seconds, 1)} second{'s' if seconds != 1 else ''}"
    minutes = (seconds + 59) // 60  # round up: "1 minute" left, not "0"
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    return " and ".join(parts)


def _what(action: str) -> str:
    return {"stop_media": "the music stops", "sleep": "the laptop goes to sleep",
            "shutdown": "the laptop shuts down"}[action]


def _parse(args: dict) -> tuple[str, float | None]:
    action = str(args.get("action") or "stop_media").lower().strip()
    action = {"stop": "stop_media", "music": "stop_media", "pause": "stop_media",
              "shut_down": "shutdown", "hibernate": "sleep"}.get(action, action)
    try:
        minutes = float(args.get("minutes"))
    except (TypeError, ValueError):
        minutes = None
    return action, minutes


# ---------- confirm step (used by actions._risky_text) ----------
def needs_confirm(args: dict) -> bool:
    action, minutes = _parse(args or {})
    return action in ("sleep", "shutdown") and minutes is not None and 0 < minutes <= MAX_MINUTES


def risky_text(args: dict) -> str | None:
    """Question words for sleep/shutdown timers, None for stop_media (no yes needed)."""
    if not needs_confirm(args):
        return None
    action, minutes = _parse(args)
    verb = "put the laptop to sleep" if action == "sleep" else "shut down the laptop"
    return f"{verb} in {_spoken(minutes * 60)}"


# ---------- background ----------
def _finish(t: dict) -> None:
    """Run the timer's action. Called without the lock held."""
    action = t["action"]
    if action == "stop_media":
        try:
            _pause_media()
        finally:
            if t.get("fade_from") is not None:
                try:
                    _set_volume(t["fade_from"])
                except Exception:
                    pass
        return
    if action == "sleep":
        _say("Good night. Going to sleep now.")
        try:
            _do_sleep()
        except Exception:
            _say("I couldn't put the laptop to sleep.")
    elif action == "shutdown":
        _say("Good night. Shutting down now.")
        try:
            _do_shutdown()
        except Exception:
            _say("I couldn't shut down the laptop.")


def _tick(now: float | None = None) -> None:
    global _timer
    now = time.time() if now is None else now
    say = None
    with _lock:
        t = _timer
        if t is None:
            return
        left = t["ends"] - now
        if left <= 0:
            _timer = None
            if -left > LATE_SECONDS:  # laptop was asleep / off long past the end: don't act now
                if t.get("fade_from") is not None:
                    try:
                        _set_volume(t["fade_from"])
                    except Exception:
                        pass
                return
            done = t
        else:
            done = None
            if t["action"] == "stop_media" and left <= FADE_SECONDS:
                try:
                    if t.get("fade_from") is None:
                        t["fade_from"] = _get_volume()
                    _set_volume(int(t["fade_from"] * left / FADE_SECONDS))
                except Exception:
                    pass  # no volume control: the pause at the end still happens
            elif t["action"] in ("sleep", "shutdown") and left <= WARN_SECONDS and not t["warned"]:
                t["warned"] = True
                verb = "go to sleep" if t["action"] == "sleep" else "shut down"
                say = f"The laptop will {verb} in 1 minute. Say cancel sleep timer to stop."
    if done is not None:
        _finish(done)
    elif say:
        _say(say)


def _loop() -> None:
    while True:
        time.sleep(TICK)
        try:
            _tick()
        except Exception:
            pass


def _ensure_thread() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-sleeptimer", daemon=True)
        _thread.start()


def _restore_fade(t: dict | None) -> None:
    if t and t.get("fade_from") is not None:
        try:
            _set_volume(t["fade_from"])
        except Exception:
            pass


# ---------- handlers ----------
def sleep_timer(args: dict) -> str:
    global _timer
    action, minutes = _parse(args or {})
    if action not in ACTIONS:
        return "I can stop the music, put the laptop to sleep, or shut it down after a time."
    if minutes is None or minutes <= 0:
        return "In how many minutes?"
    if minutes > MAX_MINUTES:
        return "A sleep timer can be at most 24 hours."
    with _lock:
        old = _timer
        _timer = {"action": action, "ends": time.time() + minutes * 60, "minutes": minutes,
                  "warned": False, "fade_from": None}
    _restore_fade(old)
    _ensure_thread()
    when = _spoken(minutes * 60)
    replaced = " I replaced the old sleep timer." if old else ""
    if action == "stop_media":
        return f"Okay, I'll fade out and stop the music in {when}.{replaced}"
    verb = "put the laptop to sleep" if action == "sleep" else "shut down the laptop"
    return f"Okay, I'll {verb} in {when}. I'll warn you 1 minute before.{replaced}"


def sleep_timer_cancel(args: dict | None = None) -> str:
    global _timer
    with _lock:
        old, _timer = _timer, None
    if not old:
        return "No sleep timer is set."
    _restore_fade(old)
    return "Sleep timer cancelled."


def sleep_timer_status(args: dict | None = None) -> str:
    with _lock:
        t = dict(_timer) if _timer else None
    if not t:
        return "No sleep timer is set."
    left = max(1.0, t["ends"] - time.time())
    return f"{_spoken(left)} left until {_what(t['action'])}."


def is_active() -> bool:
    return _timer is not None


def warning_active(now: float | None = None) -> bool:
    """True in the last minute of a sleep/shutdown timer (after the warning was spoken).
    main can then treat a bare "cancel" / "stop" as sleep_timer_cancel."""
    t = _timer
    now = time.time() if now is None else now
    return bool(t and t["action"] in ("sleep", "shutdown") and t["warned"] and t["ends"] > now)


# ======================= wiring =======================
CATALOG: dict[str, dict] = {
    "sleep_timer": {
        "description": "Bedtime sleep timer: after some minutes, fade out and stop the music (stop_media), "
                       "or put the laptop to sleep, or shut it down (Jarvis asks the user to confirm "
                       "sleep/shutdown). Replaces any running sleep timer.",
        "properties": {
            "minutes": {"description": "Minutes from now, e.g. 30, or 60 for 1 hour.", "type": "integer"},
            "action": {"type": "string", "enum": list(ACTIONS)},
        },
        "required": ["minutes", "action"],
    },
    "sleep_timer_cancel": {"description": "Cancel the sleep timer.", "properties": {}, "required": []},
    "sleep_timer_status": {"description": "Say how long is left on the sleep timer and what it will do.",
                           "properties": {}, "required": [], "info": True},
}

HANDLERS = {
    "sleep_timer": sleep_timer,
    "sleep_timer_cancel": sleep_timer_cancel,
    "sleep_timer_status": sleep_timer_status,
}
