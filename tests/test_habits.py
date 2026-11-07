"""Habits (piece AY). Uses a temp JSON file and fixed dates."""
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import habits as hb  # noqa: E402

TODAY = dt.date(2026, 11, 7)
D = dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "habits.json"
    monkeypatch.setattr(hb, "HABITS_FILE", str(path))
    monkeypatch.setattr(hb, "REMIND_AT", "")
    monkeypatch.setattr(hb, "_nudged_on", None)
    return path


def saved(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def done(name, day=TODAY, **extra):
    return hb.habit_done({"name": name, **extra}, today=day)


def test_clean_name():
    assert hb.clean_name("my workout") == "workout"
    assert hb.clean_name("meditated") == "meditation"
    assert hb.clean_name("worked out") == "workout"
    assert hb.clean_name("The Reading habit") == "reading"
    assert hb.clean_name("") == ""
    assert len(hb.clean_name("x" * 200)) <= hb.MAX_NAME


def test_first_done_creates_habit(tmp_file):
    r = done("my workout")
    assert "Started tracking workout" in r
    assert saved(tmp_file) == {"workout": ["2026-11-07"]}


def test_streak_grows_and_repeat_is_noop(tmp_file):
    done("reading", TODAY - 2 * D)
    done("reading", TODAY - D)
    r = done("reading")
    assert "Streak: 3 days" in r
    r2 = done("reading")
    assert "already marked done today" in r2
    assert len(saved(tmp_file)["reading"]) == 3


def test_yesterday_and_future_date():
    done("walk")
    r = hb.habit_done({"name": "walk", "day": "yesterday"}, today=TODAY)
    assert "yesterday" in r
    r = hb.habit_done({"name": "walk", "day": "2099-01-01"}, today=TODAY)  # future -> today
    assert "already" in r


def test_fuzzy_match_existing():
    done("meditation")
    r = done("meditate")
    assert "Meditation" in r and "already" in r
    done("workouts", TODAY - D)  # saved as "workout"
    assert "Streak: 2 days" in done("workout", TODAY)
    data = hb._load()
    assert set(data) == {"meditation", "workout"}


def test_no_name():
    assert "Which habit" in hb.habit_done({})
    assert "Which habit" in hb.habit_remove({})


def test_streak_functions():
    days = {TODAY - D, TODAY - 2 * D, TODAY - 5 * D}
    assert hb.streak(days, TODAY) == 2  # not done today yet: still alive
    assert hb.streak(days | {TODAY}, TODAY) == 3
    assert hb.streak({TODAY - 3 * D}, TODAY) == 0
    assert hb.best_streak(days) == 2
    assert hb.best_streak(set()) == 0


def test_status_empty():
    assert "not tracking any habits" in hb.habit_status({}, today=TODAY)


def test_status_one_habit():
    for i in range(1, 4):
        done("workout", TODAY - i * D)
    r = hb.habit_status({"name": "workout", "period": "today"}, today=TODAY)
    assert r.startswith("Not yet") and "3 days" in r
    done("workout")
    r = hb.habit_status({"name": "my workout", "period": "today"}, today=TODAY)
    assert r.startswith("Yes") and "4 days" in r
    r = hb.habit_status({"name": "workout"}, today=TODAY)
    assert "4 days streak, 4 of the last 7 days" in r
    assert "not tracking yoga" in hb.habit_status({"name": "yoga"}, today=TODAY)


def test_best_streak_shown():
    for i in range(10, 15):
        done("reading", TODAY - i * D)
    done("reading")
    r = hb.habit_status({"name": "reading"}, today=TODAY)
    assert "Best streak: 5 days" in r


def test_status_today_and_week():
    done("workout")
    done("reading", TODAY - D)
    r = hb.habit_status({"period": "today"}, today=TODAY)
    assert r == "Done today: workout. Still to do: reading."
    done("reading")
    assert "All done today" in hb.habit_status({"period": "today"}, today=TODAY)
    r = hb.habit_status({"period": "week"}, today=TODAY)
    assert r == "Last 7 days: reading 2 of 7 (streak 2); workout 1 of 7."
    assert hb.habit_status({"name": "all"}, today=TODAY).startswith("Last 7 days")


def test_remove(tmp_file):
    done("workout")
    done("reading")
    assert "delete the habit workout" in hb.risky_text({"name": "my workout"})
    assert "Removed the habit workout" in hb.habit_remove({"name": "workout"})
    assert saved(tmp_file) == {"reading": ["2026-11-07"]}
    assert "not tracking" in hb.habit_remove({"name": "yoga"})


def test_broken_file(tmp_file):
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text('{"workout": ["2026-11-06", "bad"], "x": 5}', encoding="utf-8")
    assert hb._load() == {"workout": {dt.date(2026, 11, 6)}}
    tmp_file.write_text("not json", encoding="utf-8")
    assert hb._load() == {}


def test_nudge(monkeypatch):
    said = []
    monkeypatch.setattr(hb, "notify", said.append)
    monkeypatch.setattr(hb, "REMIND_AT", "21:00")
    done("workout")
    done("reading", TODAY - D)
    done("journal", TODAY - D)
    assert hb.check(dt.datetime(2026, 11, 7, 20, 59)) is None
    msg = hb.check(dt.datetime(2026, 11, 7, 21, 0))
    assert msg == "Habit check: you haven't done journal and reading today."
    assert said == [msg]
    assert hb.check(dt.datetime(2026, 11, 7, 22, 0)) is None  # once a day
    assert hb.check(dt.datetime(2026, 11, 8, 21, 5)) is not None  # next day again


def test_nudge_off_or_all_done(monkeypatch):
    monkeypatch.setattr(hb, "notify", lambda m: None)
    done("workout")
    assert hb.check(dt.datetime(2026, 11, 7, 23, 0)) is None  # REMIND_AT "" = off
    monkeypatch.setattr(hb, "REMIND_AT", "25:99")
    assert hb._remind_at() is None
    monkeypatch.setattr(hb, "REMIND_AT", "21:00")
    assert hb.check(dt.datetime(2026, 11, 7, 23, 0)) is None  # all done


def test_start_without_remind_does_nothing(monkeypatch):
    monkeypatch.setattr(hb, "_thread", None)
    hb.start(lambda m: None)
    assert hb._thread is None


@pytest.mark.parametrize("text,expected", [
    ("I did my workout", ("habit_done", {"name": "workout"})),
    ("i did my workout yesterday", ("habit_done", {"name": "workout", "day": "yesterday"})),
    ("mark reading done", ("habit_done", {"name": "reading"})),
    ("Jarvis, mark my reading as done for today", ("habit_done", {"name": "reading", "day": "today"})),
    ("I meditated", ("habit_done", {"name": "meditation"})),
    ("I worked out today", ("habit_done", {"name": "workout", "day": "today"})),
    ("did I meditate today?", ("habit_status", {"period": "today", "name": "meditation"})),
    ("did I do my workout today", ("habit_status", {"period": "today", "name": "workout"})),
    ("my workout streak", ("habit_status", {"name": "workout"})),
    ("what's my reading streak", ("habit_status", {"name": "reading"})),
    ("habits this week", ("habit_status", {"period": "week"})),
    ("how are my habits", ("habit_status", {"period": "week"})),
    ("habit report", ("habit_status", {"period": "week"})),
    ("which habits are left", ("habit_status", {"period": "today"})),
    ("my habits today", ("habit_status", {"period": "today"})),
    ("remove habit reading", ("habit_remove", {"name": "reading"})),
    ("delete my workout habit", ("habit_remove", {"name": "workout"})),
    ("stop tracking meditation", ("habit_remove", {"name": "meditation"})),
])
def test_parse(text, expected):
    assert hb.parse(text) == expected


@pytest.mark.parametrize("text", [
    "I did it", "delete the file report", "remove report.txt", "open notepad",
    "mark this done", "what time is it", "I did my", "", None,
])
def test_parse_ignores(text):
    assert hb.parse(text) is None


def test_catalog_matches_handlers():
    assert set(hb.CATALOG) == set(hb.HANDLERS) == {"habit_done", "habit_status", "habit_remove"}
    for spec in hb.CATALOG.values():
        assert spec["description"] and "properties" in spec
