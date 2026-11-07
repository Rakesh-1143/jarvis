"""Tests for Hindi/Telugu commands (piece BT). Fakes replace speech models, translators and voices."""
import json

import pytest

from jarvis.actions import interpreter
from jarvis.actions import multilang as ml


@pytest.fixture(autouse=True)
def fake(tmp_path, monkeypatch):
    calls = {"claude": [], "google": [], "preload": [], "spoken": [], "voices": {"hindi": "HI-VOICE"}}
    monkeypatch.setattr(ml, "_path", lambda: tmp_path / "multilang.json")
    monkeypatch.setattr(ml, "_cfg", lambda: {"stt": {"languages": ["en"]}})
    monkeypatch.setattr(ml, "_preload", calls["preload"].append)
    monkeypatch.setattr(ml, "has_whisper", lambda: False)
    monkeypatch.setattr(ml, "_hindi_model_path", lambda: tmp_path / "no-model")

    def claude(text, lang):
        calls["claude"].append((text, lang))
        return None

    def google(text):
        calls["google"].append(text)
        return None

    monkeypatch.setattr(ml, "_claude_english", claude)
    monkeypatch.setattr(ml, "_google_english", google)
    monkeypatch.setattr(interpreter, "voice_for", lambda name: calls["voices"].get(name))
    monkeypatch.setattr(interpreter, "translate", lambda text, name: f"<{name}> {text}")
    monkeypatch.setattr(interpreter, "_speak_with", lambda vid, text: calls["spoken"].append((vid, text)) or True)
    ml.reset()
    yield calls
    ml.reset()


def test_catalog_matches_handlers():
    assert set(ml.CATALOG) == set(ml.HANDLERS) == {"language"}


def test_find_lang():
    assert ml.find_lang("Hindi") == "hi"
    assert ml.find_lang("हिंदी") == "hi"
    assert ml.find_lang("telugu") == "te"
    assert ml.find_lang("en") == "en"
    assert ml.find_lang("french") is None


@pytest.mark.parametrize("said,args", [
    ("understand hindi", {"action": "on", "lang": "hi"}),
    ("Jarvis, commands in Hindi too", {"action": "on", "lang": "hi"}),
    ("switch to hindi", {"action": "on", "lang": "hi"}),
    ("i will speak telugu", {"action": "on", "lang": "te"}),
    ("hindi mein suno", {"action": "on", "lang": "hi"}),
    ("turn off hindi", {"action": "off", "lang": "hi"}),
    ("english only", {"action": "off"}),
    ("reply in hindi", {"action": "reply", "lang": "hi"}),
    ("speak in hindi too", {"action": "reply", "lang": "hi"}),
    ("answer in english", {"action": "reply", "lang": "en"}),
    ("which languages do you understand", {"action": "status"}),
])
def test_parse(said, args):
    assert ml.parse(said) == ("language", args)


@pytest.mark.parametrize("said", ["open chrome", "switch to english", "translate mode hindi",
                                  "switch to spanish", "", "understand french"])
def test_parse_ignores_other_text(said):
    assert ml.parse(said) is None


def test_default_is_english_only():
    assert ml.languages() == ["en"]
    assert not ml.is_active()


def test_config_languages_used_as_default(monkeypatch):
    monkeypatch.setattr(ml, "_cfg", lambda: {"stt": {"languages": ["en", "hi"]}})
    ml.reset()
    assert ml.languages() == ["en", "hi"]
    assert ml.is_active()


def test_turn_on_hindi_saves_and_preloads(fake, tmp_path):
    reply = ml.language({"action": "on", "lang": "hindi"})
    assert "Hindi" in reply and "42 MB" in reply
    assert ml.is_active() and fake["preload"] == ["hi"]
    saved = json.loads((tmp_path / "multilang.json").read_text(encoding="utf-8"))
    assert saved["languages"] == ["en", "hi"]
    ml.reset()  # survives a restart
    assert ml.languages() == ["en", "hi"]
    assert "already" in ml.language({"action": "on", "lang": "hi"})


def test_telugu_needs_whisper(monkeypatch):
    reply = ml.language({"action": "on", "lang": "telugu"})
    assert "faster-whisper" in reply
    assert ml.languages() == ["en"]
    monkeypatch.setattr(ml, "has_whisper", lambda: True)
    assert "Telugu" in ml.language({"action": "on", "lang": "telugu"})
    assert ml.languages() == ["en", "te"]


def test_turn_off_one_and_all():
    ml.language({"action": "on", "lang": "hi"})
    assert "Hindi is off" in ml.language({"action": "off", "lang": "hi"})
    assert "not on" in ml.language({"action": "off", "lang": "hi"})
    ml.language({"action": "on", "lang": "hi"})
    assert "English only" in ml.language({"action": "off"})
    assert not ml.is_active()
    assert "already" in ml.language({"action": "off"})


def test_unknown_language():
    assert "only understand" in ml.language({"action": "on", "lang": "french"})
    assert "Which language" in ml.language({"action": "on"})


def test_status():
    ml.language({"action": "on", "lang": "hi"})
    reply = ml.language({"action": "status"})
    assert "English and Hindi" in reply and "reply in English" in reply


def test_reply_language_needs_voice(fake):
    assert "no Telugu voice" in ml.language({"action": "reply", "lang": "te"})
    assert ml.reply_language() == "en"
    assert "reply in Hindi" in ml.language({"action": "reply", "lang": "hi"})
    assert ml.say_reply("It is 5 PM.") is True
    assert fake["spoken"] == [("HI-VOICE", "<hindi> It is 5 PM.")]
    ml.language({"action": "reply", "lang": "en"})
    assert ml.say_reply("hello") is False


def test_say_reply_off_by_default(fake):
    assert ml.say_reply("hello") is False
    assert fake["spoken"] == []


@pytest.mark.parametrize("heard,english", [
    ("क्रोम खोलो", "open chrome"),
    ("Chrome kholo", "open chrome"),
    ("jarvis zara awaaz badhao", "volume up"),
    ("आवाज़ कम करो", "volume down"),
    ("notepad band karo", "close notepad"),
    ("chrome ko band kar do", "close chrome"),
    ("गाना बजाओ", "play music"),
    ("screenshot le lo", "take a screenshot"),
    ("समय बताओ", "what is the time"),
    ("हाँ", "yes"),
    ("nahi", "no"),
    ("క్రోమ్ తెరువు", "open chrome"),
    ("పాట పెట్టు", "play music"),
    ("youtube kholo", "open youtube"),
])
def test_phrasebook_offline(fake, heard, english):
    assert ml.to_english(heard, "hi") == english
    assert fake["claude"] == [] and fake["google"] == []


def test_unknown_words_go_to_claude_then_google(fake, monkeypatch):
    assert ml.to_english("मेरे दोस्त को मैसेज भेजो", "hi") == "मेरे दोस्त को मैसेज भेजो"  # all failed: original
    assert fake["claude"] and fake["google"]
    monkeypatch.setattr(ml, "_google_english", lambda text: "Send a message to my friend.")
    assert ml.to_english("मेरे दोस्त को मैसेज भेजो", "hi") == "send a message to my friend"
    monkeypatch.setattr(ml, "_claude_english", lambda text, lang: '"Open Ravi\'s photos"')
    assert ml.to_english("रवि की फोटो खोलो", "hi") == "open ravi's photos"


def test_english_text_unchanged(fake):
    assert ml.to_english("open chrome", "en") == "open chrome"
    assert ml.to_english("", "hi") == ""
    assert fake["claude"] == []


def _engines(monkeypatch, results, ran):
    def vosk(code, audio):
        ran.append(code)
        return results[code]
    monkeypatch.setattr(ml, "_vosk_text", vosk)
    monkeypatch.setattr(ml, "_whisper_text", vosk)


def test_recognize_clear_english_skips_other_models(monkeypatch):
    ml.language({"action": "on", "lang": "hi"})
    ran = []
    _engines(monkeypatch, {"en": ("open chrome", 0.95), "hi": ("क्रोम", 0.4)}, ran)
    assert ml.recognize(b"x") == ("open chrome", "en")
    assert ran == ["en"]


def test_recognize_unsure_english_tries_hindi(monkeypatch):
    ml.language({"action": "on", "lang": "hi"})
    ran = []
    _engines(monkeypatch, {"en": ("chrome cola", 0.4), "hi": ("क्रोम खोलो", 0.8)}, ran)
    assert ml.recognize(b"x") == ("क्रोम खोलो", "hi")
    assert ran == ["en", "hi"] and ml.last_language() == "hi"


def test_recognize_keeps_english_if_more_sure(monkeypatch):
    ml.language({"action": "on", "lang": "hi"})
    _engines(monkeypatch, {"en": ("open crow", 0.5), "hi": ("ओपन", 0.3)}, [])
    assert ml.recognize(b"x") == ("open crow", "en")


def test_recognize_skips_telugu_without_whisper(monkeypatch):
    monkeypatch.setattr(ml, "_cfg", lambda: {"stt": {"languages": ["en", "te"]}})
    ml.reset()
    ran = []
    _engines(monkeypatch, {"en": ("", 0.0), "te": ("క్రోమ్ తెరువు", 0.9)}, ran)
    assert ml.recognize(b"x") == ("", "en")
    assert ran == ["en"]
    monkeypatch.setattr(ml, "has_whisper", lambda: True)
    assert ml.recognize(b"x") == ("క్రోమ్ తెరువు", "te")


def test_recognize_survives_model_error(monkeypatch):
    ml.language({"action": "on", "lang": "hi"})

    def vosk(code, audio):
        if code == "hi":
            raise RuntimeError("no model")
        return ("hello", 0.3)
    monkeypatch.setattr(ml, "_vosk_text", vosk)
    assert ml.recognize(b"x") == ("hello", "en")


def test_listen_returns_english(monkeypatch):
    ml.language({"action": "on", "lang": "hi"})
    monkeypatch.setattr(ml, "record", lambda timeout=5: b"audio")
    _engines(monkeypatch, {"en": ("", 0.0), "hi": ("क्रोम खोलो", 0.8)}, [])
    assert ml.listen() == "open chrome"
    monkeypatch.setattr(ml, "record", lambda timeout=5: None)
    assert ml.listen() is None
