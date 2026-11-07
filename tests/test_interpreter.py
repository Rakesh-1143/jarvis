"""Piece AN: interpreter (translate) mode. Network, Claude and voices are faked."""
import json
import sys
import types

import pytest

from jarvis.actions import interpreter as it


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    it._state.update(active=False, language="", last="")
    monkeypatch.setattr(it, "_cfg", lambda: {"ai": {"api_key": ""}})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "deep_translator", None)  # import fails -> urllib path

    def no_net(*a, **k):
        raise OSError("no network in tests")

    monkeypatch.setattr(it, "_http_get", no_net)
    monkeypatch.setattr(it, "_voices", lambda: [])
    yield
    it._state.update(active=False, language="", last="")


def fake_google(monkeypatch, reply="नमस्ते"):
    urls = []

    def get(url, timeout=10.0):
        urls.append(url)
        return json.dumps([[[reply, "hello", None, None]], None, "en"])

    monkeypatch.setattr(it, "_http_get", get)
    return urls


# ---------- languages ----------

@pytest.mark.parametrize("word,name", [("Hindi", "hindi"), ("hi", "hindi"), ("TELUGU", "telugu"),
                                       ("mandarin", "chinese"), ("zh-CN", "chinese"), ("farsi", "persian"),
                                       ("es", "spanish")])
def test_find_language(word, name):
    assert it.find_language(word) == name


def test_find_language_unknown():
    assert it.find_language("klingon") is None
    assert it.find_language("") is None


# ---------- on / off ----------

def test_start_and_stop():
    r = it.interpreter({"state": "on", "language": "Hindi"})
    assert "Hindi" in r and it.is_active() and it.language() == "hindi"
    assert it.interpreter({"state": "off"}) == "Translate mode off."
    assert not it.is_active()
    assert it.stop() == "Translate mode is not on."


def test_start_unknown_or_missing_language():
    assert "don't know" in it.interpreter({"state": "on", "language": "klingon"})
    assert "Which language" in it.interpreter({"state": "on"})
    assert not it.is_active()


def test_on_again_without_language_keeps_mode():
    it.start("spanish")
    assert "already on" in it.interpreter({"state": "on"})


def test_process_does_nothing_when_off():
    assert it.process("hello") == ""


# ---------- process ----------

@pytest.mark.parametrize("phrase", ["stop translating", "Stop translation.", "jarvis stop translating",
                                    "exit translate mode", "stop interpreter", "end interpreter mode"])
def test_stop_phrases(phrase):
    it.start("hindi")
    assert it.process(phrase) == "Translate mode off."
    assert not it.is_active()


def test_translates_with_google_and_returns_text_without_voice(monkeypatch):
    urls = fake_google(monkeypatch)
    it.start("hindi")
    assert it.process("hello") == "नमस्ते"
    assert "tl=hi" in urls[0] and "q=hello" in urls[0]
    assert it._state["last"] == "नमस्ते"


def test_uses_language_voice_and_returns_empty(monkeypatch):
    fake_google(monkeypatch)
    monkeypatch.setattr(it, "_voices", lambda: [("v1", "Microsoft Zira - English"),
                                                ("v2", "Microsoft Kalpana - Hindi (India)")])
    spoken = []
    monkeypatch.setattr(it, "_speak_with", lambda vid, text: spoken.append((vid, text)) or True)
    it.start("hindi")
    assert it.process("hello") == ""
    assert spoken == [("v2", "नमस्ते")]


def test_voice_failure_falls_back_to_default_voice(monkeypatch):
    fake_google(monkeypatch)
    monkeypatch.setattr(it, "_voices", lambda: [("v2", "Microsoft Kalpana - Hindi (India)")])
    monkeypatch.setattr(it, "_speak_with", lambda vid, text: False)
    it.start("hindi")
    assert it.process("hello") == "नमस्ते"


def test_voice_for():
    assert it.voice_for("hindi") is None  # no voices in tests


def test_translate_failure_message():
    it.start("hindi")
    assert "could not translate" in it.process("hello")
    assert it.is_active()


def test_switch_language(monkeypatch):
    it.start("hindi")
    assert "Spanish" in it.process("switch to Spanish")
    assert it.language() == "spanish"
    assert "Telugu" in it.process("translate to telugu")
    assert it.language() == "telugu"


def test_switch_to_unknown_word_is_translated(monkeypatch):
    fake_google(monkeypatch, "x")
    it.start("hindi")
    assert it.process("switch to tomorrow") == "x"
    assert it.language() == "hindi"


def test_repeat_last(monkeypatch):
    urls = fake_google(monkeypatch)
    it.start("hindi")
    it.process("hello")
    assert it.process("say that again") == "नमस्ते"
    assert len(urls) == 1  # not translated again


def test_repeat_with_nothing_yet_is_translated(monkeypatch):
    urls = fake_google(monkeypatch, "फिर से")
    it.start("hindi")
    assert it.process("repeat") == "फिर से"
    assert len(urls) == 1


# ---------- Claude path ----------

class _FakeClient:
    calls = []
    reply = "हैलो"
    fail = False

    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        _FakeClient.calls.append(kw)
        if _FakeClient.fail:
            raise RuntimeError("down")
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=_FakeClient.reply)])


@pytest.fixture
def claude(monkeypatch):
    _FakeClient.calls, _FakeClient.fail = [], False
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_FakeClient))
    monkeypatch.setattr(it, "_cfg", lambda: {"ai": {"api_key": "k", "model": "m1"}})
    return _FakeClient


def test_claude_first(monkeypatch, claude):
    urls = fake_google(monkeypatch)
    it.start("hindi")
    assert it.process("hello") == "हैलो"
    assert claude.calls[0]["model"] == "m1"
    assert "Hindi" in claude.calls[0]["system"]
    assert claude.calls[0]["messages"][0]["content"] == "hello"
    assert urls == []


def test_claude_fails_then_google(monkeypatch, claude):
    claude.fail = True
    fake_google(monkeypatch)
    it.start("hindi")
    assert it.process("hello") == "नमस्ते"


def test_claude_disabled_uses_google(monkeypatch, claude):
    monkeypatch.setattr(it, "_cfg", lambda: {"ai": {"api_key": "k", "enabled": False}})
    fake_google(monkeypatch)
    it.start("hindi")
    assert it.process("hello") == "नमस्ते"
    assert claude.calls == []


def test_env_key(monkeypatch, claude):
    monkeypatch.setattr(it, "_cfg", lambda: {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "envkey")
    it.start("hindi")
    assert it.process("hello") == "हैलो"


# ---------- deep-translator path ----------

def test_deep_translator_used_when_installed(monkeypatch):
    seen = {}

    class GT:
        def __init__(self, source, target):
            seen["target"] = target

        def translate(self, text):
            return "hola"

    monkeypatch.setitem(sys.modules, "deep_translator", types.SimpleNamespace(GoogleTranslator=GT))
    it.start("spanish")
    assert it.process("hello") == "hola"
    assert seen["target"] == "es"


# ---------- catalog ----------

def test_catalog_and_handlers():
    assert set(it.CATALOG) == set(it.HANDLERS) == {"interpreter"}
    c = it.CATALOG["interpreter"]
    assert c["required"] == ["state"] and "language" in c["properties"]
    assert not c.get("info")
