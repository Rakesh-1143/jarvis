"""Piece AL: teach commands by voice. Uses a temp taught.json; no OS calls."""
import copy
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from jarvis import actions, nlu  # noqa: E402
from jarvis.actions import teach  # noqa: E402
from jarvis.config import DEFAULTS  # noqa: E402
from jarvis.nlu import Command  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "taught.json"
    monkeypatch.setattr(teach, "_path", lambda: path)
    return path


# ---------- parse helpers ----------
@pytest.mark.parametrize("text, expected", [
    ("when I say study time, open notes and start focus",
     {"phrase": "study time", "steps": ["open notes", "start focus"]}),
    ("Jarvis, when I say study time open notes then start focus",
     {"phrase": "study time", "steps": ["open notes", "start focus"]}),
    ("whenever I say movie night, mute notifications, open netflix and then set volume to 60",
     {"phrase": "movie night", "steps": ["mute notifications", "open netflix", "set volume to 60"]}),
    ("when I say open sesame open chrome", {"phrase": "open sesame", "steps": ["open chrome"]}),
    ("when I say good night, say Sleep well Rakesh", {"phrase": "good night", "answer": "Sleep well Rakesh"}),
    ("when I say who's the boss reply with You are", {"phrase": "who's the boss", "answer": "You are"}),
    ("learn that when I say focus up, do start focus", {"phrase": "focus up", "steps": ["start focus"]}),
])
def test_parse_teach(text, expected):
    assert teach.parse_teach(text) == expected


@pytest.mark.parametrize("text", ["open notes", "what time is it", "when is my next meeting", "say hello", ""])
def test_parse_teach_ignores_other_text(text):
    assert teach.parse_teach(text) is None


@pytest.mark.parametrize("text, expected", [
    ("what have you learned", {"action": "list"}),
    ("what commands have you learnt", {"action": "list"}),
    ("list my taught commands", {"action": "list"}),
    ("what did I teach you", {"action": "list"}),
    ("forget the command study time", {"action": "forget", "phrase": "study time"}),
    ("forget study time", {"action": "forget", "phrase": "study time"}),
    ("delete the command good night", {"action": "forget", "phrase": "good night"}),
    ("forget that", {"action": "forget", "phrase": ""}),
    ("open notes", None),
])
def test_parse_taught(text, expected):
    assert teach.parse_taught(text) == expected


# ---------- teach / match / answer ----------
def test_teach_saves_and_matches(tmp_file):
    reply = teach.teach({"phrase": "Study Time", "steps": ["open notes", "start focus"]})
    assert reply == "Got it. When you say study time, I'll open notes, then start focus."
    assert json.loads(tmp_file.read_text())["study time"] == {"steps": ["open notes", "start focus"]}
    assert teach.match("study time") == ["open notes", "start focus"]
    assert teach.match("Jarvis, study time please!") == ["open notes", "start focus"]
    assert teach.match("study") is None
    assert teach.answer("study time") is None


def test_teach_steps_as_string():
    teach.teach({"phrase": "work mode", "steps": "open outlook and open teams"})
    assert teach.match("work mode") == ["open outlook", "open teams"]


def test_teach_answer():
    reply = teach.teach({"phrase": "good night", "answer": "Sleep well."})
    assert "I'll say: Sleep well" in reply
    assert teach.answer("good night") == "Sleep well"
    assert teach.match("good night") is None


def test_teach_replaces():
    teach.teach({"phrase": "x mode", "steps": ["open notes"]})
    assert teach.teach({"phrase": "x mode", "steps": ["open chrome"]}).startswith("Updated.")
    assert teach.match("x mode") == ["open chrome"]


@pytest.mark.parametrize("args, part", [
    ({}, "What should I listen for"),
    ({"phrase": "yes", "steps": ["shut down"]}, "need for something else"),
    ({"phrase": "cancel", "steps": ["open notes"]}, "need for something else"),
    ({"phrase": "goodbye", "answer": "hi"}, "need for something else"),
    ({"phrase": "hi", "steps": ["open notes"]}, "need for something else"),
    ({"phrase": "study time"}, "What should I do"),
    ({"phrase": "loop", "steps": ["open notes", "loop"]}, "can't call itself"),
    ({"phrase": "many", "steps": [f"step {i}" for i in range(11)]}, "too many steps"),
    ({"phrase": "when i say x", "steps": ["open notes"]}, "can't use that"),
])
def test_teach_refuses(args, part, tmp_file):
    assert part in teach.teach(args)
    assert not tmp_file.exists()


def test_bad_file_is_ignored(tmp_file):
    tmp_file.parent.mkdir(parents=True)
    tmp_file.write_text("not json")
    assert teach.match("anything") is None
    assert "haven't taught me" in teach.taught({"action": "list"})
    tmp_file.write_text(json.dumps({"a b c": {"steps": []}, "ok one": {"steps": ["open notes"]}, "bad": 5}))
    assert teach.match("ok one") == ["open notes"]
    assert teach.match("a b c") is None


# ---------- list / forget ----------
def test_list():
    teach.teach({"phrase": "study time", "steps": ["open notes", "start focus"]})
    teach.teach({"phrase": "good night", "answer": "Sleep well"})
    reply = teach.taught({"action": "list"})
    assert reply.startswith("I know 2 taught commands.")
    assert "good night: say Sleep well" in reply and "study time: open notes, then start focus" in reply


def test_forget_asks_first_then_deletes():
    teach.teach({"phrase": "study time", "steps": ["open notes"]})
    assert teach.risky_text({"action": "forget", "phrase": "study time"}) == "forget the command study time"
    assert teach.risky_text({"action": "list"}) is None
    assert teach.risky_text({"action": "forget", "phrase": "nope"}) is None
    assert "Are you sure" in teach.taught({"action": "forget", "phrase": "study time"})
    assert teach.match("study time") == ["open notes"]  # nothing deleted without yes
    assert teach.taught({"action": "forget", "phrase": "study time", "confirm": True}) == "Okay, I forgot study time."
    assert teach.match("study time") is None


def test_forget_unknown_or_empty():
    assert "Which command" in teach.taught({"action": "forget", "phrase": ""})
    assert "don't have a command called zzz" in teach.taught({"action": "forget", "phrase": "zzz"})


# ---------- run (main.py hook) ----------
def test_run_steps_and_answer():
    teach.teach({"phrase": "study time", "steps": ["open notes", "start focus"]})
    teach.teach({"phrase": "good night", "answer": "Sleep well"})
    done, said = [], []
    assert teach.run("study time", lambda s: done.append(s) or f"did {s}", said.append) == ""
    assert done == ["open notes", "start focus"] and said == ["did open notes", "did start focus"]
    assert teach.run("good night", done.append, said.append) == "Sleep well"
    assert teach.run("something else", done.append, said.append) is None
    assert teach.run("study time", done.append, said.append, depth=3) == "That command calls itself, so I stopped."


def _cfg():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["ai"]["enabled"] = False
    return cfg


class FakeIO:
    def __init__(self, heard):
        self.heard, self.said = list(heard), []

    def listen(self, timeout=None):
        return self.heard.pop(0) if self.heard else None

    def say(self, text):
        self.said.append(text)


def _hook(text, io, cfg, depth=0):
    """What the wiring thread adds to main.handle (after shortcuts, before nlu)."""
    return teach.run(text, lambda s: main.handle(s, io, cfg, nlu, actions, None, depth + 1), io.say, depth)


@pytest.mark.parametrize("answer, ran", [("no", False), ("yes", True)])
def test_taught_risky_step_still_asks_yes(answer, ran):
    """A taught 'shut down' step goes through main.handle, so it still asks 'are you sure?'."""
    teach.teach({"phrase": "bed time", "steps": ["shut down"]})
    io = FakeIO([answer])
    with mock.patch.object(actions.system, "shutdown", return_value="Shutting down.") as sd:
        assert _hook("bed time", io, _cfg()) == ""
    assert any("sure" in s.lower() for s in io.said)
    assert sd.called is ran


# ---------- catalog ----------
def test_catalog_and_handlers():
    assert set(teach.CATALOG) == set(teach.HANDLERS) == {"teach", "taught"}
    for spec in teach.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
    assert teach.HANDLERS["taught"](Command("taught", {"action": "list"}).args)
