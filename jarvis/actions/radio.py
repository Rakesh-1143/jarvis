"""Piece BG: internet radio from radio-browser.info.

Intent:
  radio {action: play|next|stop|save|favourite|list, query?, country?}
    play       - search stations by name, then by tag ("jazz"), play the most popular one
    next       - play the next station from the last search
    stop       - stop the radio that Jarvis started in VLC
    save       - save the station that is playing to favourites
    favourite  - play a favourite (by name, or the first one)
    list       - (info) names of my favourite stations

Plays in VLC when found (config `vlc_path`, PATH, or the usual install folders), so "stop" works.
Without VLC the stream opens in the default player/browser (then "stop" cannot close it).
No extra packages: urllib + json + subprocess only.
Config (all optional):
  vlc_path: "C:/Program Files/VideoLAN/VLC/vlc.exe"
  radio_file: "~/.jarvis/radio.json"      # favourites + last station
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 8
LIMIT = 5
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"
# radio-browser.info mirrors; tried in order until one answers
HOSTS = ["https://de1.api.radio-browser.info", "https://de2.api.radio-browser.info",
         "https://fi1.api.radio-browser.info", "https://all.api.radio-browser.info"]
DEFAULT_FILE = "~/.jarvis/radio.json"
VLC_PLACES = [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]
NO_NET = "I can't reach the radio directory right now."
_FILLER = {"some", "a", "the", "radio", "station", "stations", "fm", "music", "channel", "live", "online",
           "please", "me", "play", "my", "favourite", "favorite"}

# this session only: last search results and the VLC process we started
_SESSION: dict = {"results": [], "index": -1, "query": "", "country": "", "proc": None}


# ---------- config + saved state ----------

def _config() -> dict:
    try:
        from jarvis.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _state_path() -> Path:
    return Path(os.path.expanduser(str(_config().get("radio_file") or DEFAULT_FILE)))


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    favs = data.get("favourites")
    data["favourites"] = [f for f in favs if _valid(f)] if isinstance(favs, list) else []
    if not _valid(data.get("last")):
        data["last"] = None
    return data


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _valid(st) -> bool:
    return isinstance(st, dict) and bool(st.get("name")) and is_web_link(st.get("url"))


def _norm(text: str) -> str:
    t = re.sub(r"[^\w\s&'.-]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _strip_filler(query: str) -> str:
    return " ".join(w for w in _norm(query).split() if w not in _FILLER)


# ---------- network ----------

def is_web_link(url) -> bool:
    """Only http(s) links with a host. Station data is written by strangers: never open a file path,
    a share or another protocol."""
    try:
        p = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return False
    return p.scheme.lower() in ("http", "https") and bool(p.hostname)


def _get_json(path: str, params: dict):
    """GET from the first radio-browser mirror that answers."""
    query = urllib.parse.urlencode(params)
    last_err: Exception = OSError("no mirror")
    for host in HOSTS:
        req = urllib.request.Request(f"{host}{path}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read(2 * 1024 * 1024).decode("utf-8", "replace"))
        except OSError as e:  # URLError, timeout: try the next mirror
            last_err = e
    raise last_err


def _clean(raw: list) -> list[dict]:
    out, seen = [], set()
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        url = str(s.get("url_resolved") or s.get("url") or "").strip()
        name = re.sub(r"\s+", " ", str(s.get("name") or "")).strip()
        if not name or not is_web_link(url) or url in seen:
            continue
        seen.add(url)
        out.append({"name": name[:80], "url": url, "uuid": str(s.get("stationuuid") or ""),
                    "country": str(s.get("country") or "")})
    return out


def search(query: str, country: str = "") -> list[dict]:
    """Stations for a spoken query: by name, then by tag, then by the name without filler words."""
    base = {"limit": LIMIT, "hidebroken": "true", "order": "clickcount", "reverse": "true"}
    if country:
        base["country"] = country
    q, short = _norm(query), _strip_filler(query)
    tries = []
    if q:
        tries.append({"name": q})
    if short:
        tries += [{"tag": short}, {"name": short}]
    if not tries and country:
        tries.append({})  # "play radio from india": most popular in that country
    for extra in tries:
        found = _clean(_get_json("/json/stations/search", {**base, **extra}))
        if found:
            return found
    return []


# ---------- player ----------

def find_vlc() -> str | None:
    cfg = str(_config().get("vlc_path") or "").strip()
    if cfg and os.path.isfile(os.path.expanduser(cfg)):
        return os.path.expanduser(cfg)
    found = shutil.which("vlc")
    if found:
        return found
    if sys.platform == "win32":
        for p in VLC_PLACES:
            if os.path.isfile(p):
                return p
    return None


def _stop_proc() -> bool:
    proc = _SESSION.get("proc")
    _SESSION["proc"] = None
    if proc is None or proc.poll() is not None:
        return False
    try:
        proc.terminate()
    except Exception:
        return False
    return True


def _open(url: str) -> bool:
    """Start the stream. True if Jarvis owns the player (VLC), so it can stop it later."""
    if not is_web_link(url):
        raise ValueError("not a web link")
    _stop_proc()
    vlc = find_vlc()
    if vlc:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        _SESSION["proc"] = subprocess.Popen([vlc, "--qt-start-minimized", "--no-video", url],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        import webbrowser
        webbrowser.open(url)
    return False


def _play_station(state: dict, st: dict) -> str:
    own = _open(st["url"])
    state["last"] = {k: st.get(k, "") for k in ("name", "url", "uuid")}
    _save_state(state)
    tip = "" if own else " Install VLC so I can stop it for you."
    return f"Playing {st['name']}.{tip}"


def stop_all() -> None:
    """Optional exit hook: stop the radio when Jarvis closes."""
    _stop_proc()


# ---------- actions ----------

def play(state: dict, query: str, country: str = "") -> str:
    if not query and not country:
        if state["favourites"]:
            return favourite(state, "")
        return "Which station or kind of music should I play?"
    found = search(query, country)
    if not found:
        return f"I couldn't find a radio station for {query or country}."
    _SESSION.update(results=found, index=0, query=query, country=country)
    return _play_station(state, found[0])


def next_station(state: dict) -> str:
    results = _SESSION["results"]
    if not results:
        favs = state["favourites"]
        last = state["last"]
        if len(favs) > 1:  # no search yet: walk the favourites
            urls = [f["url"] for f in favs]
            i = urls.index(last["url"]) + 1 if last and last["url"] in urls else 0
            return _play_station(state, favs[i % len(favs)])
        return "Play a station first, then say next station."
    i = _SESSION["index"] + 1
    if i >= len(results):
        i = 0
        if len(results) == 1:
            return f"{results[0]['name']} is the only station I found."
    _SESSION["index"] = i
    return _play_station(state, results[i])


def stop() -> str:
    if _stop_proc():
        return "Radio stopped."
    return "I didn't start a radio player. Say pause to pause what's playing."


def save(state: dict) -> str:
    cur = state["last"]
    if not cur:
        return "Play a station first, then say save this station."
    if any(f["url"] == cur["url"] for f in state["favourites"]):
        return f"{cur['name']} is already in your favourites."
    state["favourites"].append(dict(cur))
    _save_state(state)
    return f"Saved {cur['name']} to your favourite stations."


def _match_fav(favs: list[dict], query: str) -> dict | None:
    q = _norm(query)
    short = _strip_filler(query)
    for f in favs:
        if _norm(f["name"]) == q:
            return f
    for key in (q, short):
        if key:
            for f in favs:
                n = _norm(f["name"])
                if key in n or n in key:
                    return f
    words = set(short.split())
    best, score = None, 0
    for f in favs:
        common = len(words & set(_norm(f["name"]).split()))
        if common > score:
            best, score = f, common
    return best


def favourite(state: dict, query: str) -> str:
    favs = state["favourites"]
    if not favs:
        return "You have no favourite stations yet. Play one and say save this station."
    st = _match_fav(favs, query) if _strip_filler(query) else favs[0]
    if not st:
        return f"{query} is not in your favourite stations."
    _SESSION.update(results=[], index=-1)  # "next" now walks the favourites
    return _play_station(state, st)


def list_favs(state: dict) -> str:
    favs = state["favourites"]
    if not favs:
        return "You have no favourite stations yet. Play one and say save this station."
    return "Your stations: " + ", ".join(f["name"] for f in favs) + "."


def radio(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "play").lower()
    query = str(args.get("query") or "").strip()
    country = str(args.get("country") or "").strip()
    try:
        if action == "stop":
            return stop()
        state = _load_state()
        if action == "play":
            return play(state, query, country)
        if action == "next":
            return next_station(state)
        if action == "save":
            return save(state)
        if action in ("favourite", "favorite"):
            return favourite(state, query)
        if action == "list":
            return list_favs(state)
    except OSError:  # URLError, timeouts, player could not start
        return NO_NET if action == "play" else "I couldn't start the radio."
    except ValueError:  # bad JSON or a bad stream link
        return "The radio directory gave a bad answer. Try again later."
    return "I can play a station, next station, stop, save this station, or play a favourite."


# ---------- wiring ----------

CATALOG: dict[str, dict] = {
    "radio": {
        "description": ("Internet radio: play a station by name or music style (e.g. 'Radio Mirchi', 'jazz'), "
                        "next station, stop the radio, save this station, play a favourite station, "
                        "or list favourite stations."),
        "properties": {
            "action": {"type": "string", "enum": ["play", "next", "stop", "save", "favourite", "list"]},
            "query": {"type": "string", "description": "station name or music style"},
            "country": {"type": "string", "description": "optional country name, e.g. India"},
        },
        "required": ["action"],
    },
}
HANDLERS = {"radio": radio}
