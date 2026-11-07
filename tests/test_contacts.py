"""Piece AX: contacts by voice. Uses a temp contacts.json and fake config contacts; no OS calls."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import contacts as c  # noqa: E402

CONFIG = {"mom": {"phone": "+91 98765 00000", "email": "mom@example.com"}, "boss": "boss@work.com"}


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "contacts.json"
    monkeypatch.setattr(c, "_path", lambda: str(path))
    raw = dict(CONFIG)

    def fake_config():
        out = {}
        for k, v in raw.items():
            e = {"name": k}
            if isinstance(v, dict):
                e.update(v)
            else:
                e["email"] = v
            out[k] = e
        return out

    monkeypatch.setattr(c, "_config_contacts", fake_config)
    return path


# ---------- cleaners ----------
@pytest.mark.parametrize("spoken, expected", [
    ("98765 43210", "9876543210"),
    ("plus 91 98765 43210", "+919876543210"),
    ("+91-98765-43210", "+919876543210"),
    ("nine eight seven six five four three two one zero", "9876543210"),
    ("double nine eight seven six five four three", "99876543"),
    ("123", ""),
    ("call me", ""),
])
def test_clean_phone(spoken, expected):
    assert c.clean_phone(spoken) == expected


@pytest.mark.parametrize("spoken, expected", [
    ("ravi at gmail dot com", "ravi@gmail.com"),
    ("Ravi.Kumar@Gmail.com", "ravi.kumar@gmail.com"),
    ("ravi underscore k at yahoo dot co dot in", "ravi_k@yahoo.co.in"),
    ("ravi at the rate gmail dot com", "ravi@gmail.com"),
    ("not an email", ""),
])
def test_clean_email(spoken, expected):
    assert c.clean_email(spoken) == expected


@pytest.mark.parametrize("spoken, expected", [
    ("5 May", "05-05"), ("5th May", "05-05"), ("May 5", "05-05"), ("5th of May 1990", "1990-05-05"),
    ("1990-05-05", "1990-05-05"), ("05/05/1990", "1990-05-05"), ("29/02", "02-29"),
    ("31 feb", ""), ("tomorrow", ""), ("5 May 2999", ""),
])
def test_clean_birthday(spoken, expected):
    assert c.clean_birthday(spoken) == expected


def test_say_birthday():
    assert c.say_birthday("05-05") == "5 May"
    assert c.say_birthday("1990-12-25") == "25 December 1990"


@pytest.mark.parametrize("spoken, expected", [
    ("Ravi's", "Ravi"), ("my mom's", "mom"), ("the boss", "boss"), ("  Priya   Sharma ", "Priya Sharma"),
])
def test_clean_name(spoken, expected):
    assert c.clean_name(spoken) == expected


# ---------- parse ----------
@pytest.mark.parametrize("text, expected", [
    ("add contact Ravi phone 98765 43210", ("contact_add", {"name": "Ravi", "phone": "98765 43210"})),
    ("Jarvis, add a new contact called Priya Sharma with phone plus 91 98765 43210 and email priya at gmail dot com",
     ("contact_add", {"name": "Priya Sharma", "phone": "plus 91 98765 43210", "email": "priya at gmail dot com"})),
    ("save contact Ravi", ("contact_add", {"name": "Ravi"})),
    ("Ravi's email is ravi at gmail dot com", ("contact_add", {"name": "Ravi", "email": "ravi at gmail dot com"})),
    ("add Ravi's number 98765 43210", ("contact_add", {"name": "Ravi", "phone": "98765 43210"})),
    ("save Ravi's number as 98765 43210", ("contact_add", {"name": "Ravi", "phone": "98765 43210"})),
    ("what's Ravi's number", ("contact_get", {"name": "Ravi", "field": "phone"})),
    ("what is my mom's email", ("contact_get", {"name": "mom", "field": "email"})),
    ("tell me Ravi's phone number", ("contact_get", {"name": "Ravi", "field": "phone"})),
    ("show Ravi's details", ("contact_get", {"name": "Ravi", "field": "all"})),
    ("show contact Ravi", ("contact_get", {"name": "Ravi", "field": "all"})),
    ("find Ravi in my contacts", ("contact_get", {"name": "Ravi", "field": "all"})),
    ("delete contact Ravi", ("contact_delete", {"name": "Ravi"})),
    ("remove Ravi from my contacts", ("contact_delete", {"name": "Ravi"})),
    ("list my contacts", ("contacts_list", {})),
    ("who is in my contacts", ("contacts_list", {})),
    ("how many contacts do I have", ("contacts_list", {})),
])
def test_parse(text, expected):
    assert c.parse(text) == expected


@pytest.mark.parametrize("text", [
    "what is the time", "what's today's date", "open chrome", "open chrome's settings",
    "remove milk from my shopping list", "delete the file report", "what's the weather", "",
    "whatsapp Ravi saying hi", "send an email to mom",
])
def test_parse_ignores_other_text(text):
    assert c.parse(text) is None


def test_birthday_phrase_only_for_known_contacts():
    # "X's birthday is ..." belongs to birthdays.py unless X is a contact
    assert c.parse("Priya's birthday is 5 May") is None
    assert c.parse("mom's birthday is 12 March") == ("contact_add", {"name": "mom", "birthday": "12 March"})


# ---------- handlers ----------
def test_add_then_get(tmp_file):
    r = c.contact_add({"name": "Ravi", "phone": "plus 91 98765 43210"})
    assert r.startswith("Saved Ravi") and "9 1 9 8" in r
    data = json.loads(tmp_file.read_text(encoding="utf-8"))
    assert data == {"ravi": {"name": "Ravi", "phone": "+919876543210"}}
    assert c.contact_get({"name": "ravi", "field": "phone"}) == "Ravi's number is + 9 1 9 8 7 6 5 4 3 2 1 0."
    assert c.contact_get({"name": "Ravi", "field": "email"}) == "I don't have Ravi's email."


def test_add_updates_existing_with_fuzzy_name():
    c.contact_add({"name": "Rohit", "phone": "9876543210"})
    r = c.contact_add({"name": "Rohith", "email": "rohit at gmail dot com"})
    assert r.startswith("Updated Rohit")
    assert c.lookup("rohit") == {"name": "Rohit", "phone": "9876543210", "email": "rohit@gmail.com",
                                 "birthday": "", "notes": ""}


def test_add_bad_values():
    assert "didn't catch a valid number" in c.contact_add({"name": "Ravi", "phone": "12"})
    assert c.lookup("Ravi") is None  # nothing saved
    r = c.contact_add({"name": "Ravi", "phone": "9876543210", "email": "nope"})
    assert r.startswith("Saved Ravi") and "didn't catch a valid email" in r


def test_add_without_name():
    assert "Whose contact" in c.contact_add({"phone": "9876543210"})


def test_birthday_and_all_details():
    c.contact_add({"name": "Priya", "phone": "9876543210", "birthday": "5th May 1990", "notes": "college friend"})
    assert c.contact_get({"name": "Priya", "field": "birthday"}) == "Priya's birthday is 5 May 1990."
    r = c.contact_get({"name": "Priya"})
    assert r.startswith("Priya: number 9 8") and "birthday 5 May 1990" in r and "notes college friend" in r


def test_config_contacts_are_read():
    assert c.lookup("my mom")["email"] == "mom@example.com"
    assert c.lookup("boss")["email"] == "boss@work.com"
    assert "mom's email is mom@example.com" in c.contact_get({"name": "mom", "field": "email"})


def test_adding_to_config_contact_saves_overlay(tmp_file):
    r = c.contact_add({"name": "mom", "birthday": "12 March"})
    assert r.startswith("Updated mom")
    saved = json.loads(tmp_file.read_text(encoding="utf-8"))
    assert saved == {"mom": {"name": "mom", "birthday": "03-12"}}  # config.yaml untouched
    m = c.lookup("mom")
    assert m["birthday"] == "03-12" and m["email"] == "mom@example.com"  # merged


def test_lookup_never_guesses_short_or_unknown():
    c.contact_add({"name": "Ravi", "phone": "9876543210"})
    assert c.lookup("tom") is None  # too short to fuzzy-match "mom"
    assert c.lookup("Zaheer") is None
    assert c.lookup("") is None


def test_lookup_tie_returns_none():
    c.contact_add({"name": "Rahul", "phone": "9876543210"})
    c.contact_add({"name": "Rahil", "phone": "9876543211"})
    assert c.lookup("Rahol") is None  # two close names: no guess
    assert c.lookup("rahul")["phone"] == "9876543210"  # exact always wins


def test_get_unknown():
    assert "don't have a contact called Zaheer" in c.contact_get({"name": "Zaheer"})


def test_delete_needs_yes(tmp_file):
    c.contact_add({"name": "Ravi", "phone": "9876543210"})
    assert c.risky_text({"name": "ravi"}) == "delete the contact Ravi"
    assert "Are you sure" in c.contact_delete({"name": "Ravi"})
    assert c.lookup("Ravi") is not None
    assert c.contact_delete({"name": "Ravi", "confirm": True}) == "Deleted the contact Ravi."
    assert c.lookup("Ravi") is None
    assert json.loads(tmp_file.read_text(encoding="utf-8")) == {}


def test_delete_unknown_and_config_only():
    assert c.risky_text({"name": "Zaheer"}) is None
    assert c.contact_delete({"name": "Zaheer", "confirm": True}) == "I don't have a contact called Zaheer."
    assert c.risky_text({"name": "mom"}) is None  # config.yaml contacts are read-only
    assert "config.yaml" in c.contact_delete({"name": "mom", "confirm": True})
    assert c.lookup("mom") is not None


def test_delete_overlay_keeps_config_copy():
    c.contact_add({"name": "mom", "birthday": "12 March"})
    r = c.contact_delete({"name": "mom", "confirm": True})
    assert "still there" in r
    assert c.lookup("mom")["birthday"] == ""


def test_list():
    assert c.contacts_list({}) == "You have 2 contacts: boss and mom."
    c.contact_add({"name": "Ravi", "phone": "9876543210"})
    assert c.contacts_list({}) == "You have 3 contacts: boss, mom and Ravi."


def test_list_empty(monkeypatch):
    monkeypatch.setattr(c, "_config_contacts", lambda: {})
    assert "no contacts yet" in c.contacts_list({})


def test_list_long_is_cut(monkeypatch):
    monkeypatch.setattr(c, "_config_contacts", lambda: {f"person {i:02d}": {"name": f"Person {i:02d}"}
                                                        for i in range(25)})
    r = c.contacts_list({})
    assert r.startswith("You have 25 contacts. The first 20 are:") and "Person 19" in r and "Person 20" not in r


def test_bad_file_is_ignored(tmp_file):
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("{not json", encoding="utf-8")
    assert c.lookup("mom") is not None
    assert c.contact_add({"name": "Ravi", "phone": "9876543210"}).startswith("Saved Ravi")


def test_all_contacts_shape():
    c.contact_add({"name": "Ravi", "phone": "9876543210"})
    allc = c.all_contacts()
    assert set(allc) == {"mom", "boss", "ravi"}
    assert allc["ravi"]["name"] == "Ravi"


# ---------- catalog ----------
def test_catalog_and_handlers_match():
    assert set(c.CATALOG) == set(c.HANDLERS) == {"contact_add", "contact_get", "contact_delete", "contacts_list"}
    assert c.CATALOG["contact_get"]["info"] and c.CATALOG["contacts_list"]["info"]
    assert not c.CATALOG["contact_add"].get("info") and not c.CATALOG["contact_delete"].get("info")
    for spec in c.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])
