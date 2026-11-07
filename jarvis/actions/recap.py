"""Evening day recap (piece BO).

Says: "how was my day", "evening recap", "recap my day" -> one short summary of today:
screen time (top 3 apps), tracked project time, habits done / not done, money spent,
open to-dos, reminders still set for tonight, tomorrow's first event, birthdays tomorrow.
"what does tomorrow look like" -> tomorrow's events, reminders and birthdays.

Read only. Each part is optional: it is skipped when its module is missing, broken or empty.
It reads the other modules' data through their own load functions (under their locks)
and never writes their files.

Config (optional): `recap: {at: "21:30"}` speaks the recap once a day at that time.
Wiring: merge CATALOG and HANDLERS (recap is info); main: `recap.start(io.say)` (does nothing
when recap.at is not set).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading

AT = None       # None = read config on first use; "" = daily recap off
TICK = 30       # seconds between time checks
TOP_APPS = 3
MAX_EVENTS = 3  # events named for tomorrow

_stop = threading.Event()
_thread: threading.Thread | None = None
_spoken_on: dt.date | None = None
notify = print
log = logging.getLogger("jarvis.recap")
_DAY = dt.timedelta(days=1)


# ---------- config ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        c = (load_config() or {}).get("recap") or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _at() -> dt.time | None:
    global AT
    if AT is None:
        AT = str(_cfg().get("at") or "")
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", AT or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return dt.time(int(m.group(1)), int(m.group(2)))


# ---------- words ----------
def _dur(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m < 1:
        return "less than a minute"
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    return " ".join(parts)


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def _midnight(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time())


# ---------- parts (each returns "" when there is nothing to say) ----------
def _screen(now: dt.datetime) -> str:
    from . import screentime

    apps, _ = screentime.usage("today", now.date())
    apps = {k: v for k, v in apps.items() if v >= 60}
    if not apps:
        return ""
    total = sum(apps.values())
    top = sorted(apps.items(), key=lambda kv: -kv[1])[:TOP_APPS]
    names = _join([f"{screentime.friendly(k)} {_dur(v)}" for k, v in top])
    return f"Screen time was {_dur(total)}, mostly {names}."


def _projects(now: dt.datetime) -> str:
    from . import timetrack

    with timetrack._lock:
        sessions = timetrack._load()
    totals = timetrack._totals(sessions, _midnight(now.date()), now)
    totals = {k: v for k, v in totals.items() if v >= 60}
    if not totals:
        return ""
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:TOP_APPS]
    return "You worked " + _join([f"{_dur(v)} on {k}" for k, v in top]) + "."


def _habits(now: dt.datetime) -> str:
    from . import habits

    with habits._lock:
        data = habits._load()
    if not data:
        return ""
    today = now.date()
    done = sorted(k for k, days in data.items() if today in days)
    left = sorted(k for k, days in data.items() if today not in days)
    if done and left:
        return f"Habits: you did {_join(done)}, but not {_join(left)}."
    if done:
        return f"You did all your habits: {_join(done)}."
    return f"You haven't done your habits yet: {_join(left)}."


def _spent(now: dt.datetime) -> str:
    from . import expenses

    start = _midnight(now.date())
    with expenses._lock:
        rows = [r for r in expenses._load() if start <= r["date"] < start + _DAY]
    if not rows:
        return ""
    total = sum(r["amount"] for r in rows)
    return f"You spent {expenses.money(total)} in {_n(len(rows), 'expense')}."


def _todos(now: dt.datetime) -> str:
    from . import lists

    with lists._lock:
        items = lists._load().get("to-do") or []
    if not items:
        return ""
    return f"{_n(len(items), 'to-do')} {'is' if len(items) == 1 else 'are'} still open."


def _reminders(start: dt.datetime, end: dt.datetime) -> list[dict]:
    from . import timers

    a, b = start.timestamp(), end.timestamp()
    with timers._lock:
        items = [dict(it) for it in timers._active if it.get("kind") in ("reminder", "alarm")]
    return sorted((it for it in items if a <= it["ends"] < b), key=lambda it: it["ends"])


def _reminders_tonight(now: dt.datetime) -> str:
    items = _reminders(now, _midnight(now.date()) + _DAY)
    if not items:
        return ""
    return f"You have {_n(len(items), 'reminder')} still set for tonight."


def _reminder_text(it: dict) -> str:
    from .agenda import _say_time

    what = str(it.get("label") or "").replace("reminder: ", "").strip() or "a reminder"
    return f"{what} at {_say_time(dt.datetime.fromtimestamp(it['ends']))}"


def _reminders_on(day: dt.date) -> str:
    items = _reminders(_midnight(day), _midnight(day) + _DAY)
    if not items:
        return ""
    return "Reminders: " + _join([_reminder_text(it) for it in items[:MAX_EVENTS]]) + "."


def _events(day: dt.date) -> list[dict]:
    from . import agenda

    if not agenda.calendars_set_up():
        return []
    events, _ = agenda.events_between(_midnight(day), _midnight(day) + _DAY)
    return events


def _first_event(day: dt.date) -> str:
    from . import agenda

    events = _events(day)
    if not events:
        return ""
    timed = [e for e in events if not e["all_day"]] or events
    more = f", one of {_n(len(events), 'event')}" if len(events) > 1 else ""
    return f"Tomorrow starts with {agenda._describe(timed[0])}{more}."


def _events_text(day: dt.date) -> str:
    from . import agenda

    events = _events(day)
    if not events:
        return ""
    names = _join([agenda._describe(e) for e in events[:MAX_EVENTS]])
    extra = f", plus {len(events) - MAX_EVENTS} more" if len(events) > MAX_EVENTS else ""
    return f"You have {_n(len(events), 'event')}: {names}{extra}."


def _birthdays(day: dt.date) -> str:
    from . import birthdays

    found = [birthdays._label(ev) for ev in birthdays.all_events()
             if birthdays.next_date(ev.get("date", ""), day) == day]
    if not found:
        return ""
    names = _join(sorted(found))
    return names[:1].upper() + names[1:] + " is tomorrow."


def _safe(fn, *a) -> str:
    try:
        return fn(*a) or ""
    except Exception:
        log.debug("recap part %s skipped", getattr(fn, "__name__", fn), exc_info=True)
        return ""


# ---------- handler ----------
def _day_arg(value) -> str:
    v = str(value or "").lower().strip()
    return "tomorrow" if v in ("tomorrow", "next day") else "today"


def recap(args: dict | None = None, now: dt.datetime | None = None) -> str:
    """'how was my day' (today) or 'what does tomorrow look like' (tomorrow)."""
    now = now or dt.datetime.now()
    tomorrow = now.date() + _DAY
    if _day_arg((args or {}).get("day")) == "tomorrow":
        parts = [_safe(_events_text, tomorrow), _safe(_reminders_on, tomorrow), _safe(_birthdays, tomorrow)]
        parts = [p for p in parts if p]
        if not parts:
            return "Nothing is planned for tomorrow yet."
        return "Tomorrow: " + " ".join(parts)
    parts = [_safe(_screen, now), _safe(_projects, now), _safe(_habits, now), _safe(_spent, now),
             _safe(_todos, now), _safe(_reminders_tonight, now), _safe(_first_event, tomorrow),
             _safe(_birthdays, tomorrow)]
    parts = [p for p in parts if p]
    if not parts:
        return "I don't have anything recorded for today yet."
    return "Here's your day. " + " ".join(parts)


# ---------- daily recap at recap.at ----------
def check(now: dt.datetime | None = None) -> str | None:
    """Speak the recap once a day after recap.at. Returns the message."""
    global _spoken_on
    now = now or dt.datetime.now()
    at = _at()
    if at is None or now.time() < at or _spoken_on == now.date():
        return None
    _spoken_on = now.date()
    msg = recap({"day": "today"}, now)
    try:
        notify(msg)
    except Exception:
        pass
    return msg


def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            check()
        except Exception:
            log.exception("daily recap failed")


def start(say=None) -> None:
    """Core: recap.start(io.say). Does nothing if recap.at is not set."""
    global notify, _thread, _spoken_on
    if say is not None:
        notify = say
    at = _at()
    if at is None:
        return
    if dt.datetime.now().time() >= at:  # started late: don't speak right away
        _spoken_on = dt.date.today()
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-recap", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()


# ---------- phrases (optional helper for nlu_features) ----------
_TODAY = re.compile(
    r"^(?:how\s+was\s+my\s+day|how\s+did\s+(?:my|the)\s+day\s+go|how\s+did\s+i\s+do\s+today"
    r"|(?:give\s+me\s+(?:an?\s+|my\s+)?)?(?:evening|end\s+of\s+(?:the\s+)?day|day|daily|nightly)\s+recap"
    r"|recap\s+(?:of\s+)?(?:my|the)\s+day|recap\s+today|wrap\s+up\s+(?:my|the)\s+day)$")
_TOMORROW = re.compile(
    r"^(?:what(?:'s|\s+is|\s+does)\s+tomorrow\s+look(?:ing)?\s+like|how\s+does\s+tomorrow\s+look"
    r"|what(?:'s|\s+is)\s+tomorrow\s+like|prepare\s+me\s+for\s+tomorrow|recap\s+(?:for\s+)?tomorrow)$")


def parse(text: str) -> tuple[str, dict] | None:
    """Phrase -> (intent, args), or None. Safe to call on any text."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip().strip(" .!?"))
    t = re.sub(r"^(?:jarvis|hey jarvis|ok jarvis)[, ]+", "", t)
    t = re.sub(r"\s+(?:please|jarvis)$", "", t)
    if _TODAY.match(t):
        return "recap", {"day": "today"}
    if _TOMORROW.match(t):
        return "recap", {"day": "tomorrow"}
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "recap": {
        "description": "Evening recap of the user's day: screen time, project time, habits, money spent, "
                       "open to-dos, reminders, and tomorrow's first event and birthdays. "
                       "day=tomorrow says only tomorrow's events, reminders and birthdays.",
        "properties": {
            "day": {"type": "string", "enum": ["today", "tomorrow"], "description": "today (default) or tomorrow."},
        },
        "required": []},
}

HANDLERS = {"recap": recap}
