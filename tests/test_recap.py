"""Evening recap (piece BO). Other modules' files go to tmp; calendar and screen time are faked."""
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import (agenda, birthdays, expenses, habits, lists, recap,  # noqa: E402
                            screentime, timers, timetrack)

NOW = dt.datetime(2026, 11, 7, 21, 30)
TODAY = NOW.date()
TOMORROW = TODAY + dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(habits, "HABITS_FILE", str(tmp_path / "habits.json"))
    monkeypatch.setattr(timetrack, "TRACK_FILE", str(tmp_path / "timetrack.json"))
    monkeypatch.setattr(expenses, "EXPENSES_FILE", str(tmp_path / "expenses.csv"))
    monkeypatch.setattr(expenses, "CURRENCY", "₹")
    monkeypatch.setattr(lists, "LISTS_FILE", str(tmp_path / "lists.json"))
    monkeypatch.setattr(screentime, "usage", lambda period="today", today=None: ({}, {}))
    monkeypatch.setattr(agenda, "calendars_set_up", lambda: False)
    monkeypatch.setattr(birthdays, "all_events", lambda: [])
    monkeypatch.setattr(timers, "_active", [])
    monkeypatch.setattr(recap, "AT", "")
    monkeypatch.setattr(recap, "_spoken_on", None)
    return tmp_path


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def ev(title, h, m=0, day=TOMORROW, all_day=False):
    start = dt.datetime.combine(day, dt.time(h, m))
    return {"title": title, "start": start, "end": start + dt.timedelta(hours=1), "all_day": all_day}


def calendar(monkeypatch, events):
    monkeypatch.setattr(agenda, "calendars_set_up", lambda: True)
    monkeypatch.setattr(agenda, "events_between",
                        lambda a, b: ([e for e in events if a <= e["start"] < b], True))


# ---------- empty ----------
def test_nothing_recorded():
    assert recap.recap({}, NOW) == "I don't have anything recorded for today yet."


def test_nothing_tomorrow():
    assert recap.recap({"day": "tomorrow"}, NOW) == "Nothing is planned for tomorrow yet."


# ---------- each part ----------
def test_screen_time_top_three(monkeypatch):
    apps = {"chrome": 7200, "code": 3600, "whatsapp": 1200, "notepad": 600, "calc": 30}
    monkeypatch.setattr(screentime, "usage", lambda period="today", today=None: (apps, {}))
    out = recap.recap({}, NOW)
    assert out.startswith("Here's your day. Screen time was 3 hours 30 minutes, mostly ")
    top = out.split("mostly ")[1].split(".")[0]
    assert top.count(" and ") == 1 and top.count(",") == 1
    assert "2 hours" in top and "1 hour" in top and "20 minutes" in top


def test_screen_time_under_a_minute_skipped(monkeypatch):
    monkeypatch.setattr(screentime, "usage", lambda period="today", today=None: ({"calc": 20}, {}))
    assert recap.recap({}, NOW).startswith("I don't have anything")


def test_projects_today_only(isolate):
    write(isolate / "timetrack.json", {"sessions": [
        {"project": "college", "start": "2026-11-07T09:00:00", "end": "2026-11-07T11:30:00"},
        {"project": "website", "start": "2026-11-07T14:00:00", "end": "2026-11-07T14:45:00"},
        {"project": "old", "start": "2026-11-06T09:00:00", "end": "2026-11-06T12:00:00"},
    ]})
    out = recap.recap({}, NOW)
    assert "You worked 2 hours 30 minutes on college and 45 minutes on website." in out
    assert "old" not in out


def test_running_project_counts_to_now(isolate):
    write(isolate / "timetrack.json", {"sessions": [{"project": "jarvis", "start": "2026-11-07T20:30:00", "end": None}]})
    assert "You worked 1 hour on jarvis." in recap.recap({}, NOW)


def test_habits_done_and_left(isolate):
    write(isolate / "habits.json", {"workout": ["2026-11-07"], "reading": ["2026-11-06"], "yoga": ["2026-11-07"]})
    assert "Habits: you did workout and yoga, but not reading." in recap.recap({}, NOW)


def test_habits_all_done(isolate):
    write(isolate / "habits.json", {"workout": ["2026-11-07"]})
    assert "You did all your habits: workout." in recap.recap({}, NOW)


def test_habits_none_done(isolate):
    write(isolate / "habits.json", {"workout": ["2026-11-01"]})
    assert "You haven't done your habits yet: workout." in recap.recap({}, NOW)


def test_money_spent_today(isolate):
    (isolate / "expenses.csv").write_text(
        "date,amount,category,note\n2026-11-07 13:00,250,food,lunch\n2026-11-07 18:00,200,travel,cab\n"
        "2026-11-06 10:00,999,other,x\n", encoding="utf-8")
    assert "You spent ₹450 in 2 expenses." in recap.recap({}, NOW)


def test_open_todos(isolate):
    write(isolate / "lists.json", {"to-do": ["call bank", "pay rent", "email Ravi"], "shopping": ["milk"]})
    assert "3 to-dos are still open." in recap.recap({}, NOW)
    write(isolate / "lists.json", {"to-do": ["call bank"]})
    assert "1 to-do is still open." in recap.recap({}, NOW)


def test_reminders_tonight_counts_only_today(monkeypatch):
    late = dt.datetime(2026, 11, 7, 22, 0).timestamp()
    next_day = dt.datetime(2026, 11, 8, 9, 0).timestamp()
    monkeypatch.setattr(timers, "_active", [
        {"label": "reminder: take pills", "ends": late, "message": "", "kind": "reminder"},
        {"label": "tea timer", "ends": late, "message": "", "kind": "timer"},
        {"label": "alarm", "ends": next_day, "message": "", "kind": "alarm"},
    ])
    assert "You have 1 reminder still set for tonight." in recap.recap({}, NOW)


def test_first_event_tomorrow(monkeypatch):
    calendar(monkeypatch, [ev("Holiday", 0, all_day=True), ev("Standup", 9, 30), ev("Lunch", 13)])
    assert "Tomorrow starts with Standup at 9:30 AM, one of 3 events." in recap.recap({}, NOW)


def test_one_event_tomorrow(monkeypatch):
    calendar(monkeypatch, [ev("Dentist", 11)])
    assert "Tomorrow starts with Dentist at 11 AM." in recap.recap({}, NOW)


def test_birthday_tomorrow(monkeypatch):
    monkeypatch.setattr(birthdays, "all_events", lambda: [
        {"name": "mom", "date": "1965-11-08", "kind": "birthday"},
        {"name": "ravi", "date": "11-20", "kind": "birthday"},
    ])
    out = recap.recap({}, NOW)
    assert "Mom's birthday is tomorrow." in out and "Ravi" not in out


def test_broken_part_is_skipped(monkeypatch, isolate):
    def boom(*a, **k):
        raise RuntimeError("bad")
    monkeypatch.setattr(screentime, "usage", boom)
    monkeypatch.setattr(agenda, "calendars_set_up", boom)
    write(isolate / "lists.json", {"to-do": ["a", "b"]})
    assert recap.recap({}, NOW) == "Here's your day. 2 to-dos are still open."


def test_full_order(monkeypatch, isolate):
    monkeypatch.setattr(screentime, "usage", lambda period="today", today=None: ({"chrome": 3600}, {}))
    write(isolate / "habits.json", {"workout": ["2026-11-07"]})
    write(isolate / "lists.json", {"to-do": ["a"]})
    calendar(monkeypatch, [ev("Standup", 9)])
    out = recap.recap({}, NOW)
    assert out.index("Screen time") < out.index("habits") < out.index("to-do") < out.index("Tomorrow starts")


def test_does_not_write_files(isolate):
    write(isolate / "habits.json", {"workout": ["2026-11-07"]})
    before = sorted(os.listdir(isolate))
    recap.recap({}, NOW)
    recap.recap({"day": "tomorrow"}, NOW)
    assert sorted(os.listdir(isolate)) == before


# ---------- tomorrow ----------
def test_tomorrow_view(monkeypatch):
    calendar(monkeypatch, [ev("Standup", 9), ev("Lunch", 13), ev("Gym", 18), ev("Call", 20), ev("Today", 22, day=TODAY)])
    monkeypatch.setattr(timers, "_active", [
        {"label": "reminder: pay rent", "ends": dt.datetime(2026, 11, 8, 10, 0).timestamp(), "message": "", "kind": "reminder"}])
    monkeypatch.setattr(birthdays, "all_events", lambda: [{"name": "me", "date": "2000-11-08", "kind": "birthday"}])
    out = recap.recap({"day": "tomorrow"}, NOW)
    assert out.startswith("Tomorrow: You have 4 events: Standup at 9 AM, Lunch at 1 PM and Gym at 6 PM, plus 1 more.")
    assert "Reminders: pay rent at 10 AM." in out
    assert "Your birthday is tomorrow." in out
    assert "Today at" not in out


def test_tomorrow_skips_today_stuff(monkeypatch, isolate):
    write(isolate / "lists.json", {"to-do": ["a"]})
    assert recap.recap({"day": "tomorrow"}, NOW) == "Nothing is planned for tomorrow yet."


def test_day_arg_default_today(isolate):
    write(isolate / "lists.json", {"to-do": ["a"]})
    assert recap.recap({"day": "weird"}, NOW).startswith("Here's your day.")
    assert recap.recap(None, NOW).startswith("Here's your day.")


# ---------- daily recap ----------
def test_check_off_without_time():
    assert recap.check(NOW) is None


def test_check_speaks_once_a_day(monkeypatch, isolate):
    said = []
    monkeypatch.setattr(recap, "AT", "21:30")
    monkeypatch.setattr(recap, "notify", said.append)
    write(isolate / "lists.json", {"to-do": ["a"]})
    assert recap.check(NOW - dt.timedelta(minutes=1)) is None
    msg = recap.check(NOW)
    assert msg and said == [msg] and "to-do" in msg
    assert recap.check(NOW + dt.timedelta(minutes=5)) is None
    assert recap.check(NOW + dt.timedelta(days=1)) is not None


@pytest.mark.parametrize("value,expected", [("21:30", dt.time(21, 30)), ("7.05", dt.time(7, 5)),
                                            ("25:00", None), ("", None), ("soon", None)])
def test_at_parsing(monkeypatch, value, expected):
    monkeypatch.setattr(recap, "AT", value)
    assert recap._at() == expected


def test_start_without_time_does_nothing(monkeypatch):
    monkeypatch.setattr(recap, "_thread", None)
    recap.start(print)
    assert recap._thread is None


# ---------- phrases ----------
@pytest.mark.parametrize("text", ["how was my day", "How was my day?", "Jarvis, how was my day", "evening recap",
                                  "give me my evening recap", "day recap", "daily recap please", "recap my day",
                                  "recap of the day", "how did my day go", "wrap up my day", "end of day recap"])
def test_parse_today(text):
    assert recap.parse(text) == ("recap", {"day": "today"})


@pytest.mark.parametrize("text", ["what does tomorrow look like", "what's tomorrow look like", "how does tomorrow look",
                                  "what's tomorrow like", "prepare me for tomorrow", "recap for tomorrow"])
def test_parse_tomorrow(text):
    assert recap.parse(text) == ("recap", {"day": "tomorrow"})


@pytest.mark.parametrize("text", ["", "how was the movie", "what's on tomorrow", "summary of my day", "my day",
                                  "what's the weather tomorrow", "recap the meeting"])
def test_parse_no_match(text):
    assert recap.parse(text) is None


def test_catalog_matches_handlers():
    assert set(recap.CATALOG) == set(recap.HANDLERS) == {"recap"}
