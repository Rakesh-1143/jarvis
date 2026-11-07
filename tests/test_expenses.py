"""Expenses (piece P). Uses a temp CSV file and a fixed 'now'."""
import csv
import datetime as dt
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import expenses as ex  # noqa: E402

NOW = dt.datetime(2026, 11, 7, 14, 30)  # a Saturday


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "expenses.csv"
    monkeypatch.setattr(ex, "EXPENSES_FILE", str(path))
    monkeypatch.setattr(ex, "CURRENCY", "₹")
    return path


def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def add_at(when, amount, category=None, note=None):
    return ex.expense_add({"amount": amount, "category": category, "note": note}, now=when)


def test_parse_amount():
    assert ex.parse_amount(250) == 250
    assert ex.parse_amount("250") == 250
    assert ex.parse_amount("₹1,500") == 1500
    assert ex.parse_amount("rs 99.5") == 99.5
    assert ex.parse_amount("2.5k") == 2500
    assert ex.parse_amount("two hundred and fifty") == 250
    assert ex.parse_amount("fifteen hundred rupees") == 1500
    assert ex.parse_amount("") is None
    assert ex.parse_amount("lunch") is None
    assert ex.parse_amount(0) is None
    assert ex.parse_amount(None) is None
    assert ex.parse_amount(True) is None


def test_category_guess():
    assert ex.guess_category("lunch with Ravi") == "food"
    assert ex.guess_category("Uber to office") == "travel"
    assert ex.guess_category("electricity") == "bills"
    assert ex.guess_category("new shoes") == "shopping"
    assert ex.guess_category("books") == "shopping"
    assert ex.guess_category("gym") == "other"
    assert ex.category_of("Food") == "food"
    assert ex.category_of("groceries") == "food"
    assert ex.category_of("on petrol") == "travel"
    assert ex.category_of("gym") == "gym"
    assert ex.category_of("") is None


def test_money_format():
    assert ex.money(250) == "₹250"
    assert ex.money(1500) == "₹1,500"
    assert ex.money(12.5) == "₹12.50"


def test_add_saves_csv(tmp_file):
    r = add_at(NOW, 250, note="lunch")
    assert r == "Added ₹250 on lunch under food. Today's total is ₹250."
    saved = rows(tmp_file)
    assert saved == [{"date": "2026-11-07 14:30", "amount": "250", "category": "food", "note": "lunch"}]
    r = add_at(NOW, "120.5", category="travel", note="auto")
    assert r.endswith("Today's total is ₹370.50.")
    assert len(rows(tmp_file)) == 2


def test_add_category_word_becomes_note(tmp_file):
    # "I spent 200 on lunch" may come as category="lunch"
    add_at(NOW, 200, category="lunch")
    assert rows(tmp_file)[0]["category"] == "food"
    assert rows(tmp_file)[0]["note"] == "lunch"
    add_at(NOW, 80, category="food")
    assert rows(tmp_file)[1]["note"] == ""
    assert add_at(NOW, 50).startswith("Added ₹50 under other.")


def test_add_needs_amount(tmp_file):
    assert ex.expense_add({"amount": "", "note": "lunch"}) == "How much did you spend?"
    assert not tmp_file.exists()


def test_report_periods():
    add_at(NOW, 100, note="lunch")                              # today
    add_at(NOW - dt.timedelta(days=1), 200, note="uber")        # yesterday (Fri, this week)
    add_at(NOW - dt.timedelta(days=6), 300, note="rent")        # last Sunday (last week, this month)
    add_at(dt.datetime(2026, 10, 20, 9, 0), 1000, note="shoes")  # last month
    rep = lambda **a: ex.expense_report(a, now=NOW)  # noqa: E731
    assert rep(period="today") == "You spent ₹100 today."
    assert rep(period="yesterday") == "You spent ₹200 yesterday."
    assert rep(period="week") == "You spent ₹300 this week. ₹200 on travel and ₹100 on food."
    assert rep(period="this month").startswith("You spent ₹600 this month.")
    assert rep(period="last month") == "You spent ₹1,000 last month."
    assert rep(period="last week") == "You spent ₹300 last week."
    assert rep(period="all").startswith("You spent ₹1,600 in total.")
    assert rep().startswith("You spent ₹600 this month.")  # default month


def test_report_category():
    add_at(NOW, 100, note="lunch")
    add_at(NOW, 150, note="dinner")
    add_at(NOW, 500, note="petrol")
    r = ex.expense_report({"period": "month", "category": "food"}, now=NOW)
    assert r == "You spent ₹250 on food this month, in 2 expenses."
    r = ex.expense_report({"period": "today", "category": "shopping"}, now=NOW)
    assert r == "You spent nothing on shopping today."


def test_report_empty():
    assert ex.expense_report({"period": "today"}, now=NOW) == "You haven't spent anything today."


def test_undo(tmp_file):
    assert ex.expense_undo({}) == "There are no expenses to delete."
    add_at(NOW, 100, note="lunch")
    add_at(NOW, 40, note="tea")
    assert ex.expense_undo({}) == "Deleted the last expense: ₹40 on tea."
    assert [r["note"] for r in rows(tmp_file)] == ["lunch"]
    add_at(NOW, 70, category="travel")
    assert ex.expense_undo({}) == "Deleted the last expense: ₹70 for travel."


def test_skips_broken_lines(tmp_file):
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("date,amount,category,note\n"
                        "2026-11-07 10:00,50,food,tea\n"
                        "bad line,abc,,\n"
                        "2026-11-07 11:00,25,,\n", encoding="utf-8")
    assert ex.expense_report({"period": "today"}, now=NOW) == "You spent ₹75 today. ₹50 on food and ₹25 on other."


def test_catalog_matches_handlers():
    assert set(ex.CATALOG) == set(ex.HANDLERS)
    for spec in ex.CATALOG.values():
        assert spec["description"]
        assert set(spec["required"]) <= set(spec["properties"])
    assert ex.CATALOG["expense_report"].get("info") is True


def test_file_has_bom_and_formula_notes_are_plain_text(tmp_file):
    add_at(NOW, 10, note="=HYPERLINK(1)")
    assert tmp_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert rows(tmp_file)[0]["note"] == "'=HYPERLINK(1)"
    assert ex._load()[0]["note"] == "=HYPERLINK(1)"


def test_undo_keeps_hand_edited_lines(tmp_file):
    add_at(NOW, 10, note="tea")
    with open(tmp_file, "a", encoding="utf-8", newline="") as f:
        f.write("my own note line,,,\r\n")  # edited by hand, does not parse
    add_at(NOW, 20, note="lunch")
    assert "20" in ex.expense_undo({})
    text = tmp_file.read_text(encoding="utf-8-sig")
    assert "my own note line" in text and "tea" in text and "lunch" not in text
    assert "not an expense" in ex.expense_undo({})  # last line is the hand-edited one: left alone


def test_excel_lock_is_explained(tmp_file, monkeypatch):
    monkeypatch.setattr(ex, "_append", mock.Mock(side_effect=PermissionError(13, "denied")))
    assert "Excel" in add_at(NOW, 10, note="tea")
