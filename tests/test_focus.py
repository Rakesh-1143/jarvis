"""Focus (Pomodoro) + Do Not Disturb. Windows calls and the clock are faked."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import focus  # noqa: E402

_REAL_REGISTRY_TOASTS = focus._registry_toasts
CFG = {"work": 25, "short_break": 5, "long_break": 15, "long_every": 2, "rounds": 3, "dnd": True}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    said = []
    monkeypatch.setattr(focus, "notify", said.append)
    monkeypatch.setattr(focus, "_session", None)
    monkeypatch.setattr(focus, "_routine", "")
    monkeypatch.setattr(focus, "_dnd_on", False)
    monkeypatch.setattr(focus, "_dnd_by_focus", False)
    monkeypatch.setattr(focus, "_settings", lambda: dict(CFG))
    monkeypatch.setattr(focus, "_routines", lambda: {})
    monkeypatch.setattr(focus, "_ensure_thread", lambda: None)  # tests call _tick() by hand
    calls = []
    monkeypatch.setattr(focus, "_wnf_quiet_hours", lambda on: calls.append(("wnf", on)) or True)
    monkeypatch.setattr(focus, "_registry_toasts", lambda on: calls.append(("reg", on)) or True)
    monkeypatch.setattr(focus, "_open_settings", lambda: calls.append(("settings",)) or True)
    return said, calls


def test_catalog_matches_handlers():
    assert set(focus.CATALOG) == set(focus.HANDLERS) == {"focus", "dnd"}
    for spec in focus.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)


def test_start_status_stop(fresh):
    said, calls = fresh
    reply = focus.focus({"action": "start", "minutes": 30})
    assert "30 minutes" in reply and "Do not disturb is on" in reply
    assert ("wnf", True) in calls and focus.is_active()
    assert "left in focus round 1" in focus.focus({"action": "status"})
    assert focus.focus({"action": "stop"}) == "Focus stopped."
    assert not focus.is_active()
    assert ("wnf", False) in calls  # focus turned DND on, so it turns it off
    assert focus.focus({"action": "status"}) == "No focus session is running."
    assert focus.focus({"action": "stop"}) == "No focus session is running."


def test_default_minutes_and_bad_minutes():
    assert "25 minutes" in focus.focus({})
    assert "how many minutes" in focus.focus({"action": "start", "minutes": 0})


def test_rounds_breaks_and_finish(fresh):
    said, calls = fresh
    focus.focus({"action": "start"})
    t = focus._session["ends"]
    focus._tick(t - 1)
    assert said == []  # not yet
    focus._tick(t)
    assert said[-1] == "Time for a 5 minutes break."
    assert "left in your break" in focus._status()
    focus._tick(focus._session["ends"])
    assert said[-1] == "Break is over. Focus round 2 for 25 minutes."
    focus._tick(focus._session["ends"])
    assert said[-1] == "Time for a 15 minutes break."  # long break every 2nd round
    focus._tick(focus._session["ends"])  # round 3
    focus._tick(focus._session["ends"])  # last round over -> done
    assert said[-1].startswith("Focus session done. You finished 3 rounds")
    assert not focus.is_active()
    assert ("wnf", False) in calls


def test_stop_counts_full_rounds(fresh):
    focus.focus({"action": "start"})
    focus._tick(focus._session["ends"])  # break after round 1
    assert focus.focus({"action": "stop"}) == "Focus stopped. You did 1 full round."


def test_unlimited_rounds(monkeypatch, fresh):
    said, _ = fresh
    monkeypatch.setattr(focus, "_settings", lambda: {**CFG, "rounds": 0})
    focus.focus({"action": "start"})
    for _ in range(20):
        focus._tick(focus._session["ends"])
    assert focus.is_active()


def test_no_dnd_when_disabled_or_already_on(monkeypatch, fresh):
    _, calls = fresh
    monkeypatch.setattr(focus, "_settings", lambda: {**CFG, "dnd": False})
    assert "Do not disturb" not in focus.focus({"action": "start"})
    focus.focus({"action": "stop"})
    assert calls == []
    monkeypatch.setattr(focus, "_settings", lambda: dict(CFG))
    focus.dnd({"state": "on"})  # user turned it on themselves
    calls.clear()
    focus.focus({"action": "start"})
    focus.focus({"action": "stop"})
    assert calls == []  # focus leaves the user's DND alone
    assert focus.dnd({"state": "status"}) == "Do not disturb is on."


def test_focus_routine(monkeypatch):
    monkeypatch.setattr(focus, "_routines", lambda: {"focus": ["open spotify"]})
    focus.focus({"action": "start"})
    assert focus.take_routine() == "focus"
    assert focus.take_routine() == ""


def test_dnd_on_off(fresh):
    _, calls = fresh
    assert focus.dnd({"state": "on"}).startswith("Do not disturb is on")
    assert focus.dnd({"state": "off"}) == "Do not disturb is off."
    assert calls[:2] == [("wnf", True), ("reg", True)]


def test_dnd_falls_back_to_settings(monkeypatch, fresh):
    _, calls = fresh
    monkeypatch.setattr(focus, "_wnf_quiet_hours", lambda on: False)
    monkeypatch.setattr(focus, "_registry_toasts", lambda on: False)
    assert "opened notification settings" in focus.dnd({"state": "on"})
    monkeypatch.setattr(focus, "_open_settings", lambda: False)
    assert focus.dnd({"state": "off"}).startswith("Sorry")


def test_real_windows_calls_fail_safely_on_linux():
    # The real functions must not crash when Windows APIs are missing.
    import importlib

    real = importlib.reload(focus)
    if sys.platform != "win32":
        assert real._wnf_quiet_hours(True) is False
        assert real._registry_toasts(True) is False


def test_notifier_errors_are_ignored(monkeypatch):
    monkeypatch.setattr(focus, "notify", mock.Mock(side_effect=RuntimeError))
    focus.focus({"action": "start"})
    focus._tick(focus._session["ends"])  # must not raise


def test_dnd_banner_setting_survives_a_crash(tmp_path, monkeypatch):
    import types

    reg = {"v": 1}
    key = mock.MagicMock()
    key.__enter__ = lambda s: s
    key.__exit__ = lambda s, *a: False
    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER=0, KEY_READ=1, KEY_SET_VALUE=2, REG_DWORD=4,
        CreateKeyEx=lambda *a: key, QueryValueEx=lambda k, n: (reg["v"], 4),
        SetValueEx=lambda k, n, r, t, v: reg.update(v=v))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(focus, "SAVED_FILE", str(tmp_path / "saved"))
    monkeypatch.setattr(focus, "_saved_toasts", None)
    monkeypatch.setattr(focus, "_registry_toasts", _REAL_REGISTRY_TOASTS)
    assert focus._registry_toasts(True) and reg["v"] == 0
    assert (tmp_path / "saved").read_text() == "1"
    monkeypatch.setattr(focus, "_saved_toasts", None)  # Jarvis crashed: memory lost
    assert focus.restore_after_crash() and reg["v"] == 1
    assert not (tmp_path / "saved").exists()
    assert focus.restore_after_crash() is False  # nothing left to do
