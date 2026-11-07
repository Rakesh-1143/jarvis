"""Piece B: assistant controls (help, pause, repeat, voice). No audio needed."""
import os
import sys
from types import SimpleNamespace as NS
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import assistant as a  # noqa: E402
from jarvis.actions import catalog as _catalog_mod  # noqa: E402

# Base intents only (actions/__init__.py merges the new modules into the same dict, so filter them out).
_NEW = {"list_add", "list_remove", "list_read", "list_clear", "lists", "help", "pause_listening", "resume_listening",
        "repeat", "voice", "shortcut", "snippet", "agenda", "next_event", "free_at", "briefing", "dictation",
        "read_aloud", "convert", "world_time", "date_calc", "network", "now_playing", "mic", "app_volume",
        "audio_output", "focus", "dnd", "alerts", "check_email"}
BASE = {k: v for k, v in _catalog_mod.CATALOG.items() if k not in _NEW}


@pytest.fixture(autouse=True)
def reset():
    a._paused_until = None
    a._last_reply = ""
    a._turn_started = True
    a._start_voice = None
    a._catalog = None
    yield
    a._paused_until = None
    a._catalog = None


def test_catalog_matches_handlers():
    assert set(a.CATALOG) == set(a.HANDLERS)
    for spec in a.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
    assert a.CATALOG["help"].get("info") is True
    assert not set(a.CATALOG) & set(BASE)  # no clash with existing intents


# ---------- help ----------

def test_help_overview_lists_features():
    r = a.help({})
    assert "open and close apps" in r and "timers" in r and "help with timers" in r


def test_help_only_lists_known_features():
    a.set_catalog({"open_app": {}, "weather": {}})
    r = a.help({})
    assert "apps" in r and "weather" in r and "timers" not in r


@pytest.mark.parametrize("topic,word", [
    ("timers", "set a timer"), ("alarm", "set a timer"), ("with music", "play lofi"),
    ("the windows", "minimize"), ("voice", "speak slower"), ("setting timers", "set a timer"),
])
def test_help_topic(topic, word):
    assert word in a.help({"topic": topic})


def test_help_lists_only_when_wired():
    a.set_catalog(BASE)
    assert "shopping" not in a.help({"topic": "lists"})  # lists not in base catalog
    a.set_catalog({**BASE, "list_add": {}, "list_read": {}})
    assert "shopping list" in a.help({"topic": "lists"})


def test_help_unknown_topic():
    assert "don't have help" in a.help({"topic": "spaceships"})


def test_help_falls_back_to_catalog_description():
    a.set_catalog({"teleport": {"description": "Move you somewhere else."}})  # intent with no help group
    assert a.help({"topic": "teleport"}) == "Move you somewhere else."


# ---------- pause ----------

def test_pause_minutes_then_expires():
    with mock.patch.object(a.time, "time", return_value=1000.0):
        r = a.pause_listening({"minutes": 10})
        assert "10 minutes" in r and a.is_paused()
        assert a.seconds_left() == 600
    with mock.patch.object(a.time, "time", return_value=1000.0 + 601):
        assert not a.is_paused() and a.seconds_left() is None


def test_pause_one_minute_wording():
    assert "1 minute." in a.pause_listening({"minutes": 1})


def test_pause_until_resumed():
    r = a.pause_listening({})
    assert "start listening" in r and a.is_paused() and a.seconds_left() == float("inf")
    assert a.resume_listening({}) == "I'm listening again."
    assert not a.is_paused()
    assert a.resume_listening({}) == "I'm already listening."


def test_pause_bad_minutes_means_until_resumed():
    a.pause_listening({"minutes": "lots"})
    assert a.seconds_left() == float("inf")


@pytest.mark.parametrize("text,ok", [
    ("jarvis start listening", True), ("resume listening", True), ("wake up", True), ("I'm back", True),
    ("unpause", True), ("open chrome", False), ("what time is it", False), (None, False),
])
def test_allowed_while_paused(text, ok):
    assert a.allowed_while_paused(text) is ok


# ---------- repeat ----------

def test_repeat_nothing_yet():
    assert "haven't said" in a.repeat({})


def test_set_last_reply_and_repeat():
    a.set_last_reply("It is 5 pm.")
    a.set_last_reply("")  # empty replies are ignored
    assert a.repeat({}) == "It is 5 pm."


def test_record_keeps_streamed_answer_whole():
    a.new_turn()
    a.record("Paris is the capital.")
    a.record("It has the Eiffel Tower.")
    assert a.repeat({}) == "Paris is the capital. It has the Eiffel Tower."
    a.new_turn()  # next command replaces
    a.record("Volume is 50.")
    assert a.last_reply() == "Volume is 50."
    # "repeat that" turn: speaking the same text again must not double it
    a.new_turn()
    a.record(a.repeat({}))
    assert a.last_reply() == "Volume is 50."


# ---------- voice ----------

def fake_tts(rate=180, volume=1.0):
    t = NS(_settings={"rate": rate, "volume": volume, "voice": None})

    def configure(rate=None, volume=None, voice=None):
        if rate is not None:
            t._settings["rate"] = rate
        if volume is not None:
            t._settings["volume"] = volume
    t.configure = configure
    return t


def test_voice_slower_faster_reset():
    t = fake_tts()
    with mock.patch.object(a, "_tts", return_value=t):
        assert "slower" in a.voice({"change": "slower"})
        assert t._settings["rate"] == 150
        a.voice({"change": "faster"})
        a.voice({"change": "faster"})
        assert t._settings["rate"] == 210
        assert "normal" in a.voice({"change": "reset"})
        assert t._settings["rate"] == 180


def test_voice_limits():
    t = fake_tts(rate=a.RATE_MIN, volume=1.0)
    with mock.patch.object(a, "_tts", return_value=t):
        assert "already" in a.voice({"change": "slower"})
        assert "full volume" in a.voice({"change": "louder"})
        a.voice({"change": "quieter"})
        assert t._settings["volume"] == 0.8


def test_voice_quieter_floor_and_aliases():
    t = fake_tts(volume=a.VOLUME_MIN)
    with mock.patch.object(a, "_tts", return_value=t):
        assert "already" in a.voice({"change": "softer"})
        assert "louder" in a.voice({"change": "loud"})
        assert "slower, faster" in a.voice({"change": "weird"})


def test_voice_without_tts():
    with mock.patch.object(a, "_tts", side_effect=ImportError):
        assert "can't" in a.voice({"change": "slower"})


def test_voice_with_real_tts_module():
    from jarvis import tts
    old = dict(tts._settings)
    try:
        a.voice({"change": "slower"})
        assert tts._settings["rate"] == old["rate"] - a.RATE_STEP
    finally:
        tts._settings.update(old)
