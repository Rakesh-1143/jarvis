"""Tests for the sleep timer (piece BL). Fakes replace volume, media and power calls."""
import pytest

from jarvis.actions import sleeptimer as st


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    calls = {"said": [], "volume": [], "paused": 0, "sleep": 0, "shutdown": 0, "level": 80}

    def set_volume(v):
        calls["volume"].append(v)
        calls["level"] = v

    monkeypatch.setattr(st, "_get_volume", lambda: calls["level"])
    monkeypatch.setattr(st, "_set_volume", set_volume)
    monkeypatch.setattr(st, "_pause_media", lambda: calls.__setitem__("paused", calls["paused"] + 1))
    monkeypatch.setattr(st, "_do_sleep", lambda: calls.__setitem__("sleep", calls["sleep"] + 1))
    monkeypatch.setattr(st, "_do_shutdown", lambda: calls.__setitem__("shutdown", calls["shutdown"] + 1))
    monkeypatch.setattr(st, "_ensure_thread", lambda: None)
    monkeypatch.setattr(st, "notify", calls["said"].append)
    monkeypatch.setattr(st.time, "time", lambda: 1000.0)
    st._timer = None
    yield calls
    st._timer = None


def test_catalog_matches_handlers():
    assert set(st.CATALOG) == set(st.HANDLERS)
    assert st.CATALOG["sleep_timer_status"]["info"] is True


def test_stop_media_fades_pauses_and_restores(fake):
    reply = st.sleep_timer({"minutes": 30, "action": "stop_media"})
    assert "30 minutes" in reply and "music" in reply
    end = 1000 + 30 * 60
    st._tick(end - 100)
    assert fake["volume"] == []  # no fade yet
    st._tick(end - 30)
    st._tick(end - 15)
    assert fake["volume"][-1] == 40  # half way down from 80
    st._tick(end + 1)
    assert fake["paused"] == 1
    assert fake["level"] == 80  # old level back
    assert not st.is_active()


def test_default_action_is_stop_media():
    st.sleep_timer({"minutes": 10})
    assert st._timer["action"] == "stop_media"


def test_sleep_warns_then_sleeps(fake):
    reply = st.sleep_timer({"minutes": 60, "action": "sleep"})
    assert "1 hour" in reply and "sleep" in reply
    end = 1000 + 3600
    st._tick(end - 61)
    assert fake["said"] == []
    st._tick(end - 59)
    assert "1 minute" in fake["said"][-1] and "cancel" in fake["said"][-1]
    assert st.warning_active(end - 50)
    st._tick(end - 30)
    assert len(fake["said"]) == 1  # warned once only
    st._tick(end)
    assert fake["sleep"] == 1 and fake["shutdown"] == 0


def test_shutdown_runs(fake):
    st.sleep_timer({"minutes": 120, "action": "shutdown"})
    st._tick(1000 + 7200 + 1)
    assert fake["shutdown"] == 1


def test_cancel_stops_and_restores_volume(fake):
    st.sleep_timer({"minutes": 1, "action": "stop_media"})
    st._tick(1000 + 60 - 10)  # fading
    assert fake["level"] < 80
    assert st.sleep_timer_cancel({}) == "Sleep timer cancelled."
    assert fake["level"] == 80
    st._tick(1000 + 61)
    assert fake["paused"] == 0
    assert st.sleep_timer_cancel({}) == "No sleep timer is set."


def test_late_after_wake_does_nothing(fake):
    st.sleep_timer({"minutes": 5, "action": "shutdown"})
    st._tick(1000 + 300 + st.LATE_SECONDS + 5)
    assert fake["shutdown"] == 0
    assert not st.is_active()


def test_status(monkeypatch):
    assert st.sleep_timer_status({}) == "No sleep timer is set."
    st.sleep_timer({"minutes": 90, "action": "sleep"})
    monkeypatch.setattr(st.time, "time", lambda: 1000.0 + 600)
    assert st.sleep_timer_status({}) == "1 hour and 20 minutes left until the laptop goes to sleep."


def test_new_timer_replaces_old():
    st.sleep_timer({"minutes": 10, "action": "stop_media"})
    reply = st.sleep_timer({"minutes": 20, "action": "sleep"})
    assert "replaced" in reply
    assert st._timer["action"] == "sleep"


@pytest.mark.parametrize("args", [{}, {"minutes": 0}, {"minutes": "abc"}, {"minutes": -5}])
def test_bad_minutes_asks(args):
    assert st.sleep_timer(args) == "In how many minutes?"
    assert not st.is_active()


def test_too_long_and_bad_action():
    assert "24 hours" in st.sleep_timer({"minutes": 2000})
    assert "I can" in st.sleep_timer({"minutes": 5, "action": "explode"})


def test_risky_only_for_sleep_and_shutdown():
    assert st.risky_text({"minutes": 30, "action": "stop_media"}) is None
    assert st.risky_text({"minutes": 60, "action": "sleep"}) == "put the laptop to sleep in 1 hour"
    assert st.risky_text({"minutes": 120, "action": "shutdown"}) == "shut down the laptop in 2 hours"
    assert st.risky_text({"action": "shutdown"}) is None  # handler asks for minutes first
    assert st.needs_confirm({"minutes": 5, "action": "shut_down"})


def test_fade_without_volume_control_still_pauses(fake, monkeypatch):
    def boom():
        raise OSError("no audio")

    monkeypatch.setattr(st, "_get_volume", boom)
    st.sleep_timer({"minutes": 1})
    st._tick(1000 + 50)
    st._tick(1000 + 61)
    assert fake["paused"] == 1


def test_notifier_errors_are_ignored(monkeypatch):
    def bad(_):
        raise RuntimeError

    st.set_notifier(bad)
    monkeypatch.setattr(st, "_do_sleep", lambda: None)
    st.sleep_timer({"minutes": 2, "action": "sleep"})
    st._tick(1000 + 120 - 30)
    st._tick(1000 + 121)
    assert not st.is_active()
