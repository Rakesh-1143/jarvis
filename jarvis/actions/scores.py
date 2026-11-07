"""Piece AO: live cricket and football scores from free public feeds (no key).

Intent:
  scores {sport?: cricket|football, team?, league?}   (info)

Sources (both free, no key; they may change, so every error fails softly):
  cricket  - ESPNcricinfo live scores RSS: item titles like "India 245/3 * v Australia 180"
  football - ESPN public scoreboard JSON: site.api.espn.com/apis/site/v2/sports/soccer/<league>/scoreboard

Score text comes from the web: it is UNTRUSTED outside text. It is cleaned (safe characters only,
short length) before it is spoken or handed to the AI.

Optional config (defaults work without it):
  scores:
    teams: ["India", "Arsenal"]          # favourites, used when no team is said
    football_leagues: ["eng.1", "uefa.champions", "esp.1"]
    cricket_url: "https://static.cricinfo.com/rss/livescores.xml"
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TIMEOUT = 6
MAX_BYTES = 512_000
MAX_MATCHES = 4
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"
CRICKET_URL = "https://static.cricinfo.com/rss/livescores.xml"
FOOTBALL_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
DEFAULT_LEAGUES = ["eng.1", "uefa.champions", "esp.1", "ind.1"]

FAIL = "I couldn't get live {sport} scores right now. Try asking me to search the web."

# spoken league names -> ESPN league codes
LEAGUES = {
    "premier league": "eng.1", "epl": "eng.1", "english premier league": "eng.1",
    "championship": "eng.2", "fa cup": "eng.fa",
    "la liga": "esp.1", "laliga": "esp.1", "spanish league": "esp.1",
    "serie a": "ita.1", "italian league": "ita.1",
    "bundesliga": "ger.1", "german league": "ger.1",
    "ligue 1": "fra.1", "french league": "fra.1",
    "champions league": "uefa.champions", "ucl": "uefa.champions",
    "europa league": "uefa.europa",
    "mls": "usa.1", "isl": "ind.1", "indian super league": "ind.1",
    "world cup": "fifa.world",
}
_LEAGUE_NAMES = {
    "eng.1": "Premier League", "eng.2": "Championship", "eng.fa": "FA Cup", "esp.1": "La Liga",
    "ita.1": "Serie A", "ger.1": "Bundesliga", "fra.1": "Ligue 1", "uefa.champions": "Champions League",
    "uefa.europa": "Europa League", "usa.1": "MLS", "ind.1": "Indian Super League", "fifa.world": "World Cup",
}
# words that mean "any cricket match" rather than a team name
_CRICKET_ANY = {"cricket", "ipl", "test", "odi", "t20", "t20i", "live", "match", "matches", "score", "scores"}
_FOOTBALL_HINTS = {"football", "soccer", "fc", "united", "city", "arsenal", "chelsea", "liverpool",
                   "madrid", "barcelona", "barca", "bayern", "juventus", "milan", "inter", "psg",
                   "tottenham", "spurs", "everton", "villa", "newcastle", "dortmund", "atletico"}
_CRICKET_HINTS = {"cricket", "ipl", "test", "odi", "t20", "t20i", "india", "australia", "england",
                  "pakistan", "sri lanka", "bangladesh", "new zealand", "south africa", "west indies",
                  "afghanistan", "zimbabwe", "ireland", "csk", "rcb", "mi", "kkr", "srh", "dc", "rr",
                  "pbks", "lsg", "gt", "chennai super kings", "royal challengers", "mumbai indians"}


# ---------- helpers ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("scores") or {}
    except Exception:
        cfg = {}
    teams = cfg.get("teams") or []
    if isinstance(teams, str):
        teams = [teams]
    leagues = cfg.get("football_leagues") or DEFAULT_LEAGUES
    if isinstance(leagues, str):
        leagues = [leagues]
    return {"teams": [str(t) for t in teams if str(t).strip()],
            "football_leagues": [str(l) for l in leagues],
            "cricket_url": str(cfg.get("cricket_url") or CRICKET_URL)}


def _fetch(url: str) -> bytes:
    """Raw bytes (capped). Network errors raise."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(MAX_BYTES)


def _clean(text, limit: int = 80) -> str:
    """Untrusted web text -> short, safe, speakable text."""
    t = re.sub(r"<[^>]*>", " ", str(text or ""))  # drop any tags
    t = re.sub(r"[^\w\s/*.,:()'&+-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip()


def _norm(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text or "").lower())).strip()


def _has_word(haystack: str, needle: str) -> bool:
    n = _norm(needle)
    return bool(n) and re.search(rf"\b{re.escape(n)}\b", _norm(haystack)) is not None


def _clean_team(team) -> str:
    """'the India score' -> 'india'. Empty when the words only mean 'any match'."""
    t = _norm(team)
    t = re.sub(r"\b(what s|whats|what is|the|live|latest|current|score|scores|match|matches|game|games|"
               r"result|results|today|tonight|now|of|for|in)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return "" if t in _CRICKET_ANY or t in ("football", "soccer") else t


def _league_from(text: str) -> str:
    n = _norm(text)
    for name in sorted(LEAGUES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", n):
            return LEAGUES[name]
    return ""


def _guess_sport(text: str) -> str:
    n = _norm(text)
    if _league_from(n) or any(re.search(rf"\b{re.escape(h)}\b", n) for h in _FOOTBALL_HINTS):
        return "football"
    if any(re.search(rf"\b{re.escape(h)}\b", n) for h in _CRICKET_HINTS):
        return "cricket"
    return ""


# ---------- cricket ----------

def cricket_matches(url: str = CRICKET_URL) -> list[str]:
    """List of match lines from the cricinfo RSS. Raises on network/parse error."""
    raw = _fetch(url)
    if b"<!DOCTYPE" in raw[:2000].upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unexpected feed")  # never parse entity tricks
    root = ET.fromstring(raw)
    out: list[str] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or item.findtext("description") or "")
        if title and title not in out:
            out.append(title)
    return out


def _say_cricket(line: str) -> str:
    # "India 245/3 * v Australia 180" -> "India 245 for 3, batting, versus Australia 180"
    s = re.sub(r"(\d+)/(\d+)", r"\1 for \2", line)
    s = s.replace(" * ", ", batting, ").replace(" *", " batting")
    return re.sub(r"\bv\b", "versus", s)


def cricket(team: str, s: dict) -> str:
    try:
        matches = cricket_matches(s["cricket_url"])
    except Exception:
        return FAIL.format(sport="cricket")
    if not matches:
        return "There are no live cricket matches right now."
    wanted = [team] if team else s["teams"]
    if wanted:
        hits = [m for m in matches if any(_has_word(m, w) for w in wanted)]
        if hits:
            return ". ".join(_say_cricket(m) for m in hits[:MAX_MATCHES]) + "."
        if team:
            return f"I don't see a live cricket match for {_clean(team, 40).title()} right now."
    return "Live cricket: " + ". ".join(_say_cricket(m) for m in matches[:MAX_MATCHES]) + "."


# ---------- football ----------

def football_matches(league: str) -> list[dict]:
    """[{home, away, home_score, away_score, state, detail}] for one league. Raises on error."""
    if not re.fullmatch(r"[a-z0-9_.]{2,30}", league or ""):
        raise ValueError("bad league")
    data = json.loads(_fetch(FOOTBALL_URL.format(league=urllib.parse.quote(league))).decode("utf-8"))
    out: list[dict] = []
    for ev in (data or {}).get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
        home, away = teams.get("home"), teams.get("away")
        if not home or not away:
            continue
        status = (ev.get("status") or comp.get("status") or {}).get("type") or {}
        out.append({
            "home": _clean((home.get("team") or {}).get("displayName"), 40),
            "away": _clean((away.get("team") or {}).get("displayName"), 40),
            "home_score": _clean(home.get("score"), 4), "away_score": _clean(away.get("score"), 4),
            "state": _clean(status.get("state"), 10).lower(),  # pre | in | post
            "detail": _clean(status.get("shortDetail") or status.get("detail"), 40),
        })
    return out


def _say_football(m: dict) -> str:
    if m["state"] == "pre":
        return f"{m['home']} versus {m['away']}, not started" + (f", {m['detail']}" if m["detail"] else "")
    line = f"{m['home']} {m['home_score'] or 0}, {m['away']} {m['away_score'] or 0}"
    if m["state"] == "post":
        return line + ", full time"
    return line + (f", {m['detail']}" if m["detail"] else ", live")


def _rank(m: dict) -> int:
    return {"in": 0, "post": 1, "pre": 2}.get(m["state"], 3)


def football(team: str, league: str, s: dict) -> str:
    leagues = [league] if league else s["football_leagues"]
    wanted = [team] if team else s["teams"]
    found: list[dict] = []
    first_all: list[dict] = []
    errors = 0
    for lg in leagues:
        try:
            ms = football_matches(lg)
        except Exception:
            errors += 1
            continue
        if not first_all and ms:
            first_all = ms
        if wanted:
            found += [m for m in ms if any(_has_word(m["home"] + " " + m["away"], w) for w in wanted)]
            if team and found:
                break
    if errors == len(leagues):
        return FAIL.format(sport="football")
    if found:
        found.sort(key=_rank)
        return ". ".join(_say_football(m) for m in found[:MAX_MATCHES]) + "."
    if team:
        return f"I don't see a {_clean(team, 40).title()} match today."
    ms = first_all
    if not ms:
        name = _LEAGUE_NAMES.get(league, "football") if league else "football"
        return f"There are no {name} matches today."
    ms = sorted(ms, key=_rank)
    head = _LEAGUE_NAMES.get(league or leagues[0], "Football")
    return f"{head}: " + ". ".join(_say_football(m) for m in ms[:MAX_MATCHES]) + "."


# ---------- intent ----------

def scores(args: dict) -> str:
    text = str(args.get("text") or "")
    raw_team = str(args.get("team") or "")
    league_arg = str(args.get("league") or "")
    league = LEAGUES.get(_norm(league_arg)) or (league_arg if league_arg in _LEAGUE_NAMES else "") \
        or _league_from(raw_team) or _league_from(text)
    team = _clean_team(raw_team)
    if league and team and _league_from(team):
        team = ""  # "premier league" was the league, not a team
    sport = _norm(args.get("sport"))
    if sport in ("soccer",):
        sport = "football"
    if sport not in ("cricket", "football"):
        sport = "football" if league else (_guess_sport(f"{raw_team} {text}") or "")
    s = _settings()
    if not sport:
        if team:
            sport = "cricket"  # most asks ("India score") are cricket; football teams have hints above
        else:
            fav = " ".join(s["teams"])
            sport = _guess_sport(fav) or "cricket"
    if sport == "football":
        return football(team, league, s)
    return cricket(team, s)


# ---------- wiring ----------

_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "scores": {
        "description": "Live cricket or football (soccer) scores from free sports feeds. "
                       "Leave team out for all live matches or the user's favourite teams.",
        "properties": {
            "sport": {"type": "string", "enum": ["cricket", "football"]},
            "team": _STR,
            "league": {"type": "string", "description": "Football league, e.g. premier league, la liga, champions league."},
        },
        "required": [], "info": True,
    },
}
HANDLERS = {"scores": scores}
