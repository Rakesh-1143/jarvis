"""Project time tracking (piece BI).

Says: "start tracking college project", "stop tracking", "what am I tracking",
"how long did I work on college project today / this week", "time report this week",
"export my time report", "delete last session" (risky: asks yes first).

One session runs at a time; starting another stops the first.
File: config `timetrack.file` (default ~/.jarvis/timetrack.json):
  {"sessions": [{"project": "college project", "start": "2026-11-07T10:00:00", "end": null}]}
CSV export: config `timetrack.export_file` (default "~/Documents/Jarvis time tracking.csv").
Not the same as screentime.py (apps) or focus.py (pomodoro timer): this logs time per named project.
Wiring: merge CATALOG and HANDLERS; track_undo is risky (use risky_text); no main.py hook.
"""
from __future__ import annotations

import csv
import datetime as dt
import difflib
import json
import logging
import os
import re
import threading

DEFAULT_FILE = "~/.jarvis/timetrack.json"
DEFAULT_EXPORT = "~/Documents/Jarvis time tracking.csv"
TRACK_FILE = ""      # empty = read config on first use
EXPORT_FILE = ""     # empty = read config on first use
MAX_NAME = 50
LONG_HOURS = 12      # a session longer than this was probably left running by mistake
TOP = 5              # projects named in a full report

_lock = threading.Lock()
log = logging.getLogger("jarvis.timetrack")
_PERIODS = ("today", "week", "month")


# ---------- config + storage ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        c = (load_config() or {}).get("timetrack") or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _path() -> str:
    global TRACK_FILE
    if not TRACK_FILE:
        TRACK_FILE = _cfg().get("file") or DEFAULT_FILE
    return os.path.expanduser(TRACK_FILE)


def _export_path() -> str:
    global EXPORT_FILE
    if not EXPORT_FILE:
        EXPORT_FILE = _cfg().get("export_file") or DEFAULT_EXPORT
    return os.path.expanduser(EXPORT_FILE)


def _parse_time(v) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(v)).replace(tzinfo=None, microsecond=0)
    except (TypeError, ValueError):
        return None


def _load() -> list[dict]:
    """Sessions as [{"project", "start": datetime, "end": datetime | None}], oldest first."""
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    items = raw.get("sessions") if isinstance(raw, dict) else None
    out = []
    for s in items if isinstance(items, list) else []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("project") or "").strip()
        start = _parse_time(s.get("start"))
        end = _parse_time(s.get("end")) if s.get("end") else None
        if not name or not start or (end and end < start):
            continue  # skip broken rows (file edited by hand)
        out.append({"project": name, "start": start, "end": end})
    out.sort(key=lambda s: s["start"])
    # Only the newest session may be running; close any older open one at the next start.
    for a, b in zip(out, out[1:]):
        if a["end"] is None:
            a["end"] = b["start"]
    return out


def _save(sessions: list[dict]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    out = {"sessions": [{"project": s["project"], "start": s["start"].isoformat(),
                         "end": s["end"].isoformat() if s["end"] else None} for s in sessions]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, path)


def _running(sessions: list[dict]) -> dict | None:
    return sessions[-1] if sessions and sessions[-1]["end"] is None else None


# ---------- names + words ----------
def clean_project(text) -> str:
    """'my college project' -> 'college project', 'time on the website' -> 'website'."""
    t = str(text or "").lower().strip().strip(" .,!?'\"")
    t = re.sub(r"\s+", " ", t)
    for _ in range(3):
        t = re.sub(r"^(?:time (?:on|for) |working on |work on |on |for |my |the |project )", "", t).strip()
        t = re.sub(r"(?: now| today| this week| this month| please)$", "", t).strip()
    return t[:MAX_NAME].strip()


def _match(name: str, projects) -> str | None:
    """Find a saved project for a spoken name (exact, plural, word inside, close spelling)."""
    projects = list(dict.fromkeys(projects))
    if not name:
        return None
    if name in projects:
        return name
    for alt in (name.rstrip("s"), name + "s"):
        if alt in projects:
            return alt
    for saved in projects:  # "college" vs "college project"
        if re.search(rf"\b{re.escape(name)}\b", saved) or re.search(rf"\b{re.escape(saved)}\b", name):
            return saved
    close = difflib.get_close_matches(name, projects, n=1, cutoff=0.8)
    return close[0] if close else None


def dur(seconds: float) -> str:
    """3900 -> '1 hour 5 minutes'; under a minute -> 'less than a minute'."""
    m = int(seconds // 60)
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
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _period(value) -> str:
    v = str(value or "").lower().strip()
    v = {"day": "today", "this week": "week", "weekly": "week", "this month": "month", "monthly": "month"}.get(v, v)
    return v if v in _PERIODS else "week"


def _window(period: str, now: dt.datetime) -> tuple[dt.datetime, str]:
    """Start of the period and its spoken name. Week starts Monday."""
    day0 = dt.datetime.combine(now.date(), dt.time())
    if period == "today":
        return day0, "today"
    if period == "month":
        return day0.replace(day=1), "this month"
    return day0 - dt.timedelta(days=now.weekday()), "this week"


def _totals(sessions: list[dict], since: dt.datetime, now: dt.datetime) -> dict[str, float]:
    """Seconds per project inside [since, now]. Running session counts up to now."""
    out: dict[str, float] = {}
    for s in sessions:
        a = max(s["start"], since)
        b = min(s["end"] or now, now)
        if b > a:
            out[s["project"]] = out.get(s["project"], 0) + (b - a).total_seconds()
    return out


# ---------- handlers ----------
def _start(sessions: list[dict], project: str, now: dt.datetime) -> str:
    if not project:
        return "Which project should I track?"
    key = _match(project, [s["project"] for s in sessions]) or project
    run = _running(sessions)
    if run and run["project"] == key:
        return f"Already tracking {key}, for {dur((now - run['start']).total_seconds())}."
    msg = ""
    if run:
        run["end"] = max(now, run["start"])
        msg = f"Stopped {run['project']} after {dur((run['end'] - run['start']).total_seconds())}. "
    sessions.append({"project": key, "start": now, "end": None})
    _save(sessions)
    return msg + f"Started tracking {key}."


def _stop(sessions: list[dict], project: str, now: dt.datetime) -> str:
    run = _running(sessions)
    if not run:
        return "Nothing is being tracked right now."
    if project and _match(project, [run["project"]]) is None:
        return f"You are tracking {run['project']}, not {project}. Say 'stop tracking' to stop it."
    run["end"] = max(now, run["start"])
    _save(sessions)
    secs = (run["end"] - run["start"]).total_seconds()
    msg = f"Stopped tracking {run['project']}. That was {dur(secs)}."
    if secs > LONG_HOURS * 3600:
        msg += " That is very long; if the timer was left running by mistake, say 'delete last session'."
    return msg


def _status(sessions: list[dict], now: dt.datetime) -> str:
    run = _running(sessions)
    if not run:
        return "Nothing is being tracked right now."
    return f"You are tracking {run['project']}, for {dur((now - run['start']).total_seconds())} so far."


def track(args: dict, now: dt.datetime | None = None) -> str:
    """action: start | stop | status."""
    now = (now or dt.datetime.now()).replace(microsecond=0)
    action = str(args.get("action") or "").lower().strip()
    project = clean_project(args.get("project"))
    if action not in ("start", "stop", "status"):
        action = "start" if project else "status"
    with _lock:
        sessions = _load()
        try:
            if action == "start":
                return _start(sessions, project, now)
            if action == "stop":
                return _stop(sessions, project, now)
        except OSError as e:
            log.warning("could not save time tracking: %s", e)
            return "Sorry, I couldn't save that."
        return _status(sessions, now)


def _export(sessions: list[dict], since: dt.datetime, now: dt.datetime) -> str:
    path = _export_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = [s for s in sessions if (s["end"] or now) > since]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # -sig so Excel reads it
        w = csv.writer(f)
        w.writerow(["project", "start", "end", "minutes"])
        for s in rows:
            end = s["end"] or now
            w.writerow([s["project"], s["start"].isoformat(sep=" "),
                        s["end"].isoformat(sep=" ") if s["end"] else "running",
                        round((end - s["start"]).total_seconds() / 60)])
    return path


def track_report(args: dict, now: dt.datetime | None = None) -> str:
    """Time per project for today / this week / this month. Optional CSV export."""
    now = (now or dt.datetime.now()).replace(microsecond=0)
    period = _period(args.get("period"))
    since, when = _window(period, now)
    project = clean_project(args.get("project"))
    if project in ("all", "everything", "all projects"):
        project = ""
    with _lock:
        sessions = _load()
    if not sessions:
        return "You haven't tracked any time yet. Say, for example, 'start tracking college project'."
    tail = ""
    if args.get("export"):
        try:
            path = _export(sessions, since, now)
            tail = f" Saved the sessions to {os.path.basename(path)} in {os.path.basename(os.path.dirname(path)) or 'your folder'}."
        except OSError as e:
            log.warning("could not export time tracking: %s", e)
            tail = " I couldn't save the CSV file."
    totals = _totals(sessions, since, now)
    if project:
        key = _match(project, [s["project"] for s in sessions])
        if not key:
            names = sorted({s["project"] for s in sessions})
            return f"You haven't tracked {project}. Your projects: {_join(names[:TOP])}." + tail
        secs = totals.get(key, 0)
        if not secs:
            return f"No time on {key} {when}." + tail
        run = _running(sessions)
        extra = " (still running)" if run and run["project"] == key else ""
        return f"You worked {dur(secs)} on {key} {when}{extra}." + tail
    if not totals:
        return f"No time tracked {when}." + tail
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    parts = [f"{p} {dur(s)}" for p, s in ranked[:TOP]]
    more = f", plus {len(ranked) - TOP} more" if len(ranked) > TOP else ""
    total = sum(totals.values())
    if len(ranked) == 1:
        return f"{when.capitalize()}: {dur(total)} on {ranked[0][0]}." + tail
    return f"{when.capitalize()}: {dur(total)} in total. " + "; ".join(parts) + more + "." + tail


def _last_text(s: dict, now: dt.datetime) -> str:
    secs = ((s["end"] or now) - s["start"]).total_seconds()
    state = ", still running" if s["end"] is None else ""
    return f"{s['project']}, {dur(secs)}, started {s['start'].strftime('%d %b %H:%M')}{state}"


def track_undo(args: dict | None = None, now: dt.datetime | None = None) -> str:
    """Delete the newest session (running or finished). Risky: main asks yes first."""
    now = (now or dt.datetime.now()).replace(microsecond=0)
    with _lock:
        sessions = _load()
        if not sessions:
            return "There is no tracked session to delete."
        last = sessions.pop()
        try:
            _save(sessions)
        except OSError:
            return "Sorry, I couldn't save that."
    return f"Deleted the last session: {_last_text(last, now)}."


def risky_text(args: dict | None = None) -> str:
    """Question words for the yes/no check before track_undo."""
    try:
        sessions = _load()
    except Exception:
        sessions = []
    if not sessions:
        return "delete the last time tracking session"
    return f"delete the last time tracking session ({_last_text(sessions[-1], dt.datetime.now().replace(microsecond=0))})"


# ---------- phrases (optional helper for nlu_features) ----------
_WHEN = r"(?:\s+(?P<period>today|this week|this month))?"
_RULES: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"^(?:start|begin)\s+(?:time\s+tracking|tracking\s+time|tracking|timing)\s+(?:for\s+|on\s+)?(?P<project>.+)$"), "track", {"action": "start"}),
    (re.compile(r"^track\s+(?:my\s+)?time\s+(?:on|for)\s+(?P<project>.+)$"), "track", {"action": "start"}),
    (re.compile(r"^(?:i'?m|i am)\s+(?:starting|working)\s+on\s+(?P<project>.+?)\s+now$"), "track", {"action": "start"}),
    (re.compile(r"^(?:stop|end|finish)\s+(?:time\s+tracking|tracking\s+time|tracking|timing)(?:\s+(?:it|now|please))?$"), "track", {"action": "stop"}),
    (re.compile(r"^(?:what\s+am\s+i\s+tracking|am\s+i\s+tracking\s+(?:anything|something|time)|what(?:'s|\s+is)\s+being\s+tracked"
                r"|(?:time\s+)?tracking\s+status|what\s+am\s+i\s+timing)$"), "track", {"action": "status"}),
    (re.compile(r"^how\s+(?:long|much\s+time)\s+(?:did|have)\s+i\s+(?:work|worked|spend|spent)\s+(?:working\s+)?on\s+(?P<project>.+?)" + _WHEN + "$"), "track_report", {}),
    (re.compile(r"^(?:my\s+)?time\s+(?:tracking\s+)?(?:report|summary)" + _WHEN + "$"), "track_report", {}),
    (re.compile(r"^what\s+did\s+i\s+work\s+on" + _WHEN + "$"), "track_report", {}),
    (re.compile(r"^(?:how\s+(?:long|much)\s+did\s+i\s+work|how\s+many\s+hours\s+did\s+i\s+work)" + _WHEN + "$"), "track_report", {}),
    (re.compile(r"^export\s+(?:my\s+)?(?:time\s+tracking|tracked\s+time|time\s+(?:report|log|sessions))(?:\s+(?:report|log))?" + _WHEN + "$"), "track_report", {"export": True}),
    (re.compile(r"^(?:delete|remove|undo)\s+(?:the\s+|my\s+)?last\s+(?:time\s+tracking\s+|tracking\s+|tracked\s+)?session$"), "track_undo", {}),
]
# Shared with habits.py ("stop tracking X" = remove habit) and screentime ("how much time did I
# spend on X" = app). These only parse here when X is a tracked project.
_STOP_NAMED = re.compile(r"^(?:stop|end|finish)\s+(?:tracking|timing)\s+(?:my\s+|the\s+)?(?P<project>.+)$")


def parse(text: str, projects=None) -> tuple[str, dict] | None:
    """Phrase -> (intent, args), or None. `projects` = saved names (read from the file if None)."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip().strip(" .!?"))
    t = re.sub(r"^(?:jarvis|hey jarvis|ok jarvis)[, ]+", "", t)
    for rx, intent, extra in _RULES:
        m = rx.match(t)
        if not m:
            continue
        args = dict(extra)
        gd = m.groupdict()
        if gd.get("project"):
            p = clean_project(gd["project"])
            if not p or p in ("it", "that", "this", "something", "time"):
                return None
            if intent == "track_report" and re.search(r"\b(?:spend|spent)\b", t):
                # Screen time owns "spend on chrome"; claim it only for a tracked project.
                if projects is None:
                    projects = [s["project"] for s in _load()]
                if not _match(p, projects):
                    return None
            args["project"] = p
        if gd.get("period"):
            args["period"] = _period(gd["period"])
        return intent, args
    m = _STOP_NAMED.match(t)
    if m:
        p = clean_project(m.group("project"))
        if projects is None:
            run = _running(_load())
            projects = [run["project"]] if run else []
        if p and _match(p, projects):
            return "track", {"action": "stop", "project": p}
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "track": {
        "description": "Project time tracking: start a timer for a named project or task "
                       "(e.g. 'college project'), stop it, or say what is being tracked. "
                       "Starting a new project stops the running one. Not for app screen time or pomodoro.",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "status"]},
            "project": {"type": "string", "description": "Project or task name (for start)."},
        },
        "required": ["action"]},
    "track_report": {
        "description": "Say tracked time per project for today, this week or this month, "
                       "or for one project. export=true also saves the sessions to a CSV file in Documents.",
        "properties": {
            "project": {"type": "string", "description": "One project. Leave out for all projects."},
            "period": {"type": "string", "enum": ["today", "week", "month"],
                       "description": "Default week (starts Monday)."},
            "export": {"type": "boolean", "description": "Also save a CSV file."},
        },
        "required": []},
    "track_undo": {
        "description": "Delete the last tracked time session (running or finished). Asks yes first.",
        "properties": {},
        "required": []},
}

HANDLERS = {
    "track": track,
    "track_report": track_report,
    "track_undo": track_undo,
}
