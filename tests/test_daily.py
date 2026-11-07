"""Piece Z: daily word, quote, on this day. Network is faked."""
import datetime as dt
import os
import sys
import urllib.error
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import daily  # noqa: E402

_REAL_SETTINGS = daily._settings

FEED = {"events": [
    {"text": "Apollo 11 lands on the Moon.", "year": 1969, "pages": []},
    {"text": "  The first   event. ", "year": 1492},
    {"text": "A thing in old times", "year": -44},
    {"text": "", "year": 2000},           # skipped: empty
    {"text": "No year"},                  # skipped: no year
    "junk",                               # skipped: not a dict
]}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    daily._events_cache.clear()
    monkeypatch.setattr(daily, "_today", lambda: dt.date(2026, 11, 7))
    monkeypatch.setattr(daily, "_settings", lambda: {"events": 2})
    yield
    daily._events_cache.clear()


def fake_get(routes):
    calls = []

    def _get(url):
        calls.append(url)
        for part, result in routes:
            if part in url:
                if isinstance(result, Exception):
                    raise result
                return result
        raise urllib.error.URLError("no route")
    return _get, calls


# ---------- data ----------

def test_word_list_is_big_and_clean():
    assert len(daily.WORDS) >= 366
    names = [w for w, _, _ in daily.WORDS]
    assert len(names) == len(set(names))
    for w, part, meaning in daily.WORDS:
        assert w and meaning and part in ("noun", "verb", "adjective", "adverb")


def test_quotes_clean():
    assert len(daily.QUOTES) >= 50
    assert len({q for q, _ in daily.QUOTES}) == len(daily.QUOTES)
    assert all(q and a for q, a in daily.QUOTES)


# ---------- word ----------

def test_word_same_all_day_and_changes_next_day():
    d = dt.date(2026, 11, 7)
    assert daily.pick_word(d) == daily.pick_word(d)
    assert daily.pick_word(d) != daily.pick_word(d + dt.timedelta(days=1))


def test_word_no_repeat_within_a_year():
    start = dt.date(2027, 1, 1)
    picks = {daily.pick_word(start + dt.timedelta(days=i))[0] for i in range(365)}
    assert len(picks) == 365


def test_word_reply():
    w, part, meaning = daily.pick_word(dt.date(2026, 11, 7))
    reply = daily.daily({"what": "word"})
    assert reply.startswith(f"Today's word is {w}, ")
    assert meaning in reply and part in reply
    assert (" an adjective" in reply) == (part == "adjective")


def test_word_random():
    with mock.patch.object(daily._rng, "choice", return_value=("zest", "noun", "great energy")):
        reply = daily.daily({"what": "word", "random": True})
    assert reply == "Here's a word: zest, a noun. It means great energy."


# ---------- quote ----------

def test_quote_reply_stable():
    text, author = daily.pick_quote(dt.date(2026, 11, 7))
    assert daily.daily({"what": "quote"}) == f"Today's quote, from {author}: {text}"
    assert daily.daily({"what": "quote of the day"}) == daily.daily({"what": "quote"})


def test_quote_random_string_flag():
    with mock.patch.object(daily._rng, "choice", return_value=("Hi.", "Me")):
        assert daily.daily({"what": "quote", "random": "another"}) == "Here's a quote, from Me: Hi."


# ---------- on this day ----------

def test_on_this_day_two_events_sorted_and_url():
    get, calls = fake_get([("wikimedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        reply = daily.daily({"what": "on_this_day"})
    assert calls == ["https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/11/07"]
    assert reply.startswith("On this day in ")
    assert reply.count("And in ") == 1
    assert "No year" not in reply and "2000" not in reply
    years = [int(y) if "BC" not in y else -int(y.split()[0]) for y in
             __import__("re").findall(r"in (\d+(?: BC)?),", reply)]
    assert years == sorted(years)


def test_on_this_day_text_cleaned_and_bc():
    one = {"events": [{"text": "  The first   event. ", "year": 1492}]}
    get, _ = fake_get([("wikimedia.org", one)])
    with mock.patch.object(daily, "_get_json", get):
        assert daily.on_this_day() == "On this day in 1492, The first event."
    daily._events_cache.clear()
    bc = {"events": [{"text": "Caesar dies", "year": -44}]}
    get, _ = fake_get([("wikimedia.org", bc)])
    with mock.patch.object(daily, "_get_json", get):
        assert daily.on_this_day() == "On this day in 44 BC, Caesar dies."


def test_on_this_day_same_picks_all_day_and_cached():
    get, calls = fake_get([("wikimedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        a = daily.on_this_day()
        b = daily.on_this_day()
    assert a == b
    assert len(calls) == 1  # cached


def test_on_this_day_falls_back_to_wikipedia():
    get, calls = fake_get([("wikimedia.org", urllib.error.HTTPError("u", 503, "x", {}, None)),
                           ("en.wikipedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        reply = daily.on_this_day()
    assert len(calls) == 2 and "en.wikipedia.org/api/rest_v1/feed/onthisday/events/11/07" in calls[1]
    assert reply.startswith("On this day in ")


def test_on_this_day_offline():
    get, _ = fake_get([])
    with mock.patch.object(daily, "_get_json", get):
        assert daily.on_this_day() == daily.NO_NET


def test_on_this_day_empty():
    get, _ = fake_get([("wikimedia.org", {"events": []}), ("wikipedia.org", {})])
    with mock.patch.object(daily, "_get_json", get):
        assert "couldn't find" in daily.on_this_day()


def test_events_count_from_settings(monkeypatch):
    monkeypatch.setattr(daily, "_settings", lambda: {"events": 3})
    get, _ = fake_get([("wikimedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        reply = daily.on_this_day()
    assert reply.count("And in ") == 2


# ---------- all / defaults ----------

def test_all_has_three_parts():
    get, _ = fake_get([("wikimedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        reply = daily.daily({"what": "all"})
    assert "Today's word is" in reply and "Today's quote" in reply and "On this day in" in reply


def test_all_offline_skips_history_and_default_is_all():
    get, _ = fake_get([])
    with mock.patch.object(daily, "_get_json", get):
        reply = daily.daily({})
    assert "Today's word is" in reply and "Today's quote" in reply
    assert "internet" not in reply


def test_unknown_what_and_aliases():
    get, _ = fake_get([("wikimedia.org", FEED)])
    with mock.patch.object(daily, "_get_json", get):
        assert daily.daily({"what": "history"}).startswith("On this day")
        assert daily.daily({"what": "on this day"}).startswith("On this day")
    assert daily.daily({"what": "Word of the day"}).startswith("Today's word")
    assert daily.daily(None).startswith("Today's word")


def test_settings_values():
    for cfg, want in (({"daily": {"events": "lots"}}, 2), ({"daily": {"events": 99}}, daily.MAX_EVENTS),
                      ({"daily": {"events": 3}}, 3), ({}, 2)):
        with mock.patch("jarvis.config.load_config", return_value=cfg):
            assert _REAL_SETTINGS()["events"] == want


# ---------- wiring ----------

def test_catalog_and_handlers():
    assert set(daily.CATALOG) == set(daily.HANDLERS) == {"daily"}
    entry = daily.CATALOG["daily"]
    assert entry["info"] is True and entry["required"] == []
    assert set(entry["properties"]["what"]["enum"]) == {"word", "quote", "on_this_day", "all"}
