"""Repeating reminders (piece L). They speak again and again on a schedule.

Says: "remind me to drink water every hour", "remind me every 30 minutes to stretch",
"every day at 8 pm remind me to call mom", "every weekday at 9 take medicine",
"every Monday at 10 remind me about the team call", "list repeating reminders",
"stop the water reminder", "stop all repeating reminders" (asks yes first).

Saved to a JSON file: config `recurring_file` (default "~/Documents/Jarvis repeating.json").
Item: {"id", "text", "every_minutes"?, "at"? "HH:MM", "days" [0=Mon..6=Sun], "next" epoch}.

Own wall-clock thread (like timers.py), so it still fires right after sleep/wake.
A reminder missed by more than 1 hour (laptop off/asleep) is skipped, not spoken late.

Wiring: merge CATALOG and HANDLERS; `repeat_reminders` with action=cancel and no text
(= cancel all) is risky: use `needs_confirm(args)` and `risky_text(args)`.
main.py: `recurring.start(io.say)` at start. NLU: `parse(text)` -> (intent, args) or None.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
import time

DEFAULT_FILE = "~/Documents/Jarvis repeating.json"
STORE_FILE = ""  # empty = read config on first use
TICK = 1.0
MISSED_LIMIT = 3600  # seconds; older missed reminders are skipped
MIN_EVERY = 1  # minutes

notify = print
_lock = threading.Lock()
_items: list[dict] | None = None  # loaded on first use
_thread: threading.Thread | None = None
_stop = threading.Event()

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DAY_SHORT = {d[:3]: i for i, d in enumerate(WEEKDAYS)}
_DAY_SHORT.update({"tues": 1, "thur": 3, "thurs": 3})
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20,
              "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60,
              "half an": 0.5, "half a": 0.5}


# ---------- storage ----------
def _path() -> str:
    global STORE_FILE
    if not STORE_FILE:
        try:
            from ..config import load_config

            STORE_FILE = load_config().get("recurring_file") or DEFAULT_FILE
        except Exception:
            STORE_FILE = DEFAULT_FILE
    return os.path.expanduser(STORE_FILE)


def _load() -> list[dict]:
    global _items
    if _items is None:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = []
        _items = []
        for it in data if isinstance(data, list) else []:
            try:  # drop items edited by hand into something we can't use, so the others still fire
                if isinstance(it, dict) and it.get("text"):
                    next_time(it, time.time())
                    _items.append(it)
                    continue
            except Exception:
                pass
            logging.getLogger("jarvis.recurring").warning("skipped a bad repeating reminder: %r", it)
    return _items


def _save() -> None:
    path = _path()
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_items or [], f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def reset() -> None:
    """Forget the in-memory list (tests / file path change)."""
    global _items
    with _lock:
        _items = None


# ---------- parsing helpers ----------
def parse_time(text: str | None) -> str | None:
    """'9' / '9 am' / '9:30 pm' / '21:00' / 'noon' / 'midnight' -> 'HH:MM' (24 h)."""
    t = (text or "").lower().strip().replace(".", "")
    if not t:
        return None
    if t in ("noon", "midday"):
        return "12:00"
    if t == "midnight":
        return "00:00"
    m = re.fullmatch(r"(\d{1,2})(?:[:\s](\d{2}))?\s*(am|pm|a m|p m)?(?:\s*o'?clock)?", t)
    if not m:
        m2 = re.fullmatch(r"(\d{1,2})\s*o'?clock\s*(am|pm)?", t)
        if not m2:
            return None
        h, mi, ap = int(m2.group(1)), 0, m2.group(2)
    else:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    ap = (ap or "").replace(" ", "")
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return f"{h:02d}:{mi:02d}"


def parse_days(value) -> list[int]:
    """'weekdays' / 'weekends' / 'daily' / 'monday and friday' / [0, 4] -> sorted day numbers."""
    if value is None or value == "":
        return list(range(7))
    if isinstance(value, (list, tuple)):
        out = set()
        for v in value:
            if isinstance(v, int) and 0 <= v <= 6:
                out.add(v)
            else:
                out.update(parse_days(str(v)))
        return sorted(out) or list(range(7))
    t = str(value).lower()
    if re.search(r"\b(every ?day|daily|all days|each day)\b", t):
        return list(range(7))
    out = set()
    if re.search(r"\b(week ?days?|working days?|work ?days?)\b", t) and "weekend" not in t:
        out.update(range(5))
    if re.search(r"\bweekends?\b", t):
        out.update((5, 6))
    for word in re.findall(r"[a-z]+", t):
        w = word.rstrip("s") if word.endswith("days") else word
        if w in WEEKDAYS:
            out.add(WEEKDAYS.index(w))
        elif w in _DAY_SHORT:
            out.add(_DAY_SHORT[w])
    return sorted(out) or list(range(7))


def _say_days(days: list[int]) -> str:
    days = sorted(days)
    if days == list(range(7)):
        return "every day"
    if days == list(range(5)):
        return "every weekday"
    if days == [5, 6]:
        return "every weekend day"
    names = [WEEKDAYS[d].capitalize() for d in days]
    return "every " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])


def _say_time(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ap}" if m else f"{h12} {ap}"


def _say_every(minutes: float) -> str:
    minutes = int(minutes)
    if minutes % 1440 == 0:
        n = minutes // 1440
        return "every day" if n == 1 else f"every {n} days"
    if minutes % 60 == 0:
        n = minutes // 60
        return "every hour" if n == 1 else f"every {n} hours"
    return "every minute" if minutes == 1 else f"every {minutes} minutes"


def describe(it: dict) -> str:
    if it.get("every_minutes"):
        return f"{it['text']}, {_say_every(it['every_minutes'])}"
    return f"{it['text']}, {_say_days(it.get('days') or list(range(7)))} at {_say_time(it['at'])}"


# ---------- schedule ----------
def next_time(it: dict, after: float) -> float:
    """First fire time strictly after `after` (epoch seconds)."""
    if it.get("every_minutes"):
        step = float(it["every_minutes"]) * 60
        nxt = float(it.get("next") or after + step)
        if nxt <= after:
            nxt += step * (int((after - nxt) // step) + 1)
        return nxt
    h, m = map(int, it["at"].split(":"))
    days = it.get("days") or list(range(7))
    base = dt.datetime.fromtimestamp(after)
    for add in range(8):
        day = base.date() + dt.timedelta(days=add)
        if day.weekday() not in days:
            continue
        cand = dt.datetime.combine(day, dt.time(h, m)).timestamp()
        if cand > after:
            return cand
    return after + 86400  # not reached


def _check(now: float | None = None) -> list[str]:
    """Fire due reminders; return the messages (also sent to notify)."""
    now = time.time() if now is None else now
    msgs = []
    with _lock:
        items = _load()
        changed = False
        for it in items:
            try:  # one bad item must not stop the others
                nxt = it.get("next")
                if nxt is None:
                    it["next"] = next_time(it, now)
                    changed = True
                    continue
                if nxt > now:
                    continue
                if now - nxt <= MISSED_LIMIT:
                    msgs.append(f"Reminder: {it['text']}.")
                if it.get("every_minutes"):
                    # interval: count from now so it doesn't fire many times after a long sleep
                    it["next"] = now + float(it["every_minutes"]) * 60 if now - nxt > MISSED_LIMIT else next_time(it, now)
                else:
                    it["next"] = next_time(it, now)
                changed = True
            except Exception:
                logging.getLogger("jarvis.recurring").exception("repeating reminder failed: %r", it)
        if changed:
            _save()
    for msg in msgs:
        try:
            notify(msg)
        except Exception:
            pass
    return msgs


def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            _check()
        except Exception:
            pass


def start(say=None) -> None:
    """Start the background thread. Core: recurring.start(io.say)."""
    global notify, _thread
    if say is not None:
        notify = say
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-recurring", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()


# ---------- handlers ----------
def _clean_text(text: str) -> str:
    t = (text or "").strip().strip(" .,!?'\"")
    t = re.sub(r"^(to|that|about)\s+", "", t, flags=re.I)
    t = re.sub(r"^(i need to|i have to|i should)\s+", "", t, flags=re.I)
    return t.strip()


def repeat_reminder(args: dict) -> str:
    text = _clean_text(args.get("text") or "")
    if not text:
        return "What should I keep reminding you about?"
    every = args.get("every_minutes")
    at = parse_time(str(args["at"])) if args.get("at") not in (None, "") else None
    it: dict = {"text": text}
    if every not in (None, "", 0):
        try:
            every = float(every)
        except (TypeError, ValueError):
            return "How often should I remind you?"
        if every < MIN_EVERY:
            return f"The shortest gap is {MIN_EVERY} minute."
        it["every_minutes"] = int(every) if every == int(every) else every
    elif at:
        it["at"] = at
        it["days"] = parse_days(args.get("days"))
    elif args.get("at"):
        return "Sorry, I didn't get the time. Say something like 9 AM."
    else:
        return "How often should I remind you? For example, every hour or every day at 9 AM."
    now = time.time()
    with _lock:
        items = _load()
        it["id"] = max((x.get("id", 0) for x in items), default=0) + 1
        if it.get("every_minutes"):
            it["next"] = now + float(it["every_minutes"]) * 60
        else:
            it["next"] = next_time(it, now)
        items.append(it)
        _save()
    return f"Okay, I will remind you to {describe(it)}."


def _match(items: list[dict], text: str) -> list[dict]:
    t = re.sub(r"\b(the|my|a|an|reminder|reminders|repeating|recurring|one|for|about|to)\b", " ", text.lower())
    words = [w for w in re.findall(r"[a-z0-9]+", t)]
    if not words:
        return []
    exact = [it for it in items if it["text"].lower() == " ".join(words)]
    if exact:
        return exact
    return [it for it in items if all(w in it["text"].lower() for w in words)] or \
        [it for it in items if any(len(w) > 2 and w in it["text"].lower() for w in words)]


def _is_all(text: str) -> bool:
    return not text.strip() or bool(re.fullmatch(r"\s*(all|everything|all of them|all reminders)\s*", text.lower()))


def needs_confirm(args: dict) -> bool:
    """True for 'cancel all' (risky)."""
    return args.get("action") == "cancel" and _is_all(args.get("text") or "") and not args.get("confirm")


def risky_text(args: dict) -> str:
    return "stop all your repeating reminders"


def repeat_reminders(args: dict) -> str:
    action = args.get("action") or "list"
    text = str(args.get("text") or "")
    with _lock:
        items = _load()
        if action == "cancel":
            if _is_all(text):
                if not items:
                    return "You have no repeating reminders."
                if not args.get("confirm"):
                    return "Are you sure you want to stop all your repeating reminders?"
                n = len(items)
                items.clear()
                _save()
                return f"Stopped all {n} repeating reminder{'s' if n != 1 else ''}."
            found = _match(items, text)
            if not found:
                return f"I couldn't find a repeating reminder about {text}."
            if len(found) > 1:
                return "Which one? " + "; ".join(describe(i) for i in found[:5]) + "."
            items.remove(found[0])
            _save()
            return f"Stopped the reminder to {found[0]['text']}."
        snapshot = list(items)
    if not snapshot:
        return "You have no repeating reminders."
    n = len(snapshot)
    head = f"You have {n} repeating reminder{'s' if n != 1 else ''}: "
    return head + "; ".join(describe(i) for i in snapshot[:8]) + "."


# ---------- rule NLU (for the wiring thread) ----------
_NUM = r"(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty five|forty|fifty|sixty|half an|half a)"
_EVERY_RE = re.compile(rf"\bevery\s+(?:{_NUM}\s+)?(minutes?|mins?|hours?|hrs?)\b", re.I)
_EVERY_DAYS_RE = re.compile(
    r"\b(?:every|each|on)\s+((?:(?:week ?days?|weekends?|day|working days?|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)(?:\s*(?:,|and)\s*)?)+)", re.I)
_DAILY_RE = re.compile(r"\b(daily|every ?day|every morning|every evening|every night)\b", re.I)
_AT_RE = re.compile(r"\bat\s+(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|noon|midnight)", re.I)
_DEFAULT_AT = {"every morning": "08:00", "every evening": "18:00", "every night": "21:00"}


def _num(s: str | None) -> float:
    if not s:
        return 1
    s = s.lower()
    return float(s) if re.fullmatch(r"\d+(?:\.\d+)?", s) else _NUM_WORDS.get(s, 1)


def parse(text: str):
    """Rule parser. Returns (intent, args) or None. Call before generic reminder rules."""
    t = (text or "").strip().rstrip(".!?")
    low = t.lower()
    # list / cancel
    if re.search(r"\b(repeating|recurring|repeat)\s+reminders?\b", low) or re.search(r"\breminders?\s+that\s+repeat", low):
        if re.search(r"\b(list|what|which|show|tell|read)\b", low):
            return "repeat_reminders", {"action": "list"}
        if re.search(r"\b(stop|cancel|delete|remove|clear|turn off)\b", low):
            m = re.search(r"\b(?:stop|cancel|delete|remove|clear|turn off)\s+(?:all\s+)?(?:the\s+|my\s+)?(.*?)\s*(?:repeating|recurring|repeat)\s+reminders?", low)
            what = (m.group(1) if m else "").strip()
            if re.search(r"\ball\b", low) or not what:
                return "repeat_reminders", {"action": "cancel", "text": "all"}
            return "repeat_reminders", {"action": "cancel", "text": what}
    m = re.match(r"(?:please\s+)?(?:stop|cancel|delete|remove|turn off)\s+(?:the\s+|my\s+)?(.+?)\s+reminders?$", low)
    if m and m.group(1) not in ("all", "all the", "all my", "my"):
        with _lock:  # only claim it if a repeating reminder has these words (else timers handles it)
            hit = _match(_load(), m.group(1))
        if hit:
            return "repeat_reminders", {"action": "cancel", "text": m.group(1)}
    # create
    if "every" not in low and "daily" not in low and not re.search(r"\beach\b", low):
        return None
    if not re.search(r"\bremind\b|\breminder\b", low) and not re.match(r"(every|each|daily)\b", low):
        return None
    args: dict = {}
    m = _EVERY_RE.search(t)
    rest = t
    if m:
        n = _num(m.group(1))
        unit = m.group(2).lower()
        args["every_minutes"] = n * 60 if unit.startswith("h") else n
        rest = t[:m.start()] + " " + t[m.end():]
    else:
        at_m = _AT_RE.search(t)
        days_m = _EVERY_DAYS_RE.search(t)
        daily_m = _DAILY_RE.search(t)
        if not (at_m or daily_m or days_m):
            return None
        at = parse_time(at_m.group(1)) if at_m else None
        if not at and daily_m:
            at = _DEFAULT_AT.get(daily_m.group(1).lower())
        if not at:
            return None
        args["at"] = at
        args["days"] = parse_days(days_m.group(1)) if days_m else list(range(7))
        cut = set()
        for mm in (at_m, days_m, daily_m):
            if mm:
                cut.update(range(mm.start(), mm.end()))
        rest = "".join(" " if i in cut else ch for i, ch in enumerate(t))
    rest = re.sub(r"\b(please|jarvis|can you|could you|set (?:a |up a )?(?:repeating |recurring )?reminder|"
                  r"remind me|reminder|repeating|recurring|and|on|at)\b", " ", rest, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip(" ,.")
    args["text"] = _clean_text(rest)
    return "repeat_reminder", args


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "repeat_reminder": {
        "description": "Create a repeating reminder: every N minutes, or at a time on some days "
                       "(daily, weekdays, weekends, or named weekdays). Give every_minutes OR at.",
        "properties": {
            "text": {"type": "string", "description": "What to remind, e.g. 'drink water'."},
            "every_minutes": {"type": "number", "description": "Gap in minutes, e.g. 60 for every hour."},
            "at": {"type": "string", "description": "Time of day, 'HH:MM' 24 h or '9 am'."},
            "days": {"type": "string", "description": "With 'at': 'daily', 'weekdays', 'weekends', or day names like 'monday and friday'. Default daily."},
        },
        "required": ["text"],
    },
    "repeat_reminders": {
        "description": "List repeating reminders, or stop one (by its words) or all (text 'all'; Jarvis asks to confirm).",
        "properties": {
            "action": {"type": "string", "enum": ["list", "cancel"]},
            "text": {"type": "string", "description": "For cancel: words of the reminder, or 'all'."},
        },
        "required": ["action"],
    },
}

HANDLERS = {
    "repeat_reminder": repeat_reminder,
    "repeat_reminders": repeat_reminders,
}
