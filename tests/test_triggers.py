"""Triggers (piece AB). Sensors are faked with `sense=`; no real waiting."""
import datetime as dt
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import triggers as tg  # noqa: E402


@pytest.fixture(autouse=True)
def env(monkeypatch):
    tg.reset()
    said, ran = [], []
    monkeypatch.setattr(tg, "notify", said.append)
    monkeypatch.setattr(tg, "runner", lambda p: ran.append(p) or f"did {p}")
    yield said, ran
    tg.stop()
    tg.reset()


def ts(y, mo, d, h, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s).timestamp()


NOW = ts(2026, 11, 9, 12)  # a Monday


def S(apps=None, wifi=None, charger=None):
    return {"apps": set(apps) if apps is not None else None, "wifi": wifi, "charger": charger}


# ---------- config ----------
def test_normalise_kinds():
    assert tg.normalise({"when": {"app_opens": "Zoom"}, "do": "mute"})["aliases"] == ["zoom"]
    assert tg.normalise({"when": {"charger": True}, "do": ["x"]})["value"] == "plugged"
    assert tg.normalise({"when": {"charger": "unplugged"}, "do": ["x"]})["value"] == "unplugged"
    t = tg.normalise({"when": {"time": "9 am", "days": "weekdays"}, "do": ["x"]})
    assert t["value"] == "09:00" and t["days"] == [0, 1, 2, 3, 4]
    assert tg.normalise({"when": {"time": 540}, "do": ["x"]})["value"] == "09:00"  # YAML 09:00
    assert tg.normalise({"when": {"wifi": "Home"}, "do": ["x"]})["value"] == "Home"


@pytest.mark.parametrize("raw", [
    None, "x", {"when": {"app_opens": "zoom"}}, {"when": {"app_opens": ""}, "do": ["x"]},
    {"when": {"time": "25:00"}, "do": ["x"]}, {"when": {"charger": "maybe"}, "do": ["x"]},
    {"when": {"app_opens": "a", "wifi": "b"}, "do": ["x"]}, {"when": {"nope": 1}, "do": ["x"]},
    {"when": {"wifi": "Home"}, "do": []},
])
def test_normalise_bad(raw):
    assert tg.normalise(raw) is None


def test_app_alias_from_apps_config():
    t = tg.normalise({"when": {"app_opens": "vs code"}, "do": ["x"]},
                     {"VS Code": r"C:\Users\me\AppData\Local\Programs\Code.exe"})
    assert t["aliases"] == ["vscode", "code"]


def test_load_counts_bad():
    tg.load([{"when": {"wifi": "Home"}, "do": ["x"]}, {"bad": 1}])
    assert len(tg._get()) == 1 and tg._bad == 1


def test_load_from_config(monkeypatch):
    import jarvis.config as c

    monkeypatch.setattr(c, "load_config", lambda: {"triggers": [{"when": {"app_opens": "zoom"}, "do": ["x"]}],
                                                   "apps": {}})
    assert len(tg.load()) == 1


def test_no_triggers_in_config(monkeypatch):
    import jarvis.config as c

    monkeypatch.setattr(c, "load_config", lambda: {})
    assert tg.load() == []
    assert tg.start() is None  # no thread without triggers


# ---------- firing ----------
def test_app_opens_fires_once(env):
    said, ran = env
    tg.load([{"when": {"app_opens": "zoom"}, "do": ["volume 20", "open notes"]}])
    assert tg.check(NOW, S(["explorer"])) == []          # first look = baseline
    assert len(tg.check(NOW, S(["explorer", "zoom"]))) == 1
    assert ran == ["volume 20", "open notes"]
    assert said == ["zoom opened.", "did volume 20", "did open notes"]
    assert tg.check(NOW, S(["explorer", "zoom"])) == []  # still open: no repeat
    tg.check(NOW, S(["explorer"]))
    assert len(tg.check(NOW, S(["zoom"]))) == 1           # opened again


def test_already_open_at_start_does_not_fire(env):
    tg.load([{"when": {"app_opens": "zoom"}, "do": ["x"]}])
    assert tg.check(NOW, S(["zoom"])) == []
    assert tg.check(NOW, S(["zoom"])) == []


def test_app_closes(env):
    _, ran = env
    tg.load([{"when": {"app_closes": "Teams"}, "do": ["x"]}])
    tg.check(NOW, S(["msteams"]))  # "teams" found inside "msteams"
    assert tg.check(NOW, S(["msteams"])) == []
    assert len(tg.check(NOW, S([]))) == 1 and ran == ["x"]


def test_short_name_needs_exact_match(env):
    tg.load([{"when": {"app_opens": "vlc"}, "do": ["x"]}])
    tg.check(NOW, S([]))
    assert tg.check(NOW, S(["vlcextra"])) == []
    assert len(tg.check(NOW, S(["vlc"]))) == 1


def test_unknown_reading_keeps_state(env):
    tg.load([{"when": {"app_opens": "zoom"}, "do": ["x"]}])
    tg.check(NOW, S([]))
    assert tg.check(NOW, S(None)) == []  # psutil failed this tick
    assert len(tg.check(NOW, S(["zoom"]))) == 1


def test_wifi_join(env):
    tg.load([{"when": {"wifi": "Home"}, "do": ["x"]}])
    tg.check(NOW, S(wifi=""))
    assert len(tg.check(NOW, S(wifi="HOME"))) == 1
    assert tg.check(NOW, S(wifi="HOME")) == []
    tg.check(NOW, S(wifi="Cafe"))
    assert len(tg.check(NOW, S(wifi="Home"))) == 1


def test_charger(env):
    said, _ = env
    tg.load([{"when": {"charger": "unplugged"}, "do": ["x"], "say": ""}])
    tg.check(NOW, S(charger="plugged"))
    assert len(tg.check(NOW, S(charger="unplugged"))) == 1
    assert said == ["did x"]  # say "" = no announcement
    assert tg.check(NOW, S(charger="unplugged")) == []
    tg.load([{"when": {"charger": "unplugged"}, "do": ["x"]}])
    tg.check(NOW, S(charger=None))  # desktop: no battery
    assert tg.check(NOW, S(charger=None)) == []


def test_time_trigger_once_a_day(env):
    said, _ = env
    tg.load([{"when": {"time": "09:00", "days": "weekdays"}, "do": ["x"], "say": "Good morning."}])
    assert tg.check(ts(2026, 11, 9, 8, 59, 58), {}) == []
    assert len(tg.check(ts(2026, 11, 9, 9, 0, 1), {})) == 1
    assert said[0] == "Good morning."
    assert tg.check(ts(2026, 11, 9, 9, 0, 4), {}) == []          # same day: no repeat
    assert len(tg.check(ts(2026, 11, 10, 9, 0, 2), {})) == 1     # next day
    assert tg.check(ts(2026, 11, 14, 9, 0, 2), {}) == []         # Saturday


def test_time_trigger_skips_when_late(env):
    tg.load([{"when": {"time": "09:00"}, "do": ["x"]}])
    assert tg.check(ts(2026, 11, 9, 9, 5), {}) == []  # laptop was asleep


def test_pause_and_resume(env):
    _, ran = env
    tg.load([{"when": {"app_opens": "zoom"}, "do": ["x"]}])
    tg.check(NOW, S([]))
    assert "paused" in tg.triggers({"action": "pause"})
    assert tg.check(NOW, S(["zoom"])) == []  # opened while paused
    assert "on again" in tg.triggers({"action": "resume"})
    assert tg.check(NOW, S(["zoom"])) == []  # old change is not fired late
    assert ran == []


def test_step_error_does_not_stop_others(env, monkeypatch):
    said, _ = env

    def boom(p):
        if p == "bad":
            raise RuntimeError
        return "ok"

    monkeypatch.setattr(tg, "runner", boom)
    tg.load([{"when": {"wifi": "Home"}, "do": ["bad", "good"], "say": ""}])
    tg.check(NOW, S(wifi=""))
    tg.check(NOW, S(wifi="Home"))
    assert said == ["ok"]


def test_no_runner(env, monkeypatch):
    monkeypatch.setattr(tg, "runner", None)
    tg.load([{"when": {"wifi": "Home"}, "do": ["x"]}])
    tg.check(NOW, S(wifi=""))
    assert len(tg.check(NOW, S(wifi="Home"))) == 1  # no crash


def test_only_needed_sensors_are_read(monkeypatch):
    calls = []
    monkeypatch.setattr(tg, "running_apps", lambda: calls.append("apps") or set())
    monkeypatch.setattr(tg, "wifi_ssid", lambda: calls.append("wifi") or "")
    monkeypatch.setattr(tg, "charger_state", lambda: calls.append("charger") or None)
    tg.load([{"when": {"charger": "plugged"}, "do": ["x"]}])
    tg.check(NOW)
    assert calls == ["charger"]


# ---------- sensors ----------
def test_wifi_ssid(monkeypatch):
    from jarvis.actions import network

    monkeypatch.setattr(network, "wifi_info", lambda: {"ssid": "Home", "state": "connected"})
    assert tg.wifi_ssid() == "Home"
    monkeypatch.setattr(network, "wifi_info", lambda: {"state": "disconnected"})
    assert tg.wifi_ssid() == ""
    monkeypatch.setattr(network, "wifi_info", lambda: {})
    assert tg.wifi_ssid() is None


def test_psutil_sensors(monkeypatch):
    fake = SimpleNamespace(
        process_iter=lambda attrs: [SimpleNamespace(info={"name": "Zoom.exe"}), SimpleNamespace(info={"name": None})],
        sensors_battery=lambda: SimpleNamespace(power_plugged=False),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    assert tg.running_apps() == {"zoom"}
    assert tg.charger_state() == "unplugged"
    fake.sensors_battery = lambda: None
    assert tg.charger_state() is None


# ---------- handler + nlu ----------
def test_list(monkeypatch):
    import jarvis.config as c

    monkeypatch.setattr(c, "load_config", lambda: {"triggers": [
        {"when": {"app_opens": "Zoom"}, "do": ["volume 20", "open notes"]},
        {"when": {"time": "21:30", "days": "weekdays"}, "do": ["lock"], "name": "night"},
        {"bad": True}]})
    r = tg.triggers({"action": "list"})
    assert r.startswith("You have 2 triggers: when Zoom opens, volume 20, then open notes;")
    assert "night: at 9:30 PM every weekday, lock" in r
    assert "skipped 1 broken one" in r


def test_list_empty(monkeypatch):
    import jarvis.config as c

    monkeypatch.setattr(c, "load_config", lambda: {})
    assert "no triggers" in tg.triggers({"action": "list"})
    assert "none" in tg.triggers({"action": "resume"})


@pytest.mark.parametrize("text,action", [
    ("list my triggers", "list"), ("what triggers do I have", "list"), ("show triggers", "list"),
    ("Jarvis, pause triggers.", "pause"), ("turn off my automations", "pause"), ("triggers off", "pause"),
    ("resume triggers", "resume"), ("turn triggers on", "resume"), ("switch my triggers off", "pause"), ("turn on triggers", "resume"),
    ("start my triggers again", "resume"),
])
def test_parse(text, action):
    r = tg.parse(text)
    assert (r and r[1]["action"]) == action or (r is None and action is None)


@pytest.mark.parametrize("text", ["open zoom", "pause music", "what is a trigger", "trigger warning"])
def test_parse_ignores(text):
    assert tg.parse(text) is None


def test_catalog_matches_handlers():
    assert set(tg.CATALOG) == set(tg.HANDLERS) == {"triggers"}


def test_start_thread(monkeypatch):
    monkeypatch.setattr(tg, "TICK", 0.01)
    tg.load([{"when": {"wifi": "Home"}, "do": ["x"]}])
    monkeypatch.setattr(tg, "wifi_ssid", lambda: "")
    seen = []
    th = tg.start(runner=seen.append, notify=seen.append)
    assert th is not None and th.is_alive() and th.daemon
    assert tg.runner == seen.append
    tg.stop()
    th.join(1)
    assert not th.is_alive()
