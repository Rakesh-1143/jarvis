"""Repeating reminders (piece L). Uses a temp JSON file; no real waiting."""
import datetime as dt
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import recurring as rc  # noqa: E402


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "rep.json"
    monkeypatch.setattr(rc, "STORE_FILE", str(path))
    rc.reset()
    said = []
    monkeypatch.setattr(rc, "notify", said.append)
    yield path, said
    rc.reset()


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ts(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi).timestamp()


def test_parse_time():
    assert rc.parse_time("9") == "09:00"
    assert rc.parse_time("9 am") == "09:00"
    assert rc.parse_time("9:30 pm") == "21:30"
    assert rc.parse_time("12 am") == "00:00"
    assert rc.parse_time("12 p.m.") == "12:00"
    assert rc.parse_time("21:05") == "21:05"
    assert rc.parse_time("noon") == "12:00"
    assert rc.parse_time("7 o'clock") == "07:00"
    assert rc.parse_time("25:00") is None
    assert rc.parse_time("soon") is None


def test_parse_days():
    assert rc.parse_days("weekdays") == [0, 1, 2, 3, 4]
    assert rc.parse_days("weekends") == [5, 6]
    assert rc.parse_days("daily") == list(range(7))
    assert rc.parse_days("monday and friday") == [0, 4]
    assert rc.parse_days("Mondays") == [0]
    assert rc.parse_days(None) == list(range(7))
    assert rc.parse_days([0, "friday"]) == [0, 4]


def test_create_interval_and_list(store):
    path, _ = store
    r = rc.repeat_reminder({"text": "to drink water", "every_minutes": 60})
    assert r == "Okay, I will remind you to drink water, every hour."
    data = saved(path)
    assert data[0]["text"] == "drink water" and data[0]["every_minutes"] == 60
    assert data[0]["next"] > time.time() + 3500
    rc.repeat_reminder({"text": "stretch", "every_minutes": 30})
    assert rc.repeat_reminders({"action": "list"}) == \
        "You have 2 repeating reminders: drink water, every hour; stretch, every 30 minutes."


def test_create_daily_weekdays():
    r = rc.repeat_reminder({"text": "take medicine", "at": "9 am", "days": "weekdays"})
    assert r == "Okay, I will remind you to take medicine, every weekday at 9 AM."
    r = rc.repeat_reminder({"text": "team call", "at": "10:30", "days": "monday"})
    assert r == "Okay, I will remind you to team call, every Monday at 10:30 AM."


def test_create_errors():
    assert "What should" in rc.repeat_reminder({"every_minutes": 5})
    assert "How often" in rc.repeat_reminder({"text": "x"})
    assert "didn't get the time" in rc.repeat_reminder({"text": "x", "at": "later"})
    assert "shortest" in rc.repeat_reminder({"text": "x", "every_minutes": 0.2})


def test_next_time_weekdays():
    it = {"text": "x", "at": "09:00", "days": [0, 1, 2, 3, 4]}
    fri_10 = ts(2026, 11, 6, 10)  # Friday
    assert rc.next_time(it, fri_10) == ts(2026, 11, 9, 9)  # Monday
    mon_8 = ts(2026, 11, 9, 8)
    assert rc.next_time(it, mon_8) == ts(2026, 11, 9, 9)


def test_interval_fires_and_moves_on(store):
    _, said = store
    rc.repeat_reminder({"text": "drink water", "every_minutes": 60})
    first = rc._load()[0]["next"]
    assert rc._check(first - 1) == []
    assert rc._check(first + 5) == ["Reminder: drink water."]
    assert said == ["Reminder: drink water."]
    assert rc._load()[0]["next"] == first + 3600
    assert rc._check(first + 10) == []  # no double fire


def test_missed_over_one_hour_is_skipped(store):
    _, said = store
    rc.repeat_reminder({"text": "pills", "at": "09:00", "days": "daily"})
    it = rc._load()[0]
    nine = it["next"]
    assert rc._check(nine + 2 * 3600) == []  # laptop was asleep for 2 h
    assert said == []
    assert it["next"] == nine + 86400 or abs(it["next"] - (nine + 86400)) <= 3600  # DST safe


def test_missed_under_one_hour_still_fires():
    rc.repeat_reminder({"text": "pills", "at": "09:00", "days": "daily"})
    nine = rc._load()[0]["next"]
    assert rc._check(nine + 1800) == ["Reminder: pills."]


def test_interval_after_long_sleep_restarts_from_now():
    rc.repeat_reminder({"text": "water", "every_minutes": 30})
    first = rc._load()[0]["next"]
    later = first + 5 * 3600
    assert rc._check(later) == []
    assert rc._load()[0]["next"] == later + 1800


def test_survives_restart(store):
    path, _ = store
    rc.repeat_reminder({"text": "water", "every_minutes": 45})
    rc.reset()
    assert "water, every 45 minutes" in rc.repeat_reminders({"action": "list"})


def test_cancel_one_and_ambiguous():
    rc.repeat_reminder({"text": "drink water", "every_minutes": 60})
    rc.repeat_reminder({"text": "water the plants", "at": "18:00"})
    rc.repeat_reminder({"text": "stretch", "every_minutes": 30})
    assert rc.repeat_reminders({"action": "cancel", "text": "water"}).startswith("Which one?")
    assert rc.repeat_reminders({"action": "cancel", "text": "the stretch reminder"}) == \
        "Stopped the reminder to stretch."
    assert rc.repeat_reminders({"action": "cancel", "text": "plants"}) == \
        "Stopped the reminder to water the plants."
    assert "couldn't find" in rc.repeat_reminders({"action": "cancel", "text": "yoga"})


def test_cancel_all_needs_confirm(store):
    path, _ = store
    rc.repeat_reminder({"text": "a thing", "every_minutes": 10})
    args = {"action": "cancel", "text": "all"}
    assert rc.needs_confirm(args)
    assert not rc.needs_confirm({"action": "cancel", "text": "water"})
    assert rc.repeat_reminders(args).startswith("Are you sure")
    assert len(saved(path)) == 1
    assert rc.repeat_reminders({**args, "confirm": True}) == "Stopped all 1 repeating reminder."
    assert saved(path) == []
    assert rc.repeat_reminders({"action": "list"}) == "You have no repeating reminders."


@pytest.mark.parametrize("text,intent,args", [
    ("remind me to drink water every hour", "repeat_reminder", {"every_minutes": 60, "text": "drink water"}),
    ("remind me every 30 minutes to stretch", "repeat_reminder", {"every_minutes": 30, "text": "stretch"}),
    ("every two hours remind me to rest my eyes", "repeat_reminder", {"every_minutes": 120, "text": "rest my eyes"}),
    ("every weekday at 9 take medicine", "repeat_reminder",
     {"at": "09:00", "days": [0, 1, 2, 3, 4], "text": "take medicine"}),
    ("remind me every day at 8 pm to call mom", "repeat_reminder",
     {"at": "20:00", "days": list(range(7)), "text": "call mom"}),
    ("every Monday at 10 remind me about the team call", "repeat_reminder",
     {"at": "10:00", "days": [0], "text": "the team call"}),
    ("remind me every monday and friday at 6:30 pm to go to the gym", "repeat_reminder",
     {"at": "18:30", "days": [0, 4], "text": "go to the gym"}),
    ("remind me every morning to check email", "repeat_reminder",
     {"at": "08:00", "days": list(range(7)), "text": "check email"}),
    ("list repeating reminders", "repeat_reminders", {"action": "list"}),
    ("what are my recurring reminders", "repeat_reminders", {"action": "list"}),
    ("stop all repeating reminders", "repeat_reminders", {"action": "cancel", "text": "all"}),
    ("cancel the water repeating reminder", "repeat_reminders", {"action": "cancel", "text": "water"}),
])
def test_parse(text, intent, args):
    assert rc.parse(text) == (intent, args)


def test_parse_stop_named_only_if_it_exists():
    assert rc.parse("stop the water reminder") is None  # nothing saved: leave it to timers
    assert rc.parse("cancel my reminders") is None
    rc.repeat_reminder({"text": "drink water", "every_minutes": 60})
    assert rc.parse("stop the water reminder") == ("repeat_reminders", {"action": "cancel", "text": "water"})


@pytest.mark.parametrize("text", [
    "remind me to call mom in 10 minutes",
    "set a timer for 5 minutes",
    "what is the weather",
    "every",
])
def test_parse_ignores_other(text):
    assert rc.parse(text) is None


def test_catalog_matches_handlers():
    assert set(rc.CATALOG) == set(rc.HANDLERS)
    for spec in rc.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])


def test_thread_start_stop(monkeypatch):
    monkeypatch.setattr(rc, "TICK", 0.01)
    got = []
    rc.start(got.append)
    assert rc._thread.is_alive()
    assert rc.notify == got.append
    rc.stop()
    rc._thread.join(1)
    assert not rc._thread.is_alive()
