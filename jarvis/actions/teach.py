"""Teach Jarvis new commands by voice (piece AL).

    "when I say study time, open notes and start focus"   -> phrase -> steps
    "when I say good night, say sleep well Rakesh"        -> phrase -> fixed answer
    "what have you learned"                                -> list them
    "forget the command study time"                        -> delete (risky: asks yes)

Saved in a JSON file (config `taught_file`, default ~/.jarvis/taught.json), not config.yaml.
Each step is run later as if the user said it, so risky steps (shutdown, delete...) still ask yes.

Public:
    parse_teach(text) -> dict | None      helper for nlu: "when I say X, do Y" -> teach args
    parse_taught(text) -> dict | None     helper for nlu: list / forget -> taught args
    match(text) -> list[str] | None       steps for a taught phrase (main runs them like a routine)
    answer(text) -> str | None            fixed answer for a taught phrase ("say Y" kind)
    run(text, do_step, say, depth=0) -> str | None   all of the above in one call for main.py
    risky_text(args) -> str | None        question words when forgetting (needs a yes)
    teach(args) / taught(args) -> str     handlers
    CATALOG, HANDLERS                     merged by actions/__init__.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_FILE = "~/.jarvis/taught.json"
MAX_STEPS = 10
MAX_DEPTH = 2  # a taught step may call another taught phrase, but not forever

# Words that must keep their normal meaning (answers to "are you sure?", stop/exit, pause).
_RESERVED = {
    "yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay", "no", "nope", "cancel",
    "stop", "never mind", "goodbye", "exit jarvis", "quit jarvis", "exit", "quit",
    "start listening", "stop listening", "help", "what can i say", "repeat that",
}


def _norm(text) -> str:
    """Lower case, no punctuation (keeps '), single spaces, no 'jarvis' / 'please'."""
    t = re.sub(r"[^\w\s']", " ", str(text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:(?:hey|ok|okay)\s+)?jarvis\s+", "", t)
    t = re.sub(r"^please\s+|\s+please$", "", t)
    return t.strip(" '")


# ---------- storage ----------
def _path() -> Path:
    try:
        from jarvis.config import load_config

        cfg = load_config() or {}
    except Exception:
        cfg = {}
    return Path(os.path.expanduser(str(cfg.get("taught_file") or DEFAULT_FILE)))


def _load() -> dict[str, dict]:
    """{phrase: {"steps": [...]} or {"answer": "..."}}; bad or missing file -> {}."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    if not isinstance(data, dict):
        return out
    for phrase, entry in data.items():
        p = _norm(phrase)
        if not p or not isinstance(entry, dict):
            continue
        steps = entry.get("steps")
        if isinstance(steps, list) and any(str(s).strip() for s in steps):
            out[p] = {"steps": [str(s).strip() for s in steps if str(s).strip()][:MAX_STEPS]}
        elif isinstance(entry.get("answer"), str) and entry["answer"].strip():
            out[p] = {"answer": entry["answer"].strip()}
    return out


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # never leave a half-written file


# ---------- parsing helpers (for the nlu wiring) ----------
_TEACH_RE = re.compile(
    r"^(?:(?:can you\s+)?(?:please\s+)?(?:learn|remember)\s+(?:that\s+)?)?"
    r"(?:when(?:ever)?|if)\s+i\s+say\s+(.+?)\s*(?:,|\s+then\s+|\s+you\s+should\s+|\s+(?=(?:please\s+)?(?:say|reply|answer|respond|do|open|start|play|turn|set|run|launch|close|mute|show|search|lock|tell|read|type|go|stop|pause|take)\b))(.+)$"
)
_ANSWER_RE = re.compile(r"^(?:please\s+)?(?:just\s+)?(?:say|reply|answer|respond(?:\s+with)?)\s+(?:with\s+)?(.+)$")
_DO_RE = re.compile(r"^(?:please\s+)?do\s+(?:this\s*:?\s*)?")
_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and\s+)?(?:then\s+)?|\s+and\s+then\s+|\s+then\s+|\s+and\s+)\s*")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" ,.;:!?\"'")


def split_steps(text: str) -> list[str]:
    """'open notes and start focus' -> ['open notes', 'start focus']."""
    return [s for s in (_clean(p) for p in _SPLIT_RE.split(str(text or ""))) if s]


def parse_teach(text: str) -> dict | None:
    """'when I say study time, open notes and start focus' -> {phrase, steps:[...]};
    'when I say good night, say sleep well' -> {phrase, answer}."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    low = re.sub(r"^(?:(?:hey|ok|okay)\s+)?jarvis[,\s]+", "", raw, flags=re.I)
    m = _TEACH_RE.match(low.lower())
    if not m:
        return None
    # keep the user's own letters for the action part (an answer is spoken back as said)
    start = m.start(2)
    phrase, rest = _norm(m.group(1)), _clean(low[start:])
    if not phrase or not rest:
        return None
    a = _ANSWER_RE.match(rest.lower())
    if a:
        return {"phrase": phrase, "answer": _clean(rest[a.start(1):])}
    rest = rest[_DO_RE.match(rest.lower()).end():] if _DO_RE.match(rest.lower()) else rest
    steps = split_steps(rest)
    return {"phrase": phrase, "steps": steps} if steps else None


_LIST_RE = re.compile(
    r"^(?:what|which)\s+(?:commands\s+)?(?:have\s+you|did\s+you)\s+(?:learn(?:ed|t)?|been\s+taught)"
    r"|^(?:list|show|tell\s+me)\s+(?:all\s+)?(?:my\s+|the\s+|your\s+)?(?:taught|learned|learnt|custom)\s+commands"
    r"|^what\s+(?:commands\s+)?did\s+i\s+teach\s+you"
)
_FORGET_RE = re.compile(
    r"^(?:forget|unlearn|delete|remove)\s+(?:the\s+|my\s+)?(?:taught\s+|learned\s+|custom\s+)?"
    r"(?:command|phrase|shortcut)\s+(.+)$"
    r"|^(?:forget|unlearn)\s+(?:what\s+i\s+taught\s+you\s+(?:for|about)\s+)?(.+)$"
)


def parse_taught(text: str) -> dict | None:
    """'what have you learned' -> {action: list}; 'forget the command study time' -> {action: forget, phrase}."""
    t = _norm(text)
    if _LIST_RE.match(t):
        return {"action": "list"}
    m = _FORGET_RE.match(t)
    if m:
        phrase = _norm(m.group(1) or m.group(2))
        if phrase in ("that", "it", "everything", "all"):  # too vague: never guess what to delete
            return {"action": "forget", "phrase": ""}
        return {"action": "forget", "phrase": phrase}
    return None


# ---------- matching (main.py, before nlu) ----------
def _find(text: str) -> tuple[str, dict] | None:
    t = _norm(text)
    if not t:
        return None
    data = _load()
    return (t, data[t]) if t in data else None


def match(text: str) -> list[str] | None:
    """Steps for a taught phrase, or None. Steps are plain phrases: run each like the user said it."""
    hit = _find(text)
    return list(hit[1]["steps"]) if hit and "steps" in hit[1] else None


def answer(text: str) -> str | None:
    """Fixed answer for a taught 'say' phrase, or None."""
    hit = _find(text)
    return hit[1]["answer"] if hit and "answer" in hit[1] else None


def run(text: str, do_step, say, depth: int = 0) -> str | None:
    """One call for main.py. None = not a taught phrase (go on to nlu).

    do_step(step_text) -> reply: must be main.handle(step, ..., depth + 1), so each step goes through
    routines, shortcuts, nlu, AI and the normal "are you sure?" path.
    """
    hit = _find(text)
    if not hit:
        return None
    phrase, entry = hit
    if "answer" in entry:
        return entry["answer"]
    if depth > MAX_DEPTH:
        return "That command calls itself, so I stopped."
    for step in entry["steps"]:
        reply = do_step(step)
        if reply:
            say(reply)
    return ""


# ---------- confirm ----------
def risky_text(args: dict) -> str | None:
    """Forgetting a taught command asks yes first. Listing and teaching do not."""
    if str(args.get("action") or "") != "forget":
        return None
    phrase = _norm(args.get("phrase"))
    if not phrase or phrase not in _load():
        return None  # nothing to delete: the handler just says so
    return f"forget the command {phrase}"


# ---------- handlers ----------
def _steps_text(steps: list[str]) -> str:
    return ", then ".join(steps)


def teach(args: dict) -> str:
    phrase = _norm(args.get("phrase"))
    steps = args.get("steps")
    if isinstance(steps, str):
        steps = split_steps(steps)
    steps = [_clean(s) for s in (steps or []) if _clean(s)]
    ans = _clean(args.get("answer") or "")
    if not phrase:
        return "What should I listen for? Say: when I say study time, open notes and start focus."
    if phrase.startswith(("when i say", "whenever i say", "forget ", "what have you learn")):
        return "Sorry, I can't use that as a command phrase."
    if phrase in _RESERVED or len(phrase) < 3:
        return f"Sorry, {phrase} is a word I need for something else. Pick another phrase."
    if not steps and not ans:
        return f"What should I do when you say {phrase}?"
    if len(steps) > MAX_STEPS:
        return f"That's too many steps. I can learn up to {MAX_STEPS}."
    if any(_norm(s) == phrase for s in steps):
        return "A command can't call itself. Try different steps."
    data = _load()
    replaced = phrase in data
    data[phrase] = {"answer": ans} if ans and not steps else {"steps": steps}
    try:
        _save(data)
    except OSError as exc:
        return f"Sorry, I couldn't save that: {exc}"
    head = "Updated." if replaced else "Got it."
    if "answer" in data[phrase]:
        return f"{head} When you say {phrase}, I'll say: {ans}"
    return f"{head} When you say {phrase}, I'll {_steps_text(steps)}."


def taught(args: dict) -> str:
    action = str(args.get("action") or "list")
    data = _load()
    if action == "forget":
        phrase = _norm(args.get("phrase"))
        if not phrase:
            return "Which command should I forget? Say: forget the command study time."
        if phrase not in data:
            names = ", ".join(sorted(data)) or "none"
            return f"I don't have a command called {phrase}. I know: {names}."
        if args.get("confirm") is not True:  # never delete without a yes
            return f"Are you sure you want to {risky_text({'action': 'forget', 'phrase': phrase})}? Say yes to confirm."
        del data[phrase]
        try:
            _save(data)
        except OSError as exc:
            return f"Sorry, I couldn't save that: {exc}"
        return f"Okay, I forgot {phrase}."
    if not data:
        return "You haven't taught me any commands yet. Say: when I say study time, open notes and start focus."
    parts = []
    for phrase in sorted(data):
        e = data[phrase]
        parts.append(f"{phrase}: say {e['answer']}" if "answer" in e else f"{phrase}: {_steps_text(e['steps'])}")
    n = len(parts)
    return f"I know {n} taught command{'s' if n != 1 else ''}. " + ". ".join(parts) + "."


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {
    "teach": {
        "description": "Learn a new voice command the user teaches: 'when I say X, do Y' (steps are normal "
                       "spoken commands, run in order later) or 'when I say X, say Y' (fixed answer). "
                       "Only when the user clearly asks to teach a command.",
        "properties": {
            "phrase": {"type": "string", "description": "The trigger phrase, e.g. 'study time'."},
            "steps": {"type": "array", "items": {"type": "string"},
                      "description": "Spoken commands to run in order, e.g. ['open notes', 'start focus']."},
            "answer": {"type": "string", "description": "Fixed text to say back instead of steps."},
        },
        "required": ["phrase"],
    },
    "taught": {
        "description": "List the commands the user taught by voice, or forget one (forget asks to confirm).",
        "properties": {
            "action": {"type": "string", "enum": ["list", "forget"]},
            "phrase": {"type": "string", "description": "Taught phrase to forget."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"teach": teach, "taught": taught}
