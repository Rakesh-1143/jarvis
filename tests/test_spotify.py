"""Piece Y: spotify. spotipy and the Spotify app are faked (no network, no Windows)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import catalog as _catalog  # noqa: E402,F401  (keeps import order like other tests)
from jarvis.actions import spotify  # noqa: E402


class ApiError(Exception):
    def __init__(self, status, reason=""):
        super().__init__(reason)
        self.http_status = status
        self.reason = reason


TRACK = {"id": "t1", "uri": "spotify:track:t1", "name": "Shape of You", "artists": [{"name": "Ed Sheeran"}]}


class FakeSp:
    def __init__(self, devices=None, playback=None, playlists=None, error=None):
        self.calls = []
        self._devices = devices if devices is not None else [
            {"id": "phone", "name": "My Phone", "type": "Smartphone", "is_active": False},
            {"id": "pc", "name": "LAPTOP", "type": "Computer", "is_active": False}]
        self._playback = playback
        self._playlists = playlists or [{"id": "p1", "uri": "spotify:playlist:p1", "name": "Chill Vibes"},
                                        {"id": "p2", "uri": "spotify:playlist:p2", "name": "Workout"}]
        self.error = error

    def _raise(self):
        if self.error:
            raise self.error

    def devices(self):
        return {"devices": self._devices}

    def search(self, q, type, limit):
        self.calls.append(("search", q, type))
        if q == "nothing here":
            return {type + "s": {"items": []}}
        if type == "track":
            return {"tracks": {"items": [TRACK]}}
        return {type + "s": {"items": [{"uri": f"spotify:{type}:x", "name": q.title()}]}}

    def start_playback(self, device_id=None, uris=None, context_uri=None):
        self._raise()
        self.calls.append(("play", device_id, uris, context_uri))

    def current_user_playlists(self, limit, offset):
        return {"items": self._playlists if offset == 0 else [], "next": None}

    def current_user_saved_tracks(self, limit):
        return {"items": [{"track": TRACK}]}

    def current_playback(self):
        self._raise()
        return self._playback

    def current_user_saved_tracks_add(self, ids):
        self.calls.append(("like", ids))

    def playlist_add_items(self, pid, uris):
        self.calls.append(("add", pid, uris))

    def shuffle(self, state, device_id=None):
        self._raise()
        self.calls.append(("shuffle", state, device_id))

    def repeat(self, mode, device_id=None):
        self.calls.append(("repeat", mode, device_id))


@pytest.fixture
def keys(monkeypatch):
    """Spotify app id set; returns a function that installs a FakeSp."""
    monkeypatch.setattr(spotify, "_settings", lambda: {
        "client_id": "abc", "client_secret": "", "redirect_uri": spotify.DEFAULT_REDIRECT,
        "token_cache": "~/x", "device": ""})
    spotify.reset()

    def install(**kw):
        sp = FakeSp(**kw)
        monkeypatch.setattr(spotify, "_make_client", lambda s: sp)
        return sp
    yield install
    spotify.reset()


@pytest.fixture
def nokeys(monkeypatch):
    monkeypatch.setattr(spotify, "_settings", lambda: {
        "client_id": "", "client_secret": "", "redirect_uri": spotify.DEFAULT_REDIRECT,
        "token_cache": "~/x", "device": ""})
    opened = []
    monkeypatch.setattr(spotify, "_open_uri", opened.append)
    monkeypatch.setattr(spotify, "_make_client", lambda s: pytest.fail("must not build a client without keys"))
    spotify.reset()
    return opened


# ---------- catalog ----------

def test_catalog_matches_handlers():
    assert set(spotify.CATALOG) == set(spotify.HANDLERS) == {"spotify"}
    props = spotify.CATALOG["spotify"]["properties"]
    assert set(props["action"]["enum"]) == set(spotify.ACTIONS)


def test_unknown_action():
    assert "play" in spotify.spotify({"action": "dance"}).lower()


# ---------- settings ----------

def test_settings_env_beats_config(monkeypatch):
    import jarvis.config
    monkeypatch.setattr(jarvis.config, "load_config", lambda: {"spotify": {"client_id": "cfg", "device": "Laptop"}})
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "env")
    s = spotify._settings()
    assert s["client_id"] == "env" and s["device"] == "Laptop" and s["redirect_uri"] == spotify.DEFAULT_REDIRECT
    monkeypatch.delenv("SPOTIPY_CLIENT_ID")
    assert spotify._settings()["client_id"] == "cfg"


def test_settings_bad_config(monkeypatch):
    import jarvis.config
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.setattr(jarvis.config, "load_config", lambda: {"spotify": "oops"})
    assert spotify._settings()["client_id"] == ""


# ---------- query parsing ----------

@pytest.mark.parametrize("raw,query,kind", [
    ("shape of you", "shape of you", ""),
    ("the playlist chill vibes on spotify", "chill vibes", "playlist"),
    ("song believer", "believer", "track"),
    ("something by arijit singh", "arijit singh", "artist"),
    ("workout playlist", "workout", "playlist"),
    ("album 1989", "1989", "album"),
])
def test_clean_query(raw, query, kind):
    assert spotify._clean_query(raw) == (query, kind)


def test_link_uri():
    assert spotify._link_uri("https://open.spotify.com/intl-de/playlist/37i9dQ?si=1") == (
        "playlist", "spotify:playlist:37i9dQ")
    assert spotify._link_uri("spotify:track:abc") == ("track", "spotify:track:abc")
    assert spotify._link_uri("hello") is None


# ---------- no keys ----------

def test_play_no_keys_opens_search(nokeys):
    r = spotify.spotify({"action": "play", "query": "shape of you"})
    assert nokeys == ["spotify:search:shape%20of%20you"]
    assert "opened search" in r.lower()


def test_play_no_keys_empty_opens_app(nokeys):
    assert spotify.spotify({"action": "play"}) == "Opened Spotify."
    assert nokeys == ["spotify:"]


def test_play_no_keys_link(nokeys):
    spotify.spotify({"action": "play", "query": "https://open.spotify.com/track/abc"})
    assert nokeys == ["spotify:track:abc"]


def test_play_no_keys_app_missing(monkeypatch, nokeys):
    def boom(uri):
        raise OSError("no app")
    monkeypatch.setattr(spotify, "_open_uri", boom)
    assert "installed" in spotify.spotify({"action": "play", "query": "x"})


@pytest.mark.parametrize("action", ["like", "add_to_playlist", "shuffle", "repeat"])
def test_other_actions_need_setup(nokeys, action):
    assert spotify.spotify({"action": action, "playlist": "x"}) == spotify.NEED_SETUP


def test_now_playing_no_keys_uses_audio(monkeypatch, nokeys):
    from jarvis.actions import audio
    monkeypatch.setattr(audio, "now_playing", lambda a: "Playing X by Y.")
    assert spotify.spotify({"action": "now_playing"}) == "Playing X by Y."


# ---------- with keys: play ----------

def test_play_track_on_computer(keys):
    sp = keys()
    r = spotify.spotify({"action": "play", "query": "shape of you"})
    assert r == "Playing Shape of You by Ed Sheeran."
    assert ("play", "pc", ["spotify:track:t1"], None) in sp.calls


def test_play_prefers_active_device(keys):
    sp = keys(devices=[{"id": "pc", "name": "LAPTOP", "type": "Computer"},
                       {"id": "tv", "name": "TV", "type": "TV", "is_active": True}])
    spotify.spotify({"action": "play", "query": "x"})
    assert sp.calls[-1][1] == "tv"


def test_play_my_playlist(keys):
    sp = keys()
    r = spotify.spotify({"action": "play", "query": "my workout playlist"})
    assert r == "Playing your playlist Workout."
    assert sp.calls[-1] == ("play", "pc", None, "spotify:playlist:p2")
    assert not any(c[0] == "search" for c in sp.calls)


def test_play_public_playlist_when_not_mine(keys):
    sp = keys()
    r = spotify.spotify({"action": "play", "query": "lofi beats", "kind": "playlist"})
    assert ("search", "lofi beats", "playlist") in sp.calls
    assert r == "Playing the playlist Lofi Beats."


def test_play_artist(keys):
    sp = keys()
    r = spotify.spotify({"action": "play", "query": "songs by arijit singh"})
    assert sp.calls[-1] == ("play", "pc", None, "spotify:artist:x")
    assert r == "Playing Arijit Singh on Spotify."


def test_play_liked_songs(keys):
    sp = keys()
    assert spotify.spotify({"action": "play", "query": "my liked songs"}) == "Playing your liked songs."
    assert sp.calls[-1] == ("play", "pc", ["spotify:track:t1"], None)


def test_play_not_found(keys):
    keys()
    assert "couldn't find" in spotify.spotify({"action": "play", "query": "nothing here"})


def test_play_resume_without_query(keys):
    sp = keys()
    assert spotify.spotify({"action": "play"}) == "Playing Spotify."
    assert sp.calls[-1] == ("play", "pc", None, None)


def test_play_no_device_opens_app(monkeypatch, keys):
    keys(devices=[])
    opened = []
    monkeypatch.setattr(spotify, "_open_uri", opened.append)
    monkeypatch.setattr(spotify.time, "sleep", lambda s: None)
    assert spotify.spotify({"action": "play", "query": "x"}) == spotify.NO_DEVICE
    assert opened == ["spotify:"]


def test_play_needs_premium(keys):
    keys(error=ApiError(403, "PREMIUM_REQUIRED"))
    assert spotify.spotify({"action": "play", "query": "x"}) == spotify.NEED_PREMIUM


def test_config_device_name(monkeypatch, keys):
    sp = keys()
    monkeypatch.setattr(spotify, "_settings", lambda: {"client_id": "abc", "device": "my phone"})
    spotify.spotify({"action": "play", "query": "x"})
    assert sp.calls[-1][1] == "phone"


# ---------- with keys: other actions ----------

def test_like(keys):
    sp = keys(playback={"item": TRACK, "is_playing": True, "currently_playing_type": "track"})
    assert spotify.spotify({"action": "like"}) == "Liked Shape of You."
    assert ("like", ["t1"]) in sp.calls


def test_like_nothing_playing(keys):
    keys(playback=None)
    assert "Nothing is playing" in spotify.spotify({"action": "like"})


def test_add_to_playlist(keys):
    sp = keys(playback={"item": TRACK, "is_playing": True, "currently_playing_type": "track"})
    r = spotify.spotify({"action": "add_to_playlist", "playlist": "my chill vibes playlist"})
    assert r == "Added Shape of You to Chill Vibes."
    assert ("add", "p1", ["spotify:track:t1"]) in sp.calls


def test_add_to_missing_playlist(keys):
    keys(playback={"item": TRACK, "is_playing": True, "currently_playing_type": "track"})
    assert "couldn't find a playlist" in spotify.spotify({"action": "add_to_playlist", "playlist": "jazz"})


def test_add_needs_playlist_name(keys):
    keys()
    assert "Which playlist" in spotify.spotify({"action": "add_to_playlist"})


def test_shuffle_on_off(keys):
    sp = keys()
    assert spotify.spotify({"action": "shuffle"}) == "Shuffle on."
    assert spotify.spotify({"action": "shuffle", "state": "off"}) == "Shuffle off."
    assert sp.calls[-1] == ("shuffle", False, "pc")


@pytest.mark.parametrize("state,mode,reply", [
    (None, "track", "Repeating this song."), ("off", "off", "Repeat off."), ("playlist", "context", "Repeat on.")])
def test_repeat(keys, state, mode, reply):
    sp = keys()
    assert spotify.spotify({"action": "repeat", "state": state}) == reply
    assert sp.calls[-1][1] == mode


def test_now_playing(keys):
    keys(playback={"item": TRACK, "is_playing": False})
    assert spotify.spotify({"action": "now_playing"}) == "Paused on Shape of You by Ed Sheeran."


def test_now_playing_error(keys):
    keys(error=ApiError(500, "boom"))
    assert spotify.spotify({"action": "now_playing"}) == spotify.SPOTIFY_ERROR
