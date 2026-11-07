"""Piece AM: add calendar events by voice. Intent: calendar_add {title, start, minutes?, location?}.

"add dentist tomorrow at 4 pm for 1 hour", "add meeting with Ravi on Friday at 10".
The AI brain gives `start` as ISO ("2026-11-08T16:00"); phrase rules may give spoken text
("tomorrow at 4 pm", "friday 10 am"). Always risky: Jarvis says the event back and asks
"yes" before saving (args.confirm is True after the yes).

Where the event goes (first that works, or the one set in config):
  1. Outlook desktop (pywin32, `Outlook.Application` CreateItem(1)). Windows only.
     The "new Outlook" app has no COM, so it falls through to the next one.
  2. Google Calendar API, when config `google_calendar.credentials_file` is set
     (OAuth "Desktop app" client JSON from Google Cloud Console). First use opens a browser
     to sign in; the token is cached. Packages: google-api-python-client, google-auth-oauthlib.
  3. Google Calendar "create event" page opened in the browser with everything filled in.
     The user clicks Save. No setup needed.

Settings (all optional), config.yaml:
    calendar:
      add_with: auto          # auto | outlook | google | link
      default_minutes: 60
    google_calendar:
      credentials_file: "~/google_credentials.json"
      token_file: "~/.jarvis-google-calendar-token.json"
      calendar_id: primary
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import sys
import urllib.parse
import webbrowser

from . import agenda

DEFAULT_MINUTES = 60
MAX_MINUTES = 7 * 24 * 60
MAX_TITLE = 120
DEFAULT_TOKEN = "~/.jarvis-google-calendar-token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
LOGIN_TIMEOUT = 120  # seconds to wait for the Google sign-in in the browser
METHODS = ("auto", "outlook", "google", "link")


# ---------- settings ----------
def settings(cfg: dict | None = None) -> dict:
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config() or {}
        except Exception:
            cfg = {}
    cal = (cfg or {}).get("calendar") or {}
    g = (cfg or {}).get("google_calendar") or {}
    cal = cal if isinstance(cal, dict) else {}
    g = g if isinstance(g, dict) else {}
    method = str(cal.get("add_with") or "auto").lower().strip()
    try:
        minutes = int(cal.get("default_minutes") or DEFAULT_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    return {
        "method": method if method in METHODS else "auto",
        "default_minutes": minutes if 0 < minutes <= MAX_MINUTES else DEFAULT_MINUTES,
        "credentials_file": str(g.get("credentials_file") or ""),
        "token_file": str(g.get("token_file") or DEFAULT_TOKEN),
        "calendar_id": str(g.get("calendar_id") or "primary"),
    }


def _now() -> dt.datetime:
    """Local time, timezone-aware. Tests patch this."""
    return dt.datetime.now().astimezone()


# ---------- parsing ----------
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "ninety": 90}


def parse_minutes(value) -> int | None:
    """30, "45", "1 hour", "an hour and a half", "90 minutes", "half an hour", "2 hrs" -> minutes."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if 0 < n <= MAX_MINUTES else None
    t = str(value).strip().lower()
    t = re.sub(r"^for\s+", "", t)
    if re.fullmatch(r"\d+", t):
        return parse_minutes(int(t))
    if t in ("half an hour", "half hour", "a half hour"):
        return 30
    half = bool(re.search(r"\band (?:a )?half\b", t))
    for w, n in sorted(_NUM_WORDS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{w}\b", str(n), t)
    total = 0.0
    found = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", t):
        found = True
        total += float(num) * (60 if unit.startswith("h") else 1)
    if not found:
        return None
    if half:
        total += 30
    n = int(round(total))
    return n if 0 < n <= MAX_MINUTES else None


def _split_when(text: str) -> tuple[str, str]:
    """'tomorrow at 4 pm' -> ('tomorrow', '4 pm'); 'friday 10am' -> ('friday', '10am')."""
    t = re.sub(r"\s+", " ", text.strip().lower())
    m = re.match(r"^(.*?)\s*\bat\b\s*(.+)$", t)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(.*?)\s*\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|noon|midday|midnight)$", t)
    if m:
        last = (m.group(1).split() or [""])[-1]
        if last not in agenda._MONTHS:  # "november 20" is a date, not 8 pm
            return m.group(1), m.group(2)
    m = re.match(r"^(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:on\s+)?(.+)$", t)  # "4 pm tomorrow"
    if m:
        return m.group(2), m.group(1)
    return t, ""


def parse_start(value, now: dt.datetime | None = None) -> tuple[dt.datetime | None, str]:
    """Return (aware start, error words). ISO text or spoken 'tomorrow at 4 pm'.

    A time without a day that has already passed today means tomorrow.
    """
    now = now or _now()
    tz = now.tzinfo
    text = str(value or "").strip()
    if not text:
        return None, "When should I add it? Say a day and time."
    iso = text.replace("Z", "+00:00")
    if re.match(r"^\d{4}-\d{2}-\d{2}", iso):
        try:
            start = dt.datetime.fromisoformat(iso)
        except ValueError:
            start = None
        if start is not None:
            if len(text) <= 10:  # date only
                return None, "What time should I add it?"
            start = start.replace(tzinfo=tz) if start.tzinfo is None else start.astimezone(tz)
            if start < now - dt.timedelta(minutes=1):
                return None, "That time has already passed."
            return start, ""
    day_text, time_text = _split_when(text)
    explicit_day = bool(day_text.strip())
    day = agenda.parse_day(day_text, now.date()) if explicit_day else now.date()
    if day is None:
        return None, f"I didn't understand the day '{day_text}'."
    tm = agenda.parse_time(time_text) if time_text else None
    if tm is None:
        return None, "What time should I add it?"
    start = dt.datetime.combine(day, tm, tzinfo=tz)
    if start < now - dt.timedelta(minutes=1):
        if explicit_day and day != now.date():
            return None, "That time has already passed."
        start += dt.timedelta(days=1)
    return start, ""


def clean_title(value) -> str:
    t = re.sub(r"\s+", " ", str(value or "")).strip(" .,")
    t = re.sub(r"^(?:an?|the)\s+(?=event|appointment)", "", t, flags=re.I)
    return t[:MAX_TITLE].strip()


def build_event(args: dict, now: dt.datetime | None = None) -> tuple[dict | None, str]:
    """Turn intent args into {title, start, end, minutes, location}, or (None, what is missing)."""
    args = args or {}
    title = clean_title(args.get("title") or args.get("name") or args.get("text"))
    if not title:
        return None, "What should I call the event?"
    start, err = parse_start(args.get("start") or args.get("when"), now)
    if start is None:
        return None, err
    raw_minutes = args.get("minutes", args.get("duration"))
    minutes = parse_minutes(raw_minutes)
    if minutes is None:
        if raw_minutes not in (None, ""):
            return None, "How long is it? Say for example 'for 1 hour'."
        minutes = settings()["default_minutes"]
    location = re.sub(r"\s+", " ", str(args.get("location") or "")).strip()[:200]
    return {"title": title, "start": start, "end": start + dt.timedelta(minutes=minutes),
            "minutes": minutes, "location": location}, ""


# ---------- spoken words ----------
def _say_minutes(n: int) -> str:
    h, m = divmod(n, 60)
    parts = []
    if h:
        parts.append("1 hour" if h == 1 else f"{h} hours")
    if m:
        parts.append(f"{m} minutes")
    return " and ".join(parts)


def _say_time(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _say_day(d: dt.date, today: dt.date) -> str:
    if d == today:
        return "today"
    if d == today + dt.timedelta(days=1):
        return "tomorrow"
    if 0 < (d - today).days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}" + (f" {d.year}" if d.year != today.year else "")


def describe(ev: dict, now: dt.datetime | None = None) -> str:
    now = now or _now()
    s = f"'{ev['title']}' {_say_day(ev['start'].date(), now.date())} at {_say_time(ev['start'])} for {_say_minutes(ev['minutes'])}"
    if ev.get("location"):
        s += f" at {ev['location']}"
    return s


def risky_text(args: dict) -> str | None:
    """Words for 'are you sure you want to ...?'. None when the event can't be built yet
    (the handler then asks for the missing part instead of asking yes/no)."""
    ev, _ = build_event(args)
    if ev is None:
        return None
    return f"add {describe(ev)} to your calendar"


def needs_confirm(args: dict) -> bool:
    return risky_text(args) is not None


# ---------- saving ----------
class NotAvailable(Exception):
    """This way of adding events is not set up on this PC; try the next one."""


def _naive_local(t: dt.datetime) -> dt.datetime:
    return t.astimezone(_now().tzinfo).replace(tzinfo=None)


def _outlook_app():
    """Outlook.Application COM object. Tests patch this."""
    if sys.platform != "win32":
        raise NotAvailable("Outlook needs Windows")
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise NotAvailable("pywin32 not installed") from e
    from jarvis.winutil import com_init

    com_init()
    try:
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as e:  # not installed, or the new Outlook (no COM)
        raise NotAvailable(f"Outlook not available: {e}") from e


def add_outlook(ev: dict) -> str:
    app = _outlook_app()
    item = app.CreateItem(1)  # 1 = olAppointmentItem
    item.Subject = ev["title"]
    item.Start = _naive_local(ev["start"]).strftime("%Y-%m-%d %H:%M")
    item.Duration = ev["minutes"]
    if ev.get("location"):
        item.Location = ev["location"]
    item.ReminderSet = True
    item.ReminderMinutesBeforeStart = 15
    item.Save()
    return "Outlook"


def _google_service(conf: dict):
    """Google Calendar API service. Tests patch this."""
    cred_file = os.path.expanduser(conf.get("credentials_file") or "")
    if not cred_file:
        raise NotAvailable("google_calendar.credentials_file not set")
    if not os.path.isfile(cred_file):
        raise NotAvailable(f"credentials file not found: {cred_file}")
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        raise NotAvailable("google-api-python-client / google-auth-oauthlib not installed") from e
    token_file = os.path.expanduser(conf.get("token_file") or DEFAULT_TOKEN)
    creds = None
    if os.path.isfile(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception:
            creds = None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
        creds = flow.run_local_server(port=0, timeout_seconds=LOGIN_TIMEOUT, open_browser=True)
        if not creds:
            raise NotAvailable("Google sign-in did not finish")
    try:
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    except OSError:
        pass
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def add_google(ev: dict, conf: dict) -> str:
    service = _google_service(conf)
    body = {
        "summary": ev["title"],
        "start": {"dateTime": ev["start"].isoformat()},
        "end": {"dateTime": ev["end"].isoformat()},
    }
    if ev.get("location"):
        body["location"] = ev["location"]
    service.events().insert(calendarId=conf.get("calendar_id") or "primary", body=body).execute()
    return "Google Calendar"


def event_url(ev: dict) -> str:
    """Google Calendar 'create event' page, prefilled. Times in UTC (…Z)."""
    fmt = "%Y%m%dT%H%M%SZ"
    utc = dt.timezone.utc
    q = {"action": "TEMPLATE", "text": ev["title"],
         "dates": f"{ev['start'].astimezone(utc).strftime(fmt)}/{ev['end'].astimezone(utc).strftime(fmt)}"}
    if ev.get("location"):
        q["location"] = ev["location"]
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def _open(url: str) -> bool:
    return bool(webbrowser.open(url))


def add_link(ev: dict) -> str:
    if not _open(event_url(ev)):
        raise NotAvailable("could not open the browser")
    return "link"


def save(ev: dict, conf: dict | None = None) -> str:
    conf = conf or settings()
    method = conf.get("method", "auto")
    order = {"auto": ("outlook", "google", "link"), "outlook": ("outlook", "link"),
             "google": ("google", "link"), "link": ("link",)}[method if method in METHODS else "auto"]
    if method == "auto" and not conf.get("credentials_file"):
        order = ("outlook", "link")
    what = describe(ev)
    errors = []
    for way in order:
        try:
            if way == "outlook":
                add_outlook(ev)
                return f"Added {what} to your Outlook calendar."
            if way == "google":
                add_google(ev, conf)
                return f"Added {what} to your Google Calendar."
            add_link(ev)
            return "I opened Google Calendar in your browser with the event filled in. Click Save to add it."
        except NotAvailable as e:
            errors.append(str(e))
        except Exception as e:  # real failure: log it, then try the next way (the link always lets the user check)
            logging.getLogger("jarvis.calendar_add").exception("adding event with %s failed", way)
            if way == order[-1]:
                raise
            errors.append(f"{way}: {e}")
    return "Sorry, I couldn't add the event. " + ("; ".join(errors)[:150] if errors else "")


# ---------- intent glue ----------
def calendar_add(args: dict) -> str:
    args = args or {}
    ev, err = build_event(args)
    if ev is None:
        return err
    if args.get("confirm") is not True:
        return f"Shall I add {describe(ev)} to your calendar? Say yes to confirm."
    return save(ev)


CATALOG: dict[str, dict] = {
    "calendar_add": {
        "description": ("Add an event to the user's calendar (Outlook, Google Calendar, or the Google Calendar "
                        "page in the browser). Jarvis reads it back and asks the user to confirm first. "
                        "Work out the start from the current date and time."),
        "properties": {
            "title": {"type": "string", "description": "Event name, e.g. 'Dentist', 'Meeting with Ravi'."},
            "start": {"type": "string", "description": "Start as local ISO date-time, e.g. 2026-11-08T16:00."},
            "minutes": {"type": "integer", "description": "Length in minutes. Default 60."},
            "location": {"type": "string", "description": "Optional place."},
        },
        "required": ["title", "start"],
    },
}

HANDLERS = {"calendar_add": calendar_add}
