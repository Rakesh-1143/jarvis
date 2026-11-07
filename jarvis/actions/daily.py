"""Piece Z: daily word, daily quote, "on this day".

Says:
  "word of the day", "what's today's word", "give me a new word" (random),
  "quote of the day", "give me a quote", "another quote" (random),
  "what happened on this day", "on this day in history",
  "daily briefing" / in a "good morning" routine -> all three.

Intent:
  daily {what: word|quote|on_this_day|all, random?: bool}   (info)

Word and quote are offline (built-in lists in daily_data.py) and change once a day.
"On this day" uses the free Wikimedia feed (no key), 2 events, cached for the day.
Optional config (works without it):  daily: {events: 2}
"""
from __future__ import annotations

import datetime as _dt
import json
import random
import re
import urllib.error
import urllib.request

from .daily_data import QUOTES, WORDS_RAW

TIMEOUT = 6
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"  # Wikimedia asks for a clear User-Agent
FEED_URLS = (
    "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{mm}/{dd}",
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{mm}/{dd}",
)
NO_NET = "I can't reach the internet right now, so I can't check what happened on this day."
MAX_EVENTS = 5

WORDS: list[tuple[str, str, str]] = [tuple(l.split("|", 2)) for l in WORDS_RAW.strip().splitlines()]
# Mix the order once (fixed seed) so days don't go in A-Z order. Same order on every PC.
_WORD_ORDER = list(range(len(WORDS)))
random.Random(2026).shuffle(_WORD_ORDER)
_QUOTE_ORDER = list(range(len(QUOTES)))
random.Random(2027).shuffle(_QUOTE_ORDER)

_rng = random.SystemRandom()
_events_cache: dict[str, list[dict]] = {}  # "MM-DD" -> events from the API


def _today() -> _dt.date:
    return _dt.date.today()


def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("daily") or {}
    except Exception:
        cfg = {}
    try:
        events = int(cfg.get("events") or 2)
    except (TypeError, ValueError):
        events = 2
    return {"events": max(1, min(MAX_EVENTS, events))}


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "random", "new", "another")
    return bool(value)


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


# ---------- word ----------

def pick_word(day: _dt.date | None = None, rand: bool = False) -> tuple[str, str, str]:
    if rand:
        return _rng.choice(WORDS)
    day = day or _today()
    return WORDS[_WORD_ORDER[day.toordinal() % len(WORDS)]]


def word(args: dict | None = None) -> str:
    rand = _truthy((args or {}).get("random"))
    w, part, meaning = pick_word(rand=rand)
    lead = "Here's a word" if rand else "Today's word is"
    sep = ":" if rand else ""
    return f"{lead}{sep} {w}, {_article(part)} {part}. It means {meaning}."


# ---------- quote ----------

def pick_quote(day: _dt.date | None = None, rand: bool = False) -> tuple[str, str]:
    if rand:
        return _rng.choice(QUOTES)
    day = day or _today()
    return QUOTES[_QUOTE_ORDER[day.toordinal() % len(QUOTES)]]


def quote(args: dict | None = None) -> str:
    rand = _truthy((args or {}).get("random"))
    text, author = pick_quote(rand=rand)
    lead = "Here's a quote" if rand else "Today's quote"
    return f"{lead}, from {author}: {text}"


# ---------- on this day ----------

def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_events(day: _dt.date) -> list[dict]:
    """Events for this month/day. Tries Wikimedia, then Wikipedia. Raises if both fail."""
    key = f"{day.month:02d}-{day.day:02d}"
    if key in _events_cache:
        return _events_cache[key]
    last_err: Exception | None = None
    for url in FEED_URLS:
        try:
            data = _get_json(url.format(mm=f"{day.month:02d}", dd=f"{day.day:02d}"))
        except Exception as e:  # network error, HTTP error, bad JSON
            last_err = e
            continue
        events = []
        for ev in (data or {}).get("events") or []:
            if not isinstance(ev, dict):
                continue
            text = re.sub(r"\s+", " ", str(ev.get("text") or "")).strip()
            year = ev.get("year")
            if text and isinstance(year, int):
                events.append({"year": year, "text": text})
        if events:
            _events_cache.clear()  # keep only one day
            _events_cache[key] = events
            return events
    if last_err:
        raise last_err
    return []


def _year_words(year: int) -> str:
    return f"{-year} BC" if year < 0 else str(year)


def on_this_day(args: dict | None = None) -> str:
    day = _today()
    try:
        events = _fetch_events(day)
    except Exception:
        return NO_NET
    if not events:
        return "I couldn't find anything for today's date."
    n = min(_settings()["events"], len(events))
    if _truthy((args or {}).get("random")):
        chosen = _rng.sample(events, n)
    else:  # same picks all day, so "repeat" and the AI see the same thing
        chosen = random.Random(day.toordinal()).sample(events, n)
    chosen.sort(key=lambda e: e["year"])
    parts = []
    for i, ev in enumerate(chosen):
        text = ev["text"].rstrip(".")
        lead = "On this day in" if i == 0 else "And in"
        parts.append(f"{lead} {_year_words(ev['year'])}, {text}.")
    return " ".join(parts)


# ---------- main handler ----------

_WHAT = {
    "word": "word", "word_of_the_day": "word", "words": "word", "vocabulary": "word",
    "quote": "quote", "quote_of_the_day": "quote", "quotes": "quote", "thought": "quote",
    "on_this_day": "on_this_day", "onthisday": "on_this_day", "history": "on_this_day",
    "this_day": "on_this_day", "today_in_history": "on_this_day",
    "all": "all", "everything": "all", "briefing": "all", "daily": "all",
}


def daily(args: dict) -> str:
    args = args or {}
    raw = str(args.get("what") or args.get("kind") or "all").strip().lower()
    what = _WHAT.get(re.sub(r"[\s-]+", "_", raw), "all")
    if what == "word":
        return word(args)
    if what == "quote":
        return quote(args)
    if what == "on_this_day":
        return on_this_day(args)
    parts = [word(args), quote(args)]
    history = on_this_day(args)
    if history != NO_NET:  # in a briefing, just skip history when offline
        parts.append(history)
    return " ".join(parts)


# ---------- wiring ----------

CATALOG: dict[str, dict] = {
    "daily": {
        "description": "Word of the day (with meaning), quote of the day, or what happened on this day in history. "
                       "what=all gives all three (for a morning briefing). random=true gives a new random word/quote.",
        "properties": {
            "what": {"type": "string", "enum": ["word", "quote", "on_this_day", "all"]},
            "random": {"type": "boolean"},
        },
        "required": [],
        "info": True,
    },
}
HANDLERS = {"daily": daily}
