"""Calendar: today's agenda, next meeting, "am I free at 3", morning briefing, meeting alerts.

Calendars come from ICS links in config `calendars:` (a list). Each item is a URL
string or {name, url}. Works with Google Calendar ("Secret address in iCal format")
and Outlook.com ("Publish calendar" ICS link). webcal:// links are fine.
Optional: Outlook desktop app (needs pywin32) when config `calendar: {outlook: true}`.

Settings (all optional), config.yaml:
    calendars:
      - "https://calendar.google.com/calendar/ical/.../basic.ics"
    calendar:
      alert_minutes: 5      # speak "Meeting X starts in 5 minutes"; 0 = off
      refresh_minutes: 10   # how often to download the calendars again
      outlook: false        # also read the Outlook desktop calendar

Packages: icalendar, recurring-ical-events.
Wiring: CATALOG + HANDLERS (merge into actions), start_alerts(io.say) at start.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
import urllib.request

TIMEOUT = 10
_DAY = dt.timedelta(days=1)

# Settings; filled from config on first use (tests can set them directly).
CALENDARS: list = []
ALERT_MINUTES = 5
REFRESH_SECONDS = 600
USE_OUTLOOK = False
_configured = False

_cache: dict[str, tuple[float, bytes]] = {}  # url -> (fetched at, ics bytes)
_cache_lock = threading.Lock()
_alert_thread: threading.Thread | None = None
_alert_stop = threading.Event()
_alerted: set[tuple] = set()


# ---------- settings ----------
def configure(cfg: dict | None = None) -> None:
    """Apply settings from a config dict (default: jarvis.config.load_config())."""
    global CALENDARS, ALERT_MINUTES, REFRESH_SECONDS, USE_OUTLOOK, _configured
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config() or {}
        except Exception:
            cfg = {}
    cals = cfg.get("calendars") or []
    CALENDARS = [cals] if isinstance(cals, (str, dict)) else list(cals)
    opts = cfg.get("calendar") or {}
    ALERT_MINUTES = int(opts.get("alert_minutes", 5) or 0)
    REFRESH_SECONDS = max(60, int(float(opts.get("refresh_minutes", 10) or 10) * 60))
    USE_OUTLOOK = bool(opts.get("outlook", False))
    _configured = True


def _ensure_config() -> None:
    if not _configured:
        configure()


def _now() -> dt.datetime:
    """Local time, timezone-aware. Tests patch this."""
    return dt.datetime.now().astimezone()


def _local_tz():
    return _now().tzinfo


# ---------- loading events ----------
def _url(item) -> str:
    url = item.get("url", "") if isinstance(item, dict) else str(item)
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    return url


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _get_ics(url: str) -> bytes | None:
    """Download with a cache. On error, use the old copy if there is one."""
    with _cache_lock:
        hit = _cache.get(url)
    if hit and time.time() - hit[0] < REFRESH_SECONDS:
        return hit[1]
    try:
        data = _fetch(url)
    except Exception:
        return hit[1] if hit else None
    with _cache_lock:
        _cache[url] = (time.time(), data)
    return data


def _to_local(value, tz) -> tuple[dt.datetime, bool]:
    """ICS date/datetime -> (aware local datetime, is_all_day)."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:  # "floating" time = local time
            return value.replace(tzinfo=tz), False
        return value.astimezone(tz), False
    return dt.datetime(value.year, value.month, value.day, tzinfo=tz), True


def _parse_ics(data: bytes, start: dt.datetime, end: dt.datetime) -> list[dict]:
    import icalendar

    tz = start.tzinfo
    cal = icalendar.Calendar.from_ical(data)
    try:
        import recurring_ical_events

        comps = recurring_ical_events.of(cal).between(start, end)
    except ImportError:  # no repeat support: plain events only
        comps = list(cal.walk("VEVENT"))
    out = []
    for ev in comps:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED" or ev.get("DTSTART") is None:
            continue
        s, all_day = _to_local(ev.decoded("DTSTART"), tz)
        if ev.get("DTEND") is not None:
            e, _ = _to_local(ev.decoded("DTEND"), tz)
        elif ev.get("DURATION") is not None:
            e = s + ev.decoded("DURATION")
        else:
            e = s + (_DAY if all_day else dt.timedelta(0))
        if e < s:
            e = s
        if s >= end or (e <= start and not (e == s and s >= start)):
            continue
        out.append({"title": str(ev.get("SUMMARY", "") or "Untitled event").strip(),
                    "start": s, "end": e, "all_day": all_day,
                    "location": str(ev.get("LOCATION", "") or "").strip(),
                    "uid": str(ev.get("UID", "") or "")})
    return out


def _outlook_events(start: dt.datetime, end: dt.datetime) -> list[dict]:
    """Outlook desktop calendar (Windows + pywin32). Best effort."""
    import win32com.client  # pywin32

    from jarvis.winutil import com_init

    com_init()  # the meeting-alert thread needs COM too
    tz = start.tzinfo
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    items = ns.GetDefaultFolder(9).Items  # 9 = calendar
    items.IncludeRecurrences = True
    items.Sort("[Start]")
    fmt = "%m/%d/%Y %I:%M %p"
    found = items.Restrict(f"[Start] < '{end.strftime(fmt)}' AND [End] > '{start.strftime(fmt)}'")
    out = []
    for it in found:
        # Outlook gives local wall-clock time; keep the numbers, set our zone.
        s, e = it.Start, it.End
        s = dt.datetime(s.year, s.month, s.day, s.hour, s.minute, tzinfo=tz)
        e = dt.datetime(e.year, e.month, e.day, e.hour, e.minute, tzinfo=tz)
        out.append({"title": str(it.Subject or "Untitled event").strip(), "start": s, "end": e,
                    "all_day": bool(it.AllDayEvent), "location": str(it.Location or "").strip(),
                    "uid": str(getattr(it, "EntryID", "") or "")})
        if len(out) > 200:
            break
    return out


def calendars_set_up() -> bool:
    _ensure_config()
    return bool(CALENDARS) or USE_OUTLOOK


def events_between(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], bool]:
    """All events overlapping [start, end), sorted. Returns (events, all_ok)."""
    _ensure_config()
    events: list[dict] = []
    ok = True
    for item in CALENDARS:
        url = _url(item)
        if not url:
            continue
        data = _get_ics(url)
        if data is None:
            ok = False
            continue
        try:
            events += _parse_ics(data, start, end)
        except Exception:
            ok = False
    if USE_OUTLOOK:
        try:
            events += _outlook_events(start, end)
        except Exception:
            ok = False
    seen, unique = set(), []
    for ev in sorted(events, key=lambda e: (not e["all_day"], e["start"], e["title"])):
        key = (ev["title"].lower(), ev["start"], ev["end"])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique, ok


# ---------- spoken text helpers ----------
def _say_time(t: dt.datetime) -> str:
    s = t.strftime("%I:%M %p").lstrip("0")
    return s.replace(":00 ", " ")


def _say_date(d: dt.date) -> str:
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def _say_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    h, m = divmod(minutes, 60)
    out = f"{h} hour{'s' if h != 1 else ''}"
    return out + (f" {m} minute{'s' if m != 1 else ''}" if m else "")


def _day_name(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "today"
    if day == today + _DAY:
        return "tomorrow"
    return "on " + _say_date(day)


def _describe(ev: dict, with_end: bool = False) -> str:
    if ev["all_day"]:
        return f"{ev['title']}, all day"
    out = f"{ev['title']} at {_say_time(ev['start'])}"
    if with_end and ev["end"] > ev["start"]:
        out = f"{ev['title']} from {_say_time(ev['start'])} to {_say_time(ev['end'])}"
    return out


_NOT_SET = ("No calendar is set up. Add your calendar's ICS link under calendars: in config.yaml. "
            "In Google Calendar it's Settings, your calendar, Secret address in iCal format.")
_OFFLINE = "I couldn't reach your calendar. Check the internet connection."

# ---------- parsing spoken days and times ----------
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_day(text: str | None, today: dt.date) -> dt.date | None:
    """'today', 'tomorrow', 'monday', 'next friday', '2026-11-20', '20 november', 'nov 20th'."""
    t = (text or "today").strip().lower()
    t = re.sub(r"\b(on|the|this|of)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("", "today", "now"):
        return today
    if t == "tomorrow":
        return today + _DAY
    if t in ("day after tomorrow", "the day after tomorrow"):
        return today + 2 * _DAY
    if t == "yesterday":
        return today - _DAY
    m = re.fullmatch(r"(next )?(" + "|".join(_WEEKDAYS) + ")", t)
    if m:
        ahead = (_WEEKDAYS.index(m.group(2)) - today.weekday()) % 7
        if m.group(1) and ahead == 0:
            ahead = 7
        return today + dt.timedelta(days=ahead)
    try:
        return dt.date.fromisoformat(t[:10])
    except ValueError:
        pass
    m = (re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)(?: (\d{4}))?", t)
         or re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?", t))
    if m:
        a, b, year = m.groups()
        day, month = (a, b) if a.isdigit() else (b, a)
        if month in _MONTHS:
            try:
                d = dt.date(int(year or today.year), _MONTHS[month], int(day))
            except ValueError:
                return None
            if not year and d < today - dt.timedelta(days=30):
                d = d.replace(year=d.year + 1)
            return d
    return None


_WORD_NUM = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve"])}


def parse_time(text: str | None) -> dt.time | None:
    """'3 pm', '3:30pm', '15:00', 'noon', 'three pm', 'half past 2', '2026-11-07T15:00'."""
    t = (text or "").strip().lower().replace(".", "")
    if not t:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}[t ](\d{1,2}):(\d{2})", t)
    if m:
        return dt.time(int(m.group(1)), int(m.group(2)))
    if t in ("noon", "midday", "12 noon"):
        return dt.time(12, 0)
    if t == "midnight":
        return dt.time(0, 0)
    for w, n in _WORD_NUM.items():
        t = re.sub(rf"\b{w}\b", str(n), t)
    half = re.fullmatch(r"(half|quarter) (past|to) (\d{1,2})(?: ?([ap])m?)?", t)
    if half:
        kind, rel, h, ap = half.groups()
        mins = 30 if kind == "half" else 15
        h = int(h)
        if rel == "to":
            h, mins = (h - 1) % 12 or 12, 60 - mins
        t = f"{h}:{mins:02d}" + (f" {ap}m" if ap else "")
    m = re.fullmatch(r"(?:at )?(\d{1,2})(?::?(\d{2}))? ?(am|pm|a|p|in the morning|in the afternoon|in the evening|at night)?", t)
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3) or ""
    if h > 23 or mins > 59:
        return None
    pm = ap.startswith("p") or ap in ("in the afternoon", "in the evening", "at night")
    am = ap.startswith("a") or ap == "in the morning"
    if pm and h < 12:
        h += 12
    elif am and h == 12:
        h = 0
    elif not ap and 1 <= h <= 7:  # "free at 3" = 3 PM, not 3 AM
        h += 12
    return dt.time(h, mins)


# ---------- handlers ----------
def agenda(args: dict) -> str:
    """'what's on my calendar today / tomorrow / on friday'."""
    if not calendars_set_up():
        return _NOT_SET
    now = _now()
    day = parse_day(args.get("day") or args.get("date"), now.date())
    if day is None:
        return "Which day? Say today, tomorrow, or a date."
    start = dt.datetime.combine(day, dt.time(0), tzinfo=now.tzinfo)
    events, ok = events_between(start, start + _DAY)
    when = _day_name(day, now.date())
    if not events:
        return _OFFLINE if not ok else f"You have nothing on your calendar {when}."
    total = len(events)
    if day == now.date():  # today: skip what already ended
        events = [e for e in events if e["all_day"] or e["end"] > now]
        if not events:
            return f"You're done for today. You had {total} event{'s' if total != 1 else ''}."
    n = len(events)
    more = " more" if n < total else ""
    head = f"You have {n}{more} event{'s' if n != 1 else ''} {when}"
    parts = [_describe(e) for e in events[:6]]
    out = f"{head}: " + "; ".join(parts) + "."
    if n > 6:
        out += f" And {n - 6} more."
    return out


def next_event(args: dict) -> str:
    """'when is my next meeting'."""
    if not calendars_set_up():
        return _NOT_SET
    now = _now()
    events, ok = events_between(now - _DAY, now + dt.timedelta(days=14))
    timed = [e for e in events if not e["all_day"]]
    current = [e for e in timed if e["start"] <= now < e["end"]]
    upcoming = [e for e in timed if e["start"] > now]
    out = ""
    if current:
        c = current[0]
        out = f"You are in {c['title']} until {_say_time(c['end'])}. "
    if not upcoming:
        if not ok and not out:
            return _OFFLINE
        return out + "You have no more meetings in the next two weeks."
    e = upcoming[0]
    mins = int((e["start"] - now).total_seconds() // 60)
    if e["start"].date() == now.date():
        out += f"Your next meeting is {e['title']} at {_say_time(e['start'])}"
        out += f", in {_say_minutes(max(1, mins))}" if mins < 180 else ""
    else:
        out += (f"Your next meeting is {e['title']} {_day_name(e['start'].date(), now.date())} "
                f"at {_say_time(e['start'])}")
    if e["location"]:
        out += f", at {e['location']}"
    return out + "."


def free_at(args: dict) -> str:
    """'am I free at 3 pm (tomorrow)'."""
    if not calendars_set_up():
        return _NOT_SET
    now = _now()
    raw = str(args.get("time") or "")
    when = parse_time(raw)
    if when is None:
        return "What time should I check?"
    day = parse_day(args.get("day") or args.get("date") or (raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", raw) else None),
                    now.date())
    if day is None:
        day = now.date()
    at = dt.datetime.combine(day, when, tzinfo=now.tzinfo)
    length = dt.timedelta(minutes=int(args.get("minutes") or 30))
    events, ok = events_between(at - _DAY, at + length + _DAY)
    clash = [e for e in events if not e["all_day"] and e["start"] < at + length and e["end"] > at]
    label = f"{_say_time(at)}{'' if day == now.date() else ' ' + _day_name(day, now.date())}"
    if clash:
        return "No. At " + label + " you have " + "; ".join(_describe(e, with_end=True) for e in clash[:3]) + "."
    if not ok:
        return _OFFLINE
    after = [e for e in events if not e["all_day"] and e["start"] >= at + length]
    out = f"Yes, you're free at {label}."
    if after and after[0]["start"].date() == day:
        out += f" Your next event after that is {after[0]['title']} at {_say_time(after[0]['start'])}."
    return out


def _reminder_count() -> int:
    try:
        from jarvis.actions import timers

        with timers._lock:
            return sum(1 for it in timers._active if it.get("kind") in ("reminder", "alarm"))
    except Exception:
        return 0


def _weather() -> str:
    try:
        from jarvis.actions import info

        return info.weather({})
    except Exception:
        return ""


def briefing(args: dict) -> str:
    """'good morning briefing': time, weather, today's events, reminders."""
    now = _now()
    hello = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
    parts = [f"{hello}. It's {_say_time(now)} on {_say_date(now.date())}."]
    w = _weather()
    if w:
        parts.append(w)
    if calendars_set_up():
        parts.append(agenda({"day": "today"}))
    n = _reminder_count()
    if n:
        parts.append(f"You have {n} reminder{'s' if n != 1 else ''} set.")
    return " ".join(parts)


# ---------- meeting alerts ----------
def check_alerts(notify, now: dt.datetime | None = None) -> list[str]:
    """Announce events starting within ALERT_MINUTES (once each). Returns what was said."""
    _ensure_config()
    if ALERT_MINUTES <= 0 or not calendars_set_up():
        return []
    now = now or _now()
    lead = dt.timedelta(minutes=ALERT_MINUTES)
    events, _ = events_between(now, now + lead + dt.timedelta(minutes=1))
    said = []
    for e in events:
        if e["all_day"] or not (now < e["start"] <= now + lead):
            continue
        key = (e["uid"] or e["title"], e["start"].isoformat())
        if key in _alerted:
            continue
        _alerted.add(key)
        mins = max(1, round((e["start"] - now).total_seconds() / 60))
        text = f"{e['title']} starts in {_say_minutes(mins)}."
        if e["location"]:
            text = text[:-1] + f", at {e['location']}."
        try:
            notify(text)
        except Exception:
            pass
        said.append(text)
    if len(_alerted) > 500:
        _alerted.clear()
    return said


def _alert_loop(notify, every: float) -> None:
    while not _alert_stop.wait(every):
        try:
            check_alerts(notify)
        except Exception:
            pass


def start_alerts(notify, every: float = 30) -> threading.Thread | None:
    """Start the background meeting-alert thread (core calls start_alerts(io.say) once)."""
    global _alert_thread
    _ensure_config()
    if ALERT_MINUTES <= 0 or not calendars_set_up():
        return None
    if _alert_thread is not None and _alert_thread.is_alive():
        return _alert_thread
    _alert_stop.clear()
    _alert_thread = threading.Thread(target=_alert_loop, args=(notify, every),
                                     name="jarvis-agenda-alerts", daemon=True)
    _alert_thread.start()
    return _alert_thread


def stop_alerts() -> None:
    global _alert_thread
    _alert_stop.set()
    if _alert_thread is not None:
        _alert_thread.join(timeout=2)
    _alert_thread = None


# ---------- wiring ----------
_STR = {"type": "string"}

CATALOG: dict[str, dict] = {
    "agenda": {"description": "Read the user's calendar events for a day.",
               "properties": {"day": {"type": "string", "description":
                                      "today, tomorrow, a weekday (friday) or a date YYYY-MM-DD. Default today."}},
               "required": [], "info": True},
    "next_event": {"description": "Say the user's next calendar meeting/event and how soon it starts.",
                   "properties": {}, "required": [], "info": True},
    "free_at": {"description": "Check if the user is free (no calendar event) at a time.",
                "properties": {"time": {"type": "string", "description": "Time, e.g. '3 pm' or '15:30'."},
                               "day": {"type": "string", "description": "today, tomorrow, weekday or YYYY-MM-DD. Default today."},
                               "minutes": {"type": "integer", "description": "How long they need, default 30."}},
                "required": ["time"], "info": True},
    "briefing": {"description": "Daily briefing: time, weather, today's calendar and reminders.",
                 "properties": {}, "required": [], "info": True},
}

HANDLERS = {"agenda": agenda, "next_event": next_event, "free_at": free_at, "briefing": briefing}
