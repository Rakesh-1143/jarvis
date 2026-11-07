"""Tests for piece BF accessibility.py (all Windows calls faked)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import accessibility as acc  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    state = {"keys": [], "opened": [], "running": {}, "color": (False, True)}
    monkeypatch.setattr(acc, "_hotkey", lambda *k: state["keys"].append(k))
    monkeypatch.setattr(acc, "_start", lambda t: state["opened"].append(t))
    monkeypatch.setattr(acc, "_running", lambda f: state["running"].get(f))
    monkeypatch.setattr(acc, "_color_state", lambda: state["color"])
    return state


def run(**args):
    return acc.accessibility(args)


# ---------- magnifier ----------
def test_magnifier_on_starts_with_win_plus(fake):
    fake["running"]["magnifier"] = False
    assert "Magnifier is on" in run(feature="magnifier", action="on")
    assert fake["keys"] == [("win", "=")]


def test_magnifier_on_when_already_running(fake):
    fake["running"]["magnifier"] = True
    assert "already on" in run(feature="magnifier", action="on")
    assert fake["keys"] == []


def test_magnifier_zoom_in_and_out(fake):
    fake["running"]["magnifier"] = True
    assert run(feature="magnifier", action="zoom_in") == "Zoomed in."
    assert run(feature="magnifier", action="zoom_out") == "Zoomed out."
    assert fake["keys"] == [("win", "="), ("win", "-")]


def test_zoom_in_when_state_unknown_still_zooms(fake):
    assert run(feature="magnifier", action="zoom_in") == "Zoomed in."
    assert fake["keys"] == [("win", "=")]


def test_zoom_out_when_closed(fake):
    fake["running"]["magnifier"] = False
    assert "not on" in run(feature="magnifier", action="zoom_out")
    assert fake["keys"] == []


def test_magnifier_off(fake):
    fake["running"]["magnifier"] = True
    assert run(feature="magnifier", action="off") == "Magnifier closed."
    assert fake["keys"] == [("win", "esc")]


def test_magnifier_off_already_off(fake):
    fake["running"]["magnifier"] = False
    assert "already off" in run(feature="magnifier", action="off")
    assert fake["keys"] == []


def test_magnifier_toggle(fake):
    fake["running"]["magnifier"] = True
    assert run(feature="magnifier", action="toggle") == "Magnifier closed."
    fake["running"]["magnifier"] = False
    assert "Magnifier is on" in run(feature="magnifier")


def test_zoom_action_with_other_feature_goes_to_magnifier(fake):
    fake["running"]["magnifier"] = True
    assert run(feature="narrator", action="zoom_in") == "Zoomed in."


# ---------- narrator / captions ----------
@pytest.mark.parametrize("feature,keys,name", [
    ("narrator", ("ctrl", "win", "enter"), "Narrator"),
    ("captions", ("win", "ctrl", "l"), "Live captions"),
])
def test_toggle_features(fake, feature, keys, name):
    fake["running"][feature] = False
    assert run(feature=feature, action="on") == f"{name} is on."
    assert fake["keys"] == [keys]
    fake["running"][feature] = True
    assert run(feature=feature, action="on") == f"{name} is already on."
    assert run(feature=feature, action="off") == f"{name} is off."
    assert fake["keys"] == [keys, keys]
    fake["running"][feature] = False
    assert run(feature=feature, action="off") == f"{name} is already off."
    assert len(fake["keys"]) == 2


def test_toggle_unknown_state_presses_once(fake):
    assert run(feature="narrator", action="toggle") == "Switched Narrator."
    assert run(feature="narrator", action="off") == "Narrator is off."
    assert len(fake["keys"]) == 2


def test_toggle_with_known_state_says_result(fake):
    fake["running"]["captions"] = True
    assert run(feature="captions") == "Live captions is off."


def test_hotkey_error_opens_settings(fake, monkeypatch):
    def boom(*k):
        raise RuntimeError("no pyautogui")
    monkeypatch.setattr(acc, "_hotkey", boom)
    reply = run(feature="captions", action="on")
    assert "opened its settings" in reply and "22H2" in reply
    assert fake["opened"] == [acc.PAGES["captions"]]


def test_hotkey_and_settings_both_fail(fake, monkeypatch):
    def boom(*a):
        raise RuntimeError
    monkeypatch.setattr(acc, "_hotkey", boom)
    monkeypatch.setattr(acc, "_start", boom)
    assert "couldn't change Narrator" in run(feature="narrator", action="on")


# ---------- colour filter ----------
def test_color_filter_on(fake):
    fake["color"] = (False, True)
    assert run(feature="color_filter", action="on") == "Colour filter is on."
    assert fake["keys"] == [("win", "ctrl", "c")]


def test_color_filter_already_on(fake):
    fake["color"] = (True, True)
    assert "already on" in run(feature="color_filter", action="on")
    assert run(feature="color_filter", action="off") == "Colour filter is off."


def test_color_filter_shortcut_disabled_opens_settings(fake):
    fake["color"] = (False, False)
    reply = run(feature="color_filter", action="on")
    assert "Keyboard shortcut for color filters" in reply
    assert fake["opened"] == ["ms-settings:easeofaccess-colorfilter"]
    assert fake["keys"] == []


def test_color_filter_unknown_registry_still_toggles(fake):
    fake["color"] = (None, None)
    assert run(feature="colour filter", action="on") == "Colour filter is on."


# ---------- settings pages ----------
@pytest.mark.parametrize("feature,page", [
    ("text_size", "ms-settings:easeofaccess-display"),
    ("cursor", "ms-settings:easeofaccess-mousepointer"),
])
def test_settings_pages(fake, feature, page):
    assert "Opening" in run(feature=feature, action="on")
    assert fake["opened"] == [page]
    assert fake["keys"] == []


def test_unknown_feature(fake):
    assert "I can control" in run(feature="dark mode")
    assert fake["keys"] == [] and fake["opened"] == []


def test_bad_action_becomes_toggle(fake):
    fake["running"]["narrator"] = False
    assert run(feature="narrator", action="explode") == "Narrator is on."


# ---------- real helpers off Windows ----------
def test_running_without_exe_is_none():
    assert acc._running("cursor") is None


def test_running_uses_psutil(monkeypatch):
    from types import SimpleNamespace as NS

    class P:
        def __init__(self, n):
            self.info = {"name": n}
    fake_ps = NS(process_iter=lambda attrs: [P("explorer.exe"), P("Narrator.exe")])
    monkeypatch.setitem(sys.modules, "psutil", fake_ps)
    assert acc._running("narrator") is True
    assert acc._running("captions") is False


def test_color_state_off_windows():
    if sys.platform != "win32":
        assert acc._color_state() == (None, None)


# ---------- parse ----------
@pytest.mark.parametrize("text,feature,action", [
    ("turn on the magnifier", "magnifier", "on"),
    ("Jarvis, open magnifier", "magnifier", "on"),
    ("magnifier on", "magnifier", "on"),
    ("close the magnifier", "magnifier", "off"),
    ("magnifier off", "magnifier", "off"),
    ("magnify", "magnifier", "zoom_in"),
    ("magnify more", "magnifier", "zoom_in"),
    ("magnifier zoom in", "magnifier", "zoom_in"),
    ("zoom in with magnifier", "magnifier", "zoom_in"),
    ("magnifier zoom out", "magnifier", "zoom_out"),
    ("turn on narrator", "narrator", "on"),
    ("stop narrator", "narrator", "off"),
    ("start the screen reader", "narrator", "on"),
    ("toggle narrator", "narrator", "toggle"),
    ("turn on live captions", "captions", "on"),
    ("live captions off", "captions", "off"),
    ("show captions please", "captions", "on"),
    ("turn on colour filter", "color_filter", "on"),
    ("turn on grayscale", "color_filter", "on"),
    ("grayscale off", "color_filter", "off"),
    ("disable color filters", "color_filter", "off"),
    ("make the text bigger", "text_size", "toggle"),
    ("bigger text", "text_size", "toggle"),
    ("change text size", "text_size", "toggle"),
    ("make the cursor bigger", "cursor", "toggle"),
    ("bigger mouse pointer", "cursor", "toggle"),
    ("can you make the mouse pointer bigger", "cursor", "toggle"),
])
def test_parse(text, feature, action):
    assert acc.parse(text) == ("accessibility", {"feature": feature, "action": action})


@pytest.mark.parametrize("text", [
    "zoom in", "zoom out", "open chrome", "turn on bluetooth", "stop the music", "",
    "turn off subtitles", "make a note", "close the window", None,
])
def test_parse_ignores(text):
    assert acc.parse(text) is None


# ---------- catalog ----------
def test_catalog_matches_handlers():
    assert set(acc.CATALOG) == set(acc.HANDLERS) == {"accessibility"}
    props = acc.CATALOG["accessibility"]["properties"]
    assert set(props["feature"]["enum"]) == set(acc.FEATURES)
    assert set(props["action"]["enum"]) == set(acc.ACTIONS)
