"""Piece U: smart home (Home Assistant). All HTTP is faked."""
import os
import sys
import urllib.error
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import smarthome as sh  # noqa: E402

STATES = [
    {"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "Bedroom Light", "brightness": 128}},
    {"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen Light"}},
    {"entity_id": "fan.ceiling", "state": "on", "attributes": {"friendly_name": "Ceiling Fan", "percentage": 50}},
    {"entity_id": "climate.living_room", "state": "cool",
     "attributes": {"friendly_name": "Living Room AC", "temperature": 22, "current_temperature": 26.5,
                    "min_temp": 16, "max_temp": 30}},
    {"entity_id": "lock.front_door", "state": "locked", "attributes": {"friendly_name": "Front Door"}},
    {"entity_id": "cover.garage", "state": "closed",
     "attributes": {"friendly_name": "Garage Door", "device_class": "garage"}},
    {"entity_id": "cover.bedroom_blinds", "state": "closed",
     "attributes": {"friendly_name": "Bedroom Blinds", "device_class": "blind"}},
    {"entity_id": "switch.tv_plug", "state": "on", "attributes": {"friendly_name": "TV Plug"}},
    {"entity_id": "sensor.outside_temp", "state": "18.2",
     "attributes": {"friendly_name": "Outside Temperature", "unit_of_measurement": "°C"}},
    {"entity_id": "scene.movie_night", "state": "scening", "attributes": {"friendly_name": "Movie Night"}},
    {"entity_id": "automation.x", "state": "on", "attributes": {"friendly_name": "Bedroom Light Auto"}},
]

SETTINGS = {"url": "http://ha.local:8123", "token": "secret-token", "verify_ssl": True,
            "aliases": {"ac": "climate.living_room"}, "all_off_domains": ["light", "fan", "media_player"]}


@pytest.fixture
def ha():
    """Fake HA: records service calls."""
    calls = []

    def fake_request(method, path, body=None):
        if method == "GET" and path == "/api/states":
            return STATES
        calls.append((path, body))
        return []

    sh.clear_cache()
    with mock.patch.object(sh, "_settings", return_value=dict(SETTINGS)), \
            mock.patch.object(sh, "_request", side_effect=fake_request):
        yield calls
    sh.clear_cache()


def test_catalog_matches_handlers():
    assert set(sh.CATALOG) == set(sh.HANDLERS) == {"device", "scene"}
    for spec in sh.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])


def test_turn_on_bedroom_light(ha):
    assert sh.device({"name": "bedroom light", "action": "on"}) == "Turned on Bedroom Light."
    assert ha == [("/api/services/light/turn_on", {"entity_id": "light.bedroom"})]


def test_fuzzy_name_and_skips_other_domains(ha):
    sh.device({"name": "kitchen lights", "action": "off"})
    assert ha[-1] == ("/api/services/light/turn_off", {"entity_id": "light.kitchen"})


def test_fan_percent(ha):
    assert "50 percent" in sh.device({"name": "fan", "action": "set", "value": "50 percent"})
    assert ha[-1] == ("/api/services/fan/set_percentage", {"entity_id": "fan.ceiling", "percentage": 50})


def test_ac_alias_and_temperature(ha):
    assert sh.device({"name": "AC", "action": "set", "value": 24}) == "Set Living Room AC to 24 degrees."
    assert ha[-1] == ("/api/services/climate/set_temperature",
                      {"entity_id": "climate.living_room", "temperature": 24.0})


def test_ac_out_of_range(ha):
    assert "16 to 30" in sh.device({"name": "AC", "action": "set", "value": 50})
    assert ha == []


def test_light_brightness(ha):
    sh.device({"name": "bedroom light", "action": "set", "value": 30})
    assert ha[-1] == ("/api/services/light/turn_on", {"entity_id": "light.bedroom", "brightness_pct": 30})


def test_status_lock(ha):
    assert sh.device({"name": "front door", "action": "status"}) == "Front Door is locked."
    assert ha == []


def test_status_light_and_climate_and_sensor(ha):
    assert sh.device({"name": "bedroom light", "action": "status"}) == "Bedroom Light is on at 50 percent."
    assert "room is 26.5 degrees" in sh.device({"name": "AC", "action": "status"})
    assert sh.device({"name": "outside temperature", "action": "status"}) == "Outside Temperature is 18.2 degrees."


def test_unlock_needs_confirm(ha):
    args = {"name": "front door", "action": "unlock"}
    assert sh.needs_confirm(args)
    assert sh.device(args).startswith("Are you sure you want to unlock Front Door")
    assert ha == []
    assert sh.device({**args, "confirm": True}) == "Unlocked Front Door."
    assert ha == [("/api/services/lock/unlock", {"entity_id": "lock.front_door"})]


def test_lock_off_means_unlock_and_is_risky(ha):
    args = {"name": "front door lock", "action": "off"}
    assert sh.risky_text(args) == "unlock Front Door"
    assert "Are you sure" in sh.device(args)
    assert ha == []


def test_lock_is_not_risky(ha):
    args = {"name": "front door", "action": "lock"}
    assert not sh.needs_confirm(args)
    assert sh.device(args) == "Locked Front Door."


def test_garage_open_needs_confirm_but_close_does_not(ha):
    args = {"name": "garage door", "action": "open"}
    assert sh.risky_text(args) == "open Garage Door"
    assert "Are you sure" in sh.device(args)
    assert ha == []
    assert sh.device({**args, "confirm": True}) == "Opening Garage Door."
    assert ha[-1] == ("/api/services/cover/open_cover", {"entity_id": "cover.garage"})
    assert not sh.needs_confirm({"name": "garage door", "action": "close"})
    assert sh.device({"name": "garage door", "action": "close"}) == "Closing Garage Door."


def test_garage_set_position_is_risky(ha):
    assert sh.needs_confirm({"name": "garage", "action": "set", "value": 40})
    assert not sh.needs_confirm({"name": "garage", "action": "set", "value": 0})


def test_blinds_open_not_risky(ha):
    args = {"name": "bedroom blinds", "action": "open"}
    assert not sh.needs_confirm(args)
    assert sh.device(args) == "Opening Bedroom Blinds."


def test_everything_off_needs_confirm(ha):
    args = {"name": "everything", "action": "off"}
    assert sh.risky_text(args) == "turn off everything in the house"
    assert "Are you sure" in sh.device(args)
    assert ha == []
    assert sh.device({**args, "confirm": True}) == "Turned off everything."
    assert [p for p, _ in ha] == ["/api/services/light/turn_off", "/api/services/fan/turn_off",
                                  "/api/services/media_player/turn_off"]
    assert all(b == {"entity_id": "all"} for _, b in ha)


def test_everything_on_refused(ha):
    assert "only turn everything off" in sh.device({"name": "everything", "action": "on"})
    assert ha == []


def test_all_lights_off_not_risky(ha):
    args = {"name": "all the lights", "action": "off"}
    assert not sh.needs_confirm(args)
    assert sh.device(args) == "Turned off all the lights."
    assert ha == [("/api/services/light/turn_off", {"entity_id": "all"})]


def test_unknown_device(ha):
    assert "couldn't find" in sh.device({"name": "spaceship", "action": "on"})
    assert ha == []


def test_scene(ha):
    assert sh.scene({"name": "movie night scene"}) == "Set Movie Night."
    assert ha == [("/api/services/scene/turn_on", {"entity_id": "scene.movie_night"})]


def test_toggle_and_plug(ha):
    assert sh.device({"name": "TV plug", "action": "toggle"}) == "Toggled TV Plug."
    assert ha[-1] == ("/api/services/switch/toggle", {"entity_id": "switch.tv_plug"})


# ----- real _request: setup errors, auth header, token never in replies -----

def test_not_set_up():
    sh.clear_cache()
    with mock.patch.object(sh, "_settings", return_value={**SETTINGS, "token": ""}):
        assert sh.device({"name": "bedroom light", "action": "on"}) == sh.NOT_SET_UP


def test_bad_token_and_no_reach():
    sh.clear_cache()
    err = urllib.error.HTTPError("http://ha.local:8123/api/states", 401, "no", {}, None)
    with mock.patch.object(sh, "_settings", return_value=dict(SETTINGS)), \
            mock.patch("urllib.request.urlopen", side_effect=err):
        r = sh.device({"name": "bedroom light", "action": "on"})
        assert r == sh.BAD_TOKEN and "secret-token" not in r
    with mock.patch.object(sh, "_settings", return_value=dict(SETTINGS)), \
            mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        assert sh.device({"name": "bedroom light", "action": "on"}) == sh.NO_REACH


def test_request_sends_bearer_token():
    sh.clear_cache()
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def fake_open(req, timeout=None, context=None):
        seen["auth"] = req.get_header("Authorization")
        seen["url"] = req.full_url
        return Resp()

    with mock.patch.object(sh, "_settings", return_value=dict(SETTINGS)), \
            mock.patch("urllib.request.urlopen", side_effect=fake_open):
        assert sh._request("GET", "/api/states") == []
    assert seen == {"auth": "Bearer secret-token", "url": "http://ha.local:8123/api/states"}


def test_env_token_wins(monkeypatch):
    monkeypatch.setenv("HASS_TOKEN", "env-token")
    with mock.patch("jarvis.config.load_config",
                    return_value={"home_assistant": {"url": "http://x:8123/", "token": "cfg"}}):
        s = sh._settings()
    assert s["token"] == "env-token" and s["url"] == "http://x:8123"


def test_risky_text_never_raises_when_offline():
    sh.clear_cache()
    with mock.patch.object(sh, "_settings", return_value={**SETTINGS, "url": ""}):
        assert sh.risky_text({"name": "garage door", "action": "open"}) == "open garage door"
        assert sh.risky_text({"name": "bedroom light", "action": "on"}) is None
