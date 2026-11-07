"""Tests for piece AD: screen time + app limits (no Windows needed)."""
import datetime as dt
import json
import threading

import pytest

from jarvis.actions import screentime as st

TODAY = dt.date.today().isoformat()


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    st.stop()
    st.reset()
    monkeypatch.setattr(st, "_cfg", lambda: {})
    st.SCREENTIME_FILE = str(tmp_path / "st.json")
    st._settings = dict(st.DEFAULTS)
    yield
    st.stop()
    st.reset()


def test_norm_and_friendly():
    assert st.norm("Chrome.exe") == "chrome"
    assert st.norm("Google Chrome") == "chrome"
    assert st.norm("VS Code") == "code"
    assert st.norm("msedge.exe") == "msedge"
    assert st.friendly("msedge") == "edge"
    assert st.norm("") == ""


def test_tick_counts_active_app():
    st.tick("chrome.exe", "News", idle_s=0, dt=5)
    st.tick("chrome.exe", "News", idle_s=0, dt=5)
    st.tick("notepad.exe", "x", idle_s=0, dt=5)
    apps, _ = st.usage()
    assert apps == {"chrome": 10, "notepad": 5}


def test_idle_lockscreen_and_huge_gap():
    st.tick("chrome.exe", "", idle_s=121, dt=5)      # idle 2+ min
    st.tick("LockApp.exe", "", idle_s=0, dt=5)       # lock screen
    st.tick("", "", idle_s=0, dt=5)                  # no window
    st.tick("chrome.exe", "", idle_s=0, dt=3600)     # woke from sleep
    apps, _ = st.usage()
    assert apps == {"chrome": 60}


def test_screen_time_one_app_and_total():
    st.tick("chrome.exe", "", 0, 60, date=TODAY)
    for _ in range(60):
        st.tick("chrome.exe", "", 0, 60, date=TODAY)
    for _ in range(30):
        st.tick("code.exe", "", 0, 60, date=TODAY)
    out = st.screen_time({"app": "google chrome"})
    assert out == "You used chrome for 1 hour and 1 minute today."
    out = st.screen_time({})
    assert out.startswith("Screen time today: 1 hour and 31 minutes.")
    assert "chrome 1 hour and 1 minute" in out and "vs code 30 minutes" in out


def test_screen_time_week_sums_7_days():
    today = dt.date(2026, 11, 7)
    for i in range(8):  # day 8 is outside the week
        d = (today - dt.timedelta(days=i)).isoformat()
        for _ in range(10):
            st.tick("chrome.exe", "", 0, 60, date=d)
    out = st.screen_time({"app": "chrome", "period": "week", "_today": today})
    assert out == "You used chrome for 1 hour and 10 minutes this week."
    total = st.screen_time({"period": "week", "_today": today})
    assert "about 10 minutes a day" in total


def test_screen_time_empty_and_unknown_app():
    assert st.screen_time({}) == "I have no screen time for today yet."
    assert st.screen_time({"app": "chrome"}) == "I have no screen time for today yet."
    st.tick("notepad.exe", "", 0, 60)
    assert st.screen_time({"app": "spotify"}) == "You did not use spotify today."


def test_limit_on_title_warns_once():
    st.app_limit({"app": "YouTube", "minutes": 2})
    said = []
    for _ in range(5):
        said += st.tick("chrome.exe", "Cats - YouTube - Google Chrome", 0, 60)
    st.tick("chrome.exe", "Gmail", 0, 60)  # not youtube
    assert len(said) == 1
    assert "youtube for 2 minutes" in said[0] and "limit of 2 minutes" in said[0]
    out = st.screen_time({"app": "youtube"})
    assert out.startswith("You used youtube for 5 minutes today. That is over your limit")


def test_limit_on_process_and_time_left():
    st.app_limit({"app": "chrome", "minutes": 60})
    for _ in range(20):
        st.tick("chrome.exe", "any", 0, 60)
    assert st.screen_time({"app": "chrome"}).endswith("Your limit is 1 hour, 40 minutes left.")


def test_config_limits_and_list_and_remove():
    st._config_limits = st._limits_from({"app_limits": {"YouTube": 60, "bad": "x", "zero": 0}})
    assert st._config_limits == {"youtube": 60.0}
    st.app_limit({"app": "chrome", "minutes": 90})
    assert st.app_limit({}) == "Your daily limits: chrome 1 hour and 30 minutes, youtube 1 hour."
    assert st.app_limit({"app": "chrome"}) == "Your chrome limit is 1 hour and 30 minutes a day."
    assert st.app_limit({"app": "chrome", "minutes": 0}) == "Removed the chrome limit."
    assert st.app_limit({"app": "chrome", "minutes": 0}) == "There was no chrome limit."
    assert st.app_limit({"app": "spotify"}) == "How many minutes a day for spotify?"
    st.app_limit({"app": "youtube", "minutes": 0})
    assert st.app_limit({}).startswith("You have no app limits.")


def test_new_limit_can_warn_again_today():
    st.app_limit({"app": "chrome", "minutes": 1})
    assert st.tick("chrome.exe", "", 0, 60)
    st.app_limit({"app": "chrome", "minutes": 2})
    assert st.tick("chrome.exe", "", 0, 60)


def test_save_and_reload_drops_old_days(tmp_path):
    path = tmp_path / "st.json"
    st.SCREENTIME_FILE = str(path)
    st.tick("chrome.exe", "", 0, 60)
    st.tick("chrome.exe", "", 0, 60, date="2000-01-01")
    st.app_limit({"app": "youtube", "minutes": 30})  # also saves
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "2000-01-01" not in data["days"]
    assert data["limits"] == {"youtube": 30}
    st._data = None  # reload from disk
    assert st.usage()[0] == {"chrome": 60}


def test_bad_file_is_ignored(tmp_path):
    path = tmp_path / "st.json"
    path.write_text("not json", encoding="utf-8")
    st.SCREENTIME_FILE = str(path)
    assert st.screen_time({}) == "I have no screen time for today yet."


def test_tracking_off_message():
    st.tracking(False)
    assert "Tracking is off" in st.screen_time({})


def test_start_thread_speaks_limit(monkeypatch):
    said = []
    hit = threading.Event()

    def say(msg):
        said.append(msg)
        hit.set()

    st._data = {"days": {}, "limits": {}}
    # every tick counts 60 s (dt is capped) so the 1 minute limit is reached at once
    monkeypatch.setattr(st, "tick", lambda p, t, i, d, date=None, _o=st.tick: _o(p, t, i, 60, date))
    t = st.start(say, cfg={"screentime": {"interval": 1}, "app_limits": {"youtube": 1}},
                 get=lambda: ("chrome.exe", "YouTube", 0.0))
    assert t is not None and t.is_alive()
    assert st.start(say, get=lambda: ("", "", 0.0)) is t  # only one thread
    assert hit.wait(5)
    st.stop()
    assert "youtube" in said[0]


def test_start_off_windows_returns_none(monkeypatch):
    monkeypatch.setattr(st.os, "name", "posix")
    assert st.start(lambda m: None, cfg={}) is None


def test_catalog_matches_handlers():
    assert set(st.CATALOG) == set(st.HANDLERS) == {"screen_time", "app_limit"}
    assert st.CATALOG["screen_time"].get("info") is True
    assert not st.CATALOG["app_limit"].get("info")
