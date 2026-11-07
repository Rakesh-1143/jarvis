"""Piece AC: online meetings. Intent: meeting {action: join|leave|mute|status, when?}.

- "join my next meeting" / "join the 3 pm meeting": finds a Zoom, Teams, Google Meet or Webex
  link in the calendar event (title, location or description) and opens it.
  Zoom links open straight in the Zoom app (zoommtg://) when Zoom is installed.
- "leave meeting" / "mute in meeting": sends the app's hotkey to the meeting window.
  Zoom alt+q (Zoom then shows its own Leave button; we never press it, because for a
  host the default button can be "End meeting for all"), Teams ctrl+shift+h, Meet ctrl+w,
  mute: Zoom alt+a, Teams ctrl+shift+m, Meet ctrl+d, Webex ctrl+m.
- "am I in a meeting": checks window titles (and running processes as a hint).

Calendar comes from the agenda module (config `calendars:`). No new packages:
pyautogui (window titles + hotkeys, already in requirements), psutil optional.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sys
import time
import urllib.parse
import webbrowser

from . import agenda

APPS = {"zoom": "Zoom", "teams": "Teams", "meet": "Google Meet", "webex": "Webex"}

# (app, regex). Order matters: the first match in the text wins per position.
_LINK_RES = [
    ("zoom", re.compile(r"https?://(?:[\w-]+\.)*zoom\.us/(?:j|w|my|s)/[^\s<>\"')\]]+", re.I)),
    ("zoom", re.compile(r"zoommtg://[^\s<>\"')\]]+", re.I)),
    ("teams", re.compile(r"https?://teams\.(?:microsoft|live)\.com/(?:l/meetup-join|meet|l/meet)/[^\s<>\"')\]]+", re.I)),
    ("meet", re.compile(r"https?://meet\.google\.com/[a-z]{3,4}-[a-z]{4}-[a-z]{3,4}\b[^\s<>\"')\]]*", re.I)),
    ("webex", re.compile(r"https?://[\w-]+\.webex\.com/[^\s<>\"')\]]+", re.I)),
]

# Hotkeys per app. None = not supported for that app.
LEAVE_KEYS: dict[str, tuple[str, ...] | None] = {
    "zoom": ("alt", "q"), "teams": ("ctrl", "shift", "h"), "meet": ("ctrl", "w"), "webex": None}
MUTE_KEYS: dict[str, tuple[str, ...] | None] = {
    "zoom": ("alt", "a"), "teams": ("ctrl", "shift", "m"), "meet": ("ctrl", "d"), "webex": ("ctrl", "m")}

# Joining is allowed from 15 minutes before... until the meeting ends; look this far ahead.
LOOK_AHEAD = dt.timedelta(hours=24)
EARLY_JOIN = dt.timedelta(minutes=15)
NEAR_TIME = dt.timedelta(minutes=45)   # "join the 3 pm meeting" matches a start within this

_desc_cache: dict[str, str] = {}


# ---------- small helpers (tests patch these) ----------
def _pg():
    import pyautogui
    return pyautogui


def _window_titles() -> list[str]:
    try:
        return [t for t in _pg().getAllTitles() if t and t.strip()]
    except Exception:
        return []


def _active_title() -> str:
    try:
        return str(_pg().getActiveWindowTitle() or "")
    except Exception:
        return ""


def _focus(title: str) -> bool:
    """Bring the window with this exact title to the front."""
    try:
        wins = _pg().getWindowsWithTitle(title)
        if not wins:
            return False
        win = wins[0]
        if getattr(win, "isMinimized", False):
            win.restore()
        win.activate()
        time.sleep(0.3)
        return True
    except Exception:
        return False


def _hotkey(keys: tuple[str, ...]) -> None:
    _pg().hotkey(*keys)


def _process_names() -> set[str]:
    try:
        import psutil
    except ImportError:
        return set()
    names = set()
    for p in psutil.process_iter(["name"]):
        try:
            names.add(str(p.info.get("name") or "").lower())
        except Exception:
            pass
    return names


def _zoom_installed() -> bool:
    if sys.platform != "win32":
        return bool(shutil.which("zoom"))
    appdata = os.environ.get("APPDATA", "")
    paths = [os.path.join(appdata, "Zoom", "bin", "Zoom.exe"),
             os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Zoom", "bin", "Zoom.exe")]
    return any(os.path.exists(p) for p in paths)


def _open(url: str) -> None:
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]  # Windows only
    else:
        webbrowser.open(url)


# ---------- links ----------
def find_link(text: str) -> tuple[str, str] | None:
    """First meeting link in the text -> (app, url). Unwraps Outlook safe links."""
    if not text:
        return None
    text = urllib.parse.unquote(urllib.parse.unquote(text)).replace("&amp;", "&")
    best = None
    for app, rx in _LINK_RES:
        m = rx.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), app, m.group(0).rstrip(".,;>"))
    return (best[1], best[2]) if best else None


def zoom_app_url(url: str) -> str:
    """https://x.zoom.us/j/123?pwd=abc -> zoommtg://zoom.us/join?confno=123&pwd=abc."""
    if url.lower().startswith("zoommtg://"):
        return url
    parts = urllib.parse.urlsplit(url)
    m = re.match(r"/(?:j|w)/(\d+)", parts.path)
    if not m:
        return url  # personal link (/my/name) etc.: keep the web link
    q = urllib.parse.parse_qs(parts.query)
    out = f"zoommtg://zoom.us/join?action=join&confno={m.group(1)}"
    if q.get("pwd"):
        out += "&pwd=" + urllib.parse.quote(q["pwd"][0], safe="")
    return out


def _description(ev: dict) -> str:
    """DESCRIPTION / URL / conference fields of an ICS event, looked up by UID (best effort).

    The agenda module keeps only title + location, but Google puts the Meet link and Outlook
    puts the Teams link in the description, so read it from the cached ICS data."""
    uid = ev.get("uid") or ""
    if not uid:
        return ""
    if uid in _desc_cache:
        return _desc_cache[uid]
    try:
        import icalendar
    except ImportError:
        return ""
    for item in agenda.CALENDARS:
        url = agenda._url(item)
        data = agenda._get_ics(url) if url else None
        if not data:
            continue
        try:
            cal = icalendar.Calendar.from_ical(data)
        except Exception:
            continue
        for comp in cal.walk("VEVENT"):
            if str(comp.get("UID", "")) != uid:
                continue
            parts = [str(comp.get(k, "") or "") for k in
                     ("URL", "X-GOOGLE-CONFERENCE", "DESCRIPTION", "X-ALT-DESC")]
            text = "\n".join(p for p in parts if p)
            _desc_cache[uid] = text
            return text
    _desc_cache[uid] = ""
    return ""


def event_link(ev: dict) -> tuple[str, str] | None:
    for text in (ev.get("location", ""), ev.get("title", "")):
        hit = find_link(text)
        if hit:
            return hit
    return find_link(_description(ev))


# ---------- in a meeting? ----------
def _title_app(title: str) -> str | None:
    """Meeting app from a window title, only when it looks like a live call."""
    t = title.lower()
    if t in ("zoom meeting", "zoom webinar") or t.startswith("zoom meeting"):
        return "zoom"
    if re.match(r"meet\s*[-–]\s*[a-z]{3,4}-[a-z]{4}-[a-z]{3,4}\b", t) or (
            "google meet" in t and re.search(r"[a-z]{3,4}-[a-z]{4}-[a-z]{3,4}", t)):
        return "meet"
    if "microsoft teams" in t and re.search(r"\b(meeting|call)\b", t):
        return "teams"
    if "webex" in t and re.search(r"\bmeeting\b", t) and "start a meeting" not in t:
        return "webex"
    return None


def current_meeting() -> tuple[str, str] | None:
    """(app, window title) of a live meeting window, active window first."""
    active = _active_title()
    app = _title_app(active)
    if app:
        return app, active
    for title in _window_titles():
        app = _title_app(title)
        if app:
            return app, title
    return None


# ---------- choosing an event ----------
def _parse_when(when: str, now: dt.datetime) -> tuple[dt.date, dt.time | None] | None:
    """'' / 'next' / 'now' -> (today, None); '3 pm', 'tomorrow at 10', 'friday 2:30 pm'."""
    t = (when or "").strip().lower()
    t = re.sub(r"\b(my|the|meeting|call|one|o'?clock)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("", "next", "now", "current", "this", "upcoming"):
        return now.date(), None
    day_words = r"(today|tomorrow|day after tomorrow|(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))"
    m = re.search(day_words, t)
    day = now.date()
    if m:
        day = agenda.parse_day(m.group(1), now.date()) or day
        t = (t[:m.start()] + " " + t[m.end():]).strip()
    t = re.sub(r"^(at|on)\s+|\s+(at|on)$", "", t).strip()
    if not t:
        return day, None
    tm = agenda.parse_time(t)
    if tm is None:
        return None
    return day, tm


def _pick(when: str) -> tuple[dict | None, str | None, bool]:
    """-> (event with a link or None, error text, all calendars ok)."""
    now = agenda._now()
    parsed = _parse_when(when, now)
    if parsed is None:
        return None, "Which meeting? Say 'my next meeting' or a time like 3 PM.", True
    day, tm = parsed
    if tm is None and day == now.date():
        events, ok = agenda.events_between(now - dt.timedelta(hours=12), now + LOOK_AHEAD)
        live = [e for e in events if not e["all_day"] and e["end"] > now]
        linked = [e for e in live if event_link(e)]
        # A meeting that is on now (or starts within 15 min) beats a later one.
        soon = [e for e in linked if e["start"] - EARLY_JOIN <= now]
        pick = (soon or linked or [None])[0]
        if pick is None and live:
            return None, (f"Your next meeting, {live[0]['title']}, has no Zoom, Teams, Meet or Webex link."), ok
        return pick, None, ok
    start = dt.datetime.combine(day, dt.time(0), tzinfo=now.tzinfo)
    events, ok = agenda.events_between(start, start + dt.timedelta(days=1))
    timed = [e for e in events if not e["all_day"]]
    if tm is not None:
        target = dt.datetime.combine(day, tm, tzinfo=now.tzinfo)
        near = [e for e in timed if abs(e["start"] - target) <= NEAR_TIME or e["start"] <= target < e["end"]]
        near.sort(key=lambda e: abs(e["start"] - target))
        timed = near
    linked = [e for e in timed if event_link(e)]
    if not linked and timed:
        return None, f"{timed[0]['title']} has no Zoom, Teams, Meet or Webex link.", ok
    return (linked[0] if linked else None), None, ok


# ---------- handlers ----------
def _join(args: dict) -> str:
    if not agenda.calendars_set_up():
        return agenda._NOT_SET
    when = str(args.get("when") or "")
    ev, err, ok = _pick(when)
    if err:
        return err
    if ev is None:
        if not ok:
            return agenda._OFFLINE
        return "I found no online meeting " + ("coming up." if not when or when in ("next", "now") else "at that time.")
    app, url = event_link(ev)
    target = url
    if app == "zoom" and _zoom_installed():
        target = zoom_app_url(url)
    _open(target)
    now = agenda._now()
    mins = int((ev["start"] - now).total_seconds() // 60)
    if mins > 1:
        when_txt = f", it starts in {agenda._say_minutes(mins)}" if mins < 180 else \
            f", it starts {agenda._day_name(ev['start'].date(), now.date())} at {agenda._say_time(ev['start'])}"
    else:
        when_txt = ""
    return f"Joining {ev['title']} on {APPS[app]}{when_txt}."


def _send(keys_by_app: dict, verb: str) -> str:
    hit = current_meeting()
    if not hit:
        return "I can't see a Zoom, Teams, Meet or Webex meeting window."
    app, title = hit
    keys = keys_by_app.get(app)
    if not keys:
        return f"I can't {verb} {APPS[app]} with a shortcut. Please use the meeting window."
    # Hotkeys go to the window in front. Never send ctrl+w etc. to some other window.
    if _active_title() != title and not _focus(title):
        return f"Please click on the {APPS[app]} window first."
    if _title_app(_active_title()) != app:
        return f"Please click on the {APPS[app]} window first."
    _hotkey(keys)
    if verb == "leave":
        if app == "zoom":
            return "Zoom is asking to confirm. Click Leave meeting."
        return f"Left the {APPS[app]} meeting."
    return f"Toggled mute in {APPS[app]}."


def _status(args: dict) -> str:
    hit = current_meeting()
    if hit:
        return f"Yes, you're in a {APPS[hit[0]]} meeting."
    procs = _process_names()
    # A running app is only a hint: Teams and Zoom run in the background all day.
    if not agenda.calendars_set_up():
        return "No, I don't see a meeting window."
    try:
        now = agenda._now()
        events, _ = agenda.events_between(now - dt.timedelta(hours=12), now + dt.timedelta(minutes=1))
        cur = [e for e in events if not e["all_day"] and e["start"] <= now < e["end"]]
    except Exception:
        cur = []
    if cur:
        hint = " Zoom or Teams is running." if procs & {"zoom.exe", "ms-teams.exe", "teams.exe"} else ""
        return (f"I don't see a meeting window, but your calendar says {cur[0]['title']} is on "
                f"until {agenda._say_time(cur[0]['end'])}.{hint}")
    return "No, you're not in a meeting."


def meeting(args: dict) -> str:
    action = str(args.get("action") or "status").strip().lower()
    if action == "join":
        return _join(args)
    if action == "leave":
        return _send(LEAVE_KEYS, "leave")
    if action in ("mute", "unmute"):
        return _send(MUTE_KEYS, "mute")
    if action == "status":
        return _status(args)
    return "I can join, leave, mute, or check your meeting."


# ---------- wiring ----------
CATALOG: dict[str, dict] = {
    "meeting": {
        "description": "Online meetings (Zoom, Teams, Google Meet, Webex): join the next or a timed calendar "
                       "meeting, leave the current meeting, toggle mute, or check if the user is in a meeting.",
        "properties": {
            "action": {"type": "string", "enum": ["join", "leave", "mute", "status"],
                       "description": "join | leave | mute (toggles mute/unmute) | status (am I in a meeting)."},
            "when": {"type": "string", "description": "For join: 'next' (default) or a time like '3 pm', "
                                                      "'tomorrow at 10'."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"meeting": meeting}
