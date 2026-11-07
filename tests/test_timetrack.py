"""Time tracking (piece BI). Uses a temp JSON file and fixed times."""
import csv
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import timetrack as tt  # noqa: E402

NOW = dt.datetime(2026, 11, 7, 10, 0)   # a Saturday
M = dt.timedelta(minutes=1)
H = dt.timedelta(hours=1)


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "timetrack.json"
    monkeypatch.setattr(tt, "TRACK_FILE", str(path))
    monkeypatch.setattr(tt, "EXPORT_FILE", str(tmp_path / "Documents" / "time.csv"))
    return path


def saved(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sessions"]


def write(path, sessions):
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sessions": sessions}, f)


def start(p, at=NOW):
    return tt.track({"action": "start", "project": p}, now=at)


def stop(at, p=None):
    return tt.track({"action": "stop", "project": p}, now=at)


# ---------- helpers ----------
def test_dur():
    assert tt.dur(30) == "less than a minute"
    assert tt.dur(60) == "1 minute"
    assert tt.dur(3900) == "1 hour 5 minutes"
    assert tt.dur(7200) == "2 hours"


def test_clean_project():
    assert tt.clean_project("my College Project") == "college project"
    assert tt.clean_project("time on the website") == "website"
    assert tt.clean_project("working on thesis now") == "thesis"
    assert tt.clean_project("") == ""
    assert len(tt.clean_project("x" * 200)) <= tt.MAX_NAME


# ---------- start / stop / status ----------
def test_start_stop_saves(tmp_file):
    assert start("college project") == "Started tracking college project."
    s = saved(tmp_file)
    assert s == [{"project": "college project", "start": "2026-11-07T10:00:00", "end": None}]
    r = stop(NOW + 65 * M)
    assert r == "Stopped tracking college project. That was 1 hour 5 minutes."
    assert saved(tmp_file)[0]["end"] == "2026-11-07T11:05:00"


def test_start_other_stops_first(tmp_file):
    start("college project")
    r = start("website", NOW + 30 * M)
    assert r == "Stopped college project after 30 minutes. Started tracking website."
    s = saved(tmp_file)
    assert [x["project"] for x in s] == ["college project", "website"]
    assert s[0]["end"] == "2026-11-07T10:30:00" and s[1]["end"] is None


def test_start_same_is_noop(tmp_file):
    start("college project")
    r = start("College", NOW + 10 * M)   # matches saved name
    assert "Already tracking college project, for 10 minutes" in r
    assert len(saved(tmp_file)) == 1


def test_start_reuses_saved_name(tmp_file):
    start("college project")
    stop(NOW + H)
    start("colege project", NOW + 2 * H)  # close spelling
    assert saved(tmp_file)[-1]["project"] == "college project"


def test_start_needs_project():
    assert "Which project" in start("")


def test_stop_when_idle():
    assert stop(NOW) == "Nothing is being tracked right now."


def test_stop_wrong_project_keeps_running(tmp_file):
    start("college project")
    r = stop(NOW + H, "website")
    assert "not website" in r
    assert saved(tmp_file)[0]["end"] is None


def test_long_session_warns():
    start("thesis")
    assert "delete last session" in stop(NOW + 13 * H)


def test_status():
    assert "Nothing is being tracked" in tt.track({"action": "status"}, now=NOW)
    start("thesis")
    r = tt.track({"action": "status"}, now=NOW + 20 * M)
    assert r == "You are tracking thesis, for 20 minutes so far."


def test_missing_action_defaults():
    assert tt.track({"project": "thesis"}, now=NOW) == "Started tracking thesis."
    assert "tracking thesis" in tt.track({}, now=NOW + M)


def test_clock_going_back_no_negative(tmp_file):
    start("thesis")
    r = stop(NOW - H)
    assert "less than a minute" in r
    assert saved(tmp_file)[0]["end"] == "2026-11-07T10:00:00"


# ---------- reports ----------
def _week_data(tmp_file):
    write(tmp_file, [
        {"project": "college project", "start": "2026-11-02T09:00:00", "end": "2026-11-02T11:00:00"},  # Mon
        {"project": "website", "start": "2026-11-06T23:00:00", "end": "2026-11-07T01:00:00"},          # over midnight
        {"project": "college project", "start": "2026-11-07T08:00:00", "end": "2026-11-07T09:30:00"},
        {"project": "old", "start": "2026-10-20T08:00:00", "end": "2026-10-20T09:00:00"},             # last month
    ])


def test_report_week(tmp_file):
    _week_data(tmp_file)
    r = tt.track_report({"period": "week"}, now=NOW)
    assert r == ("This week: 5 hours 30 minutes in total. college project 3 hours 30 minutes; "
                 "website 2 hours.")


def test_report_today_clips_midnight(tmp_file):
    _week_data(tmp_file)
    r = tt.track_report({"period": "today"}, now=NOW)
    assert "college project 1 hour 30 minutes" in r and "website 1 hour" in r


def test_report_month_and_default_week(tmp_file):
    _week_data(tmp_file)
    assert tt.track_report({"period": "month"}, now=NOW).startswith("This month: 5 hours 30 minutes")
    assert tt.track_report({}, now=NOW).startswith("This week:")
    assert tt.track_report({"period": "nonsense"}, now=NOW).startswith("This week:")


def test_report_one_project(tmp_file):
    _week_data(tmp_file)
    assert tt.track_report({"project": "college", "period": "today"}, now=NOW) == \
        "You worked 1 hour 30 minutes on college project today."
    assert tt.track_report({"project": "old", "period": "week"}, now=NOW) == "No time on old this week."
    assert "haven't tracked garden" in tt.track_report({"project": "garden"}, now=NOW)


def test_report_includes_running(tmp_file):
    start("thesis", NOW - 45 * M)
    r = tt.track_report({"project": "thesis", "period": "today"}, now=NOW)
    assert r == "You worked 45 minutes on thesis today (still running)."
    assert tt.track_report({"period": "today"}, now=NOW) == "Today: 45 minutes on thesis."


def test_report_empty_and_none_in_period(tmp_file):
    assert "haven't tracked any time" in tt.track_report({}, now=NOW)
    write(tmp_file, [{"project": "old", "start": "2026-10-01T08:00:00", "end": "2026-10-01T09:00:00"}])
    assert tt.track_report({"period": "today"}, now=NOW) == "No time tracked today."


def test_report_top_limit(tmp_file):
    rows = [{"project": f"p{i}", "start": f"2026-11-07T0{i}:00:00", "end": f"2026-11-07T0{i}:{10 + i}:00"}
            for i in range(7)]
    write(tmp_file, rows)
    r = tt.track_report({"period": "today"}, now=NOW)
    assert "plus 2 more" in r and r.count(";") == 4


def test_export_csv(tmp_file, tmp_path):
    _week_data(tmp_file)
    start("thesis", NOW - 10 * M)
    r = tt.track_report({"period": "week", "export": True}, now=NOW)
    assert "Saved the sessions to time.csv in Documents" in r
    with open(tmp_path / "Documents" / "time.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["project", "start", "end", "minutes"]
    assert [r[0] for r in rows[1:]] == ["college project", "website", "college project", "thesis"]
    assert rows[-1][2] == "running" and rows[-1][3] == "10"


def test_export_failure_is_spoken(tmp_file, monkeypatch):
    _week_data(tmp_file)

    def boom(*a, **k):
        raise OSError("no")
    monkeypatch.setattr(tt, "_export", boom)
    assert "couldn't save the CSV" in tt.track_report({"export": True}, now=NOW)


# ---------- undo ----------
def test_undo(tmp_file):
    assert "no tracked session" in tt.track_undo({}, now=NOW)
    start("college project")
    start("thesis", NOW + H)
    q = tt.risky_text({})
    assert q.startswith("delete the last time tracking session (thesis")
    r = tt.track_undo({}, now=NOW + H + 5 * M)
    assert r == "Deleted the last session: thesis, 5 minutes, started 07 Nov 11:00, still running."
    assert [s["project"] for s in saved(tmp_file)] == ["college project"]


def test_risky_text_empty():
    assert tt.risky_text() == "delete the last time tracking session"


# ---------- file robustness ----------
def test_broken_file_and_rows(tmp_file):
    os.makedirs(tmp_file.parent, exist_ok=True)
    tmp_file.write_text("not json", encoding="utf-8")
    assert "Nothing is being tracked" in tt.track({"action": "status"}, now=NOW)
    write(tmp_file, [
        {"project": "", "start": "2026-11-07T08:00:00", "end": None},
        {"project": "a", "start": "bad", "end": None},
        {"project": "b", "start": "2026-11-07T09:00:00", "end": "2026-11-07T08:00:00"},
        "junk",
        {"project": "ok", "start": "2026-11-07T08:00:00", "end": "2026-11-07T09:00:00"},
    ])
    assert tt.track_report({"period": "today"}, now=NOW) == "Today: 1 hour on ok."


def test_two_open_sessions_closed(tmp_file):
    write(tmp_file, [
        {"project": "a", "start": "2026-11-07T08:00:00", "end": None},
        {"project": "b", "start": "2026-11-07T09:00:00", "end": None},
    ])
    assert "tracking b" in tt.track({"action": "status"}, now=NOW)
    assert "a 1 hour" in tt.track_report({"period": "today"}, now=NOW)


def test_save_error_spoken(monkeypatch):
    def boom(_):
        raise OSError("disk")
    monkeypatch.setattr(tt, "_save", boom)
    assert "couldn't save" in start("thesis")


# ---------- phrases ----------
@pytest.mark.parametrize("text,intent,args", [
    ("start tracking college project", "track", {"action": "start", "project": "college project"}),
    ("Jarvis, start tracking time on my website.", "track", {"action": "start", "project": "website"}),
    ("begin timing thesis", "track", {"action": "start", "project": "thesis"}),
    ("track my time on the essay", "track", {"action": "start", "project": "essay"}),
    ("i'm working on thesis now", "track", {"action": "start", "project": "thesis"}),
    ("stop tracking", "track", {"action": "stop"}),
    ("stop time tracking", "track", {"action": "stop"}),
    ("what am i tracking", "track", {"action": "status"}),
    ("am i tracking anything", "track", {"action": "status"}),
    ("how long did i work on college project today", "track_report", {"project": "college project", "period": "today"}),
    ("how much time have i worked on thesis this week", "track_report", {"project": "thesis", "period": "week"}),
    ("time report this week", "track_report", {"period": "week"}),
    ("my time tracking summary this month", "track_report", {"period": "month"}),
    ("what did i work on today", "track_report", {"period": "today"}),
    ("how many hours did i work this week", "track_report", {"period": "week"}),
    ("export my time report", "track_report", {"export": True}),
    ("delete last session", "track_undo", {}),
    ("undo the last tracking session", "track_undo", {}),
])
def test_parse(text, intent, args):
    assert tt.parse(text, projects=[]) == (intent, args)


@pytest.mark.parametrize("text", [
    "start notepad", "stop", "stop the timer", "start tracking it", "track my package",
    "how much time did i spend on chrome", "stop tracking meditation", "delete the file report",
    "what am i doing", "",
])
def test_parse_no_match(text):
    assert tt.parse(text, projects=["college project"]) is None


def test_parse_shared_phrases_need_known_project():
    # screentime phrase only when the project is tracked
    assert tt.parse("how much time did i spend on college project today", projects=["college project"]) == \
        ("track_report", {"project": "college project", "period": "today"})
    # habits phrase "stop tracking X" only when X is the running project
    assert tt.parse("stop tracking college project", projects=["college project"]) == \
        ("track", {"action": "stop", "project": "college project"})


def test_parse_stop_named_reads_running(tmp_file):
    assert tt.parse("stop tracking thesis") is None
    start("thesis")
    assert tt.parse("stop tracking thesis") == ("track", {"action": "stop", "project": "thesis"})
    assert tt.parse("stop tracking meditation") is None


def test_catalog_matches_handlers():
    assert set(tt.CATALOG) == set(tt.HANDLERS) == {"track", "track_report", "track_undo"}
    for spec in tt.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])
