"""Meetings: links, join, leave, mute, status. Calendar, windows and hotkeys are faked."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import agenda, meetings  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 9, 9, 0, tzinfo=TZ)  # Monday 9 AM


def _ev(title, h, m=0, mins=60, location="", uid="", day=0):
    s = NOW.replace(hour=h, minute=m) + dt.timedelta(days=day)
    return {"title": title, "start": s, "end": s + dt.timedelta(minutes=mins), "all_day": False,
            "location": location, "uid": uid}


@pytest.fixture
def fake(monkeypatch):
    state = {"events": [], "opened": [], "keys": [], "titles": [], "active": "", "focused": [],
             "zoom": True, "ok": True, "procs": set()}
    monkeypatch.setattr(agenda, "_now", lambda: NOW)
    monkeypatch.setattr(agenda, "calendars_set_up", lambda: True)

    def events_between(start, end):
        evs = [e for e in state["events"] if e["start"] < end and e["end"] > start]
        return sorted(evs, key=lambda e: e["start"]), state["ok"]

    monkeypatch.setattr(agenda, "events_between", events_between)
    monkeypatch.setattr(meetings, "_open", lambda url: state["opened"].append(url))
    monkeypatch.setattr(meetings, "_hotkey", lambda keys: state["keys"].append(keys))
    monkeypatch.setattr(meetings, "_window_titles", lambda: list(state["titles"]))
    monkeypatch.setattr(meetings, "_active_title", lambda: state["active"])
    monkeypatch.setattr(meetings, "_zoom_installed", lambda: state["zoom"])
    monkeypatch.setattr(meetings, "_process_names", lambda: state["procs"])
    monkeypatch.setattr(meetings, "_description", lambda ev: ev.get("desc", ""))

    def focus(title):
        state["focused"].append(title)
        state["active"] = title
        return True

    monkeypatch.setattr(meetings, "_focus", focus)
    return state


def test_catalog_matches_handlers():
    assert set(meetings.CATALOG) == set(meetings.HANDLERS) == {"meeting"}
    assert meetings.CATALOG["meeting"]["properties"]["action"]["enum"] == ["join", "leave", "mute", "status"]


@pytest.mark.parametrize("text,app", [
    ("Join: https://us02web.zoom.us/j/123456789?pwd=abcDEF.1 thanks", "zoom"),
    ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0?context=%7b%7d", "teams"),
    ("Join with Google Meet: https://meet.google.com/abc-defg-hij", "meet"),
    ("https://acme.webex.com/acme/j.php?MTID=m123", "webex"),
    ("<https://nam12.safelinks.protection.outlook.com/?url=https%3A%2F%2Fmeet.google.com%2Fabc-defg-hij&data=x>", "meet"),
])
def test_find_link(text, app):
    hit = meetings.find_link(text)
    assert hit and hit[0] == app


def test_find_link_none_and_first_wins():
    assert meetings.find_link("Room 4") is None
    assert meetings.find_link("") is None
    hit = meetings.find_link("Meet https://meet.google.com/abc-defg-hij or https://zoom.us/j/1")
    assert hit[0] == "meet"


def test_zoom_app_url():
    assert meetings.zoom_app_url("https://us02web.zoom.us/j/123456789?pwd=ab+c") == \
        "zoommtg://zoom.us/join?action=join&confno=123456789&pwd=ab%20c"
    assert meetings.zoom_app_url("https://zoom.us/j/42") == "zoommtg://zoom.us/join?action=join&confno=42"
    assert meetings.zoom_app_url("https://zoom.us/my/rakesh") == "https://zoom.us/my/rakesh"


def test_join_next_uses_zoom_app(fake):
    fake["events"] = [_ev("Standup", 8, mins=15), _ev("Design review", 10, location="https://zoom.us/j/555?pwd=x")]
    out = meetings.meeting({"action": "join"})
    assert fake["opened"] == ["zoommtg://zoom.us/join?action=join&confno=555&pwd=x"]
    assert "Design review" in out and "Zoom" in out and "1 hour" in out


def test_join_zoom_without_app_opens_web_link(fake):
    fake["zoom"] = False
    fake["events"] = [_ev("Sync", 9, 5, location="https://zoom.us/j/555")]
    meetings.meeting({"action": "join"})
    assert fake["opened"] == ["https://zoom.us/j/555"]


def test_join_prefers_meeting_on_now_and_reads_description(fake):
    fake["events"] = [_ev("Later", 11, location="https://zoom.us/j/1"),
                      dict(_ev("Class", 8, 30), desc="Join with Google Meet: https://meet.google.com/abc-defg-hij")]
    out = meetings.meeting({"action": "join", "when": "next"})
    assert fake["opened"] == ["https://meet.google.com/abc-defg-hij"]
    assert out == "Joining Class on Google Meet."


def test_join_at_time(fake):
    fake["events"] = [_ev("A", 10, location="https://zoom.us/j/1"),
                      _ev("B", 15, location="https://teams.microsoft.com/l/meetup-join/abc")]
    out = meetings.meeting({"action": "join", "when": "3 pm"})
    assert fake["opened"] == ["https://teams.microsoft.com/l/meetup-join/abc"]
    assert "B on Teams" in out


def test_join_tomorrow_at_time(fake):
    fake["events"] = [_ev("Tomorrow call", 10, day=1, location="https://meet.google.com/abc-defg-hij")]
    out = meetings.meeting({"action": "join", "when": "tomorrow at 10 am"})
    assert fake["opened"] and "tomorrow at 10 AM" in out


def test_join_no_link_and_no_meeting(fake):
    fake["events"] = [_ev("Lunch", 13, location="Cafe")]
    assert "has no Zoom" in meetings.meeting({"action": "join"})
    assert "has no Zoom" in meetings.meeting({"action": "join", "when": "1 pm"})
    fake["events"] = []
    assert "no online meeting" in meetings.meeting({"action": "join"})
    assert "at that time" in meetings.meeting({"action": "join", "when": "4 pm"})
    assert fake["opened"] == []


def test_join_offline_and_not_set(fake, monkeypatch):
    fake["ok"] = False
    assert meetings.meeting({"action": "join"}) == agenda._OFFLINE
    monkeypatch.setattr(agenda, "calendars_set_up", lambda: False)
    assert meetings.meeting({"action": "join"}) == agenda._NOT_SET


def test_join_bad_time(fake):
    assert "Which meeting" in meetings.meeting({"action": "join", "when": "banana"})


def test_title_app():
    assert meetings._title_app("Zoom Meeting") == "zoom"
    assert meetings._title_app("Zoom Workplace") is None  # main window, not a call
    assert meetings._title_app("Meet - abc-defg-hij - Google Chrome") == "meet"
    assert meetings._title_app("Meeting with Priya | Microsoft Teams") == "teams"
    assert meetings._title_app("Chat | Microsoft Teams") is None
    assert meetings._title_app("Google Meet - Google Chrome") is None  # lobby, no code
    assert meetings._title_app("Webex Meeting") == "webex"


def test_leave_teams_focuses_window_first(fake):
    fake["titles"] = ["Inbox - Outlook", "Meeting with Priya | Microsoft Teams"]
    fake["active"] = "Inbox - Outlook"
    out = meetings.meeting({"action": "leave"})
    assert fake["focused"] == ["Meeting with Priya | Microsoft Teams"]
    assert fake["keys"] == [("ctrl", "shift", "h")]
    assert out == "Left the Teams meeting."


def test_leave_zoom_never_confirms(fake):
    fake["active"] = "Zoom Meeting"
    out = meetings.meeting({"action": "leave"})
    assert fake["keys"] == [("alt", "q")]
    assert "confirm" in out


def test_leave_meet_closes_tab_only_when_meet_in_front(fake, monkeypatch):
    fake["titles"] = ["Meet - abc-defg-hij - Google Chrome"]
    fake["active"] = "Notepad"
    monkeypatch.setattr(meetings, "_focus", lambda t: False)
    out = meetings.meeting({"action": "leave"})
    assert fake["keys"] == [] and "click on the Google Meet window" in out
    fake["active"] = "Meet - abc-defg-hij - Google Chrome"
    assert meetings.meeting({"action": "leave"}) == "Left the Google Meet meeting."
    assert fake["keys"] == [("ctrl", "w")]


def test_focus_that_lands_elsewhere_sends_nothing(fake, monkeypatch):
    fake["titles"] = ["Meet - abc-defg-hij - Google Chrome"]
    fake["active"] = "Notepad"
    monkeypatch.setattr(meetings, "_focus", lambda t: True)  # says ok, but Notepad stays in front
    assert "click on" in meetings.meeting({"action": "leave"})
    assert fake["keys"] == []


def test_mute_per_app(fake):
    for title, keys in [("Zoom Meeting", ("alt", "a")),
                        ("Meeting in General | Microsoft Teams", ("ctrl", "shift", "m")),
                        ("Meet - abc-defg-hij", ("ctrl", "d"))]:
        fake["active"] = title
        fake["keys"].clear()
        assert "mute" in meetings.meeting({"action": "mute"})
        assert fake["keys"] == [keys]


def test_leave_webex_not_supported_and_no_meeting(fake):
    assert "can't see" in meetings.meeting({"action": "leave"})
    fake["active"] = "Webex Meeting"
    assert "can't leave Webex" in meetings.meeting({"action": "leave"})
    assert fake["keys"] == []


def test_status(fake):
    fake["titles"] = ["Zoom Meeting"]
    assert meetings.meeting({"action": "status"}) == "Yes, you're in a Zoom meeting."
    fake["titles"] = []
    assert meetings.meeting({"action": "status"}) == "No, you're not in a meeting."
    fake["events"] = [_ev("Standup", 8, 45, mins=30)]
    fake["procs"] = {"ms-teams.exe"}
    out = meetings.meeting({"action": "status"})
    assert "Standup" in out and "9:15 AM" in out and "running" in out


def test_unknown_action(fake):
    assert "I can join" in meetings.meeting({"action": "dance"})


def test_description_reads_ics_by_uid(monkeypatch):
    pytest.importorskip("icalendar")
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\nBEGIN:VEVENT\r\nUID:u1\r\n"
           b"SUMMARY:Class\r\nDTSTART:20261109T033000Z\r\nDTEND:20261109T043000Z\r\n"
           b"DESCRIPTION:Join with Google Meet: https://meet.google.com/abc-defg-hij\r\n"
           b"END:VEVENT\r\nEND:VCALENDAR\r\n")
    meetings._desc_cache.clear()
    monkeypatch.setattr(agenda, "CALENDARS", ["https://x/cal.ics"])
    monkeypatch.setattr(agenda, "_get_ics", lambda url: ics)
    ev = {"title": "Class", "location": "", "uid": "u1"}
    assert meetings.event_link(ev) == ("meet", "https://meet.google.com/abc-defg-hij")
    assert meetings._description({"uid": "nope"}) == ""
    assert meetings._description({}) == ""
    meetings._desc_cache.clear()
