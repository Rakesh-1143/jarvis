"""Dictation mode and read aloud (piece E).

Dictation: after "start dictation", every phrase is typed into the active window
until "stop dictation". Inside dictation you can say:
  comma, full stop / period, question mark, exclamation mark, colon, semicolon,
  new line, new paragraph, caps <word>, delete that / scratch that, undo.
A capital letter is added at the start and after . ? ! and new lines.

Read aloud: reads the selected text (or the clipboard if nothing is selected)
sentence by sentence in the background. "stop reading" stops after the current sentence.

Core wiring (main.py):
    if dictation.is_active():
        reply = dictation.process(text)   # types it; returns "" or a short reply to say
"""
from __future__ import annotations

import re
import threading

# ---------- dictation ----------
_PUNCT = {  # spoken words -> text (longest phrases first when matching)
    ("new", "paragraph"): "\n\n",
    ("new", "line"): "\n",
    ("next", "line"): "\n",
    ("full", "stop"): ".",
    ("question", "mark"): "?",
    ("exclamation", "mark"): "!",
    ("exclamation", "point"): "!",
    ("period",): ".",
    ("comma",): ",",
    ("colon",): ":",
    ("semicolon",): ";",
}
_MAX_LEN = max(len(k) for k in _PUNCT)
_DELETE = {"delete that", "scratch that", "delete last", "remove that"}
_UNDO = {"undo", "undo that"}
_STOP = re.compile(r"^(?:jarvis\s+)?(?:stop|end|finish|exit|turn off)\s+(?:the\s+)?dictat(?:ion|ing)$")
_ENDS_SENTENCE = (".", "?", "!", "\n")

_active = False
_typed: list[str] = []  # each phrase's typed text, for "delete that"


class _Keys:
    """Real keyboard. Tests swap `_keys` for a fake."""

    def type(self, text: str) -> None:
        import pyautogui

        from jarvis.actions.keyboard import type_text

        # New lines use Shift+Enter: plain Enter would SEND the message in WhatsApp, Teams, Slack, etc.
        for i, part in enumerate(text.split("\n")):
            if i:
                pyautogui.hotkey("shift", "enter")
            if part:
                type_text(part)

    def backspace(self, n: int) -> None:
        import pyautogui

        pyautogui.press("backspace", presses=n, interval=0.01)

    def undo(self) -> None:
        import pyautogui

        pyautogui.hotkey("ctrl", "z")


_keys = _Keys()


def is_active() -> bool:
    return _active


def start() -> str:
    global _active
    _active = True
    _typed.clear()
    return "Dictation on. Say stop dictation when you are done."


def stop() -> str:
    global _active
    _active = False
    _typed.clear()
    return "Dictation off."


def _bare(word: str) -> str:
    """Word without case or punctuation the speech engine added, for command matching."""
    return re.sub(r"[^\w']", "", word.lower())


def format_phrase(text: str, before: str = "") -> str:
    """Turn one spoken phrase into the text to type. `before` = text already typed (for spaces/capitals)."""
    words = text.split()
    out = ""
    last = before
    caps_next = False
    i = 0
    while i < len(words):
        # spoken punctuation (1-2 words)
        piece = None
        for n in range(_MAX_LEN, 0, -1):
            key = tuple(_bare(w) for w in words[i:i + n])
            if len(key) == n and key in _PUNCT:
                piece, i = _PUNCT[key], i + n
                break
        if piece is not None:
            if piece.startswith("\n"):
                out = out.rstrip(" ")
            out += piece
            last = before + out
            continue
        if _bare(words[i]) in ("caps", "cap", "capital") and i + 1 < len(words):
            caps_next, i = True, i + 1
            continue
        word = words[i]
        i += 1
        need_cap = caps_next or not last.strip(" ") or last.rstrip(" ").endswith(_ENDS_SENTENCE)
        if need_cap:
            word = word[:1].upper() + word[1:]
        caps_next = False
        if last and not last.endswith((" ", "\n")):
            out += " "
        out += word
        last = before + out
    return out


def process(text: str) -> str:
    """Handle one phrase while dictation is on. Types it. Returns a reply to say ("" = say nothing)."""
    if not _active:
        return ""
    phrase = (text or "").strip()
    if not phrase:
        return ""
    plain = " ".join(_bare(w) for w in phrase.split())
    if _STOP.match(plain):
        return stop()
    if plain in _DELETE:
        if not _typed:
            return "Nothing to delete."
        _keys.backspace(len(_typed.pop()))
        return ""
    if plain in _UNDO:
        _keys.undo()
        if _typed:
            _typed.pop()
        return ""
    chunk = format_phrase(phrase, "".join(_typed))
    if chunk:
        _keys.type(chunk)
        _typed.append(chunk)
    return ""


def dictation(args: dict) -> str:
    state = str(args.get("state") or "on").lower()
    if state in ("off", "stop", "false"):
        return stop() if _active else "Dictation is not on."
    return start()


# ---------- read aloud ----------
_NOTHING_SELECTED = "Nothing is selected."
_reader: threading.Thread | None = None
_stop_reading = threading.Event()


def _speak(text: str) -> None:
    from jarvis import tts

    tts.say(text)


def _selected() -> str:
    from jarvis.actions.desktop import get_selected_text

    text = get_selected_text({})
    return "" if text == _NOTHING_SELECTED else text


def _clipboard() -> str:
    import pyperclip

    return (pyperclip.paste() or "").strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _read_worker(sentences: list[str]) -> None:
    for s in sentences:
        if _stop_reading.is_set():
            break
        _speak(s)


def is_reading() -> bool:
    return _reader is not None and _reader.is_alive()


def read_aloud(args: dict) -> str:
    global _reader
    if str(args.get("action") or "").lower() == "stop":
        if not is_reading():
            return "I am not reading anything."
        _stop_reading.set()
        return "Stopped reading."
    source = str(args.get("source") or "").lower()
    text = ""
    if source != "clipboard":
        text = _selected()
    if not text and source != "selection":
        text = _clipboard()
    if not text:
        return "Select some text or copy it first, then ask again."
    if is_reading():
        _stop_reading.set()
        _reader.join(timeout=5)
    _stop_reading.clear()
    _reader = threading.Thread(target=_read_worker, args=(split_sentences(text[:20000]),), daemon=True)
    _reader.start()
    return ""  # the reading itself is the reply


# ---------- for the wiring thread ----------
_ONOFF = {"type": "string", "enum": ["on", "off"]}

CATALOG: dict[str, dict] = {
    "dictation": {"description": "Start or stop dictation mode: everything the user says after is typed into the active window.",
                  "properties": {"state": _ONOFF}, "required": ["state"]},
    "read_aloud": {"description": "Read the selected text out loud (or the clipboard if nothing is selected), or stop reading.",
                   "properties": {"source": {"type": "string", "enum": ["selection", "clipboard"]},
                                  "action": {"type": "string", "enum": ["start", "stop"]}},
                   "required": []},
}

HANDLERS = {"dictation": dictation, "read_aloud": read_aloud}
