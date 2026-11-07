"""Dictation and read aloud. Keyboard, clipboard and speech are faked."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import dictation as d  # noqa: E402


class FakeKeys:
    def __init__(self):
        self.screen = ""
        self.calls = []

    def type(self, text):
        self.calls.append(("type", text))
        self.screen += text

    def backspace(self, n):
        self.calls.append(("backspace", n))
        self.screen = self.screen[:-n]

    def undo(self):
        self.calls.append(("undo",))


@pytest.fixture
def keys(monkeypatch):
    fake = FakeKeys()
    monkeypatch.setattr(d, "_keys", fake)
    d.stop()
    yield fake
    d.stop()


@pytest.mark.parametrize("spoken, typed", [
    ("hello world", "Hello world"),
    ("hello comma how are you question mark", "Hello, how are you?"),
    ("it works full stop it really does period", "It works. It really does."),
    ("first line new line second", "First line\nSecond"),
    ("end new paragraph start", "End\n\nStart"),
    ("meet caps john at noon", "Meet John at noon"),
    ("wow exclamation mark", "Wow!"),
    ("Hello, world.", "Hello, world."),  # speech engine already added punctuation
    ("note colon buy milk", "Note: buy milk"),
])
def test_format_phrase(spoken, typed):
    assert d.format_phrase(spoken) == typed


def test_format_uses_text_before():
    assert d.format_phrase("and more", "Hello") == " and more"
    assert d.format_phrase("next one", "Done.") == " Next one"
    assert d.format_phrase("comma then", "Hi") == ", then"


def test_start_stop(keys):
    assert not d.is_active()
    assert "on" in d.dictation({"state": "on"}).lower()
    assert d.is_active()
    assert d.dictation({"state": "off"}) == "Dictation off."
    assert not d.is_active()
    assert d.dictation({"state": "off"}) == "Dictation is not on."


def test_process_types_phrases(keys):
    d.start()
    assert d.process("dear sam comma") == ""
    assert d.process("thanks for the help full stop") == ""
    assert d.process("see you soon") == ""
    assert keys.screen == "Dear sam, thanks for the help. See you soon"


def test_delete_that_removes_last_phrase(keys):
    d.start()
    d.process("keep this")
    d.process("remove this")
    d.process("delete that")
    assert keys.screen == "Keep this"
    d.process("and this full stop")
    assert keys.screen == "Keep this and this."
    d.process("scratch that")
    d.process("scratch that")
    assert keys.screen == ""
    assert d.process("delete that") == "Nothing to delete."


def test_undo_sends_ctrl_z(keys):
    d.start()
    d.process("hello")
    d.process("undo")
    assert keys.calls[-1] == ("undo",)


@pytest.mark.parametrize("phrase", ["stop dictation", "Stop dictation.", "end dictation", "jarvis stop dictating"])
def test_stop_phrase(keys, phrase):
    d.start()
    assert d.process(phrase) == "Dictation off."
    assert not d.is_active()
    assert keys.calls == []


def test_process_does_nothing_when_off(keys):
    assert d.process("hello") == ""
    assert keys.calls == []


# ---------- read aloud ----------
@pytest.fixture
def spoken(monkeypatch):
    said = []
    monkeypatch.setattr(d, "_speak", said.append)
    yield said
    if d._reader:
        d._reader.join(timeout=2)


def test_split_sentences():
    assert d.split_sentences("One. Two? Three!\nFour") == ["One.", "Two?", "Three!", "Four"]


def test_read_selection(spoken, monkeypatch):
    monkeypatch.setattr(d, "_selected", lambda: "First. Second.")
    monkeypatch.setattr(d, "_clipboard", lambda: "clip")
    assert d.read_aloud({}) == ""
    d._reader.join(timeout=2)
    assert spoken == ["First.", "Second."]


def test_read_falls_back_to_clipboard(spoken, monkeypatch):
    monkeypatch.setattr(d, "_selected", lambda: "")
    monkeypatch.setattr(d, "_clipboard", lambda: "From clipboard.")
    d.read_aloud({})
    d._reader.join(timeout=2)
    assert spoken == ["From clipboard."]


def test_read_source_clipboard_skips_selection(spoken, monkeypatch):
    sel = mock.Mock(return_value="selected")
    monkeypatch.setattr(d, "_selected", sel)
    monkeypatch.setattr(d, "_clipboard", lambda: "clip")
    d.read_aloud({"source": "clipboard"})
    d._reader.join(timeout=2)
    sel.assert_not_called()
    assert spoken == ["clip"]


def test_read_nothing(spoken, monkeypatch):
    monkeypatch.setattr(d, "_selected", lambda: "")
    monkeypatch.setattr(d, "_clipboard", lambda: "")
    assert "Select some text" in d.read_aloud({})


def test_selected_sentinel(monkeypatch):
    from jarvis.actions import desktop

    monkeypatch.setattr(desktop, "get_selected_text", lambda args: "Nothing is selected.")
    assert d._selected() == ""


def test_stop_reading(monkeypatch):
    import threading

    gate, started = threading.Event(), threading.Event()
    said = []

    def slow(s):
        said.append(s)
        started.set()
        gate.wait(2)

    monkeypatch.setattr(d, "_speak", slow)
    monkeypatch.setattr(d, "_selected", lambda: "One. Two. Three.")
    d.read_aloud({})
    started.wait(2)
    assert d.read_aloud({"action": "stop"}) == "Stopped reading."
    gate.set()
    d._reader.join(timeout=2)
    assert said == ["One."]
    assert d.read_aloud({"action": "stop"}) == "I am not reading anything."


def test_catalog_matches_handlers():
    assert set(d.CATALOG) == set(d.HANDLERS)
    for spec in d.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
