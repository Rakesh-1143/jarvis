"""Piece F: convert, world_time, date_calc. Network calls are mocked."""
import datetime as dt
import io
import json
import os
import sys
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import convert as cv  # noqa: E402

TODAY = dt.date(2026, 11, 7)  # a Saturday


@pytest.mark.parametrize("args,want", [
    ({"amount": 5, "from": "miles", "to": "km"}, "5 miles is 8.05 km."),
    ({"amount": "1", "from": "mile", "to": "kilometers"}, "1 mile is 1.61 kilometers."),
    ({"amount": "twenty five", "from": "kg", "to": "pounds"}, "25 kg is 55.12 pounds."),
    ({"amount": 6, "from": "feet", "to": "cm"}, "6 feet is 182.9 cm."),
    ({"amount": 2, "from": "GB", "to": "MB"}, "2 GB is 2,000 MB."),
    ({"amount": 100, "from": "km/h", "to": "mph"}, "100 km/h is 62.14 mph."),
    ({"amount": 3, "from": "hours", "to": "minutes"}, "3 hours is 180 minutes."),
    ({"amount": 2, "from": "cups", "to": "ml"}, "2 cups is 473.2 ml."),
    ({"amount": 1, "from": "acre", "to": "square feet"}, "1 acre is 43,560 square feet."),
])
def test_units(args, want):
    assert cv.convert(args) == want


@pytest.mark.parametrize("args,want", [
    ({"amount": 100, "from": "F", "to": "C"}, "100 degrees Fahrenheit is 37.78 degrees Celsius."),
    ({"amount": 0, "from": "celsius", "to": "fahrenheit"}, "0 degrees Celsius is 32 degrees Fahrenheit."),
    ({"amount": 300, "from": "kelvin", "to": "°C"}, "300 kelvin is 26.85 degrees Celsius."),
])
def test_temperature(args, want):
    assert cv.convert(args) == want


def test_singular_plural():
    assert cv.convert({"amount": 30.48, "from": "cm", "to": "feet"}) == "30.48 cm is 1 foot."
    assert cv.convert({"amount": 1, "from": "square foot", "to": "sq m"}) == "1 square foot is 0.0929 sq m."


def test_unit_errors():
    assert "can't convert length to weight" in cv.convert({"amount": 1, "from": "km", "to": "kg"})
    assert "don't know the unit parsecs" in cv.convert({"amount": 1, "from": "parsecs", "to": "km"})
    assert "didn't get the number" in cv.convert({"amount": "lots", "from": "km", "to": "m"})
    assert "Tell me what" in cv.convert({"amount": 1, "from": "km"})


def _fake_resp(payload):
    r = mock.MagicMock()
    r.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return r


def test_currency_and_cache():
    cv._rate_cache.clear()
    with mock.patch.object(cv.urllib.request, "urlopen",
                           return_value=_fake_resp({"rates": {"INR": 84.5}})) as u:
        assert cv.convert({"amount": 10, "from": "dollars", "to": "rupees"}) == "10 US dollars is about 845 rupees."
        assert cv.convert({"amount": 2, "from": "USD", "to": "INR"}) == "2 US dollars is about 169 rupees."
    assert u.call_count == 1  # second call used the cache
    assert "from=USD&to=INR" in u.call_args[0][0].full_url


def test_currency_offline_and_fallback_url():
    cv._rate_cache.clear()
    with mock.patch.object(cv.urllib.request, "urlopen", side_effect=OSError("down")):
        assert "couldn't get exchange rates" in cv.convert({"amount": 1, "from": "euro", "to": "pounds sterling"})
    cv._rate_cache.clear()
    with mock.patch.object(cv.urllib.request, "urlopen",
                           side_effect=[OSError("down"), _fake_resp({"rates": {"JPY": 150.0}})]) as u:
        assert cv.convert({"amount": 1, "from": "usd", "to": "yen"}) == "1 US dollars is about 150 yen."
    assert "frankfurter.dev" in u.call_args[0][0].full_url


def test_pounds_is_weight_not_currency():
    assert cv.convert({"amount": 1, "from": "pound", "to": "grams"}) == "1 pound is 453.6 grams."


def test_to_number():
    assert cv.to_number("two hundred and fifty") == 250
    assert cv.to_number("1,500") == 1500
    assert cv.to_number("2.5") == 2.5
    assert cv.to_number("half") == 0.5
    assert cv.to_number("banana") is None


# ---------------- world time
NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset (Linux/macOS)")
def test_world_time_tokyo():
    try:
        with mock.patch.dict(os.environ, {"TZ": "Asia/Kolkata"}):
            time.tzset()
            out = cv.world_time({"city": "Tokyo"}, now=NOW)
    finally:
        time.tzset()
    assert out.startswith("In Tokyo it's 9:00 PM on Saturday.")
    assert "3 hours 30 minutes ahead of you" in out


def test_world_time_iana_fallback_and_unknown():
    assert cv.world_time({"city": "Lisbon"}, now=NOW).startswith("In Lisbon it's 12:00 PM")
    assert "don't know the time zone for Atlantis" in cv.world_time({"city": "Atlantis"}, now=NOW)
    assert cv.world_time({}) == "Which city?"


def test_world_time_missing_tzdata():
    with mock.patch.object(cv, "_zone_for", side_effect=ModuleNotFoundError):
        assert "pip install tzdata" in cv.world_time({"city": "Tokyo"})


# ---------------- date maths
@pytest.mark.parametrize("q,want", [
    ("how many days until 25 December", "48 days until Friday, 25 December."),
    ("how many days until christmas", "48 days until Friday, 25 December."),
    ("days until the 1st of january", "55 days until Friday, 1 January 2027."),
    ("how many days until December twenty fifth", "48 days until Friday, 25 December."),
    ("what day is 15 August", "15 August 2027 is a Sunday."),
    ("what day was 15/08/1947", "15 August 1947 was a Friday."),
    ("what is the date in 45 days", "It will be Tuesday, 22 December."),
    ("date in three weeks", "It will be Saturday, 28 November."),
    ("what was the date 10 days ago", "It was Wednesday, 28 October."),
    ("what's the date in 2 months", "It will be Thursday, 7 January 2027."),
    ("how many weeks until christmas", "6 weeks and 6 days until Friday, 25 December."),
    ("how many days since 1 January 2026", "Thursday, 1 January was 310 days ago."),
    ("days until tomorrow", "That's tomorrow, Sunday, 8 November."),
    ("how many days until next friday", "6 days until Friday, 13 November."),
    ("how many days until blorp", "I didn't get the date. Try like: how many days until 25 December."),
])
def test_date_calc(q, want):
    assert cv.date_calc({"question": q}, today=TODAY) == want


def test_date_calc_target_date():
    assert cv.date_calc({"target_date": "2026-12-31"}, today=TODAY) == "54 days until Thursday, 31 December."


def test_wiring_shape():
    assert set(cv.CATALOG) == set(cv.HANDLERS) == {"convert", "world_time", "date_calc"}
    for spec in cv.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec) and spec["info"] is True
