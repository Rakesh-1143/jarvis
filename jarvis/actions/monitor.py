"""Health alerts: low battery, full charge, CPU hot, disk low (piece I).

A background thread checks every `interval` seconds (psutil) and speaks once per
event (no spam). An event can fire again only after it has cleared.

Wiring:
- main.py: call `monitor.start(io.say)` once at start (`monitor.stop()` on exit is optional).
- intent `alerts {state: on|off, kind?: all|battery|cpu|disk}` -> HANDLERS["alerts"].

Config (all optional), in config.yaml:
    alerts:
      enabled: true        # alerts on at start
      interval: 60         # seconds between checks
      battery_low: 20      # percent, warn when below and not charging
      battery_full: 100    # percent, say when reached while charging
      cpu_high: 90         # percent
      cpu_minutes: 2       # CPU must stay high this long
      disk_low_gb: 5       # free space in GB
      disk_path: "C:\\"    # drive to watch
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable

DEFAULTS: dict = {
    "enabled": True,
    "interval": 60,
    "battery_low": 20,
    "battery_full": 100,
    "cpu_high": 90,
    "cpu_minutes": 2,
    "disk_low_gb": 5,
    "disk_path": "C:\\" if os.name == "nt" else "/",
}

KINDS = ("battery", "cpu", "disk")

_on: dict[str, bool] = {k: True for k in KINDS}
_fired: set[str] = set()  # events already spoken and not cleared yet
_cpu_since: float | None = None  # when CPU first went over the limit
_thread: threading.Thread | None = None
_stop = threading.Event()
_settings: dict = dict(DEFAULTS)


def settings(cfg: dict | None = None) -> dict:
    """Thresholds = DEFAULTS + config `alerts:`."""
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config()
        except Exception:
            cfg = {}
    user = cfg.get("alerts") or {}
    return {**DEFAULTS, **(user if isinstance(user, dict) else {})}


def reset() -> None:
    """Clear all state (used by tests and by start())."""
    global _cpu_since
    _fired.clear()
    _cpu_since = None
    for k in KINDS:
        _on[k] = True


# ---------- reading the laptop ----------
def read(ps=None, disk_path: str | None = None) -> dict:
    """One snapshot: battery %, plugged, cpu %, free disk GB. Missing parts are None."""
    if ps is None:
        import psutil as ps  # noqa: N813
    snap: dict = {"battery": None, "plugged": None, "cpu": None, "disk_free_gb": None}
    try:
        b = ps.sensors_battery()
        if b is not None:
            snap["battery"] = float(b.percent)
            snap["plugged"] = bool(b.power_plugged)
    except Exception:
        pass
    try:
        snap["cpu"] = float(ps.cpu_percent(interval=1))
    except Exception:
        pass
    try:
        snap["disk_free_gb"] = ps.disk_usage(disk_path or _settings["disk_path"]).free / 1024**3
    except Exception:
        pass
    return snap


# ---------- deciding what to say ----------
def _edge(name: str, active: bool, cleared: bool, msg: str, out: list[str]) -> None:
    """Speak once when `active` starts; re-arm only when `cleared`."""
    if active and name not in _fired:
        _fired.add(name)
        out.append(msg)
    elif cleared:
        _fired.discard(name)


def check(snap: dict, s: dict | None = None, now: float | None = None) -> list[str]:
    """Return the alert sentences for this snapshot (empty list = nothing new)."""
    global _cpu_since
    s = s or _settings
    now = time.monotonic() if now is None else now
    out: list[str] = []

    pct, plugged = snap.get("battery"), snap.get("plugged")
    if _on["battery"] and pct is not None and plugged is not None:
        low, full = float(s["battery_low"]), float(s["battery_full"])
        _edge("battery_low", pct < low and not plugged, plugged or pct >= low + 5,
              f"Battery is low, {round(pct)} percent. Please plug in the charger.", out)
        _edge("battery_full", pct >= full and plugged, not plugged or pct < full - 5,
              "Battery is fully charged. You can unplug the charger.", out)

    cpu = snap.get("cpu")
    if _on["cpu"] and cpu is not None:
        if cpu > float(s["cpu_high"]):
            if _cpu_since is None:
                _cpu_since = now
            long_enough = now - _cpu_since >= float(s["cpu_minutes"]) * 60
            _edge("cpu_high", long_enough, False,
                  f"CPU has been over {round(float(s['cpu_high']))} percent for "
                  f"{_minutes(s['cpu_minutes'])}. Something may be stuck.", out)
        else:
            _cpu_since = None
            _fired.discard("cpu_high")

    free = snap.get("disk_free_gb")
    if _on["disk"] and free is not None:
        limit = float(s["disk_low_gb"])
        _edge("disk_low", free < limit, free >= limit + 1,
              f"Disk space is low, only {free:.1f} gigabytes free.", out)
    return out


def _minutes(m) -> str:
    m = float(m)
    if m == 1:
        return "1 minute"
    return f"{m:g} minutes"


# ---------- background thread ----------
def _loop(say: Callable[[str], None], ps) -> None:
    while not _stop.is_set():
        try:
            if any(_on.values()):
                for msg in check(read(ps)):
                    say(msg)
        except Exception:
            pass  # never crash Jarvis because of an alert
        _stop.wait(max(5.0, float(_settings["interval"])))


def start(say: Callable[[str], None], cfg: dict | None = None, ps=None) -> threading.Thread | None:
    """Start the alert thread once. Returns the thread, or None if psutil is missing."""
    global _thread, _settings
    if _thread is not None and _thread.is_alive():
        return _thread
    _settings = settings(cfg)
    reset()
    if not _settings.get("enabled", True):
        for k in KINDS:
            _on[k] = False
    if ps is None:
        try:
            import psutil as ps  # noqa: N813
        except ImportError:
            return None
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(say, ps), name="jarvis-alerts", daemon=True)
    _thread.start()
    return _thread


def stop() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None


# ---------- voice command ----------
def alerts(args: dict) -> str:
    """'turn off battery alerts', 'turn on alerts'."""
    state = str(args.get("state") or "").lower()
    kind = str(args.get("kind") or "all").lower()
    if kind not in KINDS:
        kind = "all"
    if state not in ("on", "off"):
        live = [k for k in KINDS if _on[k]]
        if not live:
            return "All alerts are off."
        return "Alerts are on for " + ", ".join(live) + "."
    kinds = KINDS if kind == "all" else (kind,)
    for k in kinds:
        _on[k] = state == "on"
        if state == "off":
            _fired.difference_update({n for n in _fired if n.startswith(k)})
    what = "All alerts" if kind == "all" else f"{kind.capitalize()} alerts"
    return f"{what} turned {state}."


CATALOG: dict[str, dict] = {
    "alerts": {
        "description": "Turn laptop health alerts on or off (low battery, full charge, CPU hot, low disk). "
                       "Leave out state to say which alerts are on.",
        "properties": {
            "state": {"type": "string", "enum": ["on", "off"]},
            "kind": {"type": "string", "enum": ["all", "battery", "cpu", "disk"],
                     "description": "Which alerts. Default all."},
        },
        "required": [],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"alerts": alerts}
