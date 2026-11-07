"""Fix words Jarvis mishears (piece AS).

    "you misheard" / "that was wrong"                     -> save the last command to misheard.jsonl
    "when you hear note pad I mean notepad"               -> save a word fix
    "when I say chrome I mean google chrome"              -> save a word fix
    "list corrections" / "remove the correction note pad" -> list / remove fixes

Word fixes live in a JSON file (config `corrections_file`, default ~/.jarvis/corrections.json):
    {"note pad": "notepad", "chrome": "google chrome"}
main.py runs `text = corrections.apply(text)` right after listening, before the NLU.

"The last command" comes from history.py (piece AF). This module keeps no command log of its own;
misheard.jsonl only holds the commands the user said were wrong (for later tuning).
Different from teach.py: teach = phrase -> actions; corrections = misheard words -> right words.

Public:
    apply(text) -> str                 whole-word, case-insensitive fixes (never raises)
    parse(text) -> (intent, args)|None helper for nlu: misheard / correction / corrections
    misheard(args), correction(args), corrections(args) -> str   handlers
    CATALOG, HANDLERS                  merged by actions/__init__.py
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Callable

DEFAULT_FILE = "~/.jarvis/corrections.json"
DEFAULT_MISHEARD_FILE = "~/.jarvis/misheard.jsonl"
MAX_FIXES = 200
MAX_WORDS = 6        # a fix is for a few misheard words, not whole sentences
MAX_CHARS = 60
SAY_MAX = 10         # how many fixes "list corrections" speaks

_lock = threading.Lock()
# Last few (raw, fixed) texts from apply(), so "you misheard" can save what was really heard.
_recent: deque = deque(maxlen=5)

# Words that must keep their normal meaning (yes/no answers, stop/exit, the wake word).
_RESERVED = {
    "jarvis", "hey jarvis", "yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "do it",
    "no", "nope", "cancel", "stop", "never mind", "goodbye", "exit", "quit", "exit jarvis",
    "quit jarvis", "start listening", "stop listening", "help",
}
_OWN_INTENTS = {"misheard", "correction", "corrections"}


def _now() -> _dt.datetime:
    return _dt.datetime.now()


def _norm(text) -> str:
    """Lower case, no punctuation (keeps ' and -), single spaces."""
    t = re.sub(r"[^\w\s'-]", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", t).strip(" '-")


# ---------- storage ----------
def _cfg() -> dict:
    try:
        from jarvis.config import load_config

        return load_config() or {}
    except Exception:
        return {}


def _path() -> Path:
    return Path(os.path.expanduser(str(_cfg().get("corrections_file") or DEFAULT_FILE)))


def _misheard_path() -> Path:
    return Path(os.path.expanduser(str(_cfg().get("misheard_file") or DEFAULT_MISHEARD_FILE)))


def _load() -> dict[str, str]:
    """{heard: meant}; a bad or missing file gives {}."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for heard, meant in data.items():
            h, m = _norm(heard), " ".join(str(meant or "").split())
            if h and m and h != _norm(m):
                out[h] = m
    return out


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # never leave a half-written file


# ---------- parsing helpers (for the nlu wiring) ----------
_PREFIX = r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis\s*,?\s+)?(?:please\s+)?"
_Q = r"[\"'“”‘’]?"
_CORRECTION_RE = re.compile(
    _PREFIX + r"(?:(?:remember|learn|note)\s+(?:that\s+)?)?"
    r"(?:when(?:ever)?|if)\s+(?:you\s+hear|i\s+say)\s+" + _Q + r"(.+?)" + _Q +
    r"\s*,?\s+(?:i\s+(?:mean|meant|said)|it\s+means|that\s+means|you\s+should\s+hear)\s+" + _Q + r"(.+?)" + _Q + r"[.!]?$",
    re.I,
)
_MISHEARD_RE = re.compile(
    _PREFIX + r"(?:no\s*,?\s+)?(?:you\s+(?:misheard|mis\s+heard|heard\s+(?:me\s+|that\s+|it\s+)?wrong(?:ly)?|got\s+(?:it|that)\s+wrong)(?:\s+me)?"
    r"|that\s+(?:was|is|'s)\s+wrong|that's\s+wrong|wrong\s+command"
    r"|that(?:\s+is|\s+was|'s)\s+not\s+what\s+i\s+(?:said|meant))"
    r"(?:\s*,?\s+i\s+said\s+(.+?))?[.!]?$",
    re.I,
)
_LIST_RE = re.compile(
    _PREFIX + r"(?:(?:list|show|read|tell\s+me)\s+(?:me\s+)?(?:my\s+|the\s+|all\s+|your\s+)?(?:word\s+)?corrections"
    r"|(?:my|your)\s+(?:word\s+)?corrections"
    r"|what\s+corrections\s+(?:do\s+you\s+(?:have|know)|have\s+you\s+(?:learned|learnt|saved)))[?.!]?$",
    re.I,
)
_REMOVE_RE = re.compile(
    _PREFIX + r"(?:remove|delete|forget|drop)\s+(?:the\s+|my\s+)?(?:word\s+)?correction\s+(?:for\s+|of\s+)?" + _Q + r"(.+?)" + _Q + r"[.!]?$",
    re.I,
)


def parse(text: str) -> tuple[str, dict] | None:
    """Spoken text -> (intent, args) for this module, or None. Check before teach.parse_teach,
    because "when I say X, I mean Y" looks like a teach phrase."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    m = _CORRECTION_RE.match(t)
    if m:
        heard, meant = _norm(m.group(1)), " ".join(m.group(2).split()).strip(" ,.;:!?\"'")
        if heard and meant:
            return "correction", {"heard": heard, "meant": meant}
    m = _REMOVE_RE.match(t)
    if m:
        return "corrections", {"action": "remove", "heard": _norm(m.group(1))}
    if _LIST_RE.match(t):
        return "corrections", {"action": "list"}
    m = _MISHEARD_RE.match(t)
    if m:
        said = (m.group(1) or "").strip(" ,.;:!?\"'")
        return "misheard", ({"said": said} if said else {})
    return None


# ---------- apply fixes (main.py, right after listen) ----------
def _pattern(heard: str) -> str:
    return r"(?<![\w'])" + r"\s+".join(re.escape(w) for w in heard.split()) + r"(?![\w'])"


def apply(text: str) -> str:
    """Replace misheard words with the right ones. Whole words only, case-insensitive,
    longest phrase first, one pass (a fix never fixes another fix). Never raises.
    Commands about corrections themselves are left as they are, so "remove the correction
    note pad" still finds "note pad"."""
    raw = str(text or "")
    try:
        fixes = _load()
        if not fixes or not raw.strip():
            out = raw
        else:
            p = parse(raw)
            if p and p[0] in ("correction", "corrections"):
                out = raw
            else:
                order = sorted(fixes, key=lambda h: (-len(h.split()), -len(h)))
                big = re.compile("|".join(f"({_pattern(h)})" for h in order), re.I)
                out = big.sub(lambda m: fixes[order[m.lastindex - 1]], raw)
    except Exception:
        out = raw
    with _lock:
        _recent.append((" ".join(raw.split()), " ".join(out.split())))
    return out


# ---------- handlers ----------
def _last_history_entry() -> dict | None:
    """Newest command in history.py that is not one of ours ("you misheard" etc.)."""
    try:
        from . import history

        for e in reversed(history.entries()):
            if e.get("intent") not in _OWN_INTENTS:
                return e
    except Exception:
        pass
    return None


def _raw_for(heard: str) -> str:
    """What was really heard before the fixes, if apply() changed it."""
    with _lock:
        for raw, fixed in reversed(_recent):
            if fixed == heard and raw != fixed:
                return raw
    return ""


def misheard(args: dict) -> str:
    args = args or {}
    e = _last_history_entry()
    if e is None:
        return "I don't know what the last command was, so there is nothing to save."
    heard = str(e.get("heard") or "")
    entry = {
        "t": _now().replace(microsecond=0).isoformat(),
        "heard": heard,
        "intent": e.get("intent"),
        "args": e.get("args") or {},
        "reply": e.get("reply") or "",
    }
    raw = _raw_for(heard)
    if raw:
        entry["raw"] = raw
    said = " ".join(str(args.get("said") or "").split())
    if said:
        entry["said"] = said
    try:
        with _lock:
            path = _misheard_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return "Sorry, I could not save that."
    tip = "If a word was wrong, say: when you hear the wrong word, I mean the right word."
    return f"Sorry. I heard \"{heard}\". I saved it so I can do better. {tip}"


def _check(heard: str, meant: str) -> str | None:
    """Reason a fix is not allowed, or None."""
    if not heard or not meant:
        return "Please say it like: when you hear note pad, I mean notepad."
    if heard == _norm(meant):
        return "Those are the same words."
    if heard in _RESERVED or _norm(meant) in _RESERVED:
        return f"Sorry, I can't change the word \"{heard if heard in _RESERVED else meant}\"; I need it as it is."
    if len(heard.split()) > MAX_WORDS or len(heard) > MAX_CHARS or len(meant) > MAX_CHARS:
        return f"That is too long. A correction is for a few words, up to {MAX_WORDS}."
    if any(w.isdigit() or w in _NUMBER_WORDS for w in heard.split()):
        return "Sorry, I can't change number words. I need them for PINs and amounts."
    try:  # a fix must never turn into "yes", "cancel" or a power command
        from jarvis import nlu

        if set(_norm(meant).split()) & _ANSWER_WORDS or nlu.parse(meant).intent in _NEVER_MEANT:
            return f"Sorry, I can't let words turn into \"{meant}\"."
    except Exception:
        pass
    return None


_ANSWER_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "no", "nope", "nah", "cancel", "stop"}
_NUMBER_WORDS = {"zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}
_NEVER_MEANT = {"confirm", "cancel", "shutdown", "restart", "sleep", "lock", "empty_recycle_bin", "jarvis_lock",
                "guest_mode"}


def correction(args: dict) -> str:
    args = args or {}
    heard = _norm(args.get("heard"))
    meant = " ".join(str(args.get("meant") or "").split()).strip(" ,.;:!?\"'")
    bad = _check(heard, meant)
    if bad:
        return bad
    with _lock:
        data = _load()
        old = data.get(heard)
        if old is None and len(data) >= MAX_FIXES:
            return f"I already have {MAX_FIXES} corrections. Remove one first."
        data[heard] = meant
        try:
            _save(data)
        except OSError:
            return "Sorry, I could not save that correction."
    if old is not None and old != meant:
        return f"Updated. When I hear \"{heard}\", I'll use \"{meant}\" instead of \"{old}\"."
    return f"Got it. When I hear \"{heard}\", I'll use \"{meant}\"."


def corrections(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "list").lower()
    if action == "remove":
        heard = _norm(args.get("heard"))
        if not heard:
            return "Which correction? Say: remove the correction note pad."
        with _lock:
            data = _load()
            key = heard if heard in data else next(
                (h for h, m in data.items() if _norm(m) == heard), None)
            if key is None:
                return f"I have no correction for \"{heard}\"."
            del data[key]
            try:
                _save(data)
            except OSError:
                return "Sorry, I could not remove that correction."
        return f"Removed. I'll keep \"{key}\" as I hear it."
    if action != "list":
        return "I can list corrections or remove one."
    data = _load()
    if not data:
        return "You have no corrections yet. Say: when you hear note pad, I mean notepad."
    items = [f"\"{h}\" means \"{m}\"" for h, m in list(data.items())[:SAY_MAX]]
    more = len(data) - len(items)
    n = len(data)
    text = f"You have {n} correction{'s' if n != 1 else ''}: " + "; ".join(items) + "."
    if more > 0:
        text += f" And {more} more."
    return text


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {
    "misheard": {
        "description": "The user says Jarvis misheard or did the wrong thing ('you misheard', 'that was wrong'). "
                       "Saves the last command for later tuning. Optional 'said' = what they really said.",
        "properties": {
            "said": {"type": "string", "description": "What the user really said, if they told you."},
        },
        "required": [],
    },
    "correction": {
        "description": "Save a word fix the user asks for: 'when you hear X, I mean Y'. Jarvis then replaces "
                       "X with Y in everything it hears. Only when the user clearly asks for it.",
        "properties": {
            "heard": {"type": "string", "description": "The wrong words Jarvis hears, e.g. 'note pad'."},
            "meant": {"type": "string", "description": "The right words, e.g. 'notepad'."},
        },
        "required": ["heard", "meant"],
    },
    "corrections": {
        "description": "List the saved word fixes, or remove one (heard = the wrong words).",
        "properties": {
            "action": {"type": "string", "enum": ["list", "remove"]},
            "heard": {"type": "string"},
        },
        "required": ["action"],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {
    "misheard": misheard,
    "correction": correction,
    "corrections": corrections,
}
