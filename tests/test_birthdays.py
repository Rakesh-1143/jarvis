"""Piece BA: birthdays and anniversaries. Temp files + fake config contacts; no OS calls."""
import datetime as dt
import json

import pytest

from jarvis.actions import birthdays as b
from jarvis.actions import contacts as c

TODAY = dt.date(2026, 11, 7)  # a Saturday


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    bpath = tmp_path / "b" / "birthdays.json"
    cpath = tmp_path / "c" / "contacts.json"
    monkeypatch.setattr(b, "_path", lambda: str(bpath))
    monkeypatch.setattr(c, "_path", lambda: str(cpath))
    monkeypatch.setattr(c, "_config_contacts", lambda: {"boss": {"name": "boss", "email": "boss@work.com"}})
    monkeypatch.setattr(b, "REMIND_AT", "09:00")
    monkeypatch.setattr(b, "DAY_BEFORE", True)
    monkeypatch.setattr(b, "_alerted_on", None)
    spoken = []
    monkeypatch.setattr(b, "notify", spoken.append)
    return {"b": bpath, "c": cpath, "spoken": spoken}


def _contact(name, **kw):
    c.contact_add({"name": name, "phone": "98765 43210", **kw})


# ---------- dates ----------
def test_next_date_today_and_wrap():
    assert b.next_date("11-07", TODAY) == TODAY
    assert b.next_date("11-06", TODAY) == dt.date(2027, 11, 6)
    assert b.next_date("1990-12-25", TODAY) == dt.date(2026, 12, 25)
    assert b.next_date("bad", TODAY) is None


def test_feb_29_in_non_leap_year():
    assert b.next_date("02-29", TODAY) == dt.date(2027, 2, 28)
    assert b.next_date("02-29", dt.date(2028, 1, 1)) == dt.date(2028, 2, 29)


def test_clean_name():
    assert b.clean_name("my mom's") == "mom"
    assert b.clean_name("my") == "me"
    assert b.clean_name("our") == "our"
    assert b.clean_name("Ravi") == "Ravi"


# ---------- add ----------
def test_add_non_contact_goes_to_own_file(tmp_files):
    msg = b.birthday_add({"name": "Priya", "date": "5 May 1990"}, TODAY)
    assert "Priya's birthday" in msg and "5 May" in msg
    data = json.loads(tmp_files["b"].read_text())
    assert data["entries"]["birthday:priya"] == {"name": "Priya", "date": "1990-05-05", "kind": "birthday"}
    assert not tmp_files["c"].exists()


def test_add_contact_birthday_goes_to_contact(tmp_files):
    _contact("Ravi")
    msg = b.birthday_add({"name": "ravi", "date": "12 March"}, TODAY)
    assert "Ravi's birthday" in msg
    assert c.lookup("Ravi")["birthday"] == "03-12"
    assert "birthday:ravi" not in b._load()["entries"]


def test_add_contact_moves_old_file_copy(tmp_files):
    b.birthday_add({"name": "Ravi", "date": "1 May"}, TODAY)
    _contact("Ravi")
    b.birthday_add({"name": "Ravi", "date": "2 May"}, TODAY)
    assert "birthday:ravi" not in b._load()["entries"]
    assert c.lookup("Ravi")["birthday"] == "05-02"


def test_anniversary_never_goes_to_contact(tmp_files):
    _contact("Ravi")
    b.birthday_add({"name": "Ravi", "date": "1 June", "kind": "anniversary"}, TODAY)
    assert b._load()["entries"]["anniversary:ravi"]["date"] == "06-01"
    assert not c.lookup("Ravi")["birthday"]


def test_add_bad_date_and_no_name():
    assert "didn't catch the date" in b.birthday_add({"name": "Priya", "date": "next friday"}, TODAY)
    assert "Whose" in b.birthday_add({"date": "5 May"}, TODAY)
    assert b._load()["entries"] == {}


def test_add_says_reminder_or_soon():
    assert "remind you the day before" in b.birthday_add({"name": "Priya", "date": "5 May"}, TODAY)
    assert "today" in b.birthday_add({"name": "Anu", "date": "7 November"}, TODAY)
    assert "tomorrow" in b.birthday_add({"name": "Raj", "date": "8 November"}, TODAY)


def test_add_self_and_our():
    assert "your birthday" in b.birthday_add({"name": "my", "date": "1 Jan"}, TODAY)
    assert "your anniversary" in b.birthday_add({"name": "our", "date": "10 June 2015", "kind": "anniversary"}, TODAY)


def test_add_save_error(monkeypatch):
    def boom(_):
        raise OSError("disk full")
    monkeypatch.setattr(b, "_save", boom)
    assert "couldn't save" in b.birthday_add({"name": "Priya", "date": "5 May"}, TODAY)


# ---------- get one ----------
def test_get_from_file_and_contacts():
    b.birthday_add({"name": "Priya", "date": "5 May 1990"}, TODAY)
    _contact("Ravi", birthday="10 November")
    assert b.birthday_get({"name": "priya"}, TODAY) == "Priya's birthday is on 5 May, in 179 days. Priya turns 37."
    msg = b.birthday_get({"name": "Ravi"}, TODAY)
    assert "10 November" in msg and "on Tuesday, in 3 days" in msg


def test_get_contact_wins_over_file(tmp_files):
    _contact("Ravi", birthday="10 November")
    tmp_files["b"].parent.mkdir(parents=True, exist_ok=True)
    tmp_files["b"].write_text(json.dumps({"entries": {"birthday:ravi": {"name": "Ravi", "date": "01-01",
                                                                         "kind": "birthday"}}}))
    assert "10 November" in b.birthday_get({"name": "Ravi"}, TODAY)


def test_get_fuzzy_name():
    b.birthday_add({"name": "Priyanka", "date": "5 May"}, TODAY)
    assert "Priyanka" in b.birthday_get({"name": "priyankaa"}, TODAY)


def test_get_today_and_age():
    b.birthday_add({"name": "Anu", "date": "7 November 2000"}, TODAY)
    assert b.birthday_get({"name": "Anu"}, TODAY) == "Today is Anu's birthday! Anu turns 26 today."


def test_get_age_without_year():
    b.birthday_add({"name": "Priya", "date": "5 May"}, TODAY)
    assert "don't know the year" in b.birthday_get({"name": "Priya", "ask": "age"}, TODAY)


def test_get_unknown():
    assert "I don't know Zed's birthday" in b.birthday_get({"name": "Zed"}, TODAY)
    assert "my birthday is" in b.birthday_get({"name": "me"}, TODAY)


def test_get_anniversary_years():
    b.birthday_add({"name": "our", "date": "10 June 2015", "kind": "anniversary"}, TODAY)
    msg = b.birthday_get({"name": "our", "kind": "anniversary"}, TODAY)
    assert msg.startswith("Your anniversary is on 10 June") and "12th anniversary" in msg


def test_get_falls_back_to_other_kind():
    b.birthday_add({"name": "mom and dad", "date": "3 February", "kind": "anniversary"}, TODAY)
    assert "Mom and dad's anniversary" in b.birthday_get({"name": "mom and dad"}, TODAY)


# ---------- lists ----------
@pytest.fixture
def some():
    for n, d in (("Anu", "7 November 2000"), ("Raj", "8 November"), ("Ravi", "12 November"),
                 ("Priya", "5 May"), ("Old", "1 November")):
        b.birthday_add({"name": n, "date": d}, TODAY)
    b.birthday_add({"name": "our", "date": "20 November 2015", "kind": "anniversary"}, TODAY)


def test_list_empty():
    assert "don't know any" in b.birthday_get({"period": "week"}, TODAY)


def test_list_week(some):
    msg = b.birthday_get({"period": "week"}, TODAY)
    assert msg == "Birthdays in the next 7 days: Anu today (turns 26), Raj tomorrow and Ravi on 12 November."


def test_list_month(some):
    msg = b.birthday_get({"period": "month"}, TODAY)
    assert msg.startswith("Birthdays in November: Old on 1, Anu (turns 26) today, Raj on 8")
    assert "your anniversary (11th) on 20" in msg
    assert b.birthday_get({"period": "month", "month": 5}, TODAY) == "Birthdays in May: Priya on 5."
    assert b.birthday_get({"period": "month", "month": "march"}, TODAY) == "No birthdays or anniversaries in March."


def test_list_today_tomorrow_next(some):
    assert b.birthday_get({"period": "today"}, TODAY) == "Today: Anu's birthday, Anu turns 26."
    assert b.birthday_get({"period": "tomorrow"}, TODAY) == "Tomorrow: Raj's birthday."
    assert b.birthday_get({"period": "next"}, TODAY).startswith("Today is Anu's birthday")


def test_list_upcoming_and_kind_filter(some):
    msg = b.birthday_get({}, TODAY)
    assert msg.startswith("Coming up in the next 30 days:") and "Priya" not in msg
    assert b.birthday_get({"period": "upcoming", "kind": "anniversary"}, TODAY).startswith(
        "Coming up in the next 30 days: your anniversary")


def test_upcoming_none_says_next():
    b.birthday_add({"name": "Priya", "date": "5 May"}, TODAY)
    msg = b.birthday_get({}, TODAY)
    assert msg.startswith("No birthdays or anniversaries in the next 30 days.") and "5 May" in msg


def test_list_caps_long(monkeypatch):
    monkeypatch.setattr(b, "MAX_SPOKEN", 2)
    for i in range(4):
        b.birthday_add({"name": f"P{i}x", "date": f"{10 + i} November"}, TODAY)
    assert b.birthday_get({"period": "month"}, TODAY).endswith("And 2 more.")


# ---------- reminder ----------
def at(h, m=0, day=TODAY):
    return dt.datetime.combine(day, dt.time(h, m))


def test_check_today_and_tomorrow(some, tmp_files):
    assert b.check(at(8, 59)) is None
    msg = b.check(at(9, 0))
    assert msg == "Reminder: Today is Anu's birthday, Anu turns 26. Tomorrow is Raj's birthday."
    assert tmp_files["spoken"] == [msg]
    assert b.check(at(10)) is None  # once a day
    assert json.loads(tmp_files["b"].read_text())["last_alert"] == "2026-11-07"


def test_check_not_repeated_after_restart(some, monkeypatch):
    assert b.check(at(9))
    monkeypatch.setattr(b, "_alerted_on", None)  # Jarvis restarted
    assert b.check(at(11)) is None


def test_check_day_before_off(some, monkeypatch):
    monkeypatch.setattr(b, "DAY_BEFORE", False)
    assert b.check(at(9)) == "Reminder: Today is Anu's birthday, Anu turns 26."


def test_check_nothing_and_off(monkeypatch):
    b.birthday_add({"name": "Priya", "date": "5 May"}, TODAY)
    assert b.check(at(9)) is None
    monkeypatch.setattr(b, "_alerted_on", None)
    monkeypatch.setattr(b, "REMIND_AT", "")
    b.birthday_add({"name": "Anu", "date": "7 November"}, TODAY)
    assert b.check(at(9)) is None


def test_check_contact_birthday(tmp_files):
    _contact("Ravi", birthday="8 November")
    assert b.check(at(9)) == "Reminder: Tomorrow is Ravi's birthday."


def test_start_off_does_not_start_thread(monkeypatch):
    monkeypatch.setattr(b, "REMIND_AT", "")
    monkeypatch.setattr(b, "_thread", None)
    b.start(lambda m: None)
    assert b._thread is None


def test_bad_file_is_ignored(tmp_files):
    tmp_files["b"].parent.mkdir(parents=True, exist_ok=True)
    tmp_files["b"].write_text('{"entries": {"x": {"name": "X", "date": "13-40"}, "y": 5}, "last_alert": 3}')
    assert b._load()["entries"] == {}
    tmp_files["b"].write_text("not json")
    assert b.all_events() == []


# ---------- phrases ----------
@pytest.mark.parametrize("text, expected", [
    ("mom's birthday is 12 March", ("birthday_add", {"name": "mom", "date": "12 march", "kind": "birthday"})),
    ("Jarvis, remember that my mom's birthday is on 12th March.",
     ("birthday_add", {"name": "mom", "date": "12th march", "kind": "birthday"})),
    ("add Ravi's birthday 5 May 1990", ("birthday_add", {"name": "ravi", "date": "5 may 1990", "kind": "birthday"})),
    ("add birthday for Priya on 5/5", ("birthday_add", {"name": "priya", "date": "5/5", "kind": "birthday"})),
    ("my birthday is 1 January", ("birthday_add", {"name": "me", "date": "1 january", "kind": "birthday"})),
    ("our anniversary is 10 June 2015", ("birthday_add", {"name": "our", "date": "10 june 2015", "kind": "anniversary"})),
    ("my wedding anniversary is 10 June", ("birthday_add", {"name": "our", "date": "10 june", "kind": "anniversary"})),
    ("mom and dad's anniversary is 3 February",
     ("birthday_add", {"name": "mom and dad", "date": "3 february", "kind": "anniversary"})),
    ("Ravi was born on 5 May 1990", ("birthday_add", {"name": "ravi", "date": "5 may 1990", "kind": "birthday"})),
    ("I was born on 1 Jan 1995", ("birthday_add", {"name": "me", "date": "1 jan 1995", "kind": "birthday"})),
    ("we got married on 10 June 2015", ("birthday_add", {"name": "our", "date": "10 june 2015", "kind": "anniversary"})),
    ("when is mom's birthday", ("birthday_get", {"name": "mom", "kind": "birthday"})),
    ("when's my birthday", ("birthday_get", {"name": "me", "kind": "birthday"})),
    ("what's Ravi's birthday?", ("birthday_get", {"name": "ravi", "kind": "birthday"})),
    ("when is our anniversary", ("birthday_get", {"name": "our", "kind": "anniversary"})),
    ("how old is Priya turning", ("birthday_get", {"name": "priya", "kind": "birthday", "ask": "age"})),
    ("how old will Priya be this year", ("birthday_get", {"name": "priya", "kind": "birthday", "ask": "age"})),
    ("how old am I turning", ("birthday_get", {"name": "me", "kind": "birthday", "ask": "age"})),
    ("birthdays this month", ("birthday_get", {"period": "month"})),
    ("any birthdays this week", ("birthday_get", {"period": "week"})),
    ("are there any birthdays today", ("birthday_get", {"period": "today"})),
    ("upcoming birthdays", ("birthday_get", {"period": "upcoming"})),
    ("birthdays in December", ("birthday_get", {"period": "month", "month": 12})),
    ("any anniversaries this month", ("birthday_get", {"period": "month", "kind": "anniversary"})),
    ("whose birthday is next", ("birthday_get", {"period": "next"})),
    ("whose birthday is today", ("birthday_get", {"period": "today"})),
    ("is today anyone's birthday", ("birthday_get", {"period": "today"})),
    ("show my birthdays and anniversaries", ("birthday_get", {"period": "upcoming"})),
])
def test_parse(text, expected):
    assert b.parse(text, TODAY) == expected


@pytest.mark.parametrize("text", [
    "", "open notepad", "happy birthday", "play happy birthday song", "mom's birthday party is at 6",
    "how old is the taj mahal", "birthday gift ideas for mom", "what's Ravi's number", "remember to buy milk",
    "my birthday is next friday", "when is it's birthday",
])
def test_parse_not_ours(text):
    assert b.parse(text, TODAY) is None


def test_parse_next_month():
    intent, args = b.parse("birthdays next month")
    assert intent == "birthday_get" and args["period"] == "month" and 1 <= args["month"] <= 12


def test_parsed_add_runs_end_to_end():
    intent, args = b.parse("Ravi was born on 5 May 1990", TODAY)
    b.HANDLERS[intent](args, TODAY)
    intent, args = b.parse("how old is Ravi turning", TODAY)
    assert "Ravi turns 37" in b.HANDLERS[intent](args, TODAY)


def test_catalog_matches_handlers():
    assert set(b.CATALOG) == set(b.HANDLERS) == {"birthday_add", "birthday_get"}
    assert b.CATALOG["birthday_get"]["info"] is True
    assert "info" not in b.CATALOG["birthday_add"]
