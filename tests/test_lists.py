"""Lists (piece A). Uses a temp JSON file."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import lists  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "lists.json"
    monkeypatch.setattr(lists, "LISTS_FILE", str(path))
    return path


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_list_name_aliases():
    assert lists.list_name("my To Do list") == "to-do"
    assert lists.list_name("todo") == "to-do"
    assert lists.list_name("groceries") == "shopping"
    assert lists.list_name("the packing list") == "packing"
    assert lists.list_name("") == "to-do"
    assert lists.list_name(None) == "to-do"


def test_add_and_read(tmp_file):
    assert lists.list_add({"list": "shopping", "item": "milk"}) == "Added milk to your shopping list."
    assert saved(tmp_file)["shopping"] == ["milk"]
    r = lists.list_add({"list": "my shopping list", "item": "eggs, bread and some butter"})
    assert r == "Added eggs, bread and butter to your shopping list."
    assert lists.list_read({"list": "shopping"}) == "Your shopping list has 4 items: milk, eggs, bread and butter."


def test_add_duplicate_is_skipped():
    lists.list_add({"list": "shopping", "item": "eggs"})
    assert "already" in lists.list_add({"list": "shopping", "item": "Egg"})
    r = lists.list_add({"list": "shopping", "item": "eggs and jam"})
    assert r.startswith("Added jam") and "already" in r


def test_add_needs_item():
    assert "What should I add" in lists.list_add({"list": "shopping", "item": ""})


def test_remove_by_name_and_number(tmp_file):
    lists.list_add({"list": "to-do", "item": "call mom, pay rent, buy gift"})
    assert lists.list_remove({"list": "todo", "item": "Pay Rent"}) == "Removed pay rent from your to-do list."
    assert lists.list_remove({"list": "to-do", "item": "item 1"}) == "Removed call mom from your to-do list."
    assert lists.list_remove({"list": "to-do", "item": "the last one"}) == "Removed buy gift from your to-do list."
    assert saved(tmp_file)["to-do"] == []


def test_remove_partial_and_missing():
    lists.list_add({"list": "shopping", "item": "orange juice"})
    assert "Removed orange juice" in lists.list_remove({"list": "shopping", "item": "juice"})
    assert "couldn't find" in lists.list_remove({"list": "shopping", "item": "cheese"})
    assert "don't have" in lists.list_remove({"list": "party", "item": "cake"})


def test_read_empty_and_unknown():
    assert lists.list_read({"list": "shopping"}) == "Your shopping list is empty."
    assert lists.list_read({"list": "party"}) == "You don't have a party list."


def test_clear_asks_first(tmp_file):
    lists.list_add({"list": "shopping", "item": "milk"})
    assert lists.list_clear({"list": "shopping"}) == "Are you sure you want to clear your shopping list?"
    assert saved(tmp_file)["shopping"] == ["milk"]
    assert lists.list_clear({"list": "shopping", "confirm": True}) == "Cleared your shopping list."
    assert saved(tmp_file)["shopping"] == []


def test_clear_custom_list_deletes_it(tmp_file):
    lists.list_add({"list": "packing", "item": "passport"})
    lists.list_clear({"list": "packing", "confirm": True})
    assert "packing" not in saved(tmp_file)


def test_lists_summary():
    lists.list_add({"list": "packing", "item": "passport"})
    assert lists.lists({}) == "Your lists: to-do (0 items), shopping (0 items) and packing (1 item)."


def test_bad_file_is_ignored(tmp_file):
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("not json", encoding="utf-8")
    assert lists.list_read({"list": "shopping"}) == "Your shopping list is empty."


def test_config_default(monkeypatch, tmp_path):
    monkeypatch.setattr(lists, "LISTS_FILE", "")
    import jarvis.config as config

    monkeypatch.setattr(config, "load_config", lambda: {"lists_file": str(tmp_path / "x.json")})
    assert lists._path() == str(tmp_path / "x.json")


def test_risky_text():
    assert lists.risky_text({"list": "groceries"}) == "clear your shopping list"


def test_catalog_matches_handlers():
    assert set(lists.CATALOG) == set(lists.HANDLERS)
    for spec in lists.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
    assert lists.CATALOG["list_read"].get("info") and lists.CATALOG["lists"].get("info")
