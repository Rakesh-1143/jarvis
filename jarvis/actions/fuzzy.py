"""Fuzzy name matching for spoken names (piece AT). No intents.

Speech-to-text often mishears names: "note pad", "spotty fly", "crome", "my mum".
Use this only when an exact lookup fails:

    key = fuzzy.app("crome", APP_PATHS)          # -> "chrome"
    key = fuzzy.contact("my mum", contacts)       # -> "mum" key from config, or None
    key = fuzzy.folder("down loads")              # -> "downloads"

Every helper returns the ORIGINAL key from the choices (so the caller can do
`choices[key]`), or None when nothing is close enough or two different things
are equally close (never guess between two contacts).

Uses `rapidfuzz` when installed (fast), else Python's `difflib` (same scores, close enough).
Smart-home devices are NOT matched here: smarthome.py has its own matching.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping

try:  # optional, faster
    from rapidfuzz import fuzz as _rf
except ImportError:  # pragma: no cover - depends on install
    _rf = None

DEFAULT_CUTOFF = 80  # 0-100. Lower = more forgiving, more wrong guesses.
MARGIN = 5  # if two different answers score within this, it is a tie -> None
MIN_FUZZY_LEN = 4  # names shorter than this must match exactly ("tom" must not become "mom")

# Common speech-to-text slips: heard words -> meant words. Whole words, lower case.
SLIPS: dict[str, str] = {
    "note pad": "notepad",
    "notes pad": "notepad",
    "spotty fly": "spotify",
    "spot if i": "spotify",
    "spot ify": "spotify",
    "spotty phi": "spotify",
    "crome": "chrome",
    "chrom": "chrome",
    "krome": "chrome",
    "fire fox": "firefox",
    "power point": "powerpoint",
    "out look": "outlook",
    "you tube": "youtube",
    "what's app": "whatsapp",
    "whats app": "whatsapp",
    "what sap": "whatsapp",
    "v s code": "vs code",
    "vs cold": "vs code",
    "vs coat": "vs code",
    "vias code": "vs code",
    "calculater": "calculator",
    "calculate her": "calculator",
    "explore her": "explorer",
    "file explore": "file explorer",
    "task manger": "task manager",
    "command prom": "command prompt",
    "power shell": "powershell",
    "down loads": "downloads",
    "down load": "downloads",
    "desk top": "desktop",
    "my pictures": "pictures",
    "net flicks": "netflix",
    "linked in": "linkedin",
    "git hub": "github",
    "chat gpt": "chatgpt",
    "chat g p t": "chatgpt",
}

_FILLER = re.compile(r"\b(the|my|a|an|please|app|application|program)\b")


def normalize(text) -> str:
    """Lower case, no punctuation, no filler words ("the", "my", "app"), single spaces."""
    t = str(text or "").lower().replace("_", " ").replace("-", " ")
    t = re.sub(r"[^a-z0-9' ]+", " ", t).replace("'", "")
    t = _FILLER.sub(" ", t)
    return " ".join(t.split())


_SLIP_RES = None


def fix_slips(text: str) -> str:
    """Replace known mishearings, whole words only: "open note pad" -> "open notepad"."""
    global _SLIP_RES
    if _SLIP_RES is None:
        keys = sorted(SLIPS, key=len, reverse=True)  # longest first
        _SLIP_RES = [(re.compile(rf"(?<![a-z0-9']){re.escape(k)}(?![a-z0-9'])"), SLIPS[k]) for k in keys]
    t = " ".join(str(text or "").lower().split())
    for rx, good in _SLIP_RES:
        t = rx.sub(good, t)
    return t


def _ratio(a: str, b: str) -> float:
    if _rf is not None:
        return float(_rf.ratio(a, b))
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


def score(heard: str, choice: str) -> float:
    """0-100 how close two names are. Ignores case, filler words, spaces and word order."""
    a, b = normalize(fix_slips(heard)), normalize(fix_slips(choice))
    if not a or not b:
        return 0.0
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return 100.0
    if min(len(a.replace(" ", "")), len(b.replace(" ", ""))) < MIN_FUZZY_LEN:
        return 0.0  # too short to guess safely
    wa, wb = set(a.split()), set(b.split())
    if wa != wb and (wa < wb or wb < wa):
        # "visual studio" vs "visual studio code", "priya" vs "priya sharma": one name has
        # extra whole words, so they are often different things. Never above the cutoff.
        return min(DEFAULT_CUTOFF - 1, _ratio(a, b))
    return max(
        _ratio(a, b),
        _ratio(a.replace(" ", ""), b.replace(" ", "")),  # "note pad" vs "notepad"
        _ratio(" ".join(sorted(a.split())), " ".join(sorted(b.split()))),  # word order
    )


def matches(name: str, choices: Iterable[str] | Mapping, cutoff: float = DEFAULT_CUTOFF,
            limit: int = 3) -> list[tuple[str, float]]:
    """Closest choices as (choice, score), best first. For "did you mean X or Y?"."""
    scored = [(c, score(name, str(c))) for c in choices]
    scored = [x for x in scored if x[1] >= cutoff]
    scored.sort(key=lambda x: (-x[1], len(str(x[0]))))
    return scored[:limit]


def best(name: str, choices: Iterable[str] | Mapping, cutoff: float = DEFAULT_CUTOFF) -> str | None:
    """The one closest choice, or None.

    `choices` can be a list of names or a dict {name: value}. With a dict, two names with
    the SAME value are not a tie ("chrome" and "google chrome" both open chrome.exe).
    """
    if not name or not choices:
        return None
    top = matches(name, choices, cutoff, limit=10)
    if not top:
        return None
    first, s1 = top[0]
    values = choices if isinstance(choices, Mapping) else None
    for other, s2 in top[1:]:
        if s1 - s2 >= MARGIN:
            break
        same = values is not None and values.get(other) == values.get(first)
        if not same and s1 < 100:
            return None  # two different things almost equally close: don't guess
    return first


# ---------- helpers for each kind of lookup ----------
def app(name: str, apps: Mapping | Iterable[str] | None = None, cutoff: float = DEFAULT_CUTOFF) -> str | None:
    """Closest app (or website) key. Default list: apps.APP_PATHS + apps.WEBSITES."""
    if apps is None:
        from . import apps as _apps

        apps = {**_apps.WEBSITES, **_apps.APP_PATHS}
    return best(name, apps, cutoff)


def contact(name: str, contacts: Mapping | Iterable[str] | None, cutoff: float = 85) -> str | None:
    """Closest saved contact key from config.yaml `contacts`. Stricter cutoff: a wrong person is worse."""
    if not contacts:
        return None
    if isinstance(contacts, Mapping):
        contacts = {str(k): str(k) for k in contacts}  # every person is different: ties stay ties
    return best(name, contacts, cutoff)


def folder(name: str, names: Mapping | Iterable[str] | None = None, cutoff: float = DEFAULT_CUTOFF) -> str | None:
    """Closest known folder name ("down loads" -> "downloads"). Default list: fileops known folders."""
    if names is None:
        from . import fileops

        names = fileops._FOLDERS
    n = re.sub(r"\bfolders?\b", " ", str(name or "").lower())
    return best(n, names, cutoff)
