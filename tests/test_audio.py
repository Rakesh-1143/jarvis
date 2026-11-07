"""Audio piece G. All Windows calls are faked."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import audio  # noqa: E402


class FakeVol:
    def __init__(self, level=1.0, muted=0):
        self.level, self.muted = level, muted

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, v, _ctx):
        self.level = v

    def GetMute(self):
        return self.muted

    def SetMute(self, m, _ctx):
        self.muted = m


# ---------- catalog / handlers ----------
def test_catalog_matches_handlers():
    assert set(audio.CATALOG) == set(audio.HANDLERS) == {"now_playing", "mic", "app_volume", "audio_output"}
    for spec in audio.CATALOG.values():
        assert spec["description"] and "properties" in spec and "required" in spec
        assert set(spec["required"]) <= set(spec["properties"])
    assert audio.CATALOG["now_playing"].get("info") is True


# ---------- now playing ----------
def test_now_playing_song():
    info = {"title": "Blinding Lights", "artist": "The Weeknd",
            "app": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "playing": True}
    with mock.patch.object(audio, "_media_info", return_value=info):
        assert audio.now_playing({}) == "Playing Blinding Lights by The Weeknd on Spotify."


def test_now_playing_paused_title_only():
    info = {"title": "Lofi beats - YouTube", "artist": "", "app": "MSEdge", "playing": False}
    with mock.patch.object(audio, "_media_info", return_value=info):
        assert audio.now_playing({}) == "Paused: Lofi beats - YouTube on Edge."


def test_now_playing_nothing_and_error():
    with mock.patch.object(audio, "_media_info", return_value=None):
        assert audio.now_playing({}) == "Nothing is playing right now."
    with mock.patch.object(audio, "_media_info", side_effect=ImportError):
        assert "can't see" in audio.now_playing({})


def test_app_label():
    assert audio._app_label("vlc.exe") == "VLC"
    assert audio._app_label("C:\\Apps\\foobar2000.exe") == "foobar2000"


# ---------- mic ----------
def test_mic_mute_unmute_all_endpoints():
    eps = [FakeVol(), FakeVol()]
    with mock.patch.object(audio, "_mic_endpoints", return_value=eps):
        assert audio.mic({"state": "off"}) == "Mic muted."
        assert all(e.muted == 1 for e in eps)
        assert audio.mic({}) == "Your mic is muted."
        assert audio.mic({"state": "on"}) == "Mic is on."
        assert all(e.muted == 0 for e in eps)
        assert audio.mic({}) == "Your mic is on."


def test_mic_missing():
    with mock.patch.object(audio, "_mic_endpoints", side_effect=OSError):
        assert audio.mic({"state": "off"}) == "I can't find a microphone."


# ---------- app volume ----------
def _fake_sessions():
    return [("Spotify.exe", FakeVol(0.8)), ("chrome.exe", FakeVol(1.0)), ("chrome.exe", FakeVol(1.0)),
            ("msedge.exe", FakeVol(0.5)), ("Zoom.exe", FakeVol(0.6))]


def test_app_volume_level():
    s = _fake_sessions()
    with mock.patch.object(audio, "_sessions", return_value=s):
        assert audio.app_volume({"app": "spotify", "level": 30}) == "Spotify volume set to 30 percent."
    assert abs(s[0][1].level - 0.3) < 1e-9
    assert s[1][1].level == 1.0  # other apps untouched


def test_app_volume_alias_hits_all_sessions():
    s = _fake_sessions()
    with mock.patch.object(audio, "_sessions", return_value=s):
        assert audio.app_volume({"app": "google chrome", "level": "20"}) == "Google Chrome volume set to 20 percent."
        assert audio.app_volume({"app": "edge", "change": "mute"}) == "Edge muted."
    assert abs(s[1][1].level - 0.2) < 1e-9 and abs(s[2][1].level - 0.2) < 1e-9
    assert s[3][1].muted == 1


def test_app_volume_change_and_read():
    s = _fake_sessions()
    with mock.patch.object(audio, "_sessions", return_value=s):
        assert audio.app_volume({"app": "zoom", "change": "down"}) == "Zoom volume set to 50 percent."
        assert audio.app_volume({"app": "zoom"}) == "Zoom volume is at 50 percent."


def test_app_volume_not_found():
    with mock.patch.object(audio, "_sessions", return_value=_fake_sessions()):
        assert audio.app_volume({"app": "discord", "level": 10}) == "Discord isn't playing any sound right now."
    assert audio.app_volume({}) == "Which app?"


# ---------- output device ----------
DEVICES = [
    {"id": "a", "name": "Speakers (Realtek(R) Audio)", "default": True},
    {"id": "b", "name": "Headphones (WH-1000XM4 Stereo)", "default": False},
    {"id": "c", "name": "LG TV (NVIDIA High Definition Audio)", "default": False},
]


def test_audio_output_list():
    with mock.patch.object(audio, "_output_devices", return_value=DEVICES):
        r = audio.audio_output({})
    assert r.startswith("Your audio outputs: Speakers (Realtek(R) Audio) (in use), Headphones")


def test_audio_output_switch_headphones():
    with mock.patch.object(audio, "_output_devices", return_value=DEVICES), \
         mock.patch.object(audio, "_set_default_output") as setdef:
        assert audio.audio_output({"name": "my headphones"}) == "Switched sound to Headphones (WH-1000XM4 Stereo)."
        setdef.assert_called_once_with("b")
        assert audio.audio_output({"name": "tv"}).endswith("LG TV (NVIDIA High Definition Audio).")
        assert audio.audio_output({"name": "speakers"}) == "Already using Speakers (Realtek(R) Audio)."


def test_audio_output_unknown_and_fallback():
    with mock.patch.object(audio, "_output_devices", return_value=DEVICES):
        assert audio.audio_output({"name": "airpods"}).startswith("I can't find airpods.")
    with mock.patch.object(audio, "_output_devices", return_value=DEVICES), \
         mock.patch.object(audio, "_set_default_output", side_effect=OSError), \
         mock.patch.object(audio, "_open") as op:
        assert "opened Sound settings" in audio.audio_output({"name": "headphones"})
        op.assert_called_once_with("ms-settings:sound")
    with mock.patch.object(audio, "_output_devices", side_effect=ImportError), \
         mock.patch.object(audio, "_open") as op:
        assert "opened Sound settings" in audio.audio_output({"name": "headphones"})
