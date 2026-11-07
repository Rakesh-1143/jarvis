"""Tests for jarvis.stt with a fake microphone and fake Vosk (no model or mic needed)."""
import json

from jarvis import stt


class FakeRec:
    """Pretends to be a Vosk recognizer. `script` = list of (final_text or None, partial_text)."""

    def __init__(self, script):
        self.script = list(script)
        self.final = ""
        self.partial = ""

    def AcceptWaveform(self, chunk):
        final, self.partial = self.script.pop(0) if self.script else (None, "")
        if final is not None:
            self.final = final
            return True
        return False

    def Result(self):
        return json.dumps({"text": self.final})

    def PartialResult(self):
        return json.dumps({"partial": self.partial})

    def FinalResult(self):
        return json.dumps({"text": ""})


class FakeModel:
    def __init__(self, vocab):
        self.vocab = vocab

    def vosk_model_find_word(self, w):
        return 1 if w in self.vocab else -1


def fake_mic(n=200):
    def gen():
        for _ in range(n):
            yield b"\0" * 10
    return gen


def setup(monkeypatch, script, vocab=("jarvis",)):
    rec = FakeRec(script)
    monkeypatch.setattr(stt, "_recognizer", lambda grammar=None: rec)
    monkeypatch.setattr(stt, "get_model", lambda: FakeModel(vocab))
    monkeypatch.setattr(stt, "_mic_chunks", fake_mic())


def test_listen_returns_text(monkeypatch):
    setup(monkeypatch, [(None, "open"), (None, "open note"), ("Open Notepad", "")])
    assert stt.listen() == "open notepad"


def test_listen_timeout_returns_none(monkeypatch):
    setup(monkeypatch, [])
    clock = iter(range(0, 1000))
    monkeypatch.setattr(stt.time, "monotonic", lambda: next(clock))
    assert stt.listen(timeout=3) is None


def test_wake_word_in_vocab(monkeypatch):
    setup(monkeypatch, [(None, ""), (None, "[unk]"), (None, "jarvis")])
    stt.wait_for_wake_word("Jarvis")  # returns = pass


def test_wake_word_sound_alike(monkeypatch):
    setup(monkeypatch, [(None, "hello"), ("hey jervis", "")], vocab=())
    stt.wait_for_wake_word("jarvis")
