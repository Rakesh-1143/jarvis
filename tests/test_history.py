"""Tests for jarvis/actions/history.py (command history, piece AF)."""
import datetime as dt
import json

import pytest

from jarvis.actions import history
from jarvis.nlu import Command

NOW = dt.datetime(2026, 11, 7, 10, 0, 0)  # a Saturday


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "history.jsonl"
    monkeypatch.setattr(history, "HISTORY_FILE", str(path))
    monkeypatch.setattr(history, "ENABLED", True)
    monkeypatch.setattr(history, "KEEP_DAYS", 30)
    monkeypatch.setattr(history, "_pruned_on", "")
    clock = {"now": NOW}
    monkeypatch.setattr(history, "_now", lambda: clock["now"])
    return {"path": path, "clock": clock}


def _log_at(setup, when, text, intent, args=None, reply="ok", from_ai=False):
    setup["clock"]["now"] = when
    history.log(text, Command(intent, args or {}), reply, from_ai=from_ai)
    setup["clock"]["now"] = NOW


def test_log_writes_json_line(setup):
    history.log("open chrome", Command("open_app", {"name": "chrome"}), "Opening chrome.")
    lines = setup["path"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    e = json.loads(lines[0])
    assert e["heard"] == "open chrome" and e["intent"] == "open_app"
    assert e["args"] == {"name": "chrome"} and e["reply"] == "Opening chrome."
    assert e["t"] == "2026-11-07T10:00:00" and e["ai"] is False


def test_log_disabled_and_empty(setup, monkeypatch):
    history.log("   ", Command("time"), "x")
    assert not setup["path"].exists()
    monkeypatch.setattr(history, "ENABLED", False)
    history.log("what time is it", Command("time"), "10 AM")
    assert not setup["path"].exists()


def test_log_never_saves_pin_or_confirm(setup):
    history.log("unlock jarvis 1234", Command("jarvis_lock", {"state": "off", "pin": "1234"}), "ok")
    history.log("shut down", Command("shutdown", {"confirm": True, "pin": "9"}), "bye")
    text = setup["path"].read_text(encoding="utf-8")
    assert "1234" not in text and '"pin"' not in text and "confirm" not in text
    assert len(text.splitlines()) == 1


def test_log_never_raises(setup, monkeypatch):
    monkeypatch.setattr(history, "_path", lambda: (_ for _ in ()).throw(OSError("disk")))
    history.log("open chrome", Command("open_app", {"name": "chrome"}), "ok")  # no error


def test_long_reply_is_cut(setup):
    history.log("tell me a story", Command("unknown"), "a" * 1000)
    assert len(history.entries()[0]["reply"]) == history.MAX_REPLY


def test_broken_line_is_skipped(setup):
    history.log("open chrome", Command("open_app", {"name": "chrome"}), "ok")
    with open(setup["path"], "a", encoding="utf-8") as f:
        f.write("not json\n")
    history.log("what time is it", Command("time"), "10")
    assert [e["heard"] for e in history.entries()] == ["open chrome", "what time is it"]


def test_old_lines_are_pruned(setup):
    _log_at(setup, NOW - dt.timedelta(days=40), "old one", "time")
    _log_at(setup, NOW - dt.timedelta(days=2), "recent one", "time")
    history._pruned_on = ""  # new day: clean-up runs on next log
    history.log("now one", Command("time"), "x")
    assert [e["heard"] for e in history.entries()] == ["recent one", "now one"]


def test_parse_day():
    today = NOW.date()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(history, "_now", lambda: NOW)
        assert history.parse_day("today") == today
        assert history.parse_day("yesterday") == today - dt.timedelta(days=1)
        assert history.parse_day("3 days ago") == today - dt.timedelta(days=3)
        assert history.parse_day("two days ago") == today - dt.timedelta(days=2)
        assert history.parse_day("on Monday") == dt.date(2026, 11, 2)
        assert history.parse_day("saturday") == today
        assert history.parse_day("2026-11-01") == dt.date(2026, 11, 1)
        assert history.parse_day("") is None
        assert history.parse_day("blue") is None


def test_list_yesterday(setup):
    y = NOW - dt.timedelta(days=1)
    _log_at(setup, y.replace(hour=9, minute=5), "open chrome", "open_app", {"name": "chrome"})
    _log_at(setup, y.replace(hour=14, minute=30), "what's the weather", "weather")
    _log_at(setup, NOW, "what time is it", "time")
    out = history.history({"action": "list", "day": "yesterday"})
    assert "2 things yesterday" in out
    assert '9:05 AM "open chrome"' in out and '2:30 PM "what\'s the weather"' in out
    assert "time is it" not in out


def test_list_default_today_and_empty(setup):
    assert history.history({"action": "list"}) == "You didn't ask me anything today."
    history.log("open notepad", Command("open_app", {"name": "notepad"}), "ok")
    assert '"open notepad"' in history.history({})


def test_list_skips_history_commands_and_caps(setup):
    for i in range(8):
        _log_at(setup, NOW.replace(minute=i), f"command {i}", "time")
    history.log("what did I ask today", Command("history", {"action": "list"}), "x")
    out = history.history({"action": "list", "day": "today"})
    assert "8 things today" in out and "The last 5 were" in out
    assert "command 2" not in out and "command 7" in out and "what did I ask" not in out


def test_list_bad_day(setup):
    assert "don't know which day" in history.history({"action": "list", "day": "blue"})


def test_search(setup):
    _log_at(setup, NOW - dt.timedelta(days=3), "what's the weather in Delhi", "weather")
    _log_at(setup, NOW - dt.timedelta(days=1), "open chrome", "open_app")
    _log_at(setup, NOW, "weather tomorrow", "weather")
    out = history.history({"action": "search", "query": "about the weather"})
    assert out.startswith("I found 2 commands about weather")
    assert out.index("weather tomorrow") < out.index("Delhi")  # newest first
    assert "on Wednesday" in out and "today" in out
    one = history.history({"action": "search", "query": "weather", "day": "today"})
    assert "I found 1 command about weather" in one and "Delhi" not in one


def test_search_by_intent_and_none(setup):
    _log_at(setup, NOW, "play some music", "spotify")
    assert "play some music" in history.history({"action": "search", "query": "spotify"})
    assert "nothing about pizza" in history.history({"action": "search", "query": "pizza"})
    assert "What should I look for" in history.history({"action": "search"})


def test_last_command_skips_history_and_confirm(setup):
    history.log("open chrome", Command("open_app", {"name": "chrome"}), "ok")
    history.log("yes", Command("confirm"), "")
    history.log("what did I ask", Command("history", {"action": "list"}), "x")
    history.log("do that again", Command("history", {"action": "repeat_last"}), "x")
    cmd = history.last_command()
    assert isinstance(cmd, Command)
    assert cmd.intent == "open_app" and cmd.args == {"name": "chrome"}


def test_repeat_risky_needs_fresh_confirm(setup):
    """The confirmed shutdown is saved without confirm=True, so a repeat asks again."""
    history.log("shut down", Command("shutdown", {"confirm": True}), "Shutting down.")
    cmd = history.last_command()
    assert cmd.intent == "shutdown" and "confirm" not in cmd.args
    from jarvis import actions

    assert actions.needs_confirm(cmd)  # actions still asks "are you sure?"


def test_last_command_none_and_ai_flag(setup):
    assert history.last_command() is None
    assert history.history({"action": "repeat_last"}) == "There is nothing to do again yet."
    history.log("set volume to 20", Command("volume", {"level": 20}), "ok", from_ai=True)
    assert history.last_was_ai() is True
    assert '"set volume to 20"' in history.history({"action": "repeat_last"})


def test_clear_needs_confirm(setup):
    history.log("open chrome", Command("open_app"), "ok")
    assert history.needs_confirm({"action": "clear"})
    assert not history.needs_confirm({"action": "list"})
    assert history.risky_text({"action": "clear"}) == "clear your command history"
    assert history.risky_text({"action": "search"}) is None
    assert "Are you sure" in history.history({"action": "clear"})
    assert setup["path"].exists()
    assert "cleared" in history.history({"action": "clear", "confirm": True})
    assert not setup["path"].exists()
    assert "cleared" in history.history({"action": "clear", "confirm": True})  # no file: still fine


def test_unknown_action(setup):
    assert "list, search, repeat or clear" in history.history({"action": "dance"})


def test_config_defaults(monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", "")
    monkeypatch.setattr(history, "ENABLED", None)
    monkeypatch.setattr(history, "KEEP_DAYS", None)
    history._settings()
    assert history.HISTORY_FILE  # config value or default
    assert history.ENABLED is True and history.KEEP_DAYS == 30


def test_catalog_and_handlers():
    assert set(history.CATALOG) == set(history.HANDLERS) == {"history"}
    spec = history.CATALOG["history"]
    assert spec["properties"]["action"]["enum"] == ["list", "search", "repeat_last", "clear"]
    assert spec["required"] == ["action"]
