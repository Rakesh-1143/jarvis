"""Habit tracker (piece AY).

Says: "I did my workout", "mark reading done", "I meditated yesterday",
"did I meditate today", "my workout streak", "habits this week", "habits today",
"remove habit reading" (risky: asks yes first).

A habit is created the first time you mark it done.
File: config `habits.file` (default ~/.jarvis/habits.json): {"workout": ["2026-11-07", ...]}.
Evening nudge: config `habits.remind_at: "21:00"` speaks the habits not done today (once a day).
Wiring: merge CATALOG and HANDLERS; habit_remove is risky (use risky_text); main: habits.start(io.say).
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import logging
import os
import re
import threading

DEFAULT_FILE = "~/.jarvis/habits.json"
HABITS_FILE = ""     # empty = read config on first use
REMIND_AT = None     # None = read config on first use; "" = nudge off
TICK = 30            # seconds between nudge checks
MAX_NAME = 40

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_nudged_on: dt.date | None = None
notify = print
log = logging.getLogger("jarvis.habits")

# Spoken verb forms -> habit name.
_STEMS = {
    "meditate": "meditation", "meditated": "meditation", "meditating": "meditation",
    "exercise": "exercise", "exercised": "exercise", "exercising": "exercise",
    "work out": "workout", "worked out": "workout", "working out": "workout", "workouts": "workout",
    "read": "reading", "reading": "reading",
    "run": "running", "ran": "running", "jog": "running", "jogged": "running",
    "walk": "walk", "walked": "walk", "walking": "walk",
    "journal": "journal", "journaled": "journal", "journalled": "journal", "journaling": "journal",
    "study": "study", "studied": "study", "studying": "study",
    "yoga": "yoga", "did yoga": "yoga", "pray": "prayer", "prayed": "prayer",
    "stretch": "stretching", "stretched": "stretching",
    "practice": "practice", "practiced": "practice", "practised": "practice",
}
_DONE_VERBS = "meditated|exercised|worked out|journaled|journalled|studied|walked|ran|jogged|prayed|stretched|practiced|practised"


# ---------- config + storage ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        c = (load_config() or {}).get("habits") or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _path() -> str:
    global HABITS_FILE
    if not HABITS_FILE:
        HABITS_FILE = _cfg().get("file") or DEFAULT_FILE
    return os.path.expanduser(HABITS_FILE)


def _remind_at() -> dt.time | None:
    global REMIND_AT
    if REMIND_AT is None:
        REMIND_AT = str(_cfg().get("remind_at") or "")
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", REMIND_AT or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return dt.time(int(m.group(1)), int(m.group(2)))


def _load() -> dict[str, set[dt.date]]:
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    data: dict[str, set[dt.date]] = {}
    if not isinstance(raw, dict):
        return data
    for name, days in raw.items():
        if not isinstance(name, str) or not isinstance(days, list):
            continue
        good = set()
        for d in days:
            try:
                good.add(dt.date.fromisoformat(str(d)))
            except ValueError:
                pass  # skip broken dates (file edited by hand)
        data[name] = good
    return data


def _save(data: dict[str, set[dt.date]]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    out = {n: sorted(d.isoformat() for d in days) for n, days in sorted(data.items())}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, path)


# ---------- names ----------
def clean_name(text) -> str:
    """'my morning workout' -> 'morning workout', 'meditated' -> 'meditation'."""
    t = str(text or "").lower().strip().strip(" .,!?'\"")
    t = re.sub(r"\s+", " ", t)
    for _ in range(3):
        t = re.sub(r"^(i |did |do |my |the |a |today'?s |habit |habits )", "", t).strip()
        t = re.sub(r"( habit| habits| today| yesterday| done| for today| streak)$", "", t).strip()
    t = _STEMS.get(t, t)
    return t[:MAX_NAME].strip()


def _match(name: str, data: dict) -> str | None:
    """Find a saved habit for a spoken name (exact, singular/plural, then close spelling)."""
    if not name:
        return None
    if name in data:
        return name
    for alt in (name.rstrip("s"), name + "s"):
        if alt in data:
            return alt
    for saved in data:  # "morning workout" vs "workout"
        if re.search(rf"\b{re.escape(saved)}\b", name) or re.search(rf"\b{re.escape(name)}\b", saved):
            return saved
    close = difflib.get_close_matches(name, list(data), n=1, cutoff=0.8)
    return close[0] if close else None


# ---------- maths ----------
def streak(days: set[dt.date], today: dt.date) -> int:
    """Days in a row up to today (or up to yesterday if not done yet today)."""
    d = today if today in days else today - dt.timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def best_streak(days: set[dt.date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == dt.timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def _week_count(days: set[dt.date], today: dt.date) -> int:
    start = today - dt.timedelta(days=6)
    return sum(1 for d in days if start <= d <= today)


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _day_of(value, today: dt.date) -> dt.date:
    v = str(value or "").lower().strip()
    if v == "yesterday":
        return today - dt.timedelta(days=1)
    try:
        d = dt.date.fromisoformat(v)
        return d if d <= today else today
    except ValueError:
        return today


# ---------- handlers ----------
def habit_done(args: dict, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    name = clean_name(args.get("name"))
    if not name:
        return "Which habit did you do?"
    day = _day_of(args.get("day"), today)
    with _lock:
        data = _load()
        key = _match(name, data) or name
        days = data.setdefault(key, set())
        new_habit = not days
        already = day in days
        days.add(day)
        if not already:
            try:
                _save(data)
            except OSError as e:
                log.warning("could not save habits: %s", e)
                return "Sorry, I couldn't save that."
    when = "today" if day == today else ("yesterday" if day == today - dt.timedelta(days=1) else day.strftime("%d %B"))
    s = streak(days, today)
    if already:
        return f"{key.capitalize()} was already marked done {when}. Streak: {_days(s)}."
    if new_habit:
        return f"Started tracking {key}. Marked done {when}."
    tail = f" Streak: {_days(s)}." if s > 1 else ""
    return f"Nice! {key.capitalize()} done {when}.{tail}"


def _one(key: str, days: set[dt.date], period: str, today: dt.date) -> str:
    s = streak(days, today)
    if period == "today":
        if today in days:
            return f"Yes, you did {key} today. Streak: {_days(s)}."
        return f"Not yet. {key.capitalize()} is not done today." + (f" Your streak is {_days(s)}, keep it going!" if s else "")
    week = _week_count(days, today)
    best = best_streak(days)
    msg = f"{key.capitalize()}: {_days(s)} streak, {week} of the last 7 days."
    if best > s:
        msg += f" Best streak: {_days(best)}."
    return msg


def habit_status(args: dict, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    period = str(args.get("period") or "").lower().strip()
    name = clean_name(args.get("name"))
    if name in ("", "all", "everything"):
        name = ""
    with _lock:
        data = _load()
    if not data:
        return "You are not tracking any habits yet. Say, for example, 'I did my workout'."
    if name:
        key = _match(name, data)
        if not key:
            return f"You are not tracking {name}. Your habits: {_join(sorted(data))}."
        return _one(key, data[key], period, today)
    if period == "today":
        done = sorted(k for k, d in data.items() if today in d)
        left = sorted(k for k, d in data.items() if today not in d)
        if not left:
            return f"All done today: {_join(done)}. Great job!"
        if not done:
            return f"Nothing done yet today. Still to do: {_join(left)}."
        return f"Done today: {_join(done)}. Still to do: {_join(left)}."
    parts = [f"{k} {_week_count(d, today)} of 7" + (f" (streak {s})" if (s := streak(d, today)) > 1 else "")
             for k, d in sorted(data.items())]
    return "Last 7 days: " + "; ".join(parts) + "."


def habit_remove(args: dict) -> str:
    name = clean_name(args.get("name"))
    if not name:
        return "Which habit should I remove?"
    with _lock:
        data = _load()
        key = _match(name, data)
        if not key:
            return f"You are not tracking {name}."
        del data[key]
        try:
            _save(data)
        except OSError:
            return "Sorry, I couldn't save that."
    return f"Removed the habit {key} and its history."


def risky_text(args: dict) -> str:
    """Question words for the yes/no check before habit_remove."""
    name = clean_name(args.get("name")) or "this"
    try:
        name = _match(name, _load()) or name
    except Exception:
        pass
    return f"delete the habit {name} and all its history"


# ---------- evening nudge ----------

def _private() -> bool:
    """Locked or guest mode: don't say names out loud (same rule as notifications)."""
    try:
        from . import security

        return bool(security.is_locked() or security.is_guest())
    except Exception:
        return False

def check(now: dt.datetime | None = None) -> str | None:
    """Speak habits not done today, once a day, after habits.remind_at. Returns the message."""
    global _nudged_on
    now = now or dt.datetime.now()
    at = _remind_at()
    if at is None or now.time() < at or _nudged_on == now.date():
        return None
    _nudged_on = now.date()
    with _lock:
        data = _load()
    left = sorted(k for k, d in data.items() if now.date() not in d)
    if not left:
        return None
    msg = f"Habit check: you haven't done {_join(left)} today."
    try:
        notify("Habit check: some habits are not done today." if _private() else msg)
    except Exception:
        pass
    return msg


def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            check()
        except Exception:
            log.exception("habit nudge failed")


def start(say=None) -> None:
    """Start the nudge thread. Core: habits.start(io.say). Does nothing if remind_at is not set."""
    global notify, _thread, _nudged_on
    if say is not None:
        notify = say
    if _remind_at() is None:
        return
    # If Jarvis starts after the nudge time, don't nag right away.
    if dt.datetime.now().time() >= _remind_at():
        _nudged_on = dt.date.today()
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-habits", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()


# ---------- phrases (optional helper for nlu_features) ----------
_RULES: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"^(?:mark|log|tick)\s+(?:off\s+)?(?:my\s+|the\s+)?(?P<name>.+?)\s+(?:as\s+)?(?:done|complete|completed)(?:\s+(?:for\s+)?(?P<day>today|yesterday))?$"), "habit_done", {}),
    (re.compile(r"^i\s+(?:did|finished|completed|have done|'ve done|ve done)\s+(?:my|the)\s+(?P<name>.+?)(?:\s+(?P<day>today|yesterday))?$"), "habit_done", {}),
    (re.compile(rf"^i\s+(?:just\s+)?(?P<name>{_DONE_VERBS}|did yoga|read)(?:\s+(?P<day>today|yesterday))?$"), "habit_done", {}),
    (re.compile(r"^did\s+i\s+(?:do\s+)?(?:my\s+|the\s+)?(?P<name>.+?)\s+today$"), "habit_status", {"period": "today"}),
    (re.compile(r"^(?:what(?:'s|\s+is)\s+|how\s+long\s+is\s+|show\s+)?my\s+(?P<name>.+?)\s+streak$"), "habit_status", {}),
    (re.compile(r"^(?:how\s+(?:am\s+i\s+doing\s+(?:on|with)|are)\s+)?my\s+habits?(?:\s+(?:this|for the|last)\s+week)?$"), "habit_status", {"period": "week"}),
    (re.compile(r"^(?:show\s+)?(?:my\s+)?habits?\s+(?:this|for the|last)\s+week$"), "habit_status", {"period": "week"}),
    (re.compile(r"^habit\s+(?:report|status|summary)$"), "habit_status", {"period": "week"}),
    (re.compile(r"^(?:my\s+)?habits?\s+(?:for\s+)?today$|^which\s+habits?\s+(?:are\s+)?(?:left|remaining|pending)(?:\s+today)?$"), "habit_status", {"period": "today"}),
    (re.compile(r"^(?:remove|delete)\s+(?:the\s+)?habit\s+(?P<name>.+)$"), "habit_remove", {}),
    (re.compile(r"^(?:remove|delete)\s+(?:my\s+|the\s+)?(?P<name>.+?)\s+habit$"), "habit_remove", {}),
    (re.compile(r"^stop\s+tracking\s+(?:my\s+|the\s+)?(?P<name>.+?)(?:\s+habit)?$"), "habit_remove", {}),
]


def parse(text: str) -> tuple[str, dict] | None:
    """Phrase -> (intent, args), or None. Safe to call on any text."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip().strip(" .!?"))
    t = re.sub(r"^(?:jarvis|hey jarvis|ok jarvis)[, ]+", "", t)
    for rx, intent, extra in _RULES:
        m = rx.match(t)
        if not m:
            continue
        args = dict(extra)
        gd = m.groupdict()
        if gd.get("name"):
            name = clean_name(gd["name"])
            if not name or name in ("it", "that", "this", "something"):
                return None
            args["name"] = name
        if gd.get("day"):
            args["day"] = gd["day"]
        return intent, args
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "habit_done": {
        "description": "Mark a daily habit done, e.g. 'I did my workout', 'mark reading done'. "
                       "A new habit starts being tracked the first time.",
        "properties": {
            "name": {"type": "string", "description": "Habit name, e.g. workout, reading, meditation."},
            "day": {"type": "string", "description": "today (default) or yesterday."},
        },
        "required": ["name"]},
    "habit_status": {
        "description": "Say habit progress: one habit's streak, whether it was done today, "
                       "or all habits today / over the last 7 days.",
        "properties": {
            "name": {"type": "string", "description": "Habit name. Leave out for all habits."},
            "period": {"type": "string", "enum": ["today", "week"],
                       "description": "today = done or not today; week = last 7 days (default)."},
        },
        "required": []},
    "habit_remove": {
        "description": "Stop tracking a habit and delete its history. Asks yes first.",
        "properties": {"name": {"type": "string", "description": "Habit name to remove."}},
        "required": ["name"]},
}

HANDLERS = {
    "habit_done": habit_done,
    "habit_status": habit_status,
    "habit_remove": habit_remove,
}
