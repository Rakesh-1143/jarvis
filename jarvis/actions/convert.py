"""Piece F: unit + currency conversion, world time, date maths.

Intents: convert {amount, from, to}, world_time {city}, date_calc {question} or {target_date}.
Units work offline. Currency uses frankfurter.app (free, no key), cached 12 hours.
World time uses zoneinfo (needs the `tzdata` package on Windows).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request

TIMEOUT = 8
CURRENCY_CACHE_SECONDS = 12 * 3600
CURRENCY_URLS = [
    "https://api.frankfurter.app/latest?from={src}&to={dst}",
    "https://api.frankfurter.dev/v1/latest?base={src}&symbols={dst}",
]

# ---------------------------------------------------------------- numbers
_SMALL = {"zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
          "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
          "half": 0.5, "quarter": 0.25}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_MULT = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "lakh": 100_000, "crore": 10_000_000}


def to_number(value) -> float | None:
    """'5', '2.5', '1,000', 'twenty five', 'two hundred' -> float. None if not a number."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip().lower().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    total, cur, seen = 0.0, 0.0, False
    for w in re.split(r"[\s-]+", s):
        if w == "and":
            continue
        if w in _SMALL:
            cur += _SMALL[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w in _MULT:
            cur = (cur or 1) * _MULT[w]
            if _MULT[w] >= 1000:
                total, cur = total + cur, 0.0
        else:
            try:
                cur += float(w)
            except ValueError:
                return None
        seen = True
    return total + cur if seen else None


def _fmt(x: float) -> str:
    """Short spoken number: 8.04672 -> '8.05', 100.0 -> '100', 0.000123 -> '0.000123'."""
    if x == 0:
        return "0"
    if abs(x) >= 100:
        s = f"{x:,.1f}"
    elif abs(x) >= 1:
        s = f"{x:.2f}"
    else:
        s = f"{x:.3g}"
        if "e" in s:
            s = f"{x:.6f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


# ---------------------------------------------------------------- units
# unit -> (category, factor to the base unit). Base: metre, kilogram, litre, m/s, byte, second.
_UNITS: dict[str, tuple[str, float]] = {}


def _add(cat: str, factor: float, *names: str) -> None:
    for n in names:
        _UNITS[n] = (cat, factor)


_add("length", 1, "m", "meter", "meters", "metre", "metres")
_add("length", 1000, "km", "kms", "kilometer", "kilometers", "kilometre", "kilometres")
_add("length", 0.01, "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_add("length", 0.001, "mm", "millimeter", "millimeters", "millimetre", "millimetres")
_add("length", 1609.344, "mi", "mile", "miles")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 0.3048, "ft", "foot", "feet")
_add("length", 0.0254, "in", "inch", "inches")
_add("length", 1852, "nautical mile", "nautical miles")
_add("weight", 1, "kg", "kgs", "kilo", "kilos", "kilogram", "kilograms")
_add("weight", 0.001, "g", "gm", "gms", "gram", "grams")
_add("weight", 1e-6, "mg", "milligram", "milligrams")
_add("weight", 1000, "tonne", "tonnes", "metric ton", "metric tons")
_add("weight", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("weight", 0.028349523125, "oz", "ounce", "ounces")
_add("weight", 6.35029318, "stone", "stones")
_add("volume", 1, "l", "liter", "liters", "litre", "litres")
_add("volume", 0.001, "ml", "milliliter", "milliliters", "millilitre", "millilitres")
_add("volume", 3.785411784, "gallon", "gallons", "gal", "us gallon", "us gallons")
_add("volume", 4.54609, "uk gallon", "uk gallons", "imperial gallon", "imperial gallons")
_add("volume", 0.946352946, "quart", "quarts", "qt")
_add("volume", 0.473176473, "pint", "pints", "pt")
_add("volume", 0.2365882365, "cup", "cups")
_add("volume", 0.0295735295625, "fluid ounce", "fluid ounces", "fl oz")
_add("volume", 0.01478676478125, "tablespoon", "tablespoons", "tbsp")
_add("volume", 0.00492892159375, "teaspoon", "teaspoons", "tsp")
_add("volume", 1000, "cubic meter", "cubic meters", "cubic metre", "cubic metres", "m3")
_add("speed", 1, "m/s", "mps", "meters per second", "metres per second")
_add("speed", 1000 / 3600, "km/h", "kmh", "kph", "kmph", "kilometers per hour", "kilometres per hour")
_add("speed", 1609.344 / 3600, "mph", "miles per hour")
_add("speed", 1852 / 3600, "knot", "knots")
_add("data", 1, "b", "byte", "bytes")
_add("data", 1 / 8, "bit", "bits")
_add("data", 1000, "kb", "kilobyte", "kilobytes")
_add("data", 1000**2, "mb", "megabyte", "megabytes")
_add("data", 1000**3, "gb", "gigabyte", "gigabytes", "gig", "gigs")
_add("data", 1000**4, "tb", "terabyte", "terabytes")
_add("data", 1024, "kib", "kibibyte", "kibibytes")
_add("data", 1024**2, "mib", "mebibyte", "mebibytes")
_add("data", 1024**3, "gib", "gibibyte", "gibibytes")
_add("data", 1000**2 / 8, "megabit", "megabits", "mbit")
_add("data", 1000**3 / 8, "gigabit", "gigabits", "gbit")
_add("time", 1, "s", "sec", "secs", "second", "seconds")
_add("time", 60, "min", "mins", "minute", "minutes")
_add("time", 3600, "h", "hr", "hrs", "hour", "hours")
_add("time", 86400, "day", "days")
_add("time", 604800, "week", "weeks")
_add("time", 2629746, "month", "months")
_add("time", 31556952, "year", "years")
_add("area", 1, "square meter", "square meters", "square metre", "square metres", "sq m", "m2")
_add("area", 0.09290304, "square foot", "square feet", "sq ft", "sqft")
_add("area", 4046.8564224, "acre", "acres")
_add("area", 10000, "hectare", "hectares")
_add("area", 1e6, "square kilometer", "square kilometers", "square kilometre", "square kilometres", "sq km")
_add("area", 2589988.110336, "square mile", "square miles", "sq mi")

_TEMPS = {
    "c": "C", "celsius": "C", "centigrade": "C", "degree celsius": "C", "degrees celsius": "C",
    "f": "F", "fahrenheit": "F", "degree fahrenheit": "F", "degrees fahrenheit": "F",
    "k": "K", "kelvin": "K", "kelvins": "K",
}
_TEMP_NAMES = {"C": "degrees Celsius", "F": "degrees Fahrenheit", "K": "kelvin"}

# Spoken names and symbols -> ISO code. Any 3-letter code also works.
CURRENCIES = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "us dollar": "USD", "us dollars": "USD", "$": "USD", "bucks": "USD",
    "rupee": "INR", "rupees": "INR", "inr": "INR", "indian rupee": "INR", "indian rupees": "INR", "rs": "INR", "₹": "INR",
    "euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR",
    "pound sterling": "GBP", "pounds sterling": "GBP", "british pound": "GBP", "british pounds": "GBP", "gbp": "GBP", "£": "GBP",
    "yen": "JPY", "jpy": "JPY", "japanese yen": "JPY", "¥": "JPY",
    "yuan": "CNY", "renminbi": "CNY", "cny": "CNY",
    "canadian dollar": "CAD", "canadian dollars": "CAD", "cad": "CAD",
    "australian dollar": "AUD", "australian dollars": "AUD", "aud": "AUD",
    "singapore dollar": "SGD", "singapore dollars": "SGD", "sgd": "SGD",
    "swiss franc": "CHF", "swiss francs": "CHF", "franc": "CHF", "francs": "CHF", "chf": "CHF",
    "dirham": "AED", "dirhams": "AED", "aed": "AED", "riyal": "SAR", "riyals": "SAR",
    "won": "KRW", "krw": "KRW", "baht": "THB", "ringgit": "MYR", "peso": "MXN", "pesos": "MXN",
    "rand": "ZAR", "real": "BRL", "reais": "BRL", "lira": "TRY", "taka": "BDT",
    "nepali rupee": "NPR", "nepali rupees": "NPR", "pakistani rupee": "PKR", "pakistani rupees": "PKR",
    "sri lankan rupee": "LKR", "sri lankan rupees": "LKR",
}
_CURRENCY_NAMES = {"USD": "US dollars", "INR": "rupees", "EUR": "euros", "GBP": "British pounds", "JPY": "yen",
                   "CNY": "yuan", "CAD": "Canadian dollars", "AUD": "Australian dollars", "SGD": "Singapore dollars",
                   "CHF": "Swiss francs", "AED": "dirhams", "SAR": "riyals"}
_rate_cache: dict[tuple[str, str], tuple[float, float]] = {}  # (src, dst) -> (rate, time fetched)


def _norm(u: str) -> str:
    u = str(u or "").strip().lower().replace(".", "")
    u = re.sub(r"^(?:a|an|the)\s+", "", u)
    return re.sub(r"\s+", " ", u)


def _unit(u: str) -> tuple[str, float] | None:
    u = _norm(u)
    if u in _UNITS:
        return _UNITS[u]
    if u.endswith("es") and u[:-2] in _UNITS:
        return _UNITS[u[:-2]]
    if u.endswith("s") and u[:-1] in _UNITS:
        return _UNITS[u[:-1]]
    return None


def _temp(u: str) -> str | None:
    u = _norm(u).replace("°", "").strip()
    return _TEMPS.get(u) or _TEMPS.get(u.replace("degree ", "").replace("degrees ", ""))


def _currency(u: str) -> str | None:
    raw = str(u or "").strip()
    u = _norm(raw)
    if u in CURRENCIES:
        return CURRENCIES[u]
    if re.fullmatch(r"[a-z]{3}", u) and _unit(u) is None and u.upper() in set(CURRENCIES.values()) | {
            "HKD", "NZD", "SEK", "NOK", "DKK", "PLN", "HUF", "CZK", "ILS", "IDR", "PHP", "ISK", "RON", "BGN"}:
        return u.upper()
    return None


def _temp_convert(x: float, src: str, dst: str) -> float:
    c = x if src == "C" else (x - 32) * 5 / 9 if src == "F" else x - 273.15
    return c if dst == "C" else c * 9 / 5 + 32 if dst == "F" else c + 273.15


def _spoken_unit(name: str, value: float) -> str:
    n = _norm(name)
    if len(n) <= 4 and n not in ("foot", "feet", "inch", "mile", "yard", "day", "week", "year", "hour", "acre", "cup", "pint"):
        return str(name).strip()  # keep short symbols like km, GB, mph as said
    if abs(value) == 1:
        if n.endswith("feet"):
            return n[:-4] + "foot"
        if n.endswith("inches"):
            return n[:-2]
        return n[:-1] if n.endswith("s") and not n.endswith("ss") else n
    if n.endswith("feet"):
        return n
    if n.endswith("foot"):
        return n[:-4] + "feet"
    if n.endswith("inch"):
        return n + "es"
    return n if n.endswith("s") else n + "s"


def _fetch_rate(src: str, dst: str) -> float:
    key = (src, dst)
    hit = _rate_cache.get(key)
    if hit and time.time() - hit[1] < CURRENCY_CACHE_SECONDS:
        return hit[0]
    last_err: Exception | None = None
    for url in CURRENCY_URLS:
        try:
            req = urllib.request.Request(url.format(src=src, dst=dst), headers={"User-Agent": "jarvis-assistant/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read())
            rate = float(data["rates"][dst])
            _rate_cache[key] = (rate, time.time())
            return rate
        except Exception as e:  # try the next URL
            last_err = e
    if hit:  # old rate is better than nothing
        return hit[0]
    raise ConnectionError(str(last_err))


def convert(args: dict) -> str:
    """{amount, from, to} -> spoken answer. Handles units, temperature and currency."""
    amount = to_number(args.get("amount", 1) if args.get("amount") not in (None, "") else 1)
    src, dst = str(args.get("from") or "").strip(), str(args.get("to") or "").strip()
    if amount is None:
        return f"I didn't get the number {args.get('amount')}."
    if not src or not dst:
        return "Tell me what to convert, like five miles in kilometers."

    ts, td = _temp(src), _temp(dst)
    if ts and td:
        out = _temp_convert(amount, ts, td)
        return f"{_fmt(amount)} {_TEMP_NAMES[ts]} is {_fmt(out)} {_TEMP_NAMES[td]}."

    us, ud = _unit(src), _unit(dst)
    if us and ud:
        if us[0] != ud[0]:
            return f"I can't convert {us[0]} to {ud[0]}."
        out = amount * us[1] / ud[1]
        return f"{_fmt(amount)} {_spoken_unit(src, amount)} is {_fmt(out)} {_spoken_unit(dst, out)}."

    cs, cd = _currency(src), _currency(dst)
    if cs and cd:
        if cs == cd:
            return f"That's the same currency: {_fmt(amount)}."
        try:
            rate = _fetch_rate(cs, cd)
        except Exception:
            return "I couldn't get exchange rates. Check the internet connection."
        out = amount * rate
        return (f"{_fmt(amount)} {_CURRENCY_NAMES.get(cs, cs)} is about {_fmt(out)} "
                f"{_CURRENCY_NAMES.get(cd, cd)}.")

    bad = src if not (ts or us or cs) else dst
    return f"I don't know the unit {bad}."


# ---------------------------------------------------------------- world time
CITY_ZONES = {
    "india": "Asia/Kolkata", "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata", "hyderabad": "Asia/Kolkata", "chennai": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata", "pune": "Asia/Kolkata",
    "new york": "America/New_York", "nyc": "America/New_York", "washington": "America/New_York",
    "boston": "America/New_York", "miami": "America/New_York", "atlanta": "America/New_York",
    "toronto": "America/Toronto", "chicago": "America/Chicago", "dallas": "America/Chicago",
    "houston": "America/Chicago", "denver": "America/Denver", "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "silicon valley": "America/Los_Angeles", "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "london": "Europe/London", "uk": "Europe/London", "england": "Europe/London", "dublin": "Europe/Dublin",
    "paris": "Europe/Paris", "france": "Europe/Paris", "berlin": "Europe/Berlin", "germany": "Europe/Berlin",
    "madrid": "Europe/Madrid", "rome": "Europe/Rome", "amsterdam": "Europe/Amsterdam", "zurich": "Europe/Zurich",
    "moscow": "Europe/Moscow", "istanbul": "Europe/Istanbul",
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "uae": "Asia/Dubai", "riyadh": "Asia/Riyadh",
    "doha": "Asia/Qatar", "karachi": "Asia/Karachi", "pakistan": "Asia/Karachi", "dhaka": "Asia/Dhaka",
    "kathmandu": "Asia/Kathmandu", "nepal": "Asia/Kathmandu", "colombo": "Asia/Colombo", "sri lanka": "Asia/Colombo",
    "bangkok": "Asia/Bangkok", "singapore": "Asia/Singapore", "kuala lumpur": "Asia/Kuala_Lumpur",
    "jakarta": "Asia/Jakarta", "manila": "Asia/Manila", "hong kong": "Asia/Hong_Kong",
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "china": "Asia/Shanghai",
    "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo", "seoul": "Asia/Seoul", "korea": "Asia/Seoul",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth", "auckland": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
    "cairo": "Africa/Cairo", "nairobi": "Africa/Nairobi", "lagos": "Africa/Lagos", "johannesburg": "Africa/Johannesburg",
    "honolulu": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    "utc": "UTC", "gmt": "UTC",
}


def _zone_for(city: str):
    from zoneinfo import ZoneInfo, available_timezones

    c = _norm(city)
    c = re.sub(r"^(?:in|at)\s+", "", c)
    name = CITY_ZONES.get(c)
    if not name:  # try the IANA list, e.g. "lisbon" -> Europe/Lisbon
        key = c.replace(" ", "_")
        for tz in sorted(available_timezones()):
            if tz.lower().rsplit("/", 1)[-1] == key:
                name = tz
                break
    return ZoneInfo(name) if name else None


def _clock(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def world_time(args: dict, now: dt.datetime | None = None) -> str:
    city = str(args.get("city") or "").strip()
    if not city:
        return "Which city?"
    try:
        zone = _zone_for(city)
    except Exception:
        return "Time zone data is missing. Run: pip install tzdata"
    if zone is None:
        return f"I don't know the time zone for {city}."
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.astimezone()
    there = now.astimezone(zone)
    here = now.astimezone()
    out = f"In {city.title()} it's {_clock(there)} on {there.strftime('%A')}."
    diff_min = round(((there.utcoffset() or dt.timedelta()) - (here.utcoffset() or dt.timedelta())).total_seconds() / 60)
    if diff_min:
        h, m = divmod(abs(diff_min), 60)
        span = f"{h} hour{'s' if h != 1 else ''}" if h else ""
        if m:
            span = (span + " " if span else "") + f"{m} minutes"
        out += f" That's {span} {'ahead of' if diff_min > 0 else 'behind'} you."
    else:
        out += " Same time as you."
    return out


# ---------------------------------------------------------------- date maths
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ORD_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
              "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
              "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
              "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
_HOLIDAYS = {"christmas": (12, 25), "christmas eve": (12, 24), "new year": (1, 1), "new years": (1, 1),
             "new year's": (1, 1), "new year's day": (1, 1), "new year's eve": (12, 31), "valentine's day": (2, 14),
             "valentines day": (2, 14), "halloween": (10, 31), "independence day": (8, 15),
             "republic day": (1, 26), "gandhi jayanti": (10, 2)}
_PERIODS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "fortnight": 14, "month": 30, "months": 30,
            "year": 365, "years": 365}
_NUM = r"(\d+|[a-z]+(?:[ -][a-z]+)?)"


def _day_num(s: str) -> int | None:
    s = s.strip().lower()
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", s)
    if m:
        return int(m.group(1))
    parts = re.split(r"[\s-]+", s)
    if len(parts) == 2 and parts[0] in ("twenty", "thirty") and parts[1] in _ORD_WORDS:
        return _TENS[parts[0]] + _ORD_WORDS[parts[1]]
    return _ORD_WORDS.get(s)


def parse_date(text: str, today: dt.date) -> dt.date | None:
    """'25 December', 'December 25th', 'the 15th of august 2027', '15/08/2026', '2026-08-15',
    'christmas', 'today', 'tomorrow', 'next friday'. Dates without a year mean the next one coming."""
    t = re.sub(r"[,.]", " ", str(text or "").lower())
    t = re.sub(r"\b(?:on|the|of|is|it|day|until|till|since|from|to)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    raw = re.sub(r"\s+", " ", str(text or "").lower().replace(",", " ")).strip()

    if re.search(r"\btoday\b", t):
        return today
    if re.search(r"\btomorrow\b", t):
        return today + dt.timedelta(days=1)
    if re.search(r"\byesterday\b", t):
        return today - dt.timedelta(days=1)
    for name, (mo, d) in sorted(_HOLIDAYS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b" + re.escape(name) + r"\b", raw):
            got = dt.date(today.year, mo, d)
            return got if got >= today else dt.date(today.year + 1, mo, d)
    m = re.search(r"\b(?:(next|this|last)\s+)?(" + "|".join(_WEEKDAYS) + r")\b", t)
    if m and not re.search(r"\d", t):
        want = _WEEKDAYS.index(m.group(2))
        ahead = (want - today.weekday()) % 7
        if m.group(1) == "last":
            return today - dt.timedelta(days=(today.weekday() - want) % 7 or 7)
        if m.group(1) == "next" and ahead == 0:
            ahead = 7
        return today + dt.timedelta(days=ahead)

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:  # day/month (India/UK style)
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else None
        if y is not None and y < 100:
            y += 2000
        return _with_year(y, mo, d, today)

    month_re = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"
    day_re = r"(\d{1,2}(?:st|nd|rd|th)?|(?:twenty|thirty)[ -][a-z]+|[a-z]+)"
    year_re = r"(?:\s+(\d{4}))?"
    m = re.search(r"\b" + day_re + r"\s+" + month_re + r"\b" + year_re, t)
    if m and _day_num(m.group(1)):
        return _with_year(int(m.group(3)) if m.group(3) else None, _MONTHS[m.group(2)], _day_num(m.group(1)), today)
    m = re.search(r"\b" + month_re + r"\s+" + day_re + r"\b" + year_re, t)
    if m and _day_num(m.group(2)):
        return _with_year(int(m.group(3)) if m.group(3) else None, _MONTHS[m.group(1)], _day_num(m.group(2)), today)
    return None


def _safe_date(y: int, mo: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _with_year(y: int | None, mo: int, d: int, today: dt.date) -> dt.date | None:
    if y is not None:
        return _safe_date(y, mo, d)
    got = _safe_date(today.year, mo, d)
    if got and got < today:
        got = _safe_date(today.year + 1, mo, d)
    return got


def _say_date(d: dt.date, today: dt.date) -> str:
    s = f"{d.strftime('%A')}, {d.day} {d.strftime('%B')}"
    return s + (f" {d.year}" if d.year != today.year else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def date_calc(args: dict, today: dt.date | None = None) -> str:
    """{question: "how many days until 25 December"} or {target_date: "2026-12-25"}."""
    today = today or dt.date.today()
    q = str(args.get("question") or "").strip().lower()
    target = str(args.get("target_date") or "").strip()

    # "date in 45 days", "what date is it in 3 weeks", "what was the date 10 days ago"
    m = re.search(r"\b(?:in|after)\s+" + _NUM + r"\s+(days?|weeks?|fortnight|months?|years?)\b", q) or \
        re.search(r"\b" + _NUM + r"\s+(days?|weeks?|fortnight|months?|years?)\s+(?:from (?:now|today)|later)\b", q)
    m_ago = re.search(r"\b" + _NUM + r"\s+(days?|weeks?|months?|years?)\s+ago\b", q)
    if (m or m_ago) and not target:
        mm = m or m_ago
        n = to_number(mm.group(1))
        if n is None:
            return "I didn't get the number."
        n = int(n)
        unit = mm.group(2)
        if unit.startswith("month") or unit.startswith("year"):
            months = n * (12 if unit.startswith("year") else 1) * (-1 if m_ago and not m else 1)
            y, mo = divmod(today.month - 1 + months, 12)
            d = _safe_date(today.year + y, mo + 1, today.day) or _safe_date(today.year + y, mo + 1, 28)
        else:
            days = n * _PERIODS[unit]
            d = today + dt.timedelta(days=-days if (m_ago and not m) else days)
        return f"It {'was' if d < today else 'will be'} {_say_date(d, today)}."

    d = parse_date(target, today) if target else parse_date(q, today)
    if d is None:
        return "I didn't get the date. Try like: how many days until 25 December."
    diff = (d - today).days

    if re.search(r"\b(?:since|ago|passed)\b", q) or (diff < 0 and not re.search(r"\bwhat day\b", q)):
        if diff > 0:
            return f"{_say_date(d, today)} hasn't come yet. It's in {_plural(diff, 'day')}."
        return f"{_say_date(d, today)} was {_plural(-diff, 'day')} ago." if diff else "That's today."
    if re.search(r"\bweeks?\b", q) and diff > 0:
        w, r = divmod(diff, 7)
        rest = f" and {_plural(r, 'day')}" if r else ""
        return f"{_plural(w, 'week')}{rest} until {_say_date(d, today)}."
    if re.search(r"\b(?:what|which) day\b", q):
        verb = "is" if diff >= 0 else "was"
        return f"{d.day} {d.strftime('%B')} {d.year} {verb} a {d.strftime('%A')}."
    if diff == 0:
        return f"That's today, {_say_date(d, today)}."
    if diff == 1:
        return f"That's tomorrow, {_say_date(d, today)}."
    return f"{_plural(diff, 'day')} until {_say_date(d, today)}."


# ---------------------------------------------------------------- wiring
_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "convert": {"description": "Convert units (length, weight, temperature, volume, speed, area, data size, time) "
                               "offline, or money between currencies with live rates.",
                "properties": {"amount": {"type": "number", "description": "How many, e.g. 5."},
                               "from": {"type": "string", "description": "Unit or currency to convert from, e.g. miles, F, dollars, USD."},
                               "to": {"type": "string", "description": "Unit or currency to convert to, e.g. km, C, rupees, INR."}},
                "required": ["amount", "from", "to"], "info": True},
    "world_time": {"description": "Current time in another city or country, and the difference from local time.",
                   "properties": {"city": {"type": "string", "description": "City or country, e.g. Tokyo, London."}},
                   "required": ["city"], "info": True},
    "date_calc": {"description": "Date maths: days until or since a date, what weekday a date is, the date N days/weeks from now.",
                  "properties": {"question": {"type": "string", "description": "The user's question in their words."},
                                 "target_date": {"type": "string", "description": "Optional date, e.g. 2026-12-25 or 25 December."}},
                  "required": [], "info": True},
}
HANDLERS = {"convert": convert, "world_time": world_time, "date_calc": date_calc}
