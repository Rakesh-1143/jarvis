"""Birthdays and anniversaries (piece BA).

Says: "mom's birthday is 12 March", "Ravi was born on 5 May 1990", "our anniversary is 10 June",
"mom and dad's anniversary is 3 February 1995", "when is mom's birthday", "how old is Priya turning",
"birthdays this month", "any birthdays this week", "birthdays in December", "whose birthday is next".

Where dates live:
- A birthday of a saved contact (contacts.py, piece AX) is saved IN the contact (contacts.contact_add).
- Everyone else, and all anniversaries, go to this module's own file:
  config `birthdays.file` (default "~/.jarvis/birthdays.json"):
  {"entries": {"birthday:priya": {"name": "Priya", "date": "1990-05-05", "kind": "birthday"}},
   "last_alert": "2026-11-07"}
  date is "MM-DD" or "YYYY-MM-DD" (same as contacts). When a name has a birthday in both places,
  the contact wins.

Reminders: birthdays.start(io.say) speaks once a day after config `birthdays.remind_at` (default "09:00";
"" = off): today's birthdays/anniversaries and, if `birthdays.day_before` (default true), tomorrow's.
The day it last spoke is saved in the file, so a restart does not repeat it.
29 February is kept on 28 February in years without 29 February.

For nlu_features.py: parse(text) -> (intent, args) | None. Put it BEFORE contacts.parse.
Wiring: merge CATALOG and HANDLERS (nothing risky); main: birthdays.start(io.say).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading

from . import contacts

DEFAULT_FILE = "~/.jarvis/birthdays.json"
BIRTHDAYS_FILE = ""   # empty = read config on first use
REMIND_AT = None      # None = read config on first use; "" = reminders off
DAY_BEFORE = None     # None = read config on first use
TICK = 30             # seconds between reminder checks
MAX_SPOKEN = 10       # events read out in one list
KINDS = ("birthday", "anniversary")
SELF_NAMES = {"me": "your", "our": "your"}  # "my birthday", "our anniversary"

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_alerted_on: dt.date | None = None
notify = print
log = logging.getLogger("jarvis.birthdays")

_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_MONTHS = {m.lower(): i for i, m in enumerate(_MONTH_NAMES, 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9


# ---------- config + storage ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        c = (load_config() or {}).get("birthdays") or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _path() -> str:
    global BIRTHDAYS_FILE
    if not BIRTHDAYS_FILE:
        BIRTHDAYS_FILE = _cfg().get("file") or DEFAULT_FILE
    return os.path.expanduser(str(BIRTHDAYS_FILE))


def _remind_at() -> dt.time | None:
    global REMIND_AT
    if REMIND_AT is None:
        v = _cfg().get("remind_at", "09:00")
        REMIND_AT = "" if v is None or v is False else str(v)
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", REMIND_AT or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return dt.time(int(m.group(1)), int(m.group(2)))


def _day_before() -> bool:
    global DAY_BEFORE
    if DAY_BEFORE is None:
        DAY_BEFORE = _cfg().get("day_before", True) is not False
    return bool(DAY_BEFORE)


def _load() -> dict:
    """{"entries": {key: {name, date, kind}}, "last_alert": str}. Bad rows are skipped."""
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    entries = {}
    for k, v in (raw.get("entries") or {}).items() if isinstance(raw.get("entries"), dict) else []:
        if not isinstance(v, dict):
            continue
        kind = v.get("kind") if v.get("kind") in KINDS else "birthday"
        date = str(v.get("date") or "")
        if _parts(date) is None or not v.get("name"):
            continue  # file edited by hand
        entries[_key(kind, v["name"])] = {"name": str(v["name"]), "date": date, "kind": kind}
    return {"entries": entries, "last_alert": str(raw.get("last_alert") or "")}


def _save(data: dict) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # never leaves a half-written file


# ---------- names + dates ----------
def _key(kind: str, name) -> str:
    return f"{kind}:{' '.join(str(name or '').lower().split())}"


def clean_name(spoken) -> str:
    """"my mom's" -> "mom", "my" / "I" -> "me", "our" / "we" / "my wedding" -> "our"."""
    n = str(spoken or "").strip(" .,!?\"").lower()
    if n in ("my", "i", "me", "myself", "mine"):
        return "me"
    if n in ("our", "we", "us", "my wedding", "our wedding", "wedding"):
        return "our"
    return contacts.clean_name(spoken)


def _parts(date: str) -> tuple[int | None, int, int] | None:
    """"05-05" -> (None, 5, 5), "1990-05-05" -> (1990, 5, 5), else None."""
    p = [int(x) for x in str(date).split("-") if x.isdigit()]
    if len(p) == 2:
        p = [None] + p
    if len(p) != 3 or not 1 <= p[1] <= 12:
        return None
    try:
        dt.date(p[0] or 2000, p[1], p[2])
    except ValueError:
        return None
    return p[0], p[1], p[2]


def _on(year: int, month: int, day: int) -> dt.date:
    """The day in `year`; 29 Feb becomes 28 Feb in a non-leap year."""
    try:
        return dt.date(year, month, day)
    except ValueError:
        return dt.date(year, month, 28)


def next_date(date: str, today: dt.date) -> dt.date | None:
    """Next time this date comes round (today counts)."""
    p = _parts(date)
    if p is None:
        return None
    d = _on(today.year, p[1], p[2])
    return d if d >= today else _on(today.year + 1, p[1], p[2])


def _years(ev: dict, on: dt.date) -> int | None:
    p = _parts(ev["date"])
    if not p or not p[0] or on.year <= p[0]:
        return None
    return on.year - p[0]


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _label(ev: dict) -> str:
    """"Mom's birthday", "your anniversary", "Mom and Dad's anniversary"."""
    own = SELF_NAMES.get(ev["name"].lower())
    who = own or _cap(ev["name"]) + "'s"
    return f"{who} {ev['kind']}"


def _age_text(ev: dict, on: dt.date) -> str:
    n = _years(ev, on)
    if n is None:
        return ""
    if ev["kind"] == "anniversary":
        return f"the {_ordinal(n)} anniversary"
    if ev["name"].lower() == "me":
        return f"you turn {n}"
    return f"{_cap(ev['name'])} turns {n}"


def _when(d: dt.date, today: dt.date) -> str:
    gap = (d - today).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    if gap < 7:
        return f"on {d.strftime('%A')}, in {gap} days"
    return f"in {gap} days"


def _say_date(date: str) -> str:
    p = _parts(date)
    return f"{p[2]} {_MONTH_NAMES[p[1] - 1]}" if p else str(date)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# ---------- all known dates ----------
def all_events() -> list[dict]:
    """Own file entries plus contact birthdays (a contact's birthday wins). [{name, date, kind, source}]."""
    with _lock:
        out = {k: {**v, "source": "file"} for k, v in _load()["entries"].items()}
    try:
        people = contacts.all_contacts()
    except Exception:
        log.exception("could not read contacts")
        people = {}
    for k, c in people.items():
        if c.get("birthday") and _parts(c["birthday"]):
            out[_key("birthday", k)] = {"name": c.get("name") or k, "date": c["birthday"],
                                        "kind": "birthday", "source": "contacts"}
    return list(out.values())


def _find(name: str, kind: str | None, events: list[dict]) -> dict | None:
    """Event for a spoken name. Exact name first, then fuzzy (never guesses between two close names)."""
    from . import fuzzy

    kinds = [kind] if kind in KINDS else list(KINDS)
    for kd in kinds:
        pool = {e["name"].lower(): e for e in events if e["kind"] == kd}
        k = " ".join(name.lower().split())
        if k in pool:
            return pool[k]
        if k in SELF_NAMES:
            continue
        hit = fuzzy.contact(k, pool)
        if hit:
            return pool[hit]
    return None


# ---------- handlers ----------
def birthday_add(args: dict, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    kind = str(args.get("kind") or "birthday").lower()
    kind = "anniversary" if kind.startswith("anniv") or "wedding" in kind else "birthday"
    name = clean_name(args.get("name"))
    if not name:
        return f"Whose {kind} is it? Say, for example: mom's {kind} is 12 March."
    date = contacts.clean_birthday(args.get("date"), today)
    label = _label({"name": name, "kind": kind})
    if not date:
        return f"Sorry, I didn't catch the date for {label}. Say it like 12 March or 12 March 1990."
    person = contacts.lookup(name) if kind == "birthday" and name not in SELF_NAMES else None
    saved = False
    if person:
        # Pass "2 May 1990", not "05-02": contact_add cleans again and reads "05-02" as 5 February.
        msg = contacts.contact_add({"name": person["name"], "birthday": contacts.say_birthday(date)})
        saved = not msg.lower().startswith("sorry")
        if saved:
            name = person["name"]
            label = _label({"name": name, "kind": kind})
    with _lock:
        data = _load()
        k = _key(kind, name)
        if saved:
            if data["entries"].pop(k, None) is not None:  # the contact now holds it; drop the old copy
                try:
                    _save(data)
                except OSError:
                    pass
        else:
            data["entries"][k] = {"name": name, "date": date, "kind": kind}
            try:
                _save(data)
            except OSError as exc:
                return f"Sorry, I couldn't save that: {exc}"
    nxt = next_date(date, today)
    msg = f"Saved {label}: {_say_date(date)}."
    if nxt and (nxt - today).days <= 1:
        msg += f" That's {_when(nxt, today)}!"
    elif _remind_at() is not None:
        msg += " I'll remind you the day before and on the day." if _day_before() else " I'll remind you on the day."
    return msg


def _one(ev: dict, today: dt.date, ask: str = "") -> str:
    nxt = next_date(ev["date"], today)
    label = _label(ev)
    age = _age_text(ev, nxt)
    if ask == "age" and not age:
        return f"I don't know the year for {label}. It's on {_say_date(ev['date'])}."
    if nxt == today:
        msg = f"Today is {label}!"
        return msg + (f" {_cap(age)} today." if age else "")
    msg = f"{_cap(label)} is on {_say_date(ev['date'])}, {_when(nxt, today)}."
    return msg + (f" {_cap(age)}." if age else "")


def _line(ev: dict, today: dt.date, with_date: bool = True) -> str:
    nxt = next_date(ev["date"], today)
    own = SELF_NAMES.get(ev["name"].lower())
    who = (f"{own} {ev['kind']}" if own else
           _cap(ev["name"]) + ("'s anniversary" if ev["kind"] == "anniversary" else ""))
    bits = [who]
    if with_date:
        bits.append("today" if nxt == today else ("tomorrow" if nxt == today + dt.timedelta(days=1)
                                                  else f"on {_say_date(ev['date'])}"))
    n = _years(ev, nxt)
    if n is not None:
        bits.append(f"({'turns ' + str(n) if ev['kind'] == 'birthday' else _ordinal(n)})")
    return " ".join(bits)


def _list(title: str, evs: list[dict], today: dt.date, empty: str) -> str:
    if not evs:
        return empty
    evs = sorted(evs, key=lambda e: (next_date(e["date"], today), e["name"].lower()))
    lines = [_line(e, today) for e in evs[:MAX_SPOKEN]]
    more = len(evs) - MAX_SPOKEN
    return f"{title}: {_join(lines)}." + (f" And {more} more." if more > 0 else "")


def birthday_get(args: dict, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    events = all_events()
    kind = str(args.get("kind") or "").lower()
    kind = "anniversary" if kind.startswith("anniv") else ("birthday" if kind.startswith("birth") else "")
    name = clean_name(args.get("name"))
    if name in ("anyone", "someone", "everyone", "anybody", "all"):
        name = ""
    if name:
        ev = _find(name, kind or None, events)
        if ev is None:
            label = _label({"name": name, "kind": kind or "birthday"})
            return (f"I don't know {label}. Say: {label} is, then the date." if name not in SELF_NAMES
                    else f"I don't know {label} yet. Say: my {kind or 'birthday'} is, then the date.")
        return _one(ev, today, str(args.get("ask") or ""))
    if kind:
        events = [e for e in events if e["kind"] == kind]
    words = "anniversaries" if kind == "anniversary" else "birthdays" if kind == "birthday" else \
        "birthdays or anniversaries"
    if not events:
        return f"I don't know any {words} yet. Say, for example: mom's birthday is 12 March."
    period = str(args.get("period") or "upcoming").lower()
    title = "Anniversaries" if kind == "anniversary" else "Birthdays"
    if period == "month":
        try:
            month = int(args.get("month") or today.month)
        except (TypeError, ValueError):
            m = str(args.get("month")).lower().strip()
            month = _MONTHS.get(m) or _MONTHS.get(m[:3]) or today.month
        month = month if 1 <= month <= 12 else today.month
        mname = _MONTH_NAMES[month - 1]
        evs = [e for e in events if _parts(e["date"])[1] == month]
        evs.sort(key=lambda e: (_parts(e["date"])[2], e["name"].lower()))
        if not evs:
            return f"No {words} in {mname}."
        lines = []
        for e in evs[:MAX_SPOKEN]:
            nxt = _on(today.year, month, _parts(e["date"])[2])
            lines.append(_line(e, today, with_date=False) + (" today" if nxt == today else f" on {nxt.day}"))
        more = len(evs) - MAX_SPOKEN
        return f"{title} in {mname}: {_join(lines)}." + (f" And {more} more." if more > 0 else "")
    if period in ("today", "tomorrow"):
        day = today + dt.timedelta(days=1 if period == "tomorrow" else 0)
        evs = [e for e in events if next_date(e["date"], day) == day]
        if not evs:
            return f"No {words} {period}."
        return f"{_cap(period)}: " + _join([_label(e) + (f", {_age_text(e, day)}" if _age_text(e, day) else "")
                                            for e in evs]) + "."
    if period == "week":
        evs = [e for e in events if (next_date(e["date"], today) - today).days < 7]
        return _list(f"{title} in the next 7 days", evs, today, f"No {words} in the next 7 days.")
    if period == "next":
        first = min(next_date(e["date"], today) for e in events)
        evs = [e for e in events if next_date(e["date"], today) == first]
        return " ".join(_one(e, today) for e in evs)
    evs = [e for e in events if (next_date(e["date"], today) - today).days <= 30]  # upcoming
    if not evs:
        return f"No {words} in the next 30 days. " + birthday_get({"period": "next", "kind": kind}, today)
    return _list(f"Coming up in the next 30 days", evs, today, "")


# ---------- daily reminder ----------

def _private() -> bool:
    """Locked or guest mode: don't say names out loud (same rule as notifications)."""
    try:
        from . import security

        return bool(security.is_locked() or security.is_guest())
    except Exception:
        return False

def check(now: dt.datetime | None = None) -> str | None:
    """Speak today's (and tomorrow's) birthdays once a day after remind_at. Returns the message."""
    global _alerted_on
    now = now or dt.datetime.now()
    at = _remind_at()
    today = now.date()
    if at is None or now.time() < at or _alerted_on == today:
        return None
    with _lock:
        last = _load()["last_alert"]
    _alerted_on = today
    if last == today.isoformat():
        return None  # already said today (before a restart)
    events = all_events()
    parts = []
    todays = [e for e in events if next_date(e["date"], today) == today]
    if todays:
        parts.append("Today is " + _join([_label(e) + (f", {_age_text(e, today)}" if _age_text(e, today) else "")
                                          for e in todays]) + ".")
    if _day_before():
        tmr = today + dt.timedelta(days=1)
        nexts = [e for e in events if next_date(e["date"], tmr) == tmr]
        if nexts:
            parts.append("Tomorrow is " + _join([_label(e) for e in nexts]) + ".")
    if not parts:
        return None
    msg = "Reminder: " + " ".join(parts)
    with _lock:
        data = _load()
        data["last_alert"] = today.isoformat()
        try:
            _save(data)
        except OSError:
            pass
    try:
        notify("You have a birthday reminder today. Ask me about birthdays after unlocking." if _private() else msg)
    except Exception:
        log.exception("birthday notify failed")
    return msg


def _loop() -> None:
    while True:
        try:
            check()
        except Exception:
            log.exception("birthday check failed")
        if _stop.wait(TICK):
            return


def start(say=None) -> None:
    """Start the daily reminder thread. Core: birthdays.start(io.say). Off when remind_at is ""."""
    global notify, _thread
    if say is not None:
        notify = say
    if _remind_at() is None:
        return
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-birthdays", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()


# ---------- phrase rules (for nlu_features.py) ----------
_NAME = r"(?P<name>[a-z][\w .'-]{0,40}?)"
_POSS = r"(?:'s|’s|s')"
_KIND = r"(?P<kind>wedding anniversary|anniversary|birthday|bday|b-day|birth day|date of birth|dob)"
_WHO = r"(?:(?:my\s+)?" + _NAME + _POSS + r"|(?P<self>our|my))"
_ADD = re.compile(r"(?:(?:please\s+)?(?:remember|note|save|add|set|store)(?:\s+that)?\s+)?" + _WHO + r"\s+" + _KIND +
                  r"\s+(?:is\s+(?:on\s+)?|falls on\s+|on\s+|as\s+|=\s*|:\s*)?(?P<date>[\w ,/.-]+)")
_ADD_FOR = re.compile(r"(?:add|save|set|store|remember)\s+(?:a\s+|the\s+)?" + _KIND + r"\s+(?:for|of)\s+(?:my\s+)?" +
                      _NAME + r"\s+(?:on|is|as)\s+(?P<date>[\w ,/.-]+)")
_BORN = re.compile(r"(?:(?:my\s+)?" + _NAME + r"|(?P<self>i))\s+(?:was|were)\s+born\s+on\s+(?:the\s+)?(?P<date>[\w ,/.-]+)")
_MARRIED = re.compile(r"(?:(?:my\s+)?" + _NAME + r"|(?P<self>we|i))\s+got\s+married\s+on\s+(?:the\s+)?(?P<date>[\w ,/.-]+)")
_GET = re.compile(r"(?:when(?:'s| is| was)|what(?:'s| is)(?: the date of)?|what date is|which (?:day|date) is|"
                  r"tell me|remind me (?:of|when))\s+(?:the\s+)?" + _WHO + r"\s+" + _KIND + r"(?:\s+is)?")
_AGE = re.compile(r"how old (?:is (?:my\s+)?" + _NAME + r"\s+(?:turning|going to (?:be|turn))|will (?:my\s+)?" +
                  _NAME.replace("name", "name2") + r"\s+(?:be|turn)(?: turning)?)"
                  r"(?:\s+(?:this year|on (?:his|her|their) birthday))?")
_AGE_ME = re.compile(r"how old (?:am i|will i be)(?: turning)?(?: this year| on my birthday)?")
_LIST = re.compile(r"(?:(?:are there|is there|do i have|do we have|any|list|show|tell me|read|what are|"
                   r"say|check)\s+)*(?:(?:me|my|the|all|any|our)\s+)*(?:upcoming\s+|coming\s+)?"
                   r"(?P<what>birthdays and anniversaries|birthdays?|anniversar(?:y|ies)|special days)\b(?P<rest>.*)")
_WHOSE = re.compile(r"(?:whose|who has a|who has their|is it anyone's|is it anybody's|is there a|any)\s+"
                    r"(?P<what>birthday|anniversary)\s+(?:is\s+)?(?P<rest>.*)")
_TODAY_ANY = re.compile(r"is (?:today|tomorrow) (?:anyone's|anybody's|someone's) (?P<what>birthday|anniversary)")
_FAMILY = {"mom", "mum", "dad", "mother", "father", "sister", "brother", "wife", "husband", "son", "daughter",
           "grandma", "grandpa", "granny", "uncle", "aunt", "aunty", "auntie", "nana", "nani", "dadi", "cousin",
           "niece", "nephew", "boss", "friend", "sis", "bro", "baby", "papa", "mama", "amma", "appa"}
_BAD_NAMES = {"it", "that", "this", "someone", "anyone", "everyone", "whose", "who", "a", "the", "your", "his", "her",
              "their", "next", "his or her"}


def _period(rest: str) -> dict | None:
    r = " ".join(rest.lower().split()).strip(" ?.")
    r = re.sub(r"^(?:are|is|do i have|coming up|falling)\s+", "", r)
    if r in ("", "coming up", "soon", "coming", "coming up soon"):
        return {"period": "upcoming"}
    if re.fullmatch(r"(?:for\s+)?today", r):
        return {"period": "today"}
    if re.fullmatch(r"(?:for\s+)?tomorrow", r):
        return {"period": "tomorrow"}
    if re.fullmatch(r"(?:in\s+|for\s+)?(?:this|the next|next|the coming|coming)\s+(?:week|7 days|seven days)", r):
        return {"period": "week"}
    if re.fullmatch(r"(?:in\s+|for\s+)?this month", r):
        return {"period": "month"}
    if re.fullmatch(r"(?:in\s+|for\s+)?next month", r):
        return {"period": "month", "month": dt.date.today().month % 12 + 1}
    m = re.fullmatch(r"(?:in|for|during)\s+([a-z]+)", r)
    if m and m.group(1) in _MONTHS:
        return {"period": "month", "month": _MONTHS[m.group(1)]}
    if r in ("next", "the next one", "is next", "next one"):
        return {"period": "next"}
    return None


def _kind_of(word: str) -> str:
    return "anniversary" if "anniv" in (word or "") else "birthday"


def _self_name(word: str | None, kind: str) -> str:
    """"my"/"our"/"i"/"we" -> "me" for a birthday, "our" for an anniversary. "" when not a self word."""
    if not word:
        return ""
    return "our" if kind == "anniversary" else "me"


def _name_ok(name: str) -> bool:
    return bool(name) and name.lower() not in _BAD_NAMES


def _no_apostrophe(t: str) -> str:
    """Speech drops the apostrophe: "moms birthday" -> "mom's birthday". Only for family words or
    known names, so "chris birthday" stays "chris"."""
    m = re.search(r"\b([a-z]+)s\s+(?=" + _KIND.replace("?P<kind>", "?:") + r")", t)
    if not m or "'" in t[max(0, m.start() - 1):m.end()]:
        return t
    base = m.group(1)
    known = base in _FAMILY
    if not known:
        try:
            known = bool(contacts.lookup(base)) or any(e["name"].lower() == base for e in all_events())
        except Exception:
            known = False
    return t[:m.start()] + base + "'s " + t[m.end():] if known else t


def parse(text: str, today: dt.date | None = None) -> tuple[str, dict] | None:
    """Spoken text -> (intent, args), or None when it is not about birthdays/anniversaries."""
    t = " ".join(str(text or "").lower().replace("’", "'").split()).strip(" .!?")
    t = _no_apostrophe(t)
    t = re.sub(r"^(?:jarvis|hey jarvis|ok jarvis)[, ]+", "", t)
    if not t or not re.search(r"birth|anniv|bday|b-day|born|married|dob|how old", t):
        return None
    m = _TODAY_ANY.fullmatch(t)
    if m:
        return "birthday_get", {"period": "today" if "today" in t else "tomorrow",
                                **({"kind": "anniversary"} if "anniv" in m.group("what") else {})}
    m = _GET.fullmatch(t)
    if m:
        kind = _kind_of(m.group("kind"))
        name = _self_name(m.group("self"), kind) or clean_name(m.group("name"))
        return ("birthday_get", {"name": name, "kind": kind}) if _name_ok(name) else None
    m = _AGE_ME.fullmatch(t)
    if m:
        return "birthday_get", {"name": "me", "kind": "birthday", "ask": "age"}
    m = _AGE.fullmatch(t)
    if m:
        name = clean_name(m.group("name") or m.group("name2"))
        return ("birthday_get", {"name": name, "kind": "birthday", "ask": "age"}) if _name_ok(name) else None
    for rx in (_ADD_FOR, _ADD):
        m = rx.fullmatch(t)
        if m:
            kind = _kind_of(m.group("kind"))
            name = _self_name(m.groupdict().get("self"), kind) or clean_name(m.group("name"))
            date = m.group("date").strip(" ,.")
            if not _name_ok(name) or not contacts.clean_birthday(date, today):
                return None  # "mom's birthday party is at 6" is not a date
            return "birthday_add", {"name": name, "date": date, "kind": kind}
    for rx, kind in ((_BORN, "birthday"), (_MARRIED, "anniversary")):
        m = rx.fullmatch(t)
        if m:
            name = clean_name("our" if kind == "anniversary" and m.group("self") else (m.group("self") or m.group("name")))
            date = m.group("date").strip(" ,.")
            if not _name_ok(name) or not contacts.clean_birthday(date, today):
                return None
            return "birthday_add", {"name": name, "date": date, "kind": kind}
    for rx in (_WHOSE, _LIST):
        m = rx.fullmatch(t)
        if m:
            p = _period(m.group("rest"))
            if p is None:
                return None
            what = m.group("what")
            if "anniv" in what and "birthday" not in what:
                p["kind"] = "anniversary"
            return "birthday_get", p
    return None


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {
    "birthday_add": {
        "description": "Remember someone's birthday or an anniversary so Jarvis can say it and remind the user "
                       "(the day before and on the day). A saved contact's birthday is stored in the contact.",
        "properties": {
            "name": {"type": "string", "description": "Person as spoken, e.g. 'mom', 'Ravi', 'mom and dad'. "
                                                      "'me' for the user's own birthday, 'our' for the user's "
                                                      "wedding anniversary."},
            "date": {"type": "string", "description": "Date like '12 March' or '12 March 1990' (year optional)."},
            "kind": {"type": "string", "enum": ["birthday", "anniversary"]},
        },
        "required": ["name", "date"],
    },
    "birthday_get": {
        "description": "Say when someone's birthday or anniversary is (and the age/years if the year is known), "
                       "or list birthdays and anniversaries today, this week, in a month, or coming up.",
        "properties": {
            "name": {"type": "string", "description": "Person. Leave out to list several."},
            "kind": {"type": "string", "enum": ["birthday", "anniversary"]},
            "period": {"type": "string", "enum": ["today", "tomorrow", "week", "month", "upcoming", "next"],
                       "description": "For lists: week = next 7 days, upcoming = next 30 days (default), "
                                      "next = the very next one."},
            "month": {"type": "integer", "description": "1-12, with period=month. Default this month."},
            "ask": {"type": "string", "enum": ["age"], "description": "'age' for 'how old is X turning'."},
        },
        "required": [],
        "info": True,
    },
}

HANDLERS = {
    "birthday_add": birthday_add,
    "birthday_get": birthday_get,
}
