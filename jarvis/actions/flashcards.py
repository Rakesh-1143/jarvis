"""Flashcards with simple spaced repetition (piece AZ).

Say:
  "add flashcard to Spanish hello means hola"   -> flashcard_add {deck, front, back}
  "quiz me on Spanish" / "study my Spanish flashcards" -> flashcard_quiz {deck?}
  "how many flashcards are due"                 -> flashcard_status {deck?}  (info)
  "delete the Spanish deck"                     -> deck_delete {deck}        (risky, asks yes first)

Spaced repetition = Leitner boxes 1-5. A new card is in box 1 and due today.
Right answer -> next box. Wrong answer -> box 1. A card in box n comes back after 2^(n-1) days
(1, 2, 4, 8, 16 days).

Quiz mode works like dictation: while `is_active()` is True, main sends each heard phrase
to `process(text)`, which returns what to say. Inside the quiz:
  "stop" / "enough" / "I'm done"      -> ends the quiz and says the score
  "skip" / "pass" / "next"            -> shows the answer, the card does not move
  "I don't know" / "show the answer"  -> counts as wrong, shows the answer
  "repeat" / "say that again"         -> asks the same card again
  "score" / "how am I doing"          -> says the score so far
Anything else is the answer (checked with a forgiving match: case, accents, "it's ...",
small spelling slips are fine).

Use `takes(text, intent)` in main (see wiring-notes/AZ-flashcards.md) so clear commands
("open chrome", "what time is it") still run during a quiz (REVIEW W1).

File: config `flashcards_file`, default ~/.jarvis/flashcards.json
  {"decks": {"spanish": {"name": "Spanish", "cards": [
      {"front": "hello", "back": "hola", "box": 1, "due": "2026-11-07", "right": 0, "wrong": 0}]}}}
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

DEFAULT_FILE = "~/.jarvis/flashcards.json"
FLASHCARDS_FILE = ""  # tests / wiring may set this; else config flashcards_file, else DEFAULT_FILE
DEFAULT_DECK = "general"
MAX_BOX = 5
QUIZ_SIZE = 20  # cards per quiz
QUIZ_TIMEOUT = 600  # seconds with no answer -> quiz ends by itself
MAX_TEXT = 200  # longest front/back we keep
MAX_CARDS = 5000  # per deck
MATCH_CUTOFF = 0.8  # 0-1, how close a spoken answer must be

_lock = threading.RLock()
_QUIZ: dict = {"active": False}


# ---------- storage ----------
def _cfg() -> dict:
    try:
        from jarvis.config import load_config

        return load_config() or {}
    except Exception:
        return {}


def _path() -> Path:
    raw = FLASHCARDS_FILE or str(_cfg().get("flashcards_file") or DEFAULT_FILE)
    return Path(os.path.expanduser(raw))


def _load() -> dict:
    p = _path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"decks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("decks"), dict):
        return {"decks": {}}
    decks = {}
    for key, deck in data["decks"].items():
        if not isinstance(deck, dict) or not isinstance(deck.get("cards"), list):
            continue
        cards = [c for c in deck["cards"] if isinstance(c, dict) and c.get("front") and c.get("back")]
        decks[str(key)] = {"name": str(deck.get("name") or key), "cards": cards}
    return {"decks": decks}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ---------- helpers ----------
def _today() -> _dt.date:
    return _dt.date.today()


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" .,!?;:\"'")[:MAX_TEXT]


def deck_key(name) -> str:
    """'My Spanish deck' / 'spanish flashcards' -> 'spanish'."""
    t = re.sub(r"[^\w\s'-]", " ", str(name or "").lower())
    t = re.sub(r"^(the|my)\s+", "", " ".join(t.split()))
    t = re.sub(r"\s+(deck|flash ?cards?|cards?)$", "", t).strip()
    return t


def _norm(text) -> str:
    """Lower case, no accents, no punctuation, no filler like "it's" / "the answer is"."""
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^\w\s]", " ", t.replace("'", ""))
    t = " ".join(t.split())
    t = re.sub(r"^(i think |i guess |maybe |its |it is |the answer is |answer is |that is |thats )+", "", t)
    return t.strip()


def is_right(said: str, back: str) -> bool:
    """Forgiving check of a spoken answer. `back` may hold choices: "hola / ola"."""
    a = _norm(said)
    if not a:
        return False
    for choice in re.split(r"\s*(?:/|;|\bor\b)\s*", str(back)):
        b = _norm(choice)
        if not b:
            continue
        if a == b or a.replace(" ", "") == b.replace(" ", ""):
            return True
        if min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= MATCH_CUTOFF:
            return True
    return False


def _due(card: dict, today: _dt.date) -> bool:
    try:
        return _dt.date.fromisoformat(str(card.get("due"))) <= today
    except ValueError:
        return True


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _find_deck(data: dict, spoken) -> str | None:
    key = deck_key(spoken)
    if not key:
        return None
    if key in data["decks"]:
        return key
    if key.endswith("s") and key[:-1] in data["decks"]:
        return key[:-1]
    hit = difflib.get_close_matches(key, list(data["decks"]), n=1, cutoff=0.8)
    return hit[0] if hit else None


def _when(day: _dt.date, today: _dt.date) -> str:
    diff = (day - today).days
    if diff <= 0:
        return "today"
    if diff == 1:
        return "tomorrow"
    if diff < 7:
        return f"on {day.strftime('%A')}"
    return f"on {day.day} {day.strftime('%B')}"


# ---------- intents ----------
def flashcard_add(args: dict) -> str:
    front, back = _clean(args.get("front")), _clean(args.get("back"))
    if not front or not back:
        return "Say it like: add flashcard to Spanish, hello means hola."
    key = deck_key(args.get("deck")) or DEFAULT_DECK
    with _lock:
        data = _load()
        key = _find_deck(data, key) or key
        deck = data["decks"].setdefault(key, {"name": _clean(args.get("deck")) or key.capitalize(), "cards": []})
        for card in deck["cards"]:
            if _norm(card["front"]) == _norm(front):
                card["back"] = back
                _save(data)
                return f"Updated that card in {deck['name']}: {front} means {back}."
        if len(deck["cards"]) >= MAX_CARDS:
            return f"Your {deck['name']} deck is full."
        deck["cards"].append({"front": front, "back": back, "box": 1, "due": _today().isoformat(),
                              "right": 0, "wrong": 0})
        _save(data)
        n = len(deck["cards"])
    return f"Added to {deck['name']}: {front} means {back}. That deck has {_plural(n, 'card')}."


def flashcard_status(args: dict) -> str:
    today = _today()
    with _lock:
        data = _load()
    if not data["decks"]:
        return "You have no flashcards yet. Say: add flashcard to Spanish, hello means hola."
    want = args.get("deck")
    keys = list(data["decks"])
    if want:
        key = _find_deck(data, want)
        if key is None:
            return f"You don't have a {deck_key(want)} deck."
        keys = [key]
    parts, total_due = [], 0
    for key in keys:
        deck = data["decks"][key]
        cards = deck["cards"]
        due = sum(1 for c in cards if _due(c, today))
        total_due += due
        part = f"{deck['name']} has {_plural(len(cards), 'card')}, {due} due"
        if not due and cards:
            nxt = min(_dt.date.fromisoformat(str(c["due"])) for c in cards if not _due(c, today))
            part += f", next {_when(nxt, today)}"
        parts.append(part)
    head = f"{_plural(total_due, 'card')} due today. " if len(keys) > 1 else ""
    return head + ". ".join(parts) + "."


def needs_confirm(args: dict) -> bool:
    return True  # deck_delete always asks first


def risky_text(args: dict) -> str:
    key = deck_key((args or {}).get("deck"))
    with _lock:
        data = _load()
    found = _find_deck(data, key)
    if found:
        deck = data["decks"][found]
        return f"delete your {deck['name']} flashcard deck with {_plural(len(deck['cards']), 'card')}"
    return f"delete your {key or 'flashcard'} deck"


def deck_delete(args: dict) -> str:
    spoken = args.get("deck")
    if not deck_key(spoken):
        return "Which deck should I delete?"
    with _lock:
        data = _load()
        key = _find_deck(data, spoken)
        if key is None:
            return f"You don't have a {deck_key(spoken)} deck."
        name = data["decks"][key]["name"]
        if not args.get("confirm"):
            return f"Are you sure you want to delete your {name} deck?"
        del data["decks"][key]
        _save(data)
        if _QUIZ.get("active") and key in {c[0] for c in _QUIZ.get("cards", [])}:
            _QUIZ.clear()
            _QUIZ["active"] = False
    return f"Deleted your {name} deck."


# ---------- quiz mode ----------
_STOP = {"stop", "stop it", "quit", "end", "exit", "enough", "thats enough", "that is enough", "im done",
         "i am done", "done", "no more", "cancel", "finish", "stop quiz", "stop the quiz", "end quiz",
         "end the quiz", "stop flashcards", "stop the flashcards", "end flashcards", "stop studying",
         "stop practice", "stop practicing", "quit quiz", "exit quiz", "finish quiz"}
_SKIP = {"skip", "skip it", "skip this", "skip this one", "skip that", "pass", "next", "next card",
         "next one", "next question"}
_DONT_KNOW = {"i dont know", "i do not know", "dont know", "no idea", "i have no idea", "not sure",
              "show answer", "show the answer", "tell me", "tell me the answer", "what is it",
              "give up", "i give up", "reveal", "reveal answer"}
_REPEAT = {"repeat", "repeat that", "say again", "say that again", "again", "come again",
           "what was the question", "repeat the question", "pardon", "sorry", "what"}
_SCORE = {"score", "my score", "whats my score", "what is my score", "how am i doing", "how many right"}
_CONTROL = _STOP | _SKIP | _DONT_KNOW | _REPEAT | _SCORE
_ANSWER_INTENTS = {"unknown", "web_search", "calculate", "answer", "quiz", "cancel", "confirm", "flashcard_quiz"}


def _phrase(text: str) -> str:
    t = re.sub(r"[^\w\s]", " ", str(text or "").lower().replace("'", ""))
    t = " ".join(t.split())
    return re.sub(r"^(jarvis |hey jarvis |please |ok |okay )+", "", t).strip()


def is_active() -> bool:
    """True while a flashcard quiz waits for an answer (ends by itself after QUIZ_TIMEOUT)."""
    with _lock:
        if not _QUIZ.get("active"):
            return False
        if time.monotonic() - _QUIZ.get("last", 0) > QUIZ_TIMEOUT:
            _QUIZ.clear()
            _QUIZ["active"] = False
            return False
        return True


def takes(text: str, intent: str | None = None) -> bool:
    """Should main give this phrase to process()? (only call while is_active()).

    Yes for quiz words (stop/skip/repeat/...), for the expected answer itself (even "open"),
    and for anything nlu does not see as a clear command. A clear command
    ("open chrome", "what time is it") returns False: main runs it and the card keeps waiting.
    """
    if not is_active():
        return False
    p = _phrase(text)
    if p in _CONTROL:
        return True
    with _lock:
        card = _current()
        if card is not None and is_right(text, card[2]):
            return True
    return intent is None or intent in _ANSWER_INTENTS


def _current():
    cards, i = _QUIZ.get("cards") or [], _QUIZ.get("i", 0)
    return cards[i] if i < len(cards) else None


def _ask() -> str:
    card = _current()
    n, total = _QUIZ["i"] + 1, len(_QUIZ["cards"])
    return f"Card {n} of {total}: {card[1]}?"


def _score_text() -> str:
    right, asked = _QUIZ.get("right", 0), _QUIZ.get("asked", 0)
    if not asked:
        return "No answers yet."
    return f"You got {right} out of {asked}."


def _finish(prefix: str = "") -> str:
    score = _score_text() if _QUIZ.get("asked") else "No cards answered."
    _QUIZ.clear()
    _QUIZ["active"] = False
    return (prefix + " " if prefix else "") + "Quiz over. " + score


def _grade(right: bool) -> None:
    """Move the current card's box in the file and count the answer."""
    key, front, _back = _current()
    today = _today()
    data = _load()
    deck = data["decks"].get(key)
    if deck is not None:
        for card in deck["cards"]:
            if card["front"] == front:
                box = int(card.get("box") or 1)
                box = min(box + 1, MAX_BOX) if right else 1
                card["box"] = box
                card["due"] = (today + _dt.timedelta(days=2 ** (box - 1))).isoformat()
                card["right" if right else "wrong"] = int(card.get("right" if right else "wrong") or 0) + 1
                _save(data)
                break
    _QUIZ["asked"] += 1
    _QUIZ["right"] += 1 if right else 0


def _next(prefix: str) -> str:
    _QUIZ["i"] += 1
    if _current() is None:
        return _finish(prefix)
    return f"{prefix} {_ask()}"


def flashcard_quiz(args: dict) -> str:
    today = _today()
    with _lock:
        data = _load()
        if not data["decks"]:
            return "You have no flashcards yet. Say: add flashcard to Spanish, hello means hola."
        spoken = args.get("deck")
        if spoken and deck_key(spoken):
            key = _find_deck(data, spoken)
            if key is None:
                return f"You don't have a {deck_key(spoken)} deck."
            keys = [key]
        else:
            keys = list(data["decks"])
        due = []
        for key in keys:
            for c in data["decks"][key]["cards"]:
                if _due(c, today):
                    due.append((int(c.get("box") or 1), str(c.get("due")), key, c["front"], c["back"]))
        label = data["decks"][keys[0]]["name"] if len(keys) == 1 else "flashcard"
        if not due:
            return f"No {label} cards are due. " + flashcard_status({"deck": spoken} if spoken else {})
        due.sort(key=lambda x: (x[0], x[1]))  # hardest (lowest box) and oldest first
        cards = [(k, f, b) for _, _, k, f, b in due[:QUIZ_SIZE]]
        _QUIZ.clear()
        _QUIZ.update({"active": True, "cards": cards, "i": 0, "asked": 0, "right": 0,
                      "last": time.monotonic()})
        return (f"{label.capitalize()} quiz, {_plural(len(cards), 'card')}. "
                f"Say skip, I don't know, or stop. {_ask()}")


def process(text: str) -> str:
    """Handle one phrase while the quiz runs. Returns what to say. Never raises."""
    try:
        with _lock:
            if not is_active():
                return "There's no flashcard quiz running."
            _QUIZ["last"] = time.monotonic()
            card = _current()
            p = _phrase(text)
            if p in _STOP:
                return _finish()
            if p in _SCORE:
                return _score_text() + " " + _ask()
            if p in _REPEAT and not is_right(text, card[2]):
                return _ask()
            if p in _SKIP and not is_right(text, card[2]):
                return _next(f"Skipped. It was {card[2]}.")
            if p in _DONT_KNOW:
                _grade(False)
                return _next(f"It's {card[2]}.")
            if not p:
                return _ask()
            ok = is_right(text, card[2])
            _grade(ok)
            return _next("Right!" if ok else f"Not quite. It's {card[2]}.")
    except Exception as exc:  # a bad file must not trap the user in quiz mode
        _QUIZ.clear()
        _QUIZ["active"] = False
        return f"The flashcard quiz stopped because of an error: {exc}"


def stop() -> str:
    with _lock:
        if not _QUIZ.get("active"):
            return ""
        return _finish()


# ---------- phrase parser (for nlu wiring) ----------
_LEAD = r"^(?:jarvis,? |hey jarvis,? |please |can you |could you |let's |lets )+"
_ADD = re.compile(r"^(?:add|make|create|new|save)(?: a| an| new| another)? (?:flash ?card|card)s?"
                  r"(?: (?:to|in|into|for|on) (?P<deck>.+?)(?: deck| flash ?cards?)?)?[:,]? (?P<rest>.+)$")
_SEP = re.compile(r"\s*(?:\bmeans\b|\banswer is\b|\banswer\b|=|\bequals\b|\btranslates to\b)\s*")


def _split_card(rest: str) -> tuple[str, str] | None:
    parts = _SEP.split(rest, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(" :,"), parts[1].strip(" :,")
    if " is " in rest:  # "the capital of France is Paris": split on the last "is"
        front, back = rest.rsplit(" is ", 1)
        if front.strip() and back.strip():
            return front.strip(" :,"), back.strip(" :,")
    return None


def parse(text: str) -> tuple[str, dict] | None:
    """Spoken text -> (intent, args) for flashcard commands, else None.

    "quiz me" alone and "quiz me on maths / gk / trivia" stay with fun.py's quiz.
    "quiz me on X" is a flashcard quiz only when X is one of your decks or the words say flashcards.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip(" .?!")
    raw = re.sub(_LEAD, "", raw, flags=re.I)
    t = raw.lower()
    if not t:
        return None

    m = re.match(r"^(?:delete|remove|erase|clear|get rid of) (?:the |my |all )?(?:(?:flash ?card|card) deck "
                 r"(?:called |named )?(?P<a>.+)|(?P<b>.+?) (?:deck|flash ?cards))$", t)
    if m:
        return "deck_delete", {"deck": deck_key(m.group("a") or m.group("b"))}

    if re.fullmatch(r"(?:add|make|create|save)(?: a| an| new| another)? (?:flash ?card|card)s?", t):
        # "add a flashcard" with nothing after it: the handler asks for the front and back
        return "flashcard_add", {"deck": DEFAULT_DECK, "front": "", "back": ""}
    m = _ADD.match(t)
    if m:
        # keep the user's own capitals for the card text
        rest = raw[m.start("rest"):]
        deck = m.group("deck")
        if deck is None:
            m2 = re.match(r"^(?P<deck>.+?) (?:deck|flash ?cards?)[:,]? (?P<rest>.+)$", rest, flags=re.I)
            if m2 and _split_card(m2.group("rest")):  # "add flashcard Spanish deck: hello means hola"
                deck, rest = m2.group("deck"), m2.group("rest")
        elif not re.search(r"\b(deck|flash ?cards?)\b", t[m.end("deck"):m.start("rest")]):
            # "add flashcard to spanish hello means hola": the deck is one word, unless a known deck is longer
            words = (deck + " " + rest).split()
            known = sorted(_load()["decks"], key=len, reverse=True)
            low = " ".join(words).lower()
            hit = next((k for k in known if low.startswith(k + " ")), None)
            n = len(hit.split()) if hit else 1
            deck, rest = " ".join(words[:n]), " ".join(words[n:])
        card = _split_card(rest)
        if card is None:
            return "flashcard_add", {"deck": deck_key(deck) or DEFAULT_DECK, "front": "", "back": ""}
        return "flashcard_add", {"deck": deck_key(deck) or DEFAULT_DECK, "front": card[0], "back": card[1]}

    if re.search(r"\b(how many|which|what) (flash ?cards?|cards)( are| is)? due\b|\bflash ?cards? (status|due)\b|"
                 r"\b(what|which) (flash ?card )?decks\b|\bmy (flash ?card )?decks\b|\bcards due\b", t):
        m = re.search(r"\bdue (?:in|for|on) (?:my |the )?(.+)$", t)
        return "flashcard_status", ({"deck": deck_key(m.group(1))} if m else {})

    m = re.match(r"^(?:quiz me|test me|drill me)(?: on| with)? (?:my |the )?(.+)$", t)
    if m:
        name = deck_key(m.group(1))
        if not name or name in {"flash", "flashcard", "flashcards", "cards"}:
            return "flashcard_quiz", {}
        if re.search(r"\b(flash ?cards?|cards|deck)\b", m.group(1)) or _find_deck(_load(), name):
            return "flashcard_quiz", {"deck": name}
        return None  # "quiz me on maths": fun.py's quiz
    m = re.match(r"^(?:study|practice|practise|review|revise|start|do)(?: my| the)?(?: (?P<deck>.+?))?"
                 r" (?:flash ?cards?|cards|deck)$", t)
    if m:
        return "flashcard_quiz", ({"deck": deck_key(m.group("deck"))} if m.group("deck") else {})
    m = re.match(r"^(?:study|practice|practise|review|revise) (?:my |the )?(.+)$", t)
    if m and _find_deck(_load(), m.group(1)):
        return "flashcard_quiz", {"deck": deck_key(m.group(1))}
    return None


# ---------- catalog ----------
CATALOG: dict[str, dict] = {
    "flashcard_add": {
        "description": "Add a flashcard (question/front and answer/back) to a deck. Same front again updates it.",
        "properties": {
            "deck": {"type": "string", "description": "Deck name, e.g. Spanish. Default 'general'."},
            "front": {"type": "string", "description": "Question side, e.g. 'hello'."},
            "back": {"type": "string", "description": "Answer side, e.g. 'hola'. Use / for other right answers."},
        },
        "required": ["front", "back"],
    },
    "flashcard_quiz": {
        "description": "Start a spoken flashcard quiz with the cards that are due (spaced repetition). "
                       "The user's next phrases are the answers.",
        "properties": {"deck": {"type": "string", "description": "Deck name. Leave out for all decks."}},
        "required": [],
    },
    "flashcard_status": {
        "description": "How many flashcards and decks the user has and how many are due today.",
        "properties": {"deck": {"type": "string", "description": "Optional deck name."}},
        "required": [],
        "info": True,
    },
    "deck_delete": {
        "description": "Delete a whole flashcard deck (Jarvis asks the user to confirm).",
        "properties": {"deck": {"type": "string", "description": "Deck name."}},
        "required": ["deck"],
    },
}

HANDLERS = {
    "flashcard_add": flashcard_add,
    "flashcard_quiz": flashcard_quiz,
    "flashcard_status": flashcard_status,
    "deck_delete": deck_delete,
}
