"""Triggers (piece AB): "when X happens, do Y". Makes Jarvis act on its own.

Config (config.yaml):
    triggers:
      - when: {app_opens: zoom}          # or app_closes: zoom
        do: ["volume 20", "open notes"]  # phrases, run like routine steps
      - when: {wifi: Home}               # joined this Wi-Fi network (name, any case)
        do: ["open spotify"]
      - when: {charger: unplugged}       # or plugged
        do: ["battery saver on"]
      - when: {time: "09:00", days: weekdays}   # days optional: daily/weekdays/weekends/"monday and friday"
        do: ["open outlook"]
        say: "Good morning."             # optional; default is a short note like "Zoom opened."; "" = silent
        name: work start                 # optional

A background thread checks every 3 s (psutil process list, `netsh wlan show interfaces`,
psutil battery). Each trigger fires once per change (app was closed -> now open), not again
while the state stays the same. What is already true when Jarvis starts does not fire.
Time triggers fire once a day, only within 2 minutes after the time (not late after sleep).

Steps are phrases. main.py gives `runner(phrase)`, which runs one phrase like a routine step
(nlu + actions + confirm). Risky steps still ask "Are you sure?"; the runner must not auto-confirm.

Voice: "list my triggers", "pause triggers", "resume triggers".
Intent: triggers {action: list|pause|resume} (list is info). Nothing risky.
Wiring: merge CATALOG and HANDLERS; NLU `parse(text)` -> (intent, args) or None;
main.py: `triggers.start(runner=..., notify=io.say)`.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time

from .recurring import _say_days, _say_time, parse_days, parse_time

log = logging.getLogger("jarvis.triggers")

TICK = 3.0
TIME_WINDOW = 120  # seconds after a time trigger's time in which it may still fire
KINDS = ("app_opens", "app_closes", "wifi", "charger", "time")

notify = print
runner = None  # runner(phrase) -> reply str or None; set by start()

_lock = threading.Lock()
_triggers: list[dict] | None = None  # valid, normalised triggers (loaded on first use)
_bad = 0  # how many config entries were skipped
_paused = False
_last: dict = {}  # last seen state: {"apps": set, "wifi": str|None, "charger": str|None}
_fired_on: dict[int, str] = {}  # time trigger index -> "YYYY-MM-DD" it last fired
_thread: threading.Thread | None = None
_stop = threading.Event()


# ---------- config ----------
def _norm_app(name) -> str:
    n = re.split(r"[\\/]", str(name or ""))[-1].lower().strip()  # Windows or / paths
    if n.endswith(".exe"):
        n = n[:-4]
    return re.sub(r"[^a-z0-9]", "", n)


def _app_aliases(name: str, apps_cfg: dict) -> list[str]:
    """Names to look for in the process list. An `apps:` entry pointing to an .exe adds its file name."""
    out = [_norm_app(name)]
    for k, v in (apps_cfg or {}).items():
        if str(k).lower().strip() == str(name).lower().strip() and str(v).lower().endswith(".exe"):
            out.append(_norm_app(v))
    return [a for a in dict.fromkeys(out) if a]


def _yaml_time(value) -> str | None:
    """YAML reads unquoted 09:00 as 540 (minutes). Accept that and normal strings."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 24 * 60:
        return f"{value // 60:02d}:{value % 60:02d}"
    return parse_time(str(value)) if value is not None else None


def normalise(raw, apps_cfg: dict | None = None) -> dict | None:
    """One config entry -> {"kind", "value", "days"?, "aliases"?, "do", "say", "name"} or None if bad."""
    if not isinstance(raw, dict):
        return None
    when = raw.get("when")
    steps = raw.get("do")
    if isinstance(steps, str):
        steps = [steps]
    if not isinstance(when, dict) or not isinstance(steps, list):
        return None
    steps = [str(s).strip() for s in steps if str(s or "").strip()]
    kinds = [k for k in KINDS if k in when]
    if len(kinds) != 1 or not steps:
        return None
    kind = kinds[0]
    val = when[kind]
    t: dict = {"kind": kind, "do": steps, "name": str(raw.get("name") or "").strip()}
    if "say" in raw:
        t["say"] = "" if raw["say"] is None else str(raw["say"])
    if kind in ("app_opens", "app_closes"):
        if not str(val or "").strip():
            return None
        t["value"] = str(val).strip()
        t["aliases"] = _app_aliases(t["value"], apps_cfg or {})
        if not t["aliases"]:
            return None
    elif kind == "wifi":
        if not str(val or "").strip():
            return None
        t["value"] = str(val).strip()
    elif kind == "charger":
        v = {True: "plugged", False: "unplugged"}.get(val, str(val or "").lower().strip())
        v = {"plugged in": "plugged", "in": "plugged", "connected": "plugged", "on": "plugged",
             "unplugged": "unplugged", "out": "unplugged", "disconnected": "unplugged", "off": "unplugged",
             "plugged": "plugged"}.get(v)
        if not v:
            return None
        t["value"] = v
    else:  # time
        hhmm = _yaml_time(val)
        if not hhmm:
            return None
        t["value"] = hhmm
        t["days"] = parse_days(when.get("days", raw.get("days")))
    return t


def load(entries=None, apps_cfg: dict | None = None) -> list[dict]:
    """(Re)load triggers. No args = read config.yaml. Tests pass a list."""
    global _triggers, _bad
    if entries is None:
        try:
            from ..config import load_config

            cfg = load_config()
            entries = cfg.get("triggers") or []
            apps_cfg = (cfg.get("apps") or {}) if apps_cfg is None else apps_cfg
        except Exception:
            entries = []
    if not isinstance(entries, list):
        entries = []
    good, bad = [], 0
    for raw in entries:
        t = normalise(raw, apps_cfg)
        if t is None:
            bad += 1
            log.warning("skipped a bad trigger in config.yaml: %r", raw)
        else:
            good.append(t)
    with _lock:
        _triggers, _bad = good, bad
        _last.clear()
        _fired_on.clear()
    return good


def _get() -> list[dict]:
    if _triggers is None:
        load()
    return _triggers or []


def reset() -> None:
    """Forget everything (tests)."""
    global _triggers, _bad, _paused
    with _lock:
        _triggers, _bad, _paused = None, 0, False
        _last.clear()
        _fired_on.clear()


# ---------- sensors (Windows; each returns None when it can't tell) ----------
def running_apps() -> set[str] | None:
    try:
        import psutil

        out = set()
        for p in psutil.process_iter(["name"]):
            n = _norm_app(p.info.get("name"))
            if n:
                out.add(n)
        return out
    except Exception:
        return None


def wifi_ssid() -> str | None:
    """Connected Wi-Fi name, "" when not connected, None when unknown."""
    try:
        from . import network

        info = network.wifi_info()
    except Exception:
        return None
    if not info:
        return None
    if info.get("state") and info["state"] != "connected":
        return ""
    return info.get("ssid") or ""


def charger_state() -> str | None:
    try:
        import psutil

        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None or b.power_plugged is None:
        return None  # desktop PC or unknown
    return "plugged" if b.power_plugged else "unplugged"


# ---------- describe ----------
def describe(t: dict) -> str:
    k, v = t["kind"], t["value"]
    if k == "app_opens":
        when = f"when {v} opens"
    elif k == "app_closes":
        when = f"when {v} closes"
    elif k == "wifi":
        when = f"when I join the {v} Wi-Fi"
    elif k == "charger":
        when = "when the charger is plugged in" if v == "plugged" else "when the charger is unplugged"
    else:
        when = f"at {_say_time(v)} {_say_days(t.get('days') or list(range(7)))}"
    label = f"{t['name']}: " if t.get("name") else ""
    return f"{label}{when}, {', then '.join(t['do'])}"


def _default_say(t: dict) -> str:
    k, v = t["kind"], t["value"]
    if k == "app_opens":
        return f"{v} opened."
    if k == "app_closes":
        return f"{v} closed."
    if k == "wifi":
        return f"Joined {v} Wi-Fi."
    if k == "charger":
        return "Charger plugged in." if v == "plugged" else "Charger unplugged."
    return f"It's {_say_time(v)}."


# ---------- check loop ----------
def _app_seen(t: dict, apps: set[str]) -> bool:
    for a in t["aliases"]:
        for p in apps:
            if p == a or (len(a) >= 4 and a in p):
                return True
    return False


def _due(now: float | None = None, sense: dict | None = None) -> list[dict]:
    """Compare with the last state; return triggers that should fire now. Updates state.
    `sense` (tests) = {"apps": set|None, "wifi": str|None, "charger": str|None}."""
    trig = _get()
    if not trig:
        return []
    now = time.time() if now is None else now
    kinds = {t["kind"] for t in trig}
    if sense is None:
        sense = {}
        if kinds & {"app_opens", "app_closes"}:
            sense["apps"] = running_apps()
        if "wifi" in kinds:
            sense["wifi"] = wifi_ssid()
        if "charger" in kinds:
            sense["charger"] = charger_state()
    fire: list[dict] = []
    with _lock:
        prev = dict(_last)
        today = dt.datetime.fromtimestamp(now)
        for i, t in enumerate(trig):
            k = t["kind"]
            if k in ("app_opens", "app_closes"):
                cur, old = sense.get("apps"), prev.get("apps")
                if cur is None or old is None:
                    continue
                was, now_on = _app_seen(t, old), _app_seen(t, cur)
                if (k == "app_opens" and now_on and not was) or (k == "app_closes" and was and not now_on):
                    fire.append(t)
            elif k == "wifi":
                cur, old = sense.get("wifi"), prev.get("wifi")
                if cur is None or old is None:
                    continue
                if cur.lower() == t["value"].lower() and old.lower() != cur.lower():
                    fire.append(t)
            elif k == "charger":
                cur, old = sense.get("charger"), prev.get("charger")
                if cur is None or old is None:
                    continue
                if cur == t["value"] and old != cur:
                    fire.append(t)
            else:  # time
                if today.weekday() not in (t.get("days") or range(7)):
                    continue
                h, m = map(int, t["value"].split(":"))
                target = today.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
                key = today.date().isoformat()
                if 0 <= now - target <= TIME_WINDOW and _fired_on.get(i) != key:
                    _fired_on[i] = key
                    fire.append(t)
        # remember the new state (unknown readings keep the old one)
        for key in ("apps", "wifi", "charger"):
            if sense.get(key) is not None:
                _last[key] = sense[key]
        if _paused:
            return []  # state still moves on, so resuming doesn't fire old changes
    return fire


def _run(t: dict) -> None:
    say = t.get("say", _default_say(t))
    try:
        if say:
            notify(say)
    except Exception:
        pass
    for step in t["do"]:
        if runner is None:
            log.warning("trigger fired but no runner is set: %s", step)
            return
        try:
            reply = runner(step)
            if isinstance(reply, str) and reply.strip():
                notify(reply)
        except Exception:
            log.exception("trigger step failed: %r", step)


def check(now: float | None = None, sense: dict | None = None) -> list[dict]:
    """One tick: find due triggers and run their steps. Returns the fired triggers."""
    fired = _due(now, sense)
    for t in fired:
        _run(t)
    return fired


def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            check()
        except Exception:
            log.exception("trigger check failed")


def start(runner=None, notify=None) -> threading.Thread | None:  # noqa: A002 - names match the spec
    """Start the background thread. main.py: triggers.start(runner=..., notify=io.say).
    Does nothing (returns None) when there are no triggers in config.yaml."""
    global _thread
    g = globals()
    if runner is not None:
        g["runner"] = runner
    if notify is not None:
        g["notify"] = notify
    if not _get():
        return None
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="jarvis-triggers", daemon=True)
        _thread.start()
    return _thread


def stop() -> None:
    _stop.set()


def is_paused() -> bool:
    return _paused


# ---------- handler ----------
def triggers(args: dict) -> str:
    global _paused
    action = str((args or {}).get("action") or "list").lower().strip()
    if action in ("pause", "stop", "off", "disable"):
        with _lock:
            _paused = True
        return "Triggers paused. Say resume triggers to turn them back on."
    if action in ("resume", "start", "on", "enable"):
        with _lock:
            _paused = False
        n = len(_get())
        if not n:
            return "Triggers are on, but you have none. Add them under triggers in config.yaml."
        return "Triggers are on again."
    load()  # pick up config.yaml edits
    items = _get()
    extra = f" I skipped {_bad} broken one{'s' if _bad != 1 else ''} in config.yaml." if _bad else ""
    if not items:
        return "You have no triggers. Add them under triggers in config.yaml." + extra
    head = f"You have {len(items)} trigger{'s' if len(items) != 1 else ''}"
    body = "; ".join(describe(t) for t in items)
    state = " Triggers are paused." if _paused else ""
    return f"{head}: {body}.{state}{extra}"


# ---------- NLU ----------
_T = r"(?:my\s+|the\s+|all\s+)?(?:triggers|automations)"
_LIST_RE = re.compile(rf"^(?:list|show|tell me|read|what are)\s+{_T}$|^what\s+{_T}\s+do i have$|^{_T}$")
_PAUSE_RE = re.compile(rf"^(?:pause|stop|disable|turn off|switch off)\s+{_T}$|^(?:(?:turn|switch)\s+)?{_T}\s+(?:off|pause)$")
_RESUME_RE = re.compile(rf"^(?:resume|restart|start|enable|turn on|switch on|unpause)\s+{_T}(?:\s+again)?$|^(?:(?:turn|switch)\s+)?{_T}\s+on(?:\s+again)?$")


def parse(text: str):
    """'list my triggers' / 'pause triggers' / 'resume triggers' -> ('triggers', {...}) or None."""
    t = re.sub(r"[^a-z' ]", " ", (text or "").lower())
    t = re.sub(r"^(?:please|jarvis|hey jarvis)\s+", "", re.sub(r"\s+", " ", t).strip())
    t = re.sub(r"\s+please$", "", t)
    if _LIST_RE.match(t):
        return "triggers", {"action": "list"}
    if _PAUSE_RE.match(t):
        return "triggers", {"action": "pause"}
    if _RESUME_RE.match(t):
        return "triggers", {"action": "resume"}
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "triggers": {
        "description": "Automatic triggers from config.yaml ('when Zoom opens, do X', Wi-Fi joins, "
                       "charger plugged/unplugged, time of day). List them, pause them all, or resume them.",
        "properties": {
            "action": {"type": "string", "enum": ["list", "pause", "resume"]},
        },
        "required": ["action"],
    },
}

HANDLERS = {
    "triggers": triggers,
}
