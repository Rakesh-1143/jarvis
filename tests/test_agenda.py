"""Calendar / agenda / briefing. Network and clock are faked."""
import datetime as dt
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import agenda  # noqa: E402

pytest.importorskip("icalendar")

TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))  # e.g. India
NOW = dt.datetime(2026, 11, 9, 9, 0, tzinfo=TZ)  # Monday 9 AM

# Times in UTC (Z) to check conversion: 04:30Z = 10:00 local.
ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:standup
SUMMARY:Standup
DTSTART:20261109T033000Z
DTEND:20261109T034500Z
RRULE:FREQ=DAILY;COUNT=10
END:VEVENT
BEGIN:VEVENT
UID:review
SUMMARY:Design review
LOCATION:Room 4
DTSTART:20261109T043000Z
DTEND:20261109T053000Z
END:VEVENT
BEGIN:VEVENT
UID:lunch
SUMMARY:Lunch with Priya
DTSTART:20261109T130000
DTEND:20261109T140000
END:VEVENT
BEGIN:VEVENT
UID:holiday
SUMMARY:Team offsite
DTSTART;VALUE=DATE:20261110
DTEND;VALUE=DATE:20261111
END:VEVENT
BEGIN:VEVENT
UID:cancelled
SUMMARY:Old meeting
STATUS:CANCELLED
DTSTART:20261109T090000
DTEND:20261109T100000
END:VEVENT
END:VCALENDAR
"""
# Standup 9:00-9:15, Design review 10:00-11:00, Lunch 13:00-14:00 (floating), offsite all day Tue.


@pytest.fixture(autouse=True)
def setup():
    agenda.configure({"calendars": ["webcal://example.com/cal.ics"], "calendar": {"alert_minutes": 5}})
    agenda._cache.clear()
    agenda._alerted.clear()
    with mock.patch.object(agenda, "_now", return_value=NOW), \
            mock.patch.object(agenda, "_fetch", return_value=ICS) as fetch:
        yield fetch


def test_catalog_matches_handlers():
    assert set(agenda.CATALOG) == set(agenda.HANDLERS)
    for spec in agenda.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
        assert spec["info"] is True


def test_webcal_becomes_https_and_is_cached(setup):
    agenda.agenda({"day": "today"})
    agenda.next_event({})
    setup.assert_called_once_with("https://example.com/cal.ics")


def test_agenda_today_skips_ended_and_cancelled():
    with mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=9, minute=30)):
        r = agenda.agenda({"day": "today"})
    assert r == "You have 2 more events today: Design review at 10 AM; Lunch with Priya at 1 PM."
    assert "Old meeting" not in r


def test_agenda_tomorrow_has_all_day_and_recurring():
    r = agenda.agenda({"day": "tomorrow"})
    assert r == "You have 2 events tomorrow: Team offsite, all day; Standup at 9 AM."


def test_agenda_empty_day_and_date_words():
    r = agenda.agenda({"day": "2026-12-25"})
    assert r == "You have nothing on your calendar on Friday 25 December."
    assert "Wednesday 11 November" in agenda.agenda({"day": "wednesday"})


def test_agenda_done_for_today():
    with mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=20)):
        assert agenda.agenda({}) == "You're done for today. You had 3 events."


def test_next_event_today_with_location():
    r = agenda.next_event({})  # 9:00 exactly: standup is "now"
    assert r == "You are in Standup until 9:15 AM. Your next meeting is Design review at 10 AM, in 1 hour, at Room 4."


def test_next_event_other_day():
    with mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=15)):
        r = agenda.next_event({})
    assert r == "Your next meeting is Standup tomorrow at 9 AM."


def test_free_at():
    assert agenda.free_at({"time": "10:30 am"}) == "No. At 10:30 AM you have Design review from 10 AM to 11 AM."
    r = agenda.free_at({"time": "11"})
    assert r == "Yes, you're free at 11 AM. Your next event after that is Lunch with Priya at 1 PM."
    assert agenda.free_at({"time": "1"}).startswith("No. At 1 PM you have Lunch")  # "1" = 1 PM
    assert agenda.free_at({"time": "3 pm", "day": "tomorrow"}) == "Yes, you're free at 3 PM tomorrow."
    assert agenda.free_at({"time": "banana"}) == "What time should I check?"


def test_parse_time():
    p = agenda.parse_time
    assert p("3 pm") == dt.time(15) and p("3:30pm") == dt.time(15, 30) and p("15:00") == dt.time(15)
    assert p("noon") == dt.time(12) and p("12 am") == dt.time(0) and p("three p.m.") == dt.time(15)
    assert p("half past 2") == dt.time(14, 30) and p("quarter to 10 am") == dt.time(9, 45)
    assert p("9") == dt.time(9) and p("2026-11-09T16:15:00") == dt.time(16, 15)
    assert p("") is None and p("25:00") is None


def test_parse_day():
    today = NOW.date()  # Monday
    p = agenda.parse_day
    assert p("tomorrow", today) == dt.date(2026, 11, 10)
    assert p("monday", today) == today and p("next monday", today) == dt.date(2026, 11, 16)
    assert p("friday", today) == dt.date(2026, 11, 13)
    assert p("25th december", today) == dt.date(2026, 12, 25) == p("Dec 25", today)
    assert p("january 3", today) == dt.date(2027, 1, 3)  # past date -> next year
    assert p("nonsense", today) is None


def test_not_set_up():
    agenda.configure({})
    assert "No calendar is set up" in agenda.agenda({})
    assert "No calendar is set up" in agenda.next_event({})
    assert agenda.start_alerts(print) is None


def test_offline_uses_message(setup):
    setup.side_effect = OSError("no internet")
    assert agenda.agenda({}) == agenda._OFFLINE
    assert agenda.next_event({}) == agenda._OFFLINE


def test_offline_uses_old_copy(setup):
    agenda.agenda({})
    agenda._cache["https://example.com/cal.ics"] = (0, ICS)  # old copy
    setup.side_effect = OSError("no internet")
    assert "Design review" in agenda.agenda({})


def test_briefing():
    with mock.patch("jarvis.actions.info.weather", return_value="In Pune it's 24 degrees and sunny."), \
            mock.patch.object(agenda, "_reminder_count", return_value=2), \
            mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=8)):
        r = agenda.briefing({})
    assert r.startswith("Good morning. It's 8 AM on Monday 9 November. In Pune it's 24 degrees and sunny.")
    assert "You have 3 events today: Standup at 9 AM" in r
    assert r.endswith("You have 2 reminders set.")


def test_briefing_without_calendar_or_internet():
    agenda.configure({})
    with mock.patch("jarvis.actions.info.weather", side_effect=OSError), \
            mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=18)):
        assert agenda.briefing({}) == "Good evening. It's 6 PM on Monday 9 November."


def test_reminder_count_reads_timers():
    from jarvis.actions import timers

    with mock.patch.object(timers, "_active", [{"kind": "reminder"}, {"kind": "timer"}, {"kind": "alarm"}]):
        assert agenda._reminder_count() == 2


def test_alerts_once_per_event():
    said = []
    at = NOW.replace(hour=9, minute=56)
    assert agenda.check_alerts(said.append, now=at) == ["Design review starts in 4 minutes, at Room 4."]
    assert agenda.check_alerts(said.append, now=at.replace(minute=58)) == []  # no repeat
    assert said == ["Design review starts in 4 minutes, at Room 4."]
    assert agenda.check_alerts(said.append, now=NOW.replace(hour=12)) == []  # lunch is 60 min away


def test_alerts_off():
    agenda.configure({"calendars": ["https://x/c.ics"], "calendar": {"alert_minutes": 0}})
    assert agenda.check_alerts(print, now=NOW.replace(hour=9, minute=56)) == []
    assert agenda.start_alerts(print) is None


def test_start_and_stop_alert_thread():
    said = []
    with mock.patch.object(agenda, "_now", return_value=NOW.replace(hour=9, minute=57)):
        t = agenda.start_alerts(said.append, every=0.01)
        assert t is not None and agenda.start_alerts(said.append) is t  # only one thread
        for _ in range(200):
            if said:
                break
            t.join(0.01)
        agenda.stop_alerts()
    assert said == ["Design review starts in 3 minutes, at Room 4."]


def test_outlook_errors_are_ignored():
    agenda.configure({"calendar": {"outlook": True}})  # no pywin32 on Linux
    assert agenda.agenda({}) == agenda._OFFLINE
