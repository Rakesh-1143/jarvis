"""Tests for actions/display.py with fake screens (no Windows needed)."""
import pytest

from jarvis.actions import display as dp


@pytest.fixture
def env(monkeypatch):
    box = {"switched": [], "menu": 0,
           "mons": [{"device": r"\\.\DISPLAY1", "width": 1920, "height": 1080, "hz": 144, "primary": True,
                     "name": "Generic PnP Monitor"}]}
    monkeypatch.setattr(dp, "_on_windows", lambda: True)
    monkeypatch.setattr(dp, "_switch", lambda mode: box["switched"].append(mode))
    monkeypatch.setattr(dp, "_menu", lambda: box.__setitem__("menu", box["menu"] + 1))
    monkeypatch.setattr(dp, "_monitors", lambda: box["mons"])
    return box


@pytest.mark.parametrize("action,mode", [
    ("extend", "extend"), ("duplicate", "duplicate"), ("mirror", "duplicate"), ("clone", "duplicate"),
    ("external_only", "external_only"), ("second screen only", "external_only"),
    ("internal_only", "internal_only"), ("laptop only", "internal_only"), ("pc-only", "internal_only"),
])
def test_switch_modes(env, action, mode):
    out = dp.display({"action": action})
    assert env["switched"] == [mode]
    assert out == dp._REPLIES[mode]


def test_switch_args_are_displayswitch_flags():
    assert dp._SWITCH_ARGS == {"extend": "/extend", "duplicate": "/clone",
                               "external_only": "/external", "internal_only": "/internal"}


def test_info_one_screen(env):
    assert dp.display({"action": "info"}) == "You have one screen. Its resolution is 1920 by 1080 at 144 hertz."


def test_info_two_screens(env):
    env["mons"].append({"device": r"\\.\DISPLAY2", "width": 2560, "height": 1440, "hz": 1, "primary": False,
                        "name": "DELL U2719D"})
    out = dp.display({"action": "resolution"})
    assert out == ("You have 2 screens. Main screen: 1920 by 1080 at 144 hertz. "
                   "Screen 2 (DELL U2719D): 2560 by 1440.")


def test_info_no_screens(env):
    env["mons"] = []
    assert dp.display({"action": "info"}) == "I can't see any screens."


def test_menu(env):
    assert dp.display({"action": "menu"}) == "Here is the projection menu."
    assert env["menu"] == 1


def test_switch_error(env, monkeypatch):
    def bad(mode):
        raise FileNotFoundError("DisplaySwitch.exe")

    monkeypatch.setattr(dp, "_switch", bad)
    assert "couldn't change the screens" in dp.display({"action": "extend"})


def test_bad_action_and_not_windows(env, monkeypatch):
    assert "I can extend" in dp.display({"action": "rotate"})
    monkeypatch.setattr(dp, "_on_windows", lambda: False)
    assert "only works on Windows" in dp.display({"action": "extend"})


@pytest.mark.parametrize("text,action", [
    ("extend my screen", "extend"),
    ("extend the display", "extend"),
    ("please extend my screen to the projector", "extend"),
    ("duplicate screen", "duplicate"),
    ("mirror my screen", "duplicate"),
    ("show my screen on the tv", "duplicate"),
    ("same picture on both screens", "duplicate"),
    ("second screen only", "external_only"),
    ("projector only", "external_only"),
    ("only use the external monitor", "external_only"),
    ("laptop screen only", "internal_only"),
    ("pc screen only", "internal_only"),
    ("disconnect the projector", "internal_only"),
    ("stop projecting", "internal_only"),
    ("what's my resolution", "info"),
    ("what is my screen resolution", "info"),
    ("how many monitors do I have", "info"),
    ("how many screens", "info"),
    ("open projection menu", "menu"),
    ("show the project menu", "menu"),
])
def test_parse(text, action):
    assert dp.parse(text) == ("display", {"action": action})


@pytest.mark.parametrize("text", [
    "turn off the screen", "turn off the tv", "turn off my pc", "open chrome", "what's the weather",
    "take a screenshot", "", "brightness up",
])
def test_parse_no_match(text):
    assert dp.parse(text) is None


def test_catalog_matches_handlers():
    assert set(dp.CATALOG) == set(dp.HANDLERS) == {"display"}
    assert dp.CATALOG["display"]["properties"]["action"]["enum"] == list(dp.ACTIONS)
