"""Watchers (piece BB): one-off "tell me when ..." watches.

Voice:
    "tell me when my download finishes"      -> watch {what: download}
    "tell me when google.com is back"        -> watch {what: website, target: "google.com"}
    "tell me when battery is 80 percent"     -> watch {what: battery, value: 80}
    "tell me when Zoom closes"               -> watch {what: app_closed, target: "zoom"}
    "tell me when the CPU is idle"           -> watch {what: cpu_idle, value?: 10}
    "what are you watching"                  -> watches {action: list}
    "stop watching" / "stop watching Zoom"   -> watches {action: cancel, target?}

Each watch is checked by one background thread, spoken ONCE, then removed.
Different from triggers.py (fixed rules from config that run actions) and monitor.py (fixed alerts).
It reuses triggers.running_apps / _app_aliases / _app_seen for apps and recent.folder_path for Downloads.

Checks:
- download: done when the Downloads folder has no partial files (.crdownload, .part, .partial,
  .opdownload) left. Says the newest finished file. No partial file after 2 minutes -> says so, stops.
- website: HTTP GET every 60 s; any 2xx/3xx answer = up. Gives up after 6 hours.
- battery: reaches N% (going up if it is now below N, going down if above). Gives up after 12 hours.
- app_closed: no process of that app is left. Gives up after 12 hours.
- cpu_idle: CPU under N% (default 10) for 2 minutes in a row. Gives up after 12 hours.

Wiring: merge CATALOG and HANDLERS. main.py: `watchers.set_notifier(io.say)`.
`watches {action: list}` is info. Nothing risky. No new packages (psutil, urllib only).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger("jarvis.watchers")

TICK = 5.0  # seconds between checks of the thread
WEBSITE_EVERY = 60.0
WEBSITE_MAX = 6 * 3600.0
LONG_MAX = 12 * 3600.0
DOWNLOAD_WAIT = 120.0  # how long to wait for a download to start
CPU_IDLE_SECONDS = 120.0
CPU_IDLE_PERCENT = 10.0
MAX_WATCHES = 10
PARTIAL_EXT = (".crdownload", ".part", ".partial", ".opdownload")
KINDS = ("download", "website", "battery", "app_closed", "cpu_idle")

notify: Callable[[str], None] = print

_lock = threading.Lock()
_watches: list[dict] = []
_thread: threading.Thread | None = None
_stop = threading.Event()
_next_id = 1


def set_notifier(fn: Callable[[str], None]) -> None:
    global notify
    notify = fn or print


def reset() -> None:
    """Remove all watches (tests)."""
    global _next_id
    with _lock:
        _watches.clear()
        _next_id = 1


# ---------- sensors (small, so tests can replace them) ----------
def downloads_dir() -> str:
    try:
        from .recent import folder_path

        return folder_path("downloads")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Downloads")


def _list_dir(folder: str) -> list[tuple[str, float]]:
    """(name, modified time) of files in the folder, top level only."""
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file():
                        out.append((e.name, e.stat().st_mtime))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _is_partial(name: str) -> bool:
    return name.lower().endswith(PARTIAL_EXT)


def battery() -> tuple[float, bool | None] | None:
    """(percent, plugged) or None when there is no battery."""
    try:
        import psutil

        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None or b.percent is None:
        return None
    return float(b.percent), b.power_plugged


def cpu_percent() -> float | None:
    try:
        import psutil

        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


def running_apps() -> set[str] | None:
    from .triggers import running_apps as ra

    return ra()


def site_up(url: str) -> bool:
    """True when the site answers 2xx/3xx within 10 s."""
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisVoiceAssistant"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - only http(s), checked in _clean_url
            return 200 <= r.status < 400
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 400
    except Exception:
        return False


# ---------- helpers ----------
def _clean_url(target: str) -> tuple[str, str] | None:
    """Spoken site -> (url, host to say). None if it does not look like a site."""
    t = str(target or "").strip().lower()
    t = re.sub(r"\s+dot\s+", ".", t)
    t = re.sub(r"^(the\s+)?(website|site|page)\s+", "", t).strip(" ,'\"")
    t = re.sub(r"\s+", "", t)
    if not t:
        return None
    if "://" not in t:
        t = "https://" + t
    try:
        p = urllib.parse.urlsplit(t)
    except ValueError:
        return None
    host = (p.hostname or "").strip(".")
    if p.scheme not in ("http", "https") or not host:
        return None
    if "." not in host and host != "localhost":
        host += ".com"  # "tell me when google is back"
    if not re.fullmatch(r"[a-z0-9.-]{1,253}", host):
        return None
    netloc = host + (f":{p.port}" if p.port else "")
    url = urllib.parse.urlunsplit((p.scheme, netloc, p.path or "/", p.query, ""))
    return url, host


def _percent(value) -> int | None:
    try:
        v = int(round(float(str(value).strip().rstrip("%").strip())))
    except (TypeError, ValueError):
        return None
    return v if 1 <= v <= 100 else None


def _pretty_app(name: str) -> str:
    n = re.split(r"[\\/]", str(name))[-1]
    n = re.sub(r"(?i)\.exe$", "", n).strip()
    return n[:1].upper() + n[1:] if n else n


def _apps_cfg() -> dict:
    try:
        from jarvis.config import load_config

        return load_config().get("apps") or {}
    except Exception:
        return {}


def label(w: dict) -> str:
    what = w["what"]
    if what == "download":
        return "your download"
    if what == "website":
        return f"{w['host']} to come back"
    if what == "battery":
        return f"the battery to reach {w['value']} percent"
    if what == "app_closed":
        return f"{w['name']} to close"
    return "the CPU to go idle"


def _same(a: dict, b: dict) -> bool:
    return a["what"] == b["what"] and label(a) == label(b)


def _add(w: dict) -> str | None:
    """Add a watch. Returns an error reply or None."""
    global _next_id
    with _lock:
        if any(_same(w, x) for x in _watches):
            return f"I'm already waiting for {label(w)}."
        if len(_watches) >= MAX_WATCHES:
            return f"I can watch {MAX_WATCHES} things at once. Say 'stop watching' to clear them."
        w["id"] = _next_id
        _next_id += 1
        _watches.append(w)
    _ensure_thread()
    return None


# ---------- start a watch ----------
def _start_download(now: float) -> str:
    folder = downloads_dir()
    files = _list_dir(folder)
    busy = [n for n, _ in files if _is_partial(n)]
    w = {"what": "download", "folder": folder, "started": now, "seen": bool(busy), "next": now}
    err = _add(w)
    if err:
        return err
    if busy:
        return "Okay, I'll tell you when your download finishes." if len(busy) == 1 else \
            f"Okay, I'll tell you when your {len(busy)} downloads finish."
    return "I don't see a download yet. I'll watch for 2 minutes for one to start."


def _start_website(target, now: float) -> str:
    got = _clean_url(target)
    if not got:
        return "Which website should I watch? Say something like google.com."
    url, host = got
    if site_up(url):
        return f"{host} is up right now."
    err = _add({"what": "website", "url": url, "host": host, "started": now, "next": now + WEBSITE_EVERY})
    return err or f"{host} is down now. I'll check every minute and tell you when it's back."


def _start_battery(value, now: float) -> str:
    n = _percent(value)
    if n is None:
        return "What battery level should I wait for? Say a percent, like 80."
    b = battery()
    if b is None:
        return "I can't read a battery on this PC."
    pct, _ = b
    if round(pct) == n:
        return f"The battery is already at {n} percent."
    up = pct < n
    err = _add({"what": "battery", "value": n, "up": up, "started": now, "next": now})
    if err:
        return err
    way = "charges up to" if up else "drops to"
    return f"Okay. The battery is at {round(pct)} percent. I'll tell you when it {way} {n} percent."


def _start_app(target, now: float) -> str:
    name = str(target or "").strip()
    if not name:
        return "Which app should I watch?"
    from .triggers import _app_aliases, _app_seen

    aliases = _app_aliases(name, _apps_cfg())
    if not aliases:
        return "Which app should I watch?"
    w = {"what": "app_closed", "name": _pretty_app(name), "aliases": aliases, "started": now, "next": now}
    apps = running_apps()
    if apps is None:
        return "I can't see running apps right now."
    if not _app_seen(w, apps):
        return f"{w['name']} is not running."
    err = _add(w)
    return err or f"Okay, I'll tell you when {w['name']} closes."


def _start_cpu(value, now: float) -> str:
    n = _percent(value) if value not in (None, "") else int(CPU_IDLE_PERCENT)
    if n is None:
        n = int(CPU_IDLE_PERCENT)
    if cpu_percent() is None:  # first call also primes psutil's counter
        return "I can't read the CPU right now."
    err = _add({"what": "cpu_idle", "value": n, "below_since": None, "started": now, "next": now + TICK})
    return err or f"Okay, I'll tell you when the CPU stays under {n} percent for 2 minutes."


def watch(args: dict) -> str:
    what = str(args.get("what") or "").lower().strip().replace(" ", "_")
    what = {"downloads": "download", "site": "website", "web": "website", "url": "website",
            "app": "app_closed", "app_close": "app_closed", "close": "app_closed",
            "cpu": "cpu_idle", "idle": "cpu_idle", "render": "cpu_idle"}.get(what, what)
    target = args.get("target")
    value = args.get("value")
    now = time.time()
    if what == "download":
        return _start_download(now)
    if what == "website":
        return _start_website(target, now)
    if what == "battery":
        return _start_battery(value if value not in (None, "") else target, now)
    if what == "app_closed":
        return _start_app(target, now)
    if what == "cpu_idle":
        return _start_cpu(value, now)
    return "I can watch a download, a website, the battery, an app closing, or the CPU going idle."


# ---------- list / cancel ----------
def watches(args: dict) -> str:
    action = str(args.get("action") or "list").lower().strip()
    target = str(args.get("target") or "").lower().strip()
    with _lock:
        current = list(_watches)
    if action in ("cancel", "stop", "clear", "remove"):
        if not current:
            return "I'm not watching anything."
        if target and target not in ("all", "everything"):
            pick = [w for w in current if target in label(w).lower() or target in w["what"].replace("_", " ")]
            if not pick:
                return f"I'm not watching {target}."
        else:
            pick = current
        with _lock:
            for w in pick:
                if w in _watches:
                    _watches.remove(w)
        if len(pick) == 1:
            return f"Stopped waiting for {label(pick[0])}."
        return f"Stopped {len(pick)} watches."
    if not current:
        return "I'm not watching anything."
    names = [label(w) for w in current]
    if len(names) > 1:
        names = names[:-1] + ["and " + names[-1]]
    return "I'm waiting for " + (", " if len(names) > 2 else " ").join(names) + "."


# ---------- checks ----------
def _check_download(w: dict, now: float) -> str | None:
    files = _list_dir(w["folder"])
    if any(_is_partial(n) for n, _ in files):
        w["seen"] = True
        return None if now - w["started"] < LONG_MAX else "Your download is still going after 12 hours. I stopped watching."
    if not w["seen"]:
        if now - w["started"] >= DOWNLOAD_WAIT:
            return "No download started, so I stopped watching."
        return None
    done = [(n, t) for n, t in files if t >= w["started"] - 5]
    if done:
        name = max(done, key=lambda x: x[1])[0]
        return f"Your download finished: {name}."
    return "Your download stopped. It may have been cancelled."


def _check_website(w: dict, now: float) -> str | None:
    if site_up(w["url"]):
        return f"{w['host']} is back up."
    if now - w["started"] >= WEBSITE_MAX:
        return f"{w['host']} is still down after 6 hours. I stopped watching."
    w["next"] = now + WEBSITE_EVERY
    return None


def _check_battery(w: dict, now: float) -> str | None:
    b = battery()
    if b is not None:
        pct = round(b[0])
        if (w["up"] and pct >= w["value"]) or (not w["up"] and pct <= w["value"]):
            return f"The battery is at {pct} percent."
    if now - w["started"] >= LONG_MAX:
        return f"The battery did not reach {w['value']} percent in 12 hours. I stopped watching."
    return None


def _check_app(w: dict, now: float) -> str | None:
    from .triggers import _app_seen

    apps = running_apps()
    if apps is not None and not _app_seen(w, apps):
        return f"{w['name']} has closed."
    if now - w["started"] >= LONG_MAX:
        return f"{w['name']} is still open after 12 hours. I stopped watching."
    return None


def _check_cpu(w: dict, now: float) -> str | None:
    c = cpu_percent()
    if c is not None and c < w["value"]:
        if w["below_since"] is None:
            w["below_since"] = now
        elif now - w["below_since"] >= CPU_IDLE_SECONDS:
            return "The CPU is idle now. Your task may be done."
    else:
        w["below_since"] = None
    if now - w["started"] >= LONG_MAX:
        return "The CPU stayed busy for 12 hours. I stopped watching."
    return None


_CHECKS = {"download": _check_download, "website": _check_website, "battery": _check_battery,
           "app_closed": _check_app, "cpu_idle": _check_cpu}


def _private() -> bool:
    """Locked or guest mode: don't say file names out loud (same rule as notifications)."""
    try:
        from . import security

        return bool(security.is_locked() or security.is_guest())
    except Exception:
        return False


def tick(now: float | None = None) -> list[str]:
    """Check every due watch once. Finished watches are removed and their messages spoken.
    Returns the messages (tests call this directly)."""
    now = time.time() if now is None else now
    with _lock:
        due = [w for w in _watches if w.get("next", 0) <= now]
    said = []
    for w in due:
        try:
            msg = _CHECKS[w["what"]](w, now)
        except Exception:
            log.exception("watch check failed")
            msg = None
        if msg is None:
            continue
        with _lock:
            if w not in _watches:  # cancelled while checking
                continue
            _watches.remove(w)
        said.append(msg)
        try:
            notify("One of your watches has finished." if _private() else msg)
        except Exception:
            log.exception("notify failed")
    return said


# ---------- thread ----------
def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            tick()
        except Exception:
            log.exception("watchers tick failed")


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="jarvis-watchers", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None


CATALOG: dict[str, dict] = {
    "watch": {
        "description": "Watch something once and speak when it happens: a download finishing, a website "
                       "coming back up, the battery reaching a percent, an app closing, or the CPU going idle "
                       "(e.g. a render finished).",
        "properties": {
            "what": {"type": "string", "enum": list(KINDS)},
            "target": {"type": "string",
                       "description": "Website (e.g. google.com) for website, app name for app_closed."},
            "value": {"type": "integer",
                      "description": "Battery percent for battery (1-100), or CPU percent limit for cpu_idle "
                                     "(default 10)."},
        },
        "required": ["what"],
    },
    "watches": {
        "description": "List what Jarvis is watching, or stop watching (all, or one by name).",
        "properties": {
            "action": {"type": "string", "enum": ["list", "cancel"]},
            "target": {"type": "string", "description": "For cancel: which watch, e.g. zoom, download, "
                                                        "battery. Leave out to stop all."},
        },
        "required": [],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"watch": watch, "watches": watches}
