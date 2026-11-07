"""Piece Y: Spotify control (the Spotify app, not YouTube).

Intent:
  spotify {action: play|like|add_to_playlist|shuffle|repeat|now_playing,
           query?, kind?, playlist?, state?}

Two modes:
  1. With a Spotify app id (Web API through `spotipy`): plays a song / playlist / artist / album on your
     Spotify app, likes the current song, adds it to one of your playlists, shuffle, repeat, what's playing.
     Setup once: make an app at https://developer.spotify.com/dashboard, add the redirect URI
     http://127.0.0.1:8888/callback, then put the Client ID in config or env. The first command opens the
     browser to log in; the token is cached (default ~/.jarvis/spotify_token.json).
     Playing / shuffle / repeat need Spotify Premium (Spotify's rule).
  2. No app id: "play X" opens `spotify:search:X` in the Spotify app and says so. Other actions explain setup.
     "what's playing" falls back to audio.now_playing (Windows media info).

Credentials are never in code. Order: env SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET / SPOTIPY_REDIRECT_URI,
then config `spotify: {client_id, client_secret, redirect_uri, token_cache, device}`.
client_secret is optional: without it, PKCE login is used (safer, nothing secret to store).

Pause / next / previous stay with the `media` intent (media keys). Not duplicated here.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
from pathlib import Path

DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"
DEFAULT_CACHE = "~/.jarvis/spotify_token.json"
SCOPES = " ".join([
    "user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
    "user-library-read", "user-library-modify",
    "playlist-read-private", "playlist-modify-private", "playlist-modify-public",
])
KINDS = ("track", "playlist", "artist", "album")
ACTIONS = ("play", "like", "add_to_playlist", "shuffle", "repeat", "now_playing")

NEED_SETUP = ("To do that I need a Spotify app ID. Add spotify client_id to config.yaml "
              "or set SPOTIPY_CLIENT_ID. The README explains how.")
NEED_PREMIUM = "Spotify only allows playback control with a Premium account."
NO_DEVICE = "Spotify isn't open on any device. Open the Spotify app and try again."
SPOTIFY_ERROR = "Spotify didn't answer. Please try again."

_client = None  # cached spotipy.Spotify


# ---------- settings + client ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("spotify") or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    env = os.environ.get
    return {
        "client_id": (env("SPOTIPY_CLIENT_ID") or str(cfg.get("client_id") or "")).strip(),
        "client_secret": (env("SPOTIPY_CLIENT_SECRET") or str(cfg.get("client_secret") or "")).strip(),
        "redirect_uri": (env("SPOTIPY_REDIRECT_URI") or str(cfg.get("redirect_uri") or "") or DEFAULT_REDIRECT),
        "token_cache": str(cfg.get("token_cache") or DEFAULT_CACHE),
        "device": str(cfg.get("device") or "").strip(),
    }


def has_keys() -> bool:
    return bool(_settings()["client_id"])


class NeedLogin(Exception):
    """No saved Spotify login yet. The message is spoken to the user."""


_login_thread = None


def _start_login(auth) -> None:
    """First login opens the browser and waits for the redirect. That wait has no time limit,
    so it runs in a background thread and never blocks the voice loop."""
    global _login_thread
    import threading

    if _login_thread is not None and _login_thread.is_alive():
        return

    def work():
        try:
            auth.get_access_token()
        except BaseException:  # closed browser, no console for input(), ...
            pass

    _login_thread = threading.Thread(target=work, name="spotify-login", daemon=True)
    _login_thread.start()


def _make_client(s: dict, login: bool = False):
    """Build a spotipy client. Tests replace this function.
    login=True (setup: python -m jarvis.actions.spotify --login) waits for the browser login."""
    import spotipy
    from spotipy.cache_handler import CacheFileHandler

    cache = Path(os.path.expanduser(s["token_cache"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    handler = CacheFileHandler(cache_path=str(cache))
    if s["client_secret"]:
        from spotipy.oauth2 import SpotifyOAuth
        auth = SpotifyOAuth(client_id=s["client_id"], client_secret=s["client_secret"],
                            redirect_uri=s["redirect_uri"], scope=SCOPES, cache_handler=handler, open_browser=True)
    else:
        from spotipy.oauth2 import SpotifyPKCE
        auth = SpotifyPKCE(client_id=s["client_id"], redirect_uri=s["redirect_uri"], scope=SCOPES,
                           cache_handler=handler, open_browser=True)
    if not login and not auth.get_cached_token():
        _start_login(auth)
        raise NeedLogin("I opened your browser to log in to Spotify. Log in there, then ask me again.")
    return spotipy.Spotify(auth_manager=auth, requests_timeout=8, retries=1)


def _sp():
    global _client
    if _client is None:
        _client = _make_client(_settings())
    return _client


def reset() -> None:
    """Forget the cached client (tests, or after changing config)."""
    global _client
    _client = None


def _api_error(e: Exception) -> str:
    """Turn a spotipy error into a short spoken reply."""
    if isinstance(e, NeedLogin):
        return str(e)
    status = getattr(e, "http_status", None)
    reason = str(getattr(e, "reason", "") or "") + " " + str(getattr(e, "msg", "") or e)
    if status == 403 and "PREMIUM" in reason.upper():
        return NEED_PREMIUM
    if status == 404 and ("NO_ACTIVE_DEVICE" in reason.upper() or "device" in reason.lower()):
        return NO_DEVICE
    if status in (401,):
        return "Spotify login expired. Say it again and log in when the browser opens."
    if status == 403:
        return NEED_PREMIUM if "premium" in reason.lower() else "Spotify said I'm not allowed to do that."
    return SPOTIFY_ERROR


# ---------- small helpers ----------

def _open_uri(uri: str) -> None:
    """Open a spotify: URI in the Spotify app (Windows)."""
    if hasattr(os, "startfile"):
        os.startfile(uri)  # type: ignore[attr-defined]
    else:  # not Windows (tests / dev only)
        import webbrowser
        webbrowser.open(uri)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _clean_query(query: str) -> tuple[str, str]:
    """'the playlist chill vibes on spotify' -> ('chill vibes', 'playlist'). kind '' = not said."""
    q = (query or "").strip()
    q = re.sub(r"\s+(on|in|from|using|with)\s+spotify\s*$", "", q, flags=re.I)
    q = re.sub(r"^\s*(play|put on)\s+", "", q, flags=re.I)
    kind = ""
    m = re.match(r"^(?:the |my )?(song|track|playlist|artist|album)\s+(?:called |named )?(.+)$", q, flags=re.I)
    if m:
        kind = {"song": "track"}.get(m.group(1).lower(), m.group(1).lower())
        q = m.group(2)
    else:
        m = re.match(r"^(?:some(?:thing)?\s+(?:music\s+)?by|songs?\s+by|music\s+by)\s+(.+)$", q, flags=re.I)
        if m:
            kind, q = "artist", m.group(1)
        else:
            m = re.match(r"^(.+?)\s+(playlist|album)$", q, flags=re.I)
            if m:
                kind, q = m.group(2).lower(), m.group(1)
    return q.strip(" .'\""), kind


_LINK = re.compile(r"(?:spotify:|open\.spotify\.com/)(?:intl-[a-z]+/)?(track|playlist|album|artist)[:/]([A-Za-z0-9]+)")


def _link_uri(query: str) -> tuple[str, str] | None:
    """A Spotify link or URI in the query -> (kind, uri)."""
    m = _LINK.search(query or "")
    if not m:
        return None
    return m.group(1), f"spotify:{m.group(1)}:{m.group(2)}"


def _pick_device(sp) -> str | None:
    """Device id to play on: config name > active > this computer > first. None = no device."""
    want = _norm(_settings()["device"])
    try:
        devices = (sp.devices() or {}).get("devices") or []
    except Exception:
        return None
    if not devices:
        return None
    if want:
        for d in devices:
            if want in _norm(d.get("name", "")):
                return d.get("id")
    for d in devices:
        if d.get("is_active"):
            return d.get("id")
    for d in devices:
        if str(d.get("type", "")).lower() == "computer":
            return d.get("id")
    return devices[0].get("id")


def _device_or_open_app(sp) -> str | None:
    """Find a device; if none, open the Spotify app and wait up to ~8 s for it to show up."""
    dev = _pick_device(sp)
    if dev:
        return dev
    try:
        _open_uri("spotify:")
    except Exception:
        return None
    for _ in range(8):
        time.sleep(1)
        dev = _pick_device(sp)
        if dev:
            return dev
    return None


def _my_playlists(sp) -> list[dict]:
    out, offset = [], 0
    while offset < 200:  # enough for a voice command, avoids long loops
        page = sp.current_user_playlists(limit=50, offset=offset) or {}
        items = [p for p in (page.get("items") or []) if p]
        out.extend(items)
        if not page.get("next") or not items:
            break
        offset += 50
    return out


def _find_my_playlist(sp, name: str) -> dict | None:
    want = _norm(name)
    if not want:
        return None
    lists = _my_playlists(sp)
    for p in lists:  # exact first
        if _norm(p.get("name", "")) == want:
            return p
    for p in lists:  # then contains
        n = _norm(p.get("name", ""))
        if want in n or (n and n in want):
            return p
    return None


def _search_one(sp, query: str, kind: str) -> dict | None:
    res = sp.search(q=query, type=kind, limit=1) or {}
    items = [i for i in ((res.get(kind + "s") or {}).get("items") or []) if i]
    return items[0] if items else None


def _artists(item: dict) -> str:
    return ", ".join(a.get("name", "") for a in (item.get("artists") or [])[:2] if a.get("name"))


def _current_track(sp) -> dict | None:
    cur = sp.current_playback() or {}
    item = cur.get("item")
    if not item or cur.get("currently_playing_type") not in (None, "track"):
        return None
    return item


# ---------- actions ----------

def _play_without_keys(query: str, kind: str) -> str:
    if not query:
        try:
            _open_uri("spotify:")
        except Exception:
            return "I couldn't open Spotify. Is it installed?"
        return "Opened Spotify."
    link = _link_uri(query)
    uri = link[1] if link else "spotify:search:" + urllib.parse.quote(query)
    try:
        _open_uri(uri)
    except Exception:
        return "I couldn't open Spotify. Is it installed?"
    if link:
        return "Opened it in Spotify."
    return f"Opened search for {query} in Spotify. Pick one to play."


def play(args: dict) -> str:
    raw = str(args.get("query") or args.get("text") or "")
    query, said_kind = _clean_query(raw)
    kind = str(args.get("kind") or said_kind or "").lower()
    if kind == "song":
        kind = "track"
    mine_hint = bool(re.match(r"^\s*(?:play\s+)?my\s", raw, flags=re.I))
    if mine_hint:
        query = re.sub(r"^my\s+", "", query, flags=re.I)
    if not has_keys():
        return _play_without_keys(query, kind)
    try:
        sp = _sp()
        dev = _device_or_open_app(sp)
        if not dev:
            return NO_DEVICE
        if not query:
            sp.start_playback(device_id=dev)
            return "Playing Spotify."
        link = _link_uri(query)
        if link:
            k, uri = link
            if k == "track":
                sp.start_playback(device_id=dev, uris=[uri])
            else:
                sp.start_playback(device_id=dev, context_uri=uri)
            return "Playing it on Spotify."
        if _norm(query) in ("my liked songs", "liked songs", "my favorites", "my favourites", "favorites",
                            "favourites", "my saved songs", "saved songs"):
            saved = (sp.current_user_saved_tracks(limit=50) or {}).get("items") or []
            uris = [s["track"]["uri"] for s in saved if s and s.get("track") and s["track"].get("uri")]
            if not uris:
                return "You have no liked songs yet."
            sp.start_playback(device_id=dev, uris=uris)
            return "Playing your liked songs."
        if kind in ("", "playlist"):
            mine = _find_my_playlist(sp, query) if (kind == "playlist" or mine_hint) else None
            if mine:
                sp.start_playback(device_id=dev, context_uri=mine["uri"])
                return f"Playing your playlist {mine.get('name', query)}."
        kind = kind or "track"
        item = _search_one(sp, query, kind)
        if not item:
            return f"I couldn't find {query} on Spotify."
        name = item.get("name", query)
        if kind == "track":
            sp.start_playback(device_id=dev, uris=[item["uri"]])
            by = _artists(item)
            return f"Playing {name}" + (f" by {by}." if by else ".")
        sp.start_playback(device_id=dev, context_uri=item["uri"])
        if kind == "artist":
            return f"Playing {name} on Spotify."
        return f"Playing the {kind} {name}."
    except Exception as e:
        return _api_error(e)


def like(args: dict) -> str:
    if not has_keys():
        return NEED_SETUP
    try:
        sp = _sp()
        item = _current_track(sp)
        if not item:
            return "Nothing is playing on Spotify right now."
        sp.current_user_saved_tracks_add([item["id"]])
        return f"Liked {item.get('name', 'this song')}."
    except Exception as e:
        return _api_error(e)


def add_to_playlist(args: dict) -> str:
    name = str(args.get("playlist") or "").strip()
    name = re.sub(r"^(?:my\s+)?(?:playlist\s+)?", "", name, flags=re.I)
    name = re.sub(r"\s+playlist$", "", name, flags=re.I).strip()
    if not has_keys():
        return NEED_SETUP
    if not name:
        return "Which playlist should I add it to?"
    try:
        sp = _sp()
        item = _current_track(sp)
        if not item:
            return "Nothing is playing on Spotify right now."
        pl = _find_my_playlist(sp, name)
        if not pl:
            return f"I couldn't find a playlist called {name}."
        sp.playlist_add_items(pl["id"], [item["uri"]])
        return f"Added {item.get('name', 'this song')} to {pl.get('name', name)}."
    except Exception as e:
        return _api_error(e)


def _on_off(value, default: bool = True) -> bool:
    v = str(value if value is not None else "").strip().lower()
    if v in ("off", "false", "no", "0", "stop", "disable"):
        return False
    if v in ("on", "true", "yes", "1", "start", "enable"):
        return True
    return default


def shuffle(args: dict) -> str:
    if not has_keys():
        return NEED_SETUP
    on = _on_off(args.get("state"), True)
    try:
        sp = _sp()
        sp.shuffle(on, device_id=_pick_device(sp))
        return "Shuffle on." if on else "Shuffle off."
    except Exception as e:
        return _api_error(e)


_REPEAT = {"track": "track", "song": "track", "one": "track", "this song": "track",
           "context": "context", "on": "context", "all": "context", "playlist": "context", "album": "context",
           "off": "off", "stop": "off", "false": "off", "no": "off"}


def repeat(args: dict) -> str:
    if not has_keys():
        return NEED_SETUP
    mode = _REPEAT.get(str(args.get("state") or "track").strip().lower(), "track")
    try:
        sp = _sp()
        sp.repeat(mode, device_id=_pick_device(sp))
        return {"track": "Repeating this song.", "context": "Repeat on.", "off": "Repeat off."}[mode]
    except Exception as e:
        return _api_error(e)


def now_playing(args: dict) -> str:
    if not has_keys():
        try:  # reuse the Windows media info from piece G instead of duplicating it
            from . import audio
            return audio.now_playing({})
        except Exception:
            return "I can't tell what's playing."
    try:
        sp = _sp()
        cur = sp.current_playback() or {}
        item = cur.get("item")
        if not item:
            return "Nothing is playing on Spotify."
        name = item.get("name", "something")
        by = _artists(item) or (item.get("show") or {}).get("name", "")
        state = "Playing" if cur.get("is_playing") else "Paused on"
        return f"{state} {name}" + (f" by {by}." if by else ".")
    except Exception as e:
        return _api_error(e)


_ACTIONS = {"play": play, "like": like, "add_to_playlist": add_to_playlist,
            "shuffle": shuffle, "repeat": repeat, "now_playing": now_playing}


def spotify(args: dict) -> str:
    action = str(args.get("action") or "play").strip().lower()
    fn = _ACTIONS.get(action)
    if not fn:
        return "With Spotify I can play, like a song, add it to a playlist, shuffle, repeat, or tell you what's playing."
    return fn(args)


# ---------- wiring ----------

_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "spotify": {
        "description": ("Control the Spotify app: play a song, playlist, artist or album (action=play, query, kind); "
                        "like the current song; add the current song to one of the user's playlists (playlist); "
                        "shuffle on/off (state); repeat track|context|off (state); what's playing on Spotify. "
                        "Use this when the user says Spotify; for plain pause/next/previous use media."),
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "query": _STR,
            "kind": {"type": "string", "enum": list(KINDS)},
            "playlist": _STR,
            "state": _STR,
        },
        "required": ["action"],
    },
}
HANDLERS = {"spotify": spotify}


if __name__ == "__main__":  # one-time setup: python -m jarvis.actions.spotify --login
    import sys

    if "--login" in sys.argv:
        me = _make_client(_settings(), login=True).current_user()
        print("Logged in to Spotify as", (me or {}).get("display_name") or "you")
