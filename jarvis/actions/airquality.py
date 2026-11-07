"""Piece BD: air quality, UV index, sunrise/sunset and "will it rain in the next hour".

Intents (all info, nothing risky):
  air_quality {city?}   "what's the air quality", "is it safe to go running"  -> US AQI + PM2.5/PM10 + advice
  sun_times   {city?}   "when is sunset", "what time is sunrise"
  rain_soon   {city?}   "will it rain in the next hour"
  uv          {city?}   "UV index today"

Services (free, no key; every error fails softly with a spoken message):
  geocode      geocoding-api.open-meteo.com/v1/search
  air quality  air-quality-api.open-meteo.com/v1/air-quality  (us_aqi, pm2_5, pm10)
  forecast     api.open-meteo.com/v1/forecast  (hourly uv_index, precipitation_probability,
               precipitation; daily sunrise, sunset, uv_index_max; timezone=auto)
  no city      ipinfo.io/json gives a rough location from the internet connection
               (same idea as the weather command, which uses wttr.in's own guess).

City: args["city"], else config weather.city, else the internet location.
Place names that come back from the web are UNTRUSTED outside text: cleaned before speaking.
The existing `weather` command (info.py) still does temperature/conditions; this module does not.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import threading
import urllib.parse
import urllib.request

TIMEOUT = 8
MAX_BYTES = 512_000
USER_AGENT = "JarvisVoiceAssistant/1.0 (personal voice assistant)"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_URL = "https://ipinfo.io/json"
OFFLINE = "I couldn't reach the weather service. Check the internet connection."

_lock = threading.Lock()
_geo_cache: dict[str, tuple | None] = {}


# ---------- helpers ----------

def _default_city() -> str:
    try:
        from jarvis.config import load_config
        cfg = load_config()
    except Exception:
        cfg = {}
    weather = cfg.get("weather") or {}
    city = str(weather.get("city") or "").strip()
    if not city:  # value set at start-up by actions/__init__ from config
        try:
            from jarvis.actions import info
            city = str(info.WEATHER_CITY or "").strip()
        except Exception:
            city = ""
    return city


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


_CITY_FILLER = re.compile(r"^(?:in|at|for|near|around)\s+", re.I)
_CITY_TAIL = re.compile(r"\s+(?:today|tonight|tomorrow|now|right now|please)$", re.I)
_HERE = {"", "here", "my city", "my area", "my location", "outside", "current location", "my current location"}


def _clean_city(city) -> str:
    c = re.sub(r"[?!.]+$", "", str(city or "").strip())
    c = _CITY_FILLER.sub("", c)
    c = _CITY_TAIL.sub("", c).strip(" ,")
    return "" if c.lower() in _HERE else c[:80]


def _num(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def geocode(city: str) -> tuple | None:
    """City name -> (lat, lon, spoken name). None if not found. Raises on network error."""
    key = city.lower()
    with _lock:
        if key in _geo_cache:
            return _geo_cache[key]
    # Open-Meteo matches the name only; "Hyderabad, India" -> search "Hyderabad", prefer country match.
    parts = [p.strip() for p in city.split(",") if p.strip()]
    name = parts[0] if parts else city
    hint = parts[-1].lower() if len(parts) > 1 else ""
    q = urllib.parse.urlencode({"name": name, "count": 5, "language": "en", "format": "json"})
    data = _fetch_json(f"{GEOCODE_URL}?{q}")
    results = (data.get("results") or []) if isinstance(data, dict) else []
    pick = None
    for r in results:
        if not isinstance(r, dict):
            continue
        if hint and hint not in " ".join(str(r.get(k) or "") for k in ("country", "admin1", "country_code")).lower():
            continue
        pick = r
        break
    if pick is None and results and isinstance(results[0], dict):
        pick = results[0]
    out = None
    if pick:
        lat, lon = _num(pick.get("latitude")), _num(pick.get("longitude"))
        if lat is not None and lon is not None:
            out = (lat, lon, _clean(pick.get("name")) or _clean(name))
    with _lock:
        _geo_cache[key] = out
    return out


def ip_location() -> tuple | None:
    """Rough location from the internet connection -> (lat, lon, city name)."""
    with _lock:
        if "\0ip" in _geo_cache:
            return _geo_cache["\0ip"]
    data = _fetch_json(IP_URL)
    out = None
    try:
        lat, lon = (float(x) for x in str(data.get("loc") or "").split(","))
        out = (lat, lon, _clean(data.get("city")) or "your area")
    except (ValueError, TypeError, AttributeError):
        out = None
    with _lock:
        _geo_cache["\0ip"] = out
    return out


def _place(args: dict):
    """-> (lat, lon, name) or an error string to speak."""
    city = _clean_city(args.get("city")) or _clean_city(_default_city())
    try:
        loc = geocode(city) if city else ip_location()
    except Exception:
        return OFFLINE
    if not loc:
        return f"I couldn't find {_clean(city)}." if city else "I couldn't work out where you are. Say a city name."
    return loc


def _forecast(lat: float, lon: float) -> dict:
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "hourly": "uv_index,precipitation_probability,precipitation",
        "daily": "sunrise,sunset,uv_index_max",
        "timezone": "auto", "forecast_days": 2,
    })
    data = _fetch_json(f"{FORECAST_URL}?{q}")
    return data if isinstance(data, dict) else {}


def _local_now(data: dict, now: _dt.datetime | None = None) -> _dt.datetime:
    """Local time at the place (naive), from the API's utc_offset_seconds."""
    off = _num(data.get("utc_offset_seconds")) or 0
    utc = now or _dt.datetime.now(_dt.timezone.utc)
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=_dt.timezone.utc)
    return (utc + _dt.timedelta(seconds=off)).replace(tzinfo=None)


def _parse(t) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(str(t))
    except (TypeError, ValueError):
        return None


def _say_time(t: _dt.datetime) -> str:
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _hour_index(times: list, local: _dt.datetime) -> int | None:
    key = local.replace(minute=0, second=0, microsecond=0)
    for i, t in enumerate(times):
        if _parse(t) == key:
            return i
    return None


# ---------- air quality ----------

AQI_BANDS = [  # (max US AQI, label, advice)
    (50, "good", "Air is clean. Fine for running and outdoor exercise."),
    (100, "moderate", "Okay for most people. If you are very sensitive, take it easy on long runs."),
    (150, "unhealthy for sensitive groups",
     "Fine for a short walk, but people with asthma, children and older people should cut back on hard exercise outside."),
    (200, "unhealthy", "Better to skip running outside today. Exercise indoors if you can."),
    (300, "very unhealthy", "Stay indoors and avoid exercise outside. Wear a good mask (N95) if you must go out."),
    (10 ** 9, "hazardous", "Stay indoors with windows closed. Do not exercise outside."),
]


def aqi_band(aqi: float) -> tuple[str, str]:
    for top, label, advice in AQI_BANDS:
        if aqi <= top:
            return label, advice
    return AQI_BANDS[-1][1], AQI_BANDS[-1][2]


def air_quality(args: dict) -> str:
    loc = _place(args)
    if isinstance(loc, str):
        return loc
    lat, lon, name = loc
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "current": "us_aqi,pm2_5,pm10", "timezone": "auto",
    })
    try:
        data = _fetch_json(f"{AIR_URL}?{q}")
    except Exception:
        return OFFLINE
    cur = data.get("current") if isinstance(data, dict) else None
    cur = cur if isinstance(cur, dict) else {}
    aqi = _num(cur.get("us_aqi"))
    if aqi is None:
        return f"I couldn't get the air quality for {name} right now."
    label, advice = aqi_band(aqi)
    out = f"Air quality in {name} is {label}, AQI {round(aqi)}."
    pm25, pm10 = _num(cur.get("pm2_5")), _num(cur.get("pm10"))
    bits = []
    if pm25 is not None:
        bits.append(f"PM 2.5 is {round(pm25)}")
    if pm10 is not None:
        bits.append(f"PM 10 is {round(pm10)}")
    if bits:
        out += " " + " and ".join(bits) + " micrograms per cubic metre."
    return f"{out} {advice}"


# ---------- sunrise / sunset ----------

def sun_times(args: dict) -> str:
    loc = _place(args)
    if isinstance(loc, str):
        return loc
    lat, lon, name = loc
    try:
        data = _forecast(lat, lon)
    except Exception:
        return OFFLINE
    daily = data.get("daily") if isinstance(data, dict) else None
    daily = daily if isinstance(daily, dict) else {}
    rises = [_parse(t) for t in daily.get("sunrise") or []]
    sets = [_parse(t) for t in daily.get("sunset") or []]
    if not rises or not sets or rises[0] is None or sets[0] is None:
        # polar day/night: the API gives no time
        return f"I couldn't get sunrise and sunset times for {name}."
    now = _local_now(data)
    rise, sset = rises[0], sets[0]
    if now < rise:
        return f"In {name}, sunrise is at {_say_time(rise)} and sunset at {_say_time(sset)}."
    if now < sset:
        return f"In {name}, sunset is at {_say_time(sset)} today. Sunrise was at {_say_time(rise)}."
    out = f"In {name}, the sun set at {_say_time(sset)}."
    if len(rises) > 1 and rises[1] is not None:
        out += f" Tomorrow's sunrise is at {_say_time(rises[1])}."
    return out


# ---------- rain in the next hour ----------

def rain_soon(args: dict) -> str:
    loc = _place(args)
    if isinstance(loc, str):
        return loc
    lat, lon, name = loc
    try:
        data = _forecast(lat, lon)
    except Exception:
        return OFFLINE
    hourly = data.get("hourly") if isinstance(data, dict) else None
    hourly = hourly if isinstance(hourly, dict) else {}
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    amounts = hourly.get("precipitation") or []
    i = _hour_index(times, _local_now(data))
    if i is None:
        return f"I couldn't get the rain forecast for {name} right now."

    def at(seq, j):
        return _num(seq[j]) if 0 <= j < len(seq) else None

    # "next hour" = this hour and the next one
    next_p = [p for p in (at(probs, i), at(probs, i + 1)) if p is not None]
    next_mm = [m for m in (at(amounts, i), at(amounts, i + 1)) if m is not None]
    if not next_p and not next_mm:
        return f"I couldn't get the rain forecast for {name} right now."
    chance = round(max(next_p)) if next_p else None
    mm = max(next_mm) if next_mm else 0.0
    if (chance is not None and chance >= 50) or mm >= 0.5:
        out = f"Yes, rain is likely in {name} in the next hour"
        out += f", {chance} percent chance." if chance is not None else "."
        return out + " Take an umbrella."
    if chance is not None and chance >= 25:
        out = f"Maybe. There's a {chance} percent chance of rain in {name} in the next hour."
    else:
        out = f"No, rain is unlikely in {name} in the next hour"
        out += f", {chance} percent chance." if chance is not None else "."
    # look ahead a few hours so the answer is useful
    later = [(j, at(probs, j)) for j in range(i + 2, i + 7)]
    later = [(j, p) for j, p in later if p is not None and p >= 50]
    if later:
        t = _parse(times[later[0][0]])
        if t:
            out += f" But rain is likely around {_say_time(t)}."
    return out


# ---------- UV index ----------

UV_BANDS = [  # (max UV, label, advice)
    (2, "low", "No sun protection needed."),
    (5, "moderate", "Use sunscreen if you're out for long."),
    (7, "high", "Use sunscreen, a hat and sunglasses. Seek shade around midday."),
    (10, "very high", "Avoid the midday sun. Sunscreen, hat and sunglasses are a must."),
    (10 ** 9, "extreme", "Stay out of the sun around midday if you can."),
]


def uv_band(uv: float) -> tuple[str, str]:
    for top, label, advice in UV_BANDS:
        if uv < top + 1:
            return label, advice
    return UV_BANDS[-1][1], UV_BANDS[-1][2]


def uv(args: dict) -> str:
    loc = _place(args)
    if isinstance(loc, str):
        return loc
    lat, lon, name = loc
    try:
        data = _forecast(lat, lon)
    except Exception:
        return OFFLINE
    hourly = data.get("hourly") if isinstance(data, dict) else None
    hourly = hourly if isinstance(hourly, dict) else {}
    daily = data.get("daily") if isinstance(data, dict) else None
    daily = daily if isinstance(daily, dict) else {}
    maxes = daily.get("uv_index_max") or []
    top = _num(maxes[0]) if maxes else None
    i = _hour_index(hourly.get("time") or [], _local_now(data))
    vals = hourly.get("uv_index") or []
    now_uv = _num(vals[i]) if i is not None and i < len(vals) else None
    if top is None and now_uv is None:
        return f"I couldn't get the UV index for {name} right now."
    ref = top if top is not None else now_uv
    label, advice = uv_band(ref)
    if top is not None:
        out = f"Today's UV index in {name} goes up to {round(top)}, which is {label}."
        if now_uv is not None:
            out += f" Right now it's {round(now_uv)}."
    else:
        out = f"The UV index in {name} is {round(now_uv)} right now, which is {label}."
    return f"{out} {advice}"


# ---------- wiring ----------

_CITY = {"type": "string", "description": "City name, e.g. Hyderabad. Leave out for the user's own city."}
CATALOG: dict[str, dict] = {
    "air_quality": {
        "description": "Air quality (US AQI, PM2.5, PM10) for a city, with simple advice like whether it's "
                       "okay to go running outside.",
        "properties": {"city": _CITY}, "required": [], "info": True,
    },
    "sun_times": {
        "description": "Sunrise and sunset times today for a city.",
        "properties": {"city": _CITY}, "required": [], "info": True,
    },
    "rain_soon": {
        "description": "Whether it will rain in the next hour in a city (and if rain is likely later in the next few hours).",
        "properties": {"city": _CITY}, "required": [], "info": True,
    },
    "uv": {
        "description": "UV index today (max and right now) for a city, with sun protection advice.",
        "properties": {"city": _CITY}, "required": [], "info": True,
    },
}
HANDLERS = {"air_quality": air_quality, "sun_times": sun_times, "rain_soon": rain_soon, "uv": uv}
