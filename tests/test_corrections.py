"""Piece AS: misheard-word fixes. Temp files only; no OS calls."""
import json

import pytest

from jarvis.actions import corrections as cr
from jarvis.actions import history, teach
from jarvis.nlu import Command


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    fix = tmp_path / "sub" / "corrections.json"
    mis = tmp_path / "sub" / "misheard.jsonl"
    monkeypatch.setattr(cr, "_path", lambda: fix)
    monkeypatch.setattr(cr, "_misheard_path", lambda: mis)
    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(history, "ENABLED", True)
    monkeypatch.setattr(history, "KEEP_DAYS", 30)
    cr._recent.clear()
    return {"fix": fix, "mis": mis}


# ---------- parse ----------
@pytest.mark.parametrize("text, expected", [
    ("when you hear note pad I mean notepad", ("correction", {"heard": "note pad", "meant": "notepad"})),
    ("Jarvis, when you hear 'note pad', I mean 'notepad'.",
     ("correction", {"heard": "note pad", "meant": "notepad"})),
    ("when I say chrome I mean google chrome", ("correction", {"heard": "chrome", "meant": "google chrome"})),
    ("whenever you hear spotty fly it means Spotify", ("correction", {"heard": "spotty fly", "meant": "Spotify"})),
    ("remember that when you hear word pad you should hear WordPad",
     ("correction", {"heard": "word pad", "meant": "WordPad"})),
    ("you misheard", ("misheard", {})),
    ("you misheard me", ("misheard", {})),
    ("that was wrong", ("misheard", {})),
    ("That's wrong!", ("misheard", {})),
    ("you heard me wrong", ("misheard", {})),
    ("no, that's not what I said", ("misheard", {})),
    ("you misheard, I said notepad", ("misheard", {"said": "notepad"})),
    ("list corrections", ("corrections", {"action": "list"})),
    ("show my corrections", ("corrections", {"action": "list"})),
    ("what corrections do you have", ("corrections", {"action": "list"})),
    ("remove correction note pad", ("corrections", {"action": "remove", "heard": "note pad"})),
    ("delete the correction for 'chrome'", ("corrections", {"action": "remove", "heard": "chrome"})),
])
def test_parse(text, expected):
    assert cr.parse(text) == expected


@pytest.mark.parametrize("text", [
    "open notepad", "when I say study time, open notes and start focus", "what is wrong with my pc",
    "correct the spelling", "list my notes", "", None,
])
def test_parse_none(text):
    assert cr.parse(text) is None


def test_parse_before_teach_wins():
    # teach would read "I mean google chrome" as a step; corrections must be checked first.
    assert cr.parse("when I say chrome, I mean google chrome")[0] == "correction"
    assert teach.parse_teach("when I say study time, open notes") is not None


# ---------- correction + apply ----------
def test_save_and_apply(files):
    assert "Got it" in cr.correction({"heard": "Note Pad", "meant": "notepad"})
    assert json.loads(files["fix"].read_text(encoding="utf-8")) == {"note pad": "notepad"}
    assert cr.apply("open note pad") == "open notepad"
    assert cr.apply("Open NOTE   PAD please") == "Open notepad please"


def test_apply_whole_words_only():
    cr.correction({"heard": "pad", "meant": "notepad"})
    assert cr.apply("open padlock") == "open padlock"
    assert cr.apply("open pad's menu") == "open pad's menu"
    assert cr.apply("open pad") == "open notepad"


def test_apply_longest_first_and_one_pass():
    cr.correction({"heard": "chrome", "meant": "google chrome"})
    cr.correction({"heard": "google", "meant": "goggle"})
    cr.correction({"heard": "spotty fly", "meant": "spotify"})
    cr.correction({"heard": "spotty", "meant": "spotless"})
    # "google chrome" result is not fixed again into "goggle chrome"
    assert cr.apply("open chrome") == "open google chrome"
    assert cr.apply("play spotty fly") == "play spotify"
    assert cr.apply("spotty") == "spotless"


def test_apply_no_file_or_bad_file(files):
    assert cr.apply("open chrome") == "open chrome"
    files["fix"].parent.mkdir(parents=True, exist_ok=True)
    files["fix"].write_text("{broken", encoding="utf-8")
    assert cr.apply("open chrome") == "open chrome"
    assert cr.apply("") == ""
    assert cr.apply(None) == ""


def test_apply_skips_correction_commands():
    cr.correction({"heard": "note pad", "meant": "notepad"})
    assert cr.apply("remove the correction note pad") == "remove the correction note pad"
    assert cr.apply("when you hear note pad I mean notes") == "when you hear note pad I mean notes"
    # misheard is not a correction command, so it is fixed normally
    assert cr.apply("you misheard, I said note pad") == "you misheard, I said notepad"


def test_apply_special_characters():
    cr.correction({"heard": "c plus plus", "meant": "C++"})
    assert cr.apply("open c plus plus docs") == "open C++ docs"


def test_update_existing():
    cr.correction({"heard": "chrome", "meant": "google chrome"})
    msg = cr.correction({"heard": "chrome", "meant": "chromium"})
    assert msg.startswith("Updated") and "google chrome" in msg
    assert cr.apply("open chrome") == "open chromium"


@pytest.mark.parametrize("heard, meant", [
    ("yes", "shutdown"), ("maybe", "yes"), ("jarvis", "bob"), ("cancel", "go"), ("stop", "play"),
    ("", "x"), ("x", ""), ("notepad", "Notepad"),
    ("one two three four five six seven", "x"), ("a", "b" * 80),
])
def test_rejected(files, heard, meant):
    msg = cr.correction({"heard": heard, "meant": meant})
    assert not msg.startswith("Got it")
    assert not files["fix"].exists()


def test_max_fixes(monkeypatch):
    monkeypatch.setattr(cr, "MAX_FIXES", 2)
    cr.correction({"heard": "a1", "meant": "b1"})
    cr.correction({"heard": "a2", "meant": "b2"})
    assert "Remove one" in cr.correction({"heard": "a3", "meant": "b3"})
    assert cr.correction({"heard": "a2", "meant": "c2"}).startswith("Updated")


# ---------- list / remove ----------
def test_list_and_remove():
    assert "no corrections" in cr.corrections({"action": "list"})
    cr.correction({"heard": "note pad", "meant": "notepad"})
    cr.correction({"heard": "chrome", "meant": "google chrome"})
    text = cr.corrections({"action": "list"})
    assert "2 corrections" in text and '"note pad" means "notepad"' in text
    assert cr.corrections({"action": "remove", "heard": "Note Pad"}).startswith("Removed")
    assert "1 correction:" in cr.corrections({"action": "list"})
    assert "no correction" in cr.corrections({"action": "remove", "heard": "nothing"})
    assert "Which" in cr.corrections({"action": "remove"})
    # remove by the right word works too
    assert cr.corrections({"action": "remove", "heard": "google chrome"}).startswith("Removed")
    assert cr.apply("open chrome") == "open chrome"


def test_list_long(monkeypatch):
    monkeypatch.setattr(cr, "SAY_MAX", 2)
    for i in range(4):
        cr.correction({"heard": f"w{i}", "meant": f"m{i}"})
    assert "And 2 more." in cr.corrections({"action": "list"})


def test_unknown_action():
    assert "list" in cr.corrections({"action": "explode"})


# ---------- misheard ----------
def test_misheard_no_history(files):
    assert "don't know" in cr.misheard({})
    assert not files["mis"].exists()


def test_misheard_saves_last_command(files):
    history.log("open spotty fly", Command("unknown", {"text": "open spotty fly"}), "Sorry, I didn't get that.")
    history.log("you misheard", Command("misheard", {}), "")  # our own command is skipped
    msg = cr.misheard({"said": "open spotify"})
    assert "open spotty fly" in msg
    e = json.loads(files["mis"].read_text(encoding="utf-8").splitlines()[0])
    assert e["heard"] == "open spotty fly" and e["intent"] == "unknown"
    assert e["said"] == "open spotify" and e["reply"] == "Sorry, I didn't get that."
    assert "raw" not in e


def test_misheard_keeps_raw_text(files):
    cr.correction({"heard": "chrome", "meant": "google chrome"})
    fixed = cr.apply("open chrome")
    history.log(fixed, Command("open_app", {"name": "google chrome"}), "Opening google chrome.")
    cr.apply("that was wrong")
    cr.misheard({})
    e = json.loads(files["mis"].read_text(encoding="utf-8").splitlines()[0])
    assert e["heard"] == "open google chrome" and e["raw"] == "open chrome"


def test_misheard_appends(files):
    history.log("open x", Command("open_app", {"name": "x"}), "ok")
    cr.misheard({})
    cr.misheard({})
    assert len(files["mis"].read_text(encoding="utf-8").splitlines()) == 2


# ---------- catalog ----------
def test_catalog_and_handlers():
    assert set(cr.CATALOG) == set(cr.HANDLERS) == {"misheard", "correction", "corrections"}
    for spec in cr.CATALOG.values():
        assert spec["description"] and "properties" in spec and "required" in spec
    for name, intent_args in [("correction", {"heard": "a", "meant": "b"}),
                              ("corrections", {"action": "list"}), ("misheard", {})]:
        assert isinstance(cr.HANDLERS[name](intent_args), str)
