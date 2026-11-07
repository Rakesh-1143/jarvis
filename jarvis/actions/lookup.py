"""Piece N: quick lookups that work without a Claude key.

Intents:
  define {word}                      (info)  - meaning from dictionaryapi.dev (free, no key)
  wikipedia {topic}                  (info)  - 2-sentence summary from Wikipedia REST API
  spell {word}                               - spoken letter by letter, offline
  synonyms {word, kind?}             (info)  - similar (or opposite) words from Datamuse

No extra packages: only urllib + json. Optional config (no change needed):
  lookup: {wiki_lang: "en", sentences: 2}
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 6
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"  # Wikipedia asks for a clear User-Agent
DICT_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
WIKI_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH_URL = "https://{lang}.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0&format=json&search={q}"
DATAMUSE_URL = "https://api.datamuse.com/words?{rel}={word}&max={n}"

NO_NET = "I can't reach the internet right now."
_LETTER_NAMES = {" ": "space", "-": "dash", "'": "apostrophe", ".": "dot"}


# ---------- helpers ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("lookup") or {}
    except Exception:
        cfg = {}
    return {"wiki_lang": str(cfg.get("wiki_lang") or "en"), "sentences": int(cfg.get("sentences") or 2)}


def _get_json(url: str):
    """Return parsed JSON, or None on 404. Other network errors raise."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _clean_word(text: str) -> str:
    """'the word "serendipity"' -> 'serendipity'. Keeps letters, spaces, - and '."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(the )?(word|meaning of|definition of|define|spell|spelling of)\s+", "", t)
    t = re.sub(r"[^\w\s'-]", "", t)
    return re.sub(r"\s+", " ", t).strip(" '-")


def _first_sentences(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    # split after . ! ? followed by a space and a capital/digit; avoid "Dr. Smith" style cuts a bit
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", text)
    out: list[str] = []
    for p in parts:
        if out and re.search(r"\b(?:[A-Z]|Dr|Mr|Mrs|Ms|St|Jr|Sr|vs|etc|e\.g|i\.e)\.$", out[-1]):
            out[-1] += " " + p  # previous piece ended with an abbreviation: join
        else:
            out.append(p)
    return " ".join(out[:n]).strip()


def _word_arg(args: dict) -> str:
    return _clean_word(str(args.get("word") or args.get("text") or args.get("topic") or ""))


# ---------- define ----------

def define(args: dict) -> str:
    word = _word_arg(args)
    if not word:
        return "Which word should I define?"
    try:
        data = _get_json(DICT_URL.format(word=urllib.parse.quote(word)))
    except Exception:
        return NO_NET
    if not data or not isinstance(data, list):
        return f"I couldn't find a meaning for {word}."
    lines: list[str] = []
    seen_pos: set[str] = set()
    for entry in data:
        for m in entry.get("meanings") or []:
            pos = (m.get("partOfSpeech") or "").strip()
            defs = m.get("definitions") or []
            if not defs or pos in seen_pos:
                continue
            seen_pos.add(pos)
            d = defs[0]
            line = f"As a {pos}: {d.get('definition', '').strip()}" if pos else d.get("definition", "").strip()
            if d.get("example"):
                line += f" For example: {d['example'].strip()}"
            lines.append(line.rstrip())
            if len(lines) >= 2:
                break
        if len(lines) >= 2:
            break
    if not lines:
        return f"I couldn't find a meaning for {word}."
    return f"{word.capitalize()}. " + " ".join(l if l.endswith((".", "!", "?")) else l + "." for l in lines)


# ---------- wikipedia ----------

def _wiki_search_title(topic: str, lang: str) -> str | None:
    data = _get_json(WIKI_SEARCH_URL.format(lang=lang, q=urllib.parse.quote(topic)))
    if isinstance(data, list) and len(data) > 1 and data[1]:
        return data[1][0]
    return None


def _wiki_summary(title: str, lang: str):
    t = urllib.parse.quote(title.strip().replace(" ", "_"), safe="")
    return _get_json(WIKI_SUMMARY_URL.format(lang=lang, title=t))


def wikipedia(args: dict) -> str:
    topic = re.sub(r"\s+", " ", str(args.get("topic") or args.get("text") or "")).strip(" ?.!")
    topic = re.sub(r"^(?:who|what)\s+(?:is|was|are|were)\s+(?:a |an |the )?", "", topic, flags=re.I)
    if not topic:
        return "What should I look up on Wikipedia?"
    s = _settings()
    lang, n = s["wiki_lang"], s["sentences"]
    try:
        data = _wiki_summary(topic, lang)
        if not data or data.get("type") == "disambiguation" or not data.get("extract"):
            # exact title failed or is ambiguous: let Wikipedia search pick the best page
            title = _wiki_search_title(topic, lang)
            if title and title.lower() != topic.lower():
                data = _wiki_summary(title, lang)
    except Exception:
        return NO_NET
    if not data or not data.get("extract"):
        return f"I couldn't find {topic} on Wikipedia."
    if data.get("type") == "disambiguation":
        return f"{data.get('title', topic)} can mean several things. Please be more specific."
    return _first_sentences(data["extract"], n)


# ---------- spell ----------

def spell(args: dict) -> str:
    word = _word_arg(args)
    if not word:
        return "Which word should I spell?"
    letters = [_LETTER_NAMES.get(c, c.upper()) for c in word]
    return f"{word.capitalize()} is spelled: " + ", ".join(letters) + "."


# ---------- synonyms ----------

def synonyms(args: dict) -> str:
    word = _word_arg(args)
    if not word:
        return "Which word do you want synonyms for?"
    opposite = str(args.get("kind") or "").lower() in ("antonyms", "antonym", "opposite", "opposites")
    rel = "rel_ant" if opposite else "rel_syn"
    q = urllib.parse.quote(word)
    try:
        data = _get_json(DATAMUSE_URL.format(rel=rel, word=q, n=8)) or []
        if not data and not opposite:  # fall back to "means like"
            data = _get_json(DATAMUSE_URL.format(rel="ml", word=q, n=8)) or []
    except Exception:
        return NO_NET
    words = [d["word"] for d in data if isinstance(d, dict) and d.get("word") and d["word"] != word][:6]
    if not words:
        return f"I couldn't find {'opposites' if opposite else 'synonyms'} for {word}."
    label = "Opposites" if opposite else "Words like"
    return f"{label} {word}: " + ", ".join(words) + "."


# ---------- wiring ----------

_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "define": {"description": "Dictionary meaning of an English word (free dictionary, no AI needed).",
               "properties": {"word": _STR}, "required": ["word"], "info": True},
    "wikipedia": {"description": "Short Wikipedia summary (2 sentences) of a person, place or thing.",
                  "properties": {"topic": _STR}, "required": ["topic"], "info": True},
    "spell": {"description": "Spell a word letter by letter, out loud.",
              "properties": {"word": _STR}, "required": ["word"]},
    "synonyms": {"description": "Words with a similar meaning (or opposite meaning with kind=antonyms).",
                 "properties": {"word": _STR, "kind": {"type": "string", "enum": ["synonyms", "antonyms"]}},
                 "required": ["word"], "info": True},
}
HANDLERS = {"define": define, "wikipedia": wikipedia, "spell": spell, "synonyms": synonyms}
