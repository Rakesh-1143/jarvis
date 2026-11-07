"""Timers, reminders and alarms. They run in the background and speak when done.

One background thread checks the wall clock every half second, so a reminder
still fires right after the laptop wakes from sleep. Reminders are saved to a
file (STORE_FILE) so they survive a restart of Jarvis.
"""
from __future__ import annotations

import json
import os
import threading
import time

# Called with the text to announce. Core sets it with actions.set_notifier().
notify = print
STORE_FILE = ""  # set by actions.configure(); empty = don't save
TICK = 0.5

_lock = threading.Lock()
_active: list[dict] = []  # {"label", "ends" (epoch seconds), "message", "kind"}
_thread: threading.Thread | None = None


def _spoken_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    parts = []
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return " and ".join(parts[:2]) or "0 seconds"


def _beep(long: bool = False) -> None:
    try:
        import winsound  # Windows only

        for _ in range(6 if long else 3):
            winsound.Beep(880, 300)
    except Exception:
        pass


def _save() -> None:
    if not STORE_FILE:
        return
    try:
        data = [{k: it[k] for k in ("label", "ends", "message", "kind")} for it in _active if it["kind"] != "timer"]
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def load_saved() -> None:
    """Restore saved reminders. Ones missed while Jarvis was off are announced."""
    if not STORE_FILE or not os.path.exists(STORE_FILE):
        return
    try:
        with open(STORE_FILE, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return
    now = time.time()
    with _lock:
        for it in items:
            if it["ends"] > now:
                _active.append(it)
            elif now - it["ends"] < 12 * 3600:
                _active.append({**it, "ends": now, "message": "Missed earlier: " + it["message"]})
    _ensure_thread()


def _loop() -> None:
    while True:
        time.sleep(TICK)
        now = time.time()
        with _lock:
            due = [it for it in _active if it["ends"] <= now]
            for it in due:
                _active.remove(it)
            if due:
                _save()
        for it in due:
            _beep(long=it["kind"] == "alarm")
            try:
                notify(it["message"])
            except Exception:
                pass


def _ensure_thread() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-timers", daemon=True)
        _thread.start()


def _start(seconds: float, label: str, message: str, kind: str) -> None:
    with _lock:
        _active.append({"label": label, "ends": time.time() + seconds, "message": message, "kind": kind})
        _save()
    _ensure_thread()


def timer(args: dict) -> str:
    seconds = int(args.get("seconds") or 0)
    if seconds <= 0:
        return "For how long should I set the timer?"
    label = (args.get("label") or "").strip()
    name = f"{label} timer" if label else "timer"
    _start(seconds, name, f"Your {name} is done.", "timer")
    return f"Timer set for {_spoken_duration(seconds)}."


def reminder(args: dict) -> str:
    seconds = int(args.get("seconds") or 0)
    text = (args.get("text") or "").strip()
    if seconds <= 0:
        return "When should I remind you?"
    if text.lower() in ("alarm", "wake up", "an alarm"):
        _start(seconds, "alarm", "Wake up! This is your alarm.", "alarm")
        at = time.strftime("%I:%M %p", time.localtime(time.time() + seconds)).lstrip("0")
        return f"Alarm set for {at}."
    if not text:
        return "What should I remind you about?"
    _start(seconds, f"reminder: {text}", f"Reminder: {text}.", "reminder")
    return f"Okay, I will remind you in {_spoken_duration(seconds)}."


def timers(args: dict) -> str:
    action = args.get("action", "list")
    with _lock:
        items = list(_active)
        if action == "cancel":
            _active.clear()
            _save()
    if action == "cancel":
        return f"Cancelled {len(items)} timer{'s' if len(items) != 1 else ''}." if items else "No timers to cancel."
    if not items:
        return "You have no timers or reminders."
    now = time.time()
    items.sort(key=lambda it: it["ends"])
    parts = [f"{it['label']} in {_spoken_duration(max(1, it['ends'] - now))}" for it in items[:5]]
    return "You have: " + "; ".join(parts) + "."
