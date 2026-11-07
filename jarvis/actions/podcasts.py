"""Piece AI: podcasts from RSS feeds.

Intent:
  podcast {action: play_latest|next|subscribe|unsubscribe|whats_new|list, name?}
    play_latest  - open the newest episode of <name> in the default player
    next         - open the episode after the last one played (of <name>, or of the last show played)
    subscribe    - find the feed with the iTunes search API and save it
    unsubscribe  - remove a saved show
    whats_new    - (info) new episodes since the last check, per show
    list         - (info) names of my shows

No extra packages: urllib + xml.etree + json only.
Config (all optional):
  podcasts: {"the daily": "https://feeds.example.com/daily.xml"}   # shows from config
  podcasts_file: "~/.jarvis/podcasts.json"                          # saved subscriptions + last played
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

TIMEOUT = 8
MAX_FEED_BYTES = 15 * 1024 * 1024
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"
ITUNES_URL = "https://itunes.apple.com/search?media=podcast&limit=5&term={q}"
DEFAULT_FILE = "~/.jarvis/podcasts.json"
NO_NET = "I can't reach the internet right now."


# ---------- config + saved state ----------

def _config() -> dict:
    try:
        from jarvis.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _state_path() -> Path:
    return Path(os.path.expanduser(str(_config().get("podcasts_file") or DEFAULT_FILE)))


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    for key in ("subs", "played", "seen"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    if not isinstance(data.get("last_show"), str):
        data["last_show"] = ""
    return data


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _norm(name: str) -> str:
    t = (name or "").lower().strip()
    t = re.sub(r"^(the )?(podcast|show)\s+", "", t)
    t = re.sub(r"\s+(podcast|show)$", "", t)
    t = re.sub(r"[^\w\s&'-]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _shows(state: dict) -> dict[str, str]:
    """All shows: config ones + saved subscriptions. name -> feed url."""
    out: dict[str, str] = {}
    cfg = _config().get("podcasts") or {}
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if k and v:
                out[_norm(str(k))] = str(v)
    for k, v in state["subs"].items():
        if k and v:
            out.setdefault(k, str(v))
    return out


def _find_show(name: str, shows: dict[str, str]) -> str | None:
    """Best matching saved show name, or None."""
    n = _norm(name)
    if not n:
        return None
    if n in shows:
        return n
    for key in shows:  # "daily" -> "the daily"
        if n in key or key in n:
            return key
    words = set(n.split())
    best, score = None, 0
    for key in shows:
        common = len(words & set(key.split()))
        if common > score:
            best, score = key, common
    return best


# ---------- network ----------

def is_web_link(url: str) -> bool:
    """Only http(s) links with a host. Feeds are written by strangers: a link to a file, a share
    (\\\\host\\x.exe), file:// or ms-msdt: must never be opened or fetched."""
    try:
        p = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return False
    return p.scheme.lower() in ("http", "https") and bool(p.hostname)


def _fetch(url: str) -> bytes:
    if not is_web_link(url):
        raise ValueError("not a web link")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(MAX_FEED_BYTES)


def _itunes_search(term: str) -> list[dict]:
    """[{name, feed}] from the iTunes search API."""
    raw = _fetch(ITUNES_URL.format(q=urllib.parse.quote(term)))
    data = json.loads(raw.decode("utf-8", "replace"))
    out = []
    for r in data.get("results") or []:
        feed = r.get("feedUrl")
        if feed and is_web_link(feed):
            out.append({"name": str(r.get("collectionName") or term), "feed": str(feed),
                        "author": str(r.get("artistName") or "")})
    return out


def _date_key(text: str) -> float:
    try:
        return parsedate_to_datetime(text).timestamp()
    except Exception:
        return 0.0


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Episodes newest first: [{title, url, id, date}]. Only items with an audio/video link."""
    root = ET.fromstring(xml_bytes)
    episodes = []
    for pos, item in enumerate(root.iter("item")):
        enc = item.find("enclosure")
        url = ((enc.get("url") if enc is not None else "") or "").strip()
        if not url or not is_web_link(url):
            continue  # only web links; never a file path or another protocol
        title = (item.findtext("title") or "").strip() or "Untitled episode"
        guid = (item.findtext("guid") or "").strip() or url
        date = (item.findtext("pubDate") or "").strip()
        episodes.append({"title": title, "url": url.strip(), "id": guid, "date": date,
                         "_ts": _date_key(date), "_pos": pos})
    # newest first; feeds are usually newest first already, so keep feed order when dates are missing
    episodes.sort(key=lambda e: (-e["_ts"], e["_pos"]))
    for e in episodes:
        e.pop("_ts"), e.pop("_pos")
    return episodes


def _episodes(feed_url: str) -> list[dict]:
    return parse_feed(_fetch(feed_url))


def _open(url: str) -> None:
    """Open the episode in the default media player (Windows) or the browser."""
    if not is_web_link(url):
        raise ValueError("not a web link")
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        import webbrowser
        webbrowser.open(url)


# ---------- actions ----------

def _play(state: dict, show: str, ep: dict) -> str:
    _open(ep["url"])
    state["played"][show] = ep["id"]
    state["last_show"] = show
    _save_state(state)
    return f"Playing {ep['title']} from {show}."


def _resolve(state: dict, name: str, allow_search: bool) -> tuple[str, str] | None:
    """(show name, feed url) from saved shows, else (optionally) an iTunes search."""
    shows = _shows(state)
    key = _find_show(name, shows)
    if key:
        return key, shows[key]
    if allow_search:
        found = _itunes_search(name)
        if found:
            return _norm(found[0]["name"]) or _norm(name), found[0]["feed"]
    return None


def play_latest(state: dict, name: str) -> str:
    if not name:
        name = state["last_show"]
        if not name:
            return "Which podcast should I play?"
    res = _resolve(state, name, allow_search=True)
    if not res:
        return f"I couldn't find a podcast called {name}."
    show, feed = res
    eps = _episodes(feed)
    if not eps:
        return f"I couldn't find any episodes of {show}."
    return _play(state, show, eps[0])


def next_episode(state: dict, name: str) -> str:
    name = name or state["last_show"]
    if not name:
        return "Play a podcast first, then say next episode."
    res = _resolve(state, name, allow_search=False)
    if not res:
        return f"{name} is not one of your podcasts. Say play the latest episode of {name}."
    show, feed = res
    eps = _episodes(feed)
    if not eps:
        return f"I couldn't find any episodes of {show}."
    last = state["played"].get(show)
    ids = [e["id"] for e in eps]
    if last not in ids:
        return _play(state, show, eps[0])
    i = ids.index(last)
    if i == 0:
        return f"You're up to date with {show}. No newer episode."
    return _play(state, show, eps[i - 1])  # list is newest first, so the next one is at i-1


def needs_confirm(args: dict) -> bool:
    return str((args or {}).get("action") or "").lower() == "subscribe" and bool(str(args.get("name") or "").strip())


def risky_text(args: dict) -> str | None:
    """'subscribe to <show> by <author>' (asks yes first). Pins the found feed in args, so "yes"
    saves exactly the show that was named. Never raises."""
    if not needs_confirm(args):
        return None
    name = str(args.get("name")).strip()
    if not (args.get("feed") and args.get("show")):
        try:
            found = _itunes_search(name)
        except Exception:
            found = []
        if not found:
            return f"subscribe to a podcast called {name}"
        args["feed"], args["show"] = found[0]["feed"], found[0]["name"]
        args["author"] = found[0].get("author") or ""
    by = f" by {args['author']}" if args.get("author") else ""
    return f"subscribe to {args['show']}{by}"


def subscribe(state: dict, name: str, args: dict | None = None) -> str:
    args = args or {}
    if not name:
        return "Which podcast should I subscribe to?"
    if args.get("confirm") is not True:
        return f"Are you sure you want to {risky_text({**args, 'name': name}) or 'subscribe'}? Say yes to confirm."
    if args.get("feed") and is_web_link(args["feed"]):
        found = [{"name": str(args.get("show") or name), "feed": str(args["feed"])}]
    else:
        found = _itunes_search(name)
    if not found:
        return f"I couldn't find a podcast called {name}."
    show, feed = _norm(found[0]["name"]) or _norm(name), found[0]["feed"]
    if show in _shows(state):
        return f"You're already subscribed to {show}."
    state["subs"][show] = feed
    try:
        eps = _episodes(feed)
        if eps:
            state["seen"][show] = eps[0]["id"]  # count new episodes from now on
    except Exception:
        pass
    _save_state(state)
    return f"Subscribed to {show}."


def unsubscribe(state: dict, name: str) -> str:
    if not name:
        return "Which podcast should I remove?"
    key = _find_show(name, dict(state["subs"]))
    if key:
        state["subs"].pop(key, None)
        for part in ("played", "seen"):
            state[part].pop(key, None)
        if state["last_show"] == key:
            state["last_show"] = ""
        _save_state(state)
        return f"Unsubscribed from {key}."
    cfg_key = _find_show(name, _shows(state))
    if cfg_key:
        return f"{cfg_key} is in config.yaml under podcasts. Remove it there."
    return f"You're not subscribed to {name}."


def whats_new(state: dict) -> str:
    shows = _shows(state)
    if not shows:
        return "You have no podcasts yet. Say subscribe to, and a podcast name."
    lines, failed = [], 0
    for show, feed in shows.items():
        try:
            eps = _episodes(feed)
        except Exception:
            failed += 1
            continue
        if not eps:
            continue
        seen = state["seen"].get(show)
        ids = [e["id"] for e in eps]
        new = ids.index(seen) if seen in ids else (0 if seen else 1)
        if new:
            word = "episode" if new == 1 else "episodes"
            lines.append(f"{show}: {new} new {word}, latest is {eps[0]['title']}")
        state["seen"][show] = eps[0]["id"]
    _save_state(state)
    if failed == len(shows):
        return NO_NET
    if not lines:
        return "No new podcast episodes."
    return ". ".join(lines) + "."


def list_shows(state: dict) -> str:
    shows = sorted(_shows(state))
    if not shows:
        return "You have no podcasts yet. Say subscribe to, and a podcast name."
    return "Your podcasts: " + ", ".join(shows) + "."


def podcast(args: dict) -> str:
    action = str(args.get("action") or "play_latest").lower()
    name = str(args.get("name") or "").strip()
    state = _load_state()
    try:
        if action in ("play_latest", "play", "latest"):
            return play_latest(state, name)
        if action == "next":
            return next_episode(state, name)
        if action == "subscribe":
            return subscribe(state, name, args)
        if action == "unsubscribe":
            return unsubscribe(state, name)
        if action == "whats_new":
            return whats_new(state)
        if action == "list":
            return list_shows(state)
    except ET.ParseError:
        return "That podcast feed looks broken."
    except OSError:  # URLError, timeouts, file errors
        return NO_NET
    except ValueError:  # bad JSON from the search API
        return "The podcast search gave a bad answer. Try again later."
    return "I can play the latest episode, the next episode, subscribe, unsubscribe, list, or tell you what's new."


# ---------- wiring ----------

CATALOG: dict[str, dict] = {
    "podcast": {
        "description": ("Podcasts from RSS: play the latest episode of a show, play the next episode, "
                        "subscribe/unsubscribe (finds the feed by name), list shows, or what's new."),
        "properties": {
            "action": {"type": "string",
                       "enum": ["play_latest", "next", "subscribe", "unsubscribe", "whats_new", "list"]},
            "name": {"type": "string"},
        },
        "required": ["action"],
    },
}
HANDLERS = {"podcast": podcast}
