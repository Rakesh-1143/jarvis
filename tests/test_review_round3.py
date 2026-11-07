"""Tests for REVIEW.md Round 3 fixes (T1-T10). All outside calls are faked."""
import os
import sys
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis import actions, brain, nlu  # noqa: E402
from jarvis.actions import cliphistory, generate, smarthome as sh, software, spotify  # noqa: E402
from jarvis.config import DEFAULTS  # noqa: E402


def test_t1_generated_secret_is_not_kept_in_history(monkeypatch):
    monkeypatch.setattr(generate, "_copy_private_windows", lambda t: False)
    monkeypatch.setitem(sys.modules, "pyperclip", NS(copy=lambda t: None, paste=lambda: "4821"))
    assert generate._copy("4821")
    assert cliphistory._last_seen == "4821"  # the poller will skip it


def test_t3_t4_sets():
    for intent in ("agenda", "next_event", "briefing", "free_at"):
        assert intent in brain.UNTRUSTED_INFO
    assert "recent_files" not in brain.UNTRUSTED_INFO
    for intent in ("move_file", "rename_file", "copy_file", "create_item", "copy_text"):
        assert intent in brain.GUARDED_ACTIONS


def test_t5_ai_cannot_pick_the_package():
    b = brain.Brain(DEFAULTS, actions.CATALOG, client=object())
    block = NS(name="software", input={"action": "install", "name": "notepad++", "id": "Evil.Pkg",
                                       "pkg": "Notepad++", "confirm": True})
    assert b._command(block) == nlu.Command("software", {"action": "install", "name": "notepad++"})


def test_t6_install_updates_and_no_random_package():
    assert nlu.parse("install updates") == nlu.Command("software", {"action": "update_all"})
    rows = [{"name": "Some Tool", "id": "A.Tool"}, {"name": "Other", "id": "B.Other"}]
    assert software._pick(rows, "updates") is None
    assert software._pick(rows, "tool")["id"] == "A.Tool"


def test_t2_first_spotify_login_does_not_block():
    started = []
    with mock.patch.object(spotify, "_start_login", started.append):
        auth = NS(get_cached_token=lambda: None)
        fake_oauth = NS(SpotifyPKCE=lambda **kw: auth, SpotifyOAuth=lambda **kw: auth)
        mods = {"spotipy": NS(Spotify=lambda **kw: "client"), "spotipy.oauth2": fake_oauth,
                "spotipy.cache_handler": NS(CacheFileHandler=lambda **kw: None)}
        with mock.patch.dict(sys.modules, mods):
            s = {"client_id": "x", "client_secret": "", "redirect_uri": "http://127.0.0.1:8888/callback",
                 "token_cache": os.path.join(os.path.dirname(__file__), "..", ".tmp-spotify-cache")}
            try:
                spotify._make_client(s)
                raise AssertionError("expected NeedLogin")
            except spotify.NeedLogin as e:
                assert "log in" in spotify._api_error(e)
    assert started == [auth]


def test_t7_seq_number_and_lowercase_digit_secret(monkeypatch):
    assert cliphistory.looks_like_secret("hunter2024x")
    assert not cliphistory.looks_like_secret("hello world")
    reads = []
    monkeypatch.setattr(cliphistory, "_clipboard_seq", lambda: 5)
    monkeypatch.setattr(cliphistory, "_last_seq", 5)
    monkeypatch.setattr(cliphistory, "_read_clipboard", lambda: reads.append(1) or "x")
    cliphistory.poll_once({})
    assert reads == []  # clipboard did not change: not opened


def test_t8_statements_do_not_switch_devices(monkeypatch):
    from jarvis import nlu_features

    monkeypatch.setattr(nlu_features, "_home_ready", lambda: True)
    for text in ("the lights are off", "the light is on"):
        assert nlu.parse(text).intent != "device", text
    assert nlu.parse("bedroom light on").intent == "device"


def test_t9_risky_question_when_home_assistant_is_down():
    with mock.patch.object(sh, "find", side_effect=OSError("down")):
        assert sh.risky_text({"name": "garage door", "action": "open"}) == "open garage door"
        assert sh.risky_text({"name": "front door lock", "action": "off"}) == "unlock front door lock"
        assert sh.risky_text({"name": "kitchen light", "action": "off"}) is None


def test_t10_scripts_need_to_be_allowed():
    st = {"entity_id": "script.open_garage", "state": "off", "attributes": {"friendly_name": "Open Garage"}}
    calls = []
    with mock.patch.object(sh, "find", return_value=(st, [])), \
            mock.patch.object(sh, "_call", lambda *a: calls.append(a)), \
            mock.patch.object(sh, "_settings", return_value={"allowed_scripts": set()}):
        assert "only run scripts" in sh.scene({"name": "open garage"})
    assert calls == []
    with mock.patch.object(sh, "find", return_value=(st, [])), \
            mock.patch.object(sh, "_call", lambda *a: calls.append(a)), \
            mock.patch.object(sh, "_settings", return_value={"allowed_scripts": {"script.open_garage"}}):
        assert sh.scene({"name": "open garage"}).startswith("Started")
    assert len(calls) == 1
