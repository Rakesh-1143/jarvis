"""Piece AV: travel time, distance and directions (free OpenStreetMap services, no key).

Intents:
  travel_time {to, from?, mode?: driving|walking}            (info) "how long to drive to Hyderabad", "how far is X"
  directions  {to, from?, mode?: driving|walking|transit}    opens Google Maps directions in the browser

Services (free, no key; every error fails softly):
  geocode - Nominatim (nominatim.openstreetmap.org). Rules: a real User-Agent, max 1 request per second.
  route   - OSRM public demo server (router.project-osrm.org), car profile only.
            Walking time = road distance at 5 km/h (rough).
No live traffic: times are normal road times, and the reply says so.

Start point: "from X" if said, else config maps.home, else the weather city (config / voice setup).
Place names that come back from Nominatim are UNTRUSTED outside text: cleaned before they are spoken.

Optional config (defaults work without it):
  maps:
    home: "Banjara Hills, Hyderabad"     # start point when no "from" is said
    units: ""                             # km | miles; empty = from weather.units (imperial -> miles)
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

TIMEOUT = 8
MAX_BYTES = 256_000
USER_AGENT = "JarvisVoiceAssistant/1.0 (personal voice assistant)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{a};{b}?overview=false"
GMAPS_URL = "https://www.google.com/maps/dir/?api=1"
WALK_KMH = 5.0
BIAS_DEGREES = 1.5  # prefer places within ~150 km of the start point ("the airport")
MODES = {"driving", "walking", "transit"}
NO_TRAFFIC = "That's normal road time, without live traffic."

_lock = threading.Lock()
_last_call = [0.0]          # time of the last Nominatim request (1 per second rule)
_cache: dict[tuple, tuple | None] = {}


# ---------- helpers ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config()
    except Exception:
        cfg = {}
    maps = cfg.get("maps") or {}
    weather = cfg.get("weather") or {}
    home = str(maps.get("home") or cfg.get("home") or weather.get("city") or "").strip()
    units = str(maps.get("units") or "").strip().lower()
    if units not in ("km", "miles"):
        units = "miles" if str(weather.get("units") or "").lower() == "imperial" else "km"
    return {"home": home, "units": units}


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(MAX_BYTES).decode("utf-8", "replace"))


def _clean(text, limit: int = 60) -> str:
    """Untrusted web text -> short, safe, speakable text."""
    t = re.sub(r"<[^>]*>", " ", str(text or ""))
    t = re.sub(r"[^\w\s.,'()&-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip(" ,.-")


_FILLER = re.compile(
    r"^(?:(?:hey )?jarvis,? )?(?:please )?(?:(?:can|could) you )?(?:tell me |show me |give me |get me |open |find )?"
    r"(?:how (?:long|far)(?: (?:is|does|will|would) it(?: take)?)?(?: (?:is|to|for))?(?: (?:it|me))?"
    r"(?: to)?(?: (?:drive|driving|walk|walking|get|go|reach|travel))?(?: (?:to|till|until))?"
    r"|what(?:'s| is) the (?:distance|travel time|drive|driving time) (?:to|till)"
    r"|(?:driving |walking |transit )?directions? (?:to|for)"
    r"|(?:the )?(?:way|route|road) to|navigate to|take me to|distance to|travel time to)?\s*",
    re.I)


def _clean_place(text) -> str:
    """'how long to drive to the airport?' -> 'the airport'. User words, so only light cleaning."""
    t = re.sub(r"\s+", " ", str(text or "")).strip(" ?.!,")
    t = _FILLER.sub("", t, count=1)
    t = re.sub(r"\s+(?:by (?:car|road|bus|train|metro|foot)|on foot|from here|right now|now|please)$", "", t, flags=re.I)
    t = re.sub(r"[^\w\s.,'&()/#-]", " ", t)
    return re.sub(r"\s+", " ", t).strip(" ,.")[:100]


def _split_from(to: str, frm: str) -> tuple[str, str]:
    """'Hyderabad from Vizag' said as one 'to' -> ('Hyderabad', 'Vizag')."""
    if not frm:
        to = _FILLER.sub("", re.sub(r"\s+", " ", to).strip(" ?.!,"), count=1)
        m = re.match(r"^(?:from (.+?) to (.+)|(.+?) from (.+))$", to, re.I)
        if m:
            frm, to = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return _clean_place(to), _clean_place(frm)


def _mode(args: dict, text: str = "") -> str:
    m = str(args.get("mode") or "").lower().strip()
    if m in ("walk", "foot", "on foot"):
        m = "walking"
    if m in ("drive", "car", "road"):
        m = "driving"
    if m in ("bus", "train", "metro", "public transport", "transport"):
        m = "transit"
    if m not in MODES:
        low = text.lower()
        m = ("walking" if re.search(r"\bwalk|\bon foot\b", low)
             else "transit" if re.search(r"\b(?:bus|train|metro|transit|public transport)\b", low)
             else "driving")
    return m


def _is_here(place: str) -> bool:
    return place.lower() in ("", "here", "my location", "current location", "my current location")


def _is_home(place: str) -> bool:
    return place.lower() in ("home", "my home", "my house", "house")


def geocode(place: str, near: tuple | None = None) -> tuple | None:
    """(lat, lon, short name) or None when not found. Network errors raise. Max 1 request/s."""
    key = (place.lower(), None if near is None else (round(near[0], 1), round(near[1], 1)))
    if key in _cache:
        return _cache[key]
    q = {"q": place, "format": "jsonv2", "limit": "1", "addressdetails": "0"}
    if near:
        lat, lon = near[0], near[1]
        q["viewbox"] = f"{lon - BIAS_DEGREES},{lat + BIAS_DEGREES},{lon + BIAS_DEGREES},{lat - BIAS_DEGREES}"
        q["bounded"] = "0"  # prefer nearby, still allow far places
    with _lock:
        wait = 1.0 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            data = _fetch_json(NOMINATIM_URL + "?" + urllib.parse.urlencode(q))
        finally:
            _last_call[0] = time.monotonic()
    hit = None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        try:
            d = data[0]
            name = _clean(d.get("name") or str(d.get("display_name") or "").split(",")[0]) or _clean(place)
            hit = (float(d["lat"]), float(d["lon"]), name)
        except (KeyError, TypeError, ValueError):
            hit = None
    _cache[key] = hit
    return hit


def route(a: tuple, b: tuple) -> tuple[float, float] | None:
    """(seconds, metres) by car, or None when there is no road route. Network errors raise."""
    url = OSRM_URL.format(a=f"{a[1]:.6f},{a[0]:.6f}", b=f"{b[1]:.6f},{b[0]:.6f}")
    data = _fetch_json(url)
    if not isinstance(data, dict) or data.get("code") != "Ok" or not data.get("routes"):
        return None
    r = data["routes"][0]
    try:
        return float(r["duration"]), float(r["distance"])
    except (KeyError, TypeError, ValueError):
        return None


def straight_km(a: tuple, b: tuple) -> float:
    """Great-circle distance in km."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def say_duration(seconds: float) -> str:
    mins = max(1, int(round(seconds / 60)))
    if mins >= 600:  # long trips: round to the half hour
        mins = int(round(mins / 30)) * 30
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''}"
    h, m = divmod(mins, 60)
    out = f"{h} hour{'s' if h != 1 else ''}"
    return out + (f" {m} minute{'s' if m != 1 else ''}" if m else "")


def say_distance(km: float, units: str) -> str:
    if units == "miles":
        v, u = km * 0.621371, "miles"
    else:
        v, u = km, "kilometres"
    if v < 1:
        if units == "miles":
            return f"{int(round(v * 5280, -1))} feet"
        return f"{int(round(km * 1000, -1))} metres"
    return f"{v:.1f} {u}" if v < 10 else f"{int(round(v))} {u}"


# ---------- intents ----------

def travel_time(args: dict) -> str:
    raw_to = str(args.get("to") or args.get("place") or args.get("destination") or "")
    to, frm = _split_from(raw_to, str(args.get("from") or ""))
    mode = _mode(args, f"{raw_to} {args.get('text') or ''}")
    s = _settings()
    if not to or _is_here(to):
        return "Where do you want to go?"
    if _is_home(to):
        if not s["home"]:
            return "I don't know your home yet. Set maps home in config.yaml."
        to = s["home"]
    from_home = _is_here(frm) or _is_home(frm)
    start = s["home"] if from_home else frm
    if not start:
        return ("I don't know where you are starting from. Say 'from' and a place, "
                "or set your city in the voice setup.")
    if mode == "transit":
        return "I can't get bus or train times. Say 'directions to " + to + " by bus' and I'll open Google Maps."
    try:
        a = geocode(start)
        if not a:
            return f"I couldn't find {start} on the map."
        b = geocode(to, near=a)
        if not b:
            return f"I couldn't find {to} on the map. Try adding the city name."
    except Exception:
        return "I couldn't reach the map service. Check the internet connection."
    where = "from home" if from_home else f"from {_clean(start, 40)}"
    try:
        r = route(a, b)
    except Exception:
        r = None
    if not r:
        km = straight_km(a, b)
        if km < 0.05:
            return f"{b[2]} is right where you are."
        return (f"I couldn't get a road route. {b[2]} is about {say_distance(km, s['units'])} "
                f"{where} in a straight line.")
    secs, metres = r
    km = metres / 1000
    if mode == "walking":
        walk = say_duration(km / WALK_KMH * 3600)
        return f"Walking to {b[2]} {where} takes about {walk}. It's {say_distance(km, s['units'])}."
    return (f"Driving to {b[2]} {where} takes about {say_duration(secs)}. "
            f"It's {say_distance(km, s['units'])}. {NO_TRAFFIC}")


def directions_url(to: str, frm: str = "", mode: str = "driving") -> str:
    q = {"destination": to, "travelmode": mode if mode in MODES else "driving"}
    if frm:
        q["origin"] = frm
    return GMAPS_URL + "&" + urllib.parse.urlencode(q)


def directions(args: dict) -> str:
    raw_to = str(args.get("to") or args.get("place") or args.get("destination") or "")
    to, frm = _split_from(raw_to, str(args.get("from") or ""))
    mode = _mode(args, f"{raw_to} {args.get('text') or ''}")
    s = _settings()
    if not to or _is_here(to):
        return "Where do you want directions to?"
    if _is_home(to):
        if not s["home"]:
            return "I don't know your home yet. Set maps home in config.yaml."
        to = s["home"]
    if _is_home(frm):
        frm = s["home"]
    elif _is_here(frm):
        frm = ""  # Google Maps uses your current location
    try:
        ok = webbrowser.open(directions_url(to, frm, mode))
    except Exception:
        ok = False
    if not ok:
        return "I couldn't open the browser for directions."
    how = {"walking": "walking ", "transit": "bus and train "}.get(mode, "")
    return f"Opening {how}directions to {to}" + (f" from {frm}" if frm else "") + " in Google Maps."


# ---------- wiring ----------

_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "travel_time": {
        "description": "How long it takes to drive (or walk) to a place, and how far it is. "
                       "Uses free OpenStreetMap data, no live traffic. Start is home/city unless 'from' is given.",
        "properties": {
            "to": {"type": "string", "description": "Destination place, e.g. Hyderabad, the airport."},
            "from": {"type": "string", "description": "Start place. Leave out to start from home."},
            "mode": {"type": "string", "enum": ["driving", "walking"]},
        },
        "required": ["to"], "info": True,
    },
    "directions": {
        "description": "Open Google Maps directions to a place in the browser.",
        "properties": {
            "to": {"type": "string", "description": "Destination place."},
            "from": {"type": "string", "description": "Start place. Leave out for current location."},
            "mode": {"type": "string", "enum": ["driving", "walking", "transit"]},
        },
        "required": ["to"],
    },
}
HANDLERS = {"travel_time": travel_time, "directions": directions}
