"""Tests for actions/hotspot.py with a fake hotspot (no Windows needed)."""
import pytest

from jarvis.actions import hotspot as hs


class FakeHotspot:
    def __init__(self, state="off", start=("success", ""), stop=("success", ""), ssid="RAKESH-PC 1234",
                 password="s3cret-pass", clients=(0, 8, [])):
        self._state, self._start, self._stop = state, start, stop
        self.ssid, self.password, self._clients = ssid, password, clients
        self.calls = []

    def state(self):
        return self._state

    def start(self):
        self.calls.append("start")
        if self._start[0] == "success":
            self._state = "on"
        return self._start

    def stop(self):
        self.calls.append("stop")
        if self._stop[0] == "success":
            self._state = "off"
        return self._stop

    def ssid_and_password(self):
        return self.ssid, self.password

    def clients(self):
        return self._clients


@pytest.fixture
def env(monkeypatch):
    box = {"fake": FakeHotspot(), "settings": 0, "copied": [], "shown": [], "error": None}

    def backend():
        if box["error"]:
            raise box["error"]
        return box["fake"]

    monkeypatch.setattr(hs, "_backend", backend)
    monkeypatch.setattr(hs, "_open_settings", lambda: box.__setitem__("settings", box["settings"] + 1))
    monkeypatch.setattr(hs, "_copy", lambda t: box["copied"].append(t))
    monkeypatch.setattr(hs, "_show", lambda title, text: box["shown"].append(text))
    return box


def test_turn_on(env):
    assert hs.hotspot({"action": "on"}) == "Hotspot is on. Connect to RAKESH-PC 1234."
    assert env["fake"].calls == ["start"]


def test_turn_on_when_already_on(env):
    env["fake"]._state = "on"
    assert "already on" in hs.hotspot({"action": "on"})
    assert env["fake"].calls == []


def test_turn_on_wifi_off_opens_settings(env):
    env["fake"] = FakeHotspot(start=("wi_fi_device_off", ""))
    out = hs.hotspot({"action": "on"})
    assert "Wi-Fi is turned off" in out and "opened the hotspot settings" in out
    assert env["settings"] == 1


def test_turn_on_unknown_failure_includes_message(env):
    env["fake"] = FakeHotspot(start=("unknown", "driver error"))
    assert "driver error" in hs.hotspot({"action": "start"})


def test_turn_off(env):
    env["fake"]._state = "on"
    assert hs.hotspot({"action": "off"}) == "Hotspot is off."
    assert hs.hotspot({"action": "off"}) == "Your hotspot is already off."


def test_status_on_with_devices(env):
    env["fake"] = FakeHotspot(state="on", clients=(2, 8, ["Pixel-7", "iPad"]))
    out = hs.hotspot({"action": "status"})
    assert out == ("Your hotspot is on. Its name is RAKESH-PC 1234. "
                   "2 devices are connected: Pixel-7, iPad (up to 8 can join).")


def test_status_on_no_devices_and_off(env):
    env["fake"]._state = "on"
    assert "No devices are connected." in hs.hotspot({"action": "devices"})
    env["fake"]._state = "off"
    assert hs.hotspot({"action": "status"}) == "Your hotspot is off."


def test_password_never_in_reply(env):
    out = hs.hotspot({"action": "password"})
    assert "s3cret-pass" not in out
    assert "clipboard" in out and "RAKESH-PC 1234" in out
    assert env["copied"] == ["s3cret-pass"]
    assert "Password: s3cret-pass" in env["shown"][0]


def test_password_clipboard_fails_still_shows(env, monkeypatch):
    def bad(t):
        raise RuntimeError("no clipboard")

    monkeypatch.setattr(hs, "_copy", bad)
    out = hs.hotspot({"action": "password"})
    assert "showed the password on screen" in out and "s3cret" not in out
    assert env["shown"]


def test_no_internet_falls_back(env):
    env["error"] = hs.HotspotError("This PC is not connected to the internet, so there is nothing to share.")
    out = hs.hotspot({"action": "on"})
    assert out.startswith("This PC is not connected") and env["settings"] == 1


def test_odd_error_falls_back(env):
    env["error"] = OSError("class not registered")
    assert "class not registered" in hs.hotspot({"action": "on"})
    assert env["settings"] == 1


def test_settings_cannot_open(env, monkeypatch):
    env["error"] = hs.HotspotError("No hotspot.")

    def bad():
        raise OSError

    monkeypatch.setattr(hs, "_open_settings", bad)
    assert "Mobile hotspot" in hs.hotspot({"action": "on"})


def test_bad_action(env):
    assert "I can turn the hotspot" in hs.hotspot({"action": "dance"})


def test_not_windows_real_backend(monkeypatch):
    monkeypatch.setattr(hs.sys, "platform", "linux")
    with pytest.raises(hs.HotspotError):
        hs._backend()


@pytest.mark.parametrize("text,action", [
    ("turn on hotspot", "on"),
    ("turn on my mobile hotspot", "on"),
    ("switch the hotspot on", "on"),
    ("start hotspot", "on"),
    ("hotspot on", "on"),
    ("turn off hotspot", "off"),
    ("stop the hot spot", "off"),
    ("switch hotspot off", "off"),
    ("what's my hotspot password", "password"),
    ("show me the hotspot password", "password"),
    ("what is the password for my hotspot", "password"),
    ("is my hotspot on", "status"),
    ("how many devices are connected to my hotspot", "status"),
    ("how many devices are on my hotspot", "status"),
    ("who is on my hotspot", "status"),
    ("what's my hotspot name", "status"),
    ("hotspot status", "status"),
])
def test_parse(text, action):
    assert hs.parse(text) == ("hotspot", {"action": action})


@pytest.mark.parametrize("text", [
    "open hotspot settings", "hotspot settings", "turn on wifi", "what is a hotspot", "", "what's my wifi password",
])
def test_parse_no_match(text):
    assert hs.parse(text) is None


def test_catalog_matches_handlers():
    assert set(hs.CATALOG) == set(hs.HANDLERS) == {"hotspot"}
    assert hs.CATALOG["hotspot"]["properties"]["action"]["enum"] == list(hs.ACTIONS)
