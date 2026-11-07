"""Weather, news and system info (battery, CPU, memory, disk)."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

WEATHER_CITY = ""  # empty = guess from your internet location
WEATHER_UNITS = "metric"  # metric (C) or imperial (F)
NEWS_FEED = "https://news.google.com/rss?hl=en&gl=US&ceid=US:en"
NEWS_SEARCH = "https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"
TIMEOUT = 8


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


# ---------- weather (wttr.in, no API key) ----------
def weather(args: dict) -> str:
    city = (args.get("city") or WEATHER_CITY or "").strip()
    try:
        data = json.loads(_get(f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"))
    except Exception:
        return "I couldn't get the weather. Check the internet connection."
    f = WEATHER_UNITS == "imperial"
    unit = "Fahrenheit" if f else "degrees"
    try:  # the site may change its data format
        cur = data["current_condition"][0]
        today = data.get("weather", [{}])[0]
        temp = cur["temp_F" if f else "temp_C"]
        desc = cur["weatherDesc"][0]["value"].strip().lower()
    except (KeyError, IndexError, TypeError, AttributeError):
        return "I couldn't read the weather right now."
    place = city.title() if city else ""
    if not place:
        try:
            place = data["nearest_area"][0]["areaName"][0]["value"]
        except Exception:
            place = "your area"
    out = f"In {place} it's {temp} {unit} and {desc}."
    hi, lo = today.get("maxtempF" if f else "maxtempC"), today.get("mintempF" if f else "mintempC")
    if hi and lo:
        out += f" Today's high is {hi}, low {lo}."
    try:
        rain = max(int(h.get("chanceofrain", 0)) for h in today.get("hourly", []))
        if rain >= 40:
            out += f" Chance of rain up to {rain} percent."
    except ValueError:
        pass
    return out


# ---------- news (RSS) ----------
def news(args: dict, count: int = 3) -> str:
    topic = (args.get("topic") or "").strip()
    url = NEWS_SEARCH.replace("{query}", urllib.parse.quote_plus(topic)) if topic else NEWS_FEED
    try:
        root = ET.fromstring(_get(url))
    except Exception:
        return "I couldn't get the news. Check the internet connection."
    titles = []
    for item in root.iter("item"):
        t = (item.findtext("title") or "").strip()
        t = re.sub(r"\s+-\s+[^-]+$", "", t)  # drop " - Source name"
        if t:
            titles.append(t)
        if len(titles) >= count:
            break
    if not titles:
        return f"I found no news{' about ' + topic if topic else ''}."
    head = f"Top news about {topic}: " if topic else "Top headlines: "
    return head + " ... ".join(f"{i}. {t}." for i, t in enumerate(titles, 1))


# ---------- system info (psutil) ----------
def system_info(args: dict) -> str:
    import psutil

    what = args.get("what") or "all"
    parts = []
    if what in ("battery", "all"):
        b = psutil.sensors_battery()
        if b is None:
            parts.append("No battery found." if what == "battery" else "")
        else:
            s = f"Battery is at {int(b.percent)} percent"
            if b.power_plugged:
                s += " and charging"
            elif b.secsleft and b.secsleft > 0:
                h, m = divmod(int(b.secsleft) // 60, 60)
                s += f", about {h} hours {m} minutes left" if h else f", about {m} minutes left"
            parts.append(s + ".")
    if what in ("cpu", "all"):
        parts.append(f"CPU is at {int(psutil.cpu_percent(interval=0.5))} percent.")
    if what in ("memory", "all"):
        m = psutil.virtual_memory()
        parts.append(f"Memory is {int(m.percent)} percent used, {m.available / 2**30:.1f} gigabytes free.")
    if what in ("disk", "all"):
        import os

        d = psutil.disk_usage(os.path.abspath(os.sep))
        parts.append(f"Disk has {d.free / 2**30:.0f} gigabytes free of {d.total / 2**30:.0f}.")
    return " ".join(p for p in parts if p) or "I can tell you battery, CPU, memory or disk."
