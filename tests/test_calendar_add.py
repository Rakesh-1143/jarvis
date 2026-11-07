"""Tests for piece AM: actions/calendar_add.py (no real Outlook, Google or browser)."""
import datetime as dt
import urllib.parse

import pytest

from jarvis.actions import calendar_add as ca

TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 7, 10, 0, tzinfo=TZ)  # Saturday


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setattr(ca, "_now", lambda: NOW)
    conf = {"method": "auto", "default_minutes": 60, "credentials_file": "",
            "token_file": "~/t.json", "calendar_id": "primary"}
    monkeypatch.setattr(ca, "settings", lambda cfg=None: dict(conf))
    opened = []
    monkeypatch.setattr(ca, "_open", lambda url: opened.append(url) or True)

    def no_outlook():
        raise ca.NotAvailable("no outlook")

    monkeypatch.setattr(ca, "_outlook_app", no_outlook)
    return {"conf": conf, "opened": opened}


def _start(text):
    return ca.parse_start(text, NOW)


# ---------- parsing ----------
@pytest.mark.parametrize("text,expect", [
    ("tomorrow at 4 pm", dt.datetime(2026, 11, 8, 16, 0, tzinfo=TZ)),
    ("friday at 10", dt.datetime(2026, 11, 13, 10, 0, tzinfo=TZ)),
    ("on Friday at 10 am", dt.datetime(2026, 11, 13, 10, 0, tzinfo=TZ)),
    ("friday 10am", dt.datetime(2026, 11, 13, 10, 0, tzinfo=TZ)),
    ("4 pm tomorrow", dt.datetime(2026, 11, 8, 16, 0, tzinfo=TZ)),
    ("5 pm", dt.datetime(2026, 11, 7, 17, 0, tzinfo=TZ)),
    ("20 november at 3:30 pm", dt.datetime(2026, 11, 20, 15, 30, tzinfo=TZ)),
    ("next friday at noon", dt.datetime(2026, 11, 13, 12, 0, tzinfo=TZ)),
    ("2026-11-08T16:00", dt.datetime(2026, 11, 8, 16, 0, tzinfo=TZ)),
    ("2026-11-08T10:30:00Z", dt.datetime(2026, 11, 8, 16, 0, tzinfo=TZ)),
])
def test_parse_start(text, expect):
    start, err = _start(text)
    assert err == "" and start == expect


def test_time_passed_today_means_tomorrow():
    start, _ = _start("9 am")
    assert start == dt.datetime(2026, 11, 8, 9, 0, tzinfo=TZ)


@pytest.mark.parametrize("text,words", [
    ("", "When should I add it"),
    ("tomorrow", "What time"),
    ("november 20", "What time"),
    ("2026-11-08", "What time"),
    ("2026-11-01T10:00", "already passed"),
    ("blursday at 3", "didn't understand"),
])
def test_parse_start_errors(text, words):
    start, err = _start(text)
    assert start is None and words in err


@pytest.mark.parametrize("value,mins", [
    (30, 30), ("45", 45), ("1 hour", 60), ("an hour", 60), ("for 2 hours", 120),
    ("90 minutes", 90), ("half an hour", 30), ("an hour and a half", 90), ("1 hour 15 minutes", 75),
    ("2 hrs", 120), (0, None), (-5, None), ("soon", None), (True, None), (None, None),
])
def test_parse_minutes(value, mins):
    assert ca.parse_minutes(value) == mins


def test_build_event_defaults():
    ev, err = ca.build_event({"title": " Dentist ", "start": "tomorrow at 4 pm"}, NOW)
    assert err == ""
    assert ev["title"] == "Dentist" and ev["minutes"] == 60
    assert ev["end"] - ev["start"] == dt.timedelta(hours=1)


def test_build_event_missing_title_and_bad_minutes():
    assert ca.build_event({"start": "tomorrow at 4"}, NOW)[1].startswith("What should I call")
    ev, err = ca.build_event({"title": "x", "start": "tomorrow at 4", "minutes": "soon"}, NOW)
    assert ev is None and "How long" in err


# ---------- confirm flow ----------
def test_handler_asks_first_and_saves_nothing(_fake):
    reply = ca.calendar_add({"title": "Dentist", "start": "tomorrow at 4 pm", "minutes": "1 hour"})
    assert reply.startswith("Shall I add 'Dentist' tomorrow at 4:00 PM for 1 hour")
    assert _fake["opened"] == []


def test_risky_text_and_needs_confirm():
    args = {"title": "Meeting with Ravi", "start": "friday at 10", "location": "Office"}
    assert ca.risky_text(args) == "add 'Meeting with Ravi' Friday at 10:00 AM for 1 hour at Office to your calendar"
    assert ca.needs_confirm(args)
    assert ca.risky_text({"title": "x"}) is None  # missing time: handler asks instead
    assert not ca.needs_confirm({"start": "tomorrow at 4"})


def test_handler_reports_missing_parts():
    assert "What time" in ca.calendar_add({"title": "Gym", "start": "tomorrow", "confirm": True})


# ---------- saving ----------
def test_link_fallback(_fake):
    reply = ca.calendar_add({"title": "Dentist & co", "start": "tomorrow at 4 pm", "minutes": 30,
                             "location": "MG Road", "confirm": True})
    assert "Click Save" in reply
    url = _fake["opened"][0]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert q["action"] == ["TEMPLATE"] and q["text"] == ["Dentist & co"] and q["location"] == ["MG Road"]
    assert q["dates"] == ["20261108T103000Z/20261108T110000Z"]  # 4 pm IST = 10:30 UTC


class FakeItem:
    def __init__(self):
        self.saved = False

    def Save(self):
        self.saved = True


class FakeOutlook:
    def __init__(self):
        self.items = []

    def CreateItem(self, kind):
        assert kind == 1
        item = FakeItem()
        self.items.append(item)
        return item


def test_outlook_used_when_available(monkeypatch, _fake):
    app = FakeOutlook()
    monkeypatch.setattr(ca, "_outlook_app", lambda: app)
    reply = ca.calendar_add({"title": "Dentist", "start": "2026-11-08T16:00", "minutes": 45,
                             "location": "Clinic", "confirm": True})
    assert reply == "Added 'Dentist' tomorrow at 4:00 PM for 45 minutes at Clinic to your Outlook calendar."
    item = app.items[0]
    assert item.saved and item.Subject == "Dentist" and item.Start == "2026-11-08 16:00"
    assert item.Duration == 45 and item.Location == "Clinic" and item.ReminderSet is True
    assert _fake["opened"] == []


class FakeService:
    def __init__(self):
        self.calls = []

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.calls.append((calendarId, body))
        return self

    def execute(self):
        return {"id": "1"}


def test_google_used_when_configured(monkeypatch, _fake):
    _fake["conf"]["credentials_file"] = "~/creds.json"
    svc = FakeService()
    monkeypatch.setattr(ca, "_google_service", lambda conf: svc)
    reply = ca.calendar_add({"title": "Gym", "start": "tomorrow at 7 am", "confirm": True})
    assert reply.endswith("to your Google Calendar.")
    cal_id, body = svc.calls[0]
    assert cal_id == "primary" and body["summary"] == "Gym"
    assert body["start"]["dateTime"] == "2026-11-08T07:00:00+05:30"
    assert body["end"]["dateTime"] == "2026-11-08T08:00:00+05:30"


def test_google_error_falls_back_to_link(monkeypatch, _fake):
    _fake["conf"]["credentials_file"] = "~/creds.json"

    def broken(conf):
        raise RuntimeError("quota")

    monkeypatch.setattr(ca, "_google_service", broken)
    reply = ca.calendar_add({"title": "Gym", "start": "tomorrow at 7 am", "confirm": True})
    assert "Click Save" in reply and len(_fake["opened"]) == 1


def test_google_missing_credentials_file_not_available(tmp_path):
    with pytest.raises(ca.NotAvailable):
        ca._google_service({"credentials_file": str(tmp_path / "nope.json")})
    with pytest.raises(ca.NotAvailable):
        ca._google_service({"credentials_file": ""})


def test_method_link_skips_outlook(monkeypatch, _fake):
    _fake["conf"]["method"] = "link"
    monkeypatch.setattr(ca, "_outlook_app", lambda: pytest.fail("outlook must not be used"))
    assert "Click Save" in ca.calendar_add({"title": "x", "start": "tomorrow at 4", "confirm": True})


def test_nothing_works(monkeypatch, _fake):
    monkeypatch.setattr(ca, "_open", lambda url: False)
    reply = ca.calendar_add({"title": "x", "start": "tomorrow at 4", "confirm": True})
    assert reply.startswith("Sorry, I couldn't add the event.")


def test_outlook_not_available_off_windows(monkeypatch):
    monkeypatch.setattr(ca.sys, "platform", "linux")
    monkeypatch.undo()  # restore real _outlook_app from the autouse fixture
    monkeypatch.setattr(ca.sys, "platform", "linux")
    with pytest.raises(ca.NotAvailable):
        ca._outlook_app()


# ---------- settings + catalog ----------
def test_settings_reads_config(monkeypatch):
    monkeypatch.undo()
    s = ca.settings({"calendar": {"add_with": "GOOGLE", "default_minutes": 30},
                     "google_calendar": {"credentials_file": "c.json", "calendar_id": "work"}})
    assert s["method"] == "google" and s["default_minutes"] == 30
    assert s["credentials_file"] == "c.json" and s["calendar_id"] == "work"
    s = ca.settings({"calendar": {"add_with": "fax", "default_minutes": "x"}})
    assert s["method"] == "auto" and s["default_minutes"] == 60 and s["token_file"] == ca.DEFAULT_TOKEN


def test_catalog_matches_handlers():
    assert set(ca.CATALOG) == set(ca.HANDLERS) == {"calendar_add"}
    spec = ca.CATALOG["calendar_add"]
    assert spec["required"] == ["title", "start"] and not spec.get("info")
