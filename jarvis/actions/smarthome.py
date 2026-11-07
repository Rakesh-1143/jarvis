"""Piece U: smart home through Home Assistant (REST API).

Intents:
  device {name, action: on|off|toggle|set|status|lock|unlock|open|close, value?}
  scene  {name}

Config (config.yaml):
  home_assistant:
    url: "http://homeassistant.local:8123"
    token: ""            # better: set env var HASS_TOKEN (long-lived access token)
    verify_ssl: true     # false only for a self-signed https certificate on your own network
    aliases: {}          # spoken name -> entity_id, e.g. {"ac": "climate.living_room"}
    all_off_domains: [light, fan, media_player]   # what "turn off everything" turns off

Risky (ask yes first): unlock a lock, open a garage/gate/door cover, "turn off everything".
The handler never does a risky thing without args["confirm"] is True.
No extra packages: urllib + json only. The token is never spoken, logged or put in a reply.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

TIMEOUT = 6
CACHE_SECONDS = 20
MATCH_CUTOFF = 0.6

NOT_SET_UP = ("Smart home is not set up. Add home_assistant url in config.yaml "
              "and set the HASS_TOKEN environment variable.")
NO_REACH = "I can't reach Home Assistant right now."
BAD_TOKEN = "Home Assistant refused my token. Please make a new long-lived access token."

# Only these domains are matched by name.
DOMAINS = ("light", "switch", "fan", "climate", "lock", "cover", "media_player", "input_boolean",
           "sensor", "binary_sensor", "scene", "script")
DEVICE_DOMAINS = tuple(d for d in DOMAINS if d not in ("scene", "script"))

# Spoken word -> domain it hints at.
_HINTS = {
    "light": "light", "lights": "light", "lamp": "light", "bulb": "light",
    "fan": "fan",
    "ac": "climate", "a/c": "climate", "air conditioner": "climate", "aircon": "climate",
    "heater": "climate", "thermostat": "climate", "heating": "climate",
    "lock": "lock",
    "garage": "cover", "gate": "cover", "blind": "cover", "blinds": "cover", "curtain": "cover",
    "curtains": "cover", "shutter": "cover", "shutters": "cover",
    "tv": "media_player", "speaker": "media_player",
    "plug": "switch", "socket": "switch", "switch": "switch",
    "temperature": "sensor", "humidity": "sensor",
}
_EVERYTHING = {"everything", "all", "all devices", "every device", "the whole house", "whole house",
               "the house", "all the devices"}
_ALL_LIGHTS = {"all lights", "all the lights", "every light", "lights"}
_RISKY_COVER_CLASSES = {"garage", "gate", "door"}

_cache: dict = {"t": 0.0, "states": []}


# ---------- settings + HTTP ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("home_assistant") or {}
    except Exception:
        cfg = {}
    url = str(cfg.get("url") or os.environ.get("HASS_URL") or "").strip().rstrip("/")
    token = str(os.environ.get("HASS_TOKEN") or cfg.get("token") or "").strip()
    aliases = {_norm(k): str(v) for k, v in (cfg.get("aliases") or {}).items()}
    domains = cfg.get("all_off_domains") or ["light", "fan", "media_player"]
    domains = [d for d in domains if d in DEVICE_DOMAINS and d not in ("lock", "cover", "sensor", "binary_sensor")]
    scripts = {str(x).strip().lower() for x in (cfg.get("allowed_scripts") or [])}
    return {"url": url, "token": token, "verify_ssl": cfg.get("verify_ssl", True) is not False,
            "aliases": aliases, "all_off_domains": domains, "allowed_scripts": scripts}


class _HAError(Exception):
    """Message is safe to speak."""


def _request(method: str, path: str, body: dict | None = None):
    s = _settings()
    if not s["url"] or not s["token"]:
        raise _HAError(NOT_SET_UP)
    if not s["url"].startswith(("http://", "https://")):
        raise _HAError("The Home Assistant url must start with http or https.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(s["url"] + path, data=data, method=method, headers={
        "Authorization": "Bearer " + s["token"], "Content-Type": "application/json"})
    ctx = None
    if s["url"].startswith("https://") and not s["verify_ssl"]:
        ctx = ssl._create_unverified_context()  # user chose this for a self-signed cert at home
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise _HAError(BAD_TOKEN) from None
        if e.code == 400:
            raise _HAError("Home Assistant did not accept that.") from None
        raise _HAError(NO_REACH) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise _HAError(NO_REACH) from None
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return None


def _states(refresh: bool = False) -> list[dict]:
    if refresh or not _cache["states"] or time.monotonic() - _cache["t"] > CACHE_SECONDS:
        data = _request("GET", "/api/states")
        _cache["states"] = [x for x in (data or []) if isinstance(x, dict) and "entity_id" in x]
        _cache["t"] = time.monotonic()
    return _cache["states"]


def _call(domain: str, service: str, data: dict) -> None:
    _request("POST", f"/api/services/{domain}/{service}", data)
    _cache["t"] = 0.0  # states changed


def clear_cache() -> None:
    _cache["t"], _cache["states"] = 0.0, []


# ---------- name matching ----------

def _norm(text) -> str:
    t = str(text or "").lower().replace("_", " ")
    t = re.sub(r"[^a-z0-9/ ]+", " ", t)
    t = re.sub(r"\b(the|my|a|an|please)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _fname(st: dict) -> str:
    return str((st.get("attributes") or {}).get("friendly_name") or st["entity_id"].split(".", 1)[-1])


def _hint(name: str) -> str | None:
    n = _norm(name)
    for word in sorted(_HINTS, key=len, reverse=True):
        if re.search(rf"(^| ){re.escape(word)}( |$)", n):
            return _HINTS[word]
    return None


def _score(name: str, st: dict, hint: str | None) -> float:
    n = _norm(name)
    cands = {_norm(_fname(st)), _norm(st["entity_id"].split(".", 1)[-1])}
    best = 0.0
    for c in cands:
        if not c:
            continue
        if c == n:
            return 2.0
        r = difflib.SequenceMatcher(None, n, c).ratio()
        nw, cw = set(n.split()), set(c.split())
        if nw and cw:
            r = max(r, len(nw & cw) / len(nw | cw) + (0.2 if nw <= cw or cw <= nw else 0))
        best = max(best, r)
    d = _domain(st["entity_id"])
    if hint and d == hint:
        best += 0.15
    elif hint == "cover" and d == "lock" or hint == "lock" and d == "cover":
        best += 0.05  # "door" words
    return best


def find(name: str, domains: tuple[str, ...] = DEVICE_DOMAINS) -> tuple[dict | None, list[dict]]:
    """Best entity for a spoken name -> (entity or None, close others when unsure)."""
    s = _settings()
    states = [x for x in _states() if _domain(x["entity_id"]) in domains]
    alias = s["aliases"].get(_norm(name))
    if alias:
        for st in states:
            if st["entity_id"] == alias:
                return st, []
    hint = _hint(name)
    scored = sorted(((_score(name, st, hint), st) for st in states), key=lambda x: -x[0])
    if not scored or scored[0][0] < MATCH_CUTOFF:
        return None, []
    top = scored[0][0]
    if top >= 2.0:
        return scored[0][1], []
    close = [st for sc, st in scored[1:3] if top - sc < 0.03]
    return scored[0][1], close


# ---------- helpers ----------

def _num(value) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(value if value is not None else ""))
    return float(m.group()) if m else None


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _is_risky_cover(st: dict | None, name: str) -> bool:
    if st is not None:
        if _domain(st["entity_id"]) != "cover":
            return False
        dc = str((st.get("attributes") or {}).get("device_class") or "")
        if dc in _RISKY_COVER_CLASSES:
            return True
    return bool(re.search(r"\b(garage|gate|door)\b", _norm(name)))


def _action(args: dict) -> str:
    a = str(args.get("action") or "").lower().strip()
    return {"turn_on": "on", "turn_off": "off", "switch on": "on", "switch off": "off",
            "check": "status", "state": "status"}.get(a, a)


def _status_text(st: dict) -> str:
    d, name, state = _domain(st["entity_id"]), _fname(st), str(st.get("state", "unknown"))
    a = st.get("attributes") or {}
    if state in ("unavailable", "unknown"):
        return f"{name} is {state} right now."
    if d == "light" and state == "on" and a.get("brightness") is not None:
        return f"{name} is on at {round(int(a['brightness']) * 100 / 255)} percent."
    if d == "fan" and state == "on" and a.get("percentage") is not None:
        return f"{name} is on at {_fmt(float(a['percentage']))} percent."
    if d == "climate":
        parts = [f"{name} is {state.replace('_', ' ')}"]
        if a.get("temperature") is not None:
            parts.append(f"set to {_fmt(float(a['temperature']))} degrees")
        if a.get("current_temperature") is not None:
            parts.append(f"room is {_fmt(float(a['current_temperature']))} degrees")
        return ", ".join(parts) + "."
    if d in ("sensor",):
        unit = str(a.get("unit_of_measurement") or "")
        unit = {"°C": "degrees", "°F": "degrees", "%": "percent"}.get(unit, unit)
        return f"{name} is {state} {unit}".strip() + "."
    if d == "binary_sensor":
        return f"{name} is {'on' if state == 'on' else 'off'}."
    return f"{name} is {state.replace('_', ' ')}."


# ---------- risky ----------

def risky_text(args: dict) -> str | None:
    """Words for 'are you sure you want to ...?' or None if not risky. Never raises."""
    name, action = str(args.get("name") or ""), _action(args)
    if _norm(name) in _EVERYTHING and action == "off":
        return "turn off everything in the house"
    if action == "unlock":
        return f"unlock {name or 'the lock'}"
    if action == "set" and (_num(args.get("value")) or 0) <= 0:
        return None
    if action in ("open", "on", "off", "toggle", "set"):
        st = None
        try:
            st, _ = find(name)
        except Exception:
            # Can't look it up (Home Assistant down): ask anyway for risky words, so "yes" is always remembered.
            if action in ("open", "off") and (_is_risky_cover(None, name) or re.search(r"\block\b", _norm(name))):
                return f"{'open' if action == 'open' else 'unlock'} {name}"
        if st is not None and _domain(st["entity_id"]) == "lock":
            return {"open": f"open {_fname(st)}", "off": f"unlock {_fname(st)}"}.get(action)
        if action != "off" and _is_risky_cover(st, name):
            if st is None and action != "open":
                return None
            return f"open {_fname(st) if st else name}"
    return None


def needs_confirm(args: dict) -> bool:
    return risky_text(args) is not None


# ---------- handlers ----------

def device(args: dict) -> str:
    try:
        return _device(args)
    except _HAError as e:
        return str(e)


def _all_off(args: dict, domains: list[str], question: str | None) -> str:
    if question and args.get("confirm") is not True:
        return f"Are you sure you want to {question}? Say yes to confirm."
    if not domains:
        return "Nothing is set to turn off."
    for d in domains:
        _call(d, "turn_off", {"entity_id": "all"})
    if domains == ["light"]:
        return "Turned off all the lights."
    return "Turned off everything."


def _device(args: dict) -> str:
    name = str(args.get("name") or "").strip()
    action = _action(args)
    if not name:
        return "Which device?"
    if action not in ("on", "off", "toggle", "set", "status", "lock", "unlock", "open", "close"):
        return "I can turn devices on or off, set them, lock, unlock, open, close, or tell you their state."

    n = _norm(name)
    if n in _EVERYTHING:
        if action == "off":
            return _all_off(args, _settings()["all_off_domains"], "turn off everything in the house")
        if action != "status":
            return "For safety I only turn everything off, not on."
    if n in _ALL_LIGHTS and action in ("on", "off"):
        if action == "off":
            return _all_off(args, ["light"], None)
        _call("light", "turn_on", {"entity_id": "all"})
        return "Turned on all the lights."

    st, close = find(name)
    if st is None:
        return f"I couldn't find a device called {name} in Home Assistant."
    if close:
        names = ", ".join(_fname(x) for x in [st, *close])
        return f"I found more than one: {names}. Please say the full name."
    eid, d, fname = st["entity_id"], _domain(st["entity_id"]), _fname(st)
    attrs = st.get("attributes") or {}
    target = {"entity_id": eid}

    if action == "status":
        return _status_text(st)

    if d in ("sensor", "binary_sensor"):
        return _status_text(st)

    # ----- locks -----
    if d == "lock":
        if action in ("on", "lock", "close"):
            _call("lock", "lock", target)
            return f"Locked {fname}."
        if action in ("off", "unlock", "toggle", "open"):
            if action == "toggle":
                return f"Please say lock or unlock {fname}."
            service = "open" if action == "open" else "unlock"
            if args.get("confirm") is not True:
                return f"Are you sure you want to {service} {fname}? Say yes to confirm."
            _call("lock", service, target)
            return f"{'Opened' if service == 'open' else 'Unlocked'} {fname}."
        return f"I can lock or unlock {fname}."

    # ----- covers (blinds, garage, gate) -----
    if d == "cover":
        if action == "toggle":
            action = "close" if st.get("state") in ("open", "opening") else "open"
        if action in ("on", "open"):
            if _is_risky_cover(st, name) and args.get("confirm") is not True:
                return f"Are you sure you want to open {fname}? Say yes to confirm."
            _call("cover", "open_cover", target)
            return f"Opening {fname}."
        if action in ("off", "close", "lock"):
            _call("cover", "close_cover", target)
            return f"Closing {fname}."
        if action == "set":
            v = _num(args.get("value"))
            if v is None or not 0 <= v <= 100:
                return "Say a position from 0 to 100 percent."
            if v > 0 and _is_risky_cover(st, name) and args.get("confirm") is not True:
                return f"Are you sure you want to open {fname}? Say yes to confirm."
            _call("cover", "set_cover_position", {**target, "position": int(v)})
            return f"Set {fname} to {_fmt(v)} percent."
        return f"I can open or close {fname}."

    if action in ("lock", "unlock", "open", "close"):
        action = "on" if action == "open" else "off" if action == "close" else action
        if action in ("lock", "unlock"):
            return f"{fname} is not a lock."

    # ----- set a value -----
    if action == "set":
        v = _num(args.get("value"))
        if v is None:
            return f"What should I set {fname} to?"
        if d == "light":
            if not 0 <= v <= 100:
                return "Brightness goes from 0 to 100 percent."
            _call("light", "turn_on", {**target, "brightness_pct": int(v)})
            return f"Set {fname} to {_fmt(v)} percent."
        if d == "fan":
            if not 0 <= v <= 100:
                return "Fan speed goes from 0 to 100 percent."
            _call("fan", "set_percentage", {**target, "percentage": int(v)})
            return f"Set {fname} to {_fmt(v)} percent."
        if d == "climate":
            lo, hi = attrs.get("min_temp"), attrs.get("max_temp")
            if lo is not None and hi is not None and not float(lo) <= v <= float(hi):
                return f"{fname} can be set from {_fmt(float(lo))} to {_fmt(float(hi))} degrees."
            _call("climate", "set_temperature", {**target, "temperature": v})
            return f"Set {fname} to {_fmt(v)} degrees."
        if d == "media_player":
            if not 0 <= v <= 100:
                return "Volume goes from 0 to 100 percent."
            _call("media_player", "volume_set", {**target, "volume_level": round(v / 100, 2)})
            return f"Set {fname} volume to {_fmt(v)} percent."
        return f"I can't set a value on {fname}, only turn it on or off."

    # ----- on / off / toggle -----
    service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
    if d == "climate" and action == "toggle":
        service = "turn_off" if st.get("state") not in ("off", "unavailable") else "turn_on"
    _call(d, service, target)
    if action == "toggle":
        return f"Toggled {fname}."
    return f"Turned {'on' if action == 'on' else 'off'} {fname}."


def scene(args: dict) -> str:
    name = str(args.get("name") or "").strip()
    if not name:
        return "Which scene?"
    try:
        st, close = find(name, ("scene", "script"))
        if st is None:
            n = re.sub(r"\b(scene|mode|script)\b", " ", name, flags=re.I).strip()
            if n and n != name:
                st, close = find(n, ("scene", "script"))
        if st is None:
            return f"I couldn't find a scene called {name}."
        if close:
            return "I found more than one: " + ", ".join(_fname(x) for x in [st, *close]) + ". Which one?"
        d = _domain(st["entity_id"])
        if d == "script":  # a script can unlock doors or open the garage: only ones the user allowed
            allowed = _settings().get("allowed_scripts") or set()
            if st["entity_id"].lower() not in allowed and _fname(st).lower() not in allowed:
                return (f"For safety I only run scripts listed under home_assistant, allowed_scripts in config.yaml. "
                        f"{_fname(st)} is not there.")
        _call(d, "turn_on", {"entity_id": st["entity_id"]})
        return f"{'Started' if d == 'script' else 'Set'} {_fname(st)}."
    except _HAError as e:
        return str(e)


# ---------- wiring ----------

CATALOG: dict[str, dict] = {
    "device": {
        "description": ("Control a smart home device through Home Assistant: lights, plugs, fans, AC/heater, "
                        "locks, blinds, garage door, TV. on/off/toggle; set = brightness or fan percent, "
                        "AC temperature, blind position or TV volume (value); status = say its state "
                        "(e.g. 'is the door locked'). name 'everything' with off turns off the house. "
                        "Unlock, garage/gate open and 'everything off' ask the user to confirm."),
        "properties": {
            "name": {"type": "string", "description": "Spoken device name, e.g. 'bedroom light', 'AC', 'front door'."},
            "action": {"type": "string",
                       "enum": ["on", "off", "toggle", "set", "status", "lock", "unlock", "open", "close"]},
            "value": {"type": "number", "description": "For set: percent (0-100) or temperature in degrees."},
        },
        "required": ["name", "action"],
    },
    "scene": {
        "description": "Turn on a Home Assistant scene or run a script by name, e.g. 'movie night'.",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}

HANDLERS = {"device": device, "scene": scene}
