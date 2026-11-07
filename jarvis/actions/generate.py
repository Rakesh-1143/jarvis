"""Piece AA: quick generators - password, PIN, UUID, QR code.

Intent:
  generate {kind: password|pin|uuid|qr, text?, length?}

Safety:
  - Passwords and PINs use the `secrets` module (crypto-safe random).
  - They are copied to the clipboard and NOT spoken aloud (someone may be listening).
  - The clipboard is cleared after `clear_after` seconds, but only if it still holds the secret.

Packages: pyperclip (already used), qrcode + Pillow (for QR only).
Optional config (defaults work without it):
  generate: {password_length: 16, pin_length: 4, symbols: true, speak_secrets: false, clear_after: 60}
"""
from __future__ import annotations

import os
import re
import secrets
import string
import sys
import tempfile
import threading
import uuid

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*-_=+?"
# Letters that look alike (l/1/I, O/0) are left out so a password is easy to type by hand.
_LOOKALIKE = set("lI1O0")

PW_MIN, PW_MAX = 8, 128
PIN_MIN, PIN_MAX = 4, 12
QR_MAX_CHARS = 1500  # a QR code can hold ~2900 bytes; keep it readable by phone cameras
QR_FILE = "jarvis_qr.png"

# Words that mean "use what I copied" instead of real QR text.
_CLIPBOARD_WORDS = {"", "this", "it", "that", "this link", "that link", "the link", "link", "clipboard",
                    "my clipboard", "the clipboard", "what i copied", "copied text", "this text", "the text"}

_clear_timer: threading.Timer | None = None


# ---------- helpers ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("generate") or {}
    except Exception:
        cfg = {}
    return {
        "password_length": _int(cfg.get("password_length"), 16),
        "pin_length": _int(cfg.get("pin_length"), 4),
        "symbols": cfg.get("symbols", True) is not False,
        "speak_secrets": cfg.get("speak_secrets") is True,
        "clear_after": _int(cfg.get("clear_after"), 60),
    }


def _int(value, default: int) -> int:
    """'20', 20, 'twenty characters' -> int, else default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value or ""))
    if m:
        return int(m.group())
    words = {"four": 4, "five": 5, "six": 6, "eight": 8, "ten": 10, "twelve": 12, "fourteen": 14,
             "sixteen": 16, "eighteen": 18, "twenty": 20, "twenty four": 24, "thirty two": 32,
             "sixty four": 64}
    t = str(value or "").lower().replace("-", " ")
    for w in sorted(words, key=len, reverse=True):  # "twenty four" before "four"
        if re.search(rf"\b{w}\b", t):
            return words[w]
    return default


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _copy_private_windows(text: str) -> bool:
    """Copy so that Win+V clipboard history, cloud sync and clipboard monitors skip it."""
    try:
        import win32clipboard  # pywin32, Windows only

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            for fmt, value in (("ExcludeClipboardContentFromMonitorProcessing", b"\x00"),
                               ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"),
                               ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00")):
                win32clipboard.SetClipboardData(win32clipboard.RegisterClipboardFormat(fmt), value)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        return False


def _copy(text: str) -> bool:
    try:  # Jarvis's own clipboard history must not keep it either
        from . import cliphistory

        cliphistory.ignore(text)
    except Exception:
        pass
    if _copy_private_windows(text):
        return True
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def _paste() -> str:
    try:
        import pyperclip
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def _schedule_clear(secret: str, seconds: int) -> None:
    """Empty the clipboard later, only if it still holds this secret."""
    global _clear_timer
    if seconds <= 0:
        return
    if _clear_timer is not None:
        _clear_timer.cancel()

    def _clear():
        if _paste() == secret:
            _copy("")

    _clear_timer = threading.Timer(seconds, _clear)
    _clear_timer.daemon = True
    _clear_timer.start()


def _spell_out(text: str) -> str:
    """'aB3' -> 'a, capital B, 3' so TTS reads it char by char."""
    names = {"!": "exclamation", "@": "at", "#": "hash", "$": "dollar", "%": "percent", "^": "caret",
             "&": "and sign", "*": "star", "-": "dash", "_": "underscore", "=": "equals", "+": "plus",
             "?": "question mark"}
    parts = []
    for ch in text:
        if ch.isupper():
            parts.append(f"capital {ch}")
        else:
            parts.append(names.get(ch, ch))
    return ", ".join(parts)


# ---------- password / pin / uuid ----------

def make_password(length: int = 16, symbols: bool = True) -> str:
    """Random password with at least one lower, upper, digit (and symbol if on)."""
    length = _clamp(length, PW_MIN, PW_MAX)
    pools = [LOWER, UPPER, DIGITS] + ([SYMBOLS] if symbols else [])
    pools = ["".join(c for c in p if c not in _LOOKALIKE) for p in pools]
    alphabet = "".join(pools)
    chars = [secrets.choice(p) for p in pools]  # one from each group
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    # Fisher-Yates shuffle with secrets so the forced chars are not always first.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def make_pin(length: int = 4) -> str:
    length = _clamp(length, PIN_MIN, PIN_MAX)
    return "".join(secrets.choice(DIGITS) for _ in range(length))


def _secret_reply(kind: str, value: str, s: dict) -> str:
    copied = _copy(value)
    n = len(value)
    if s["speak_secrets"]:
        spoken = f"Your {kind} is {_spell_out(value)}."
        if copied:
            _schedule_clear(value, s["clear_after"])
            return spoken + " It's also on your clipboard."
        return spoken
    if not copied:
        # Never fall back to speaking a secret the user did not ask to hear.
        return f"I made a {n}-character {kind} but couldn't copy it to the clipboard."
    _schedule_clear(value, s["clear_after"])
    tail = f" It will be cleared in {s['clear_after']} seconds." if s["clear_after"] > 0 else ""
    return f"I copied a {n}-character {kind} to your clipboard.{tail}"


def password(args: dict) -> str:
    s = _settings()
    length = _clamp(_int(args.get("length"), s["password_length"]), PW_MIN, PW_MAX)
    return _secret_reply("password", make_password(length, s["symbols"]), s)


def pin(args: dict) -> str:
    s = _settings()
    length = _clamp(_int(args.get("length"), s["pin_length"]), PIN_MIN, PIN_MAX)
    return _secret_reply("PIN", make_pin(length), s)


def new_uuid(args: dict) -> str:
    value = str(uuid.uuid4())
    if _copy(value):
        return "I copied a new UUID to your clipboard."
    return f"Here is a new UUID: {value}"


# ---------- QR code ----------

def _qr_text(args: dict) -> tuple[str, bool]:
    """Return (text, from_clipboard)."""
    raw = str(args.get("text") or "").strip()
    if raw.lower().strip(" .!?") in _CLIPBOARD_WORDS:
        return _paste(), True
    return raw, False


def _open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens our own PNG in the default image viewer
    else:
        import webbrowser
        webbrowser.open("file://" + path)


def _short(text: str, n: int = 40) -> str:
    text = re.sub(r"^https?://(www\.)?", "", text).rstrip("/")
    return text if len(text) <= n else text[: n - 3] + "..."


def qr(args: dict) -> str:
    text, from_clip = _qr_text(args)
    if not text:
        return ("Your clipboard is empty. Copy a link first, or say the text for the QR code."
                if from_clip else "What should the QR code say?")
    if len(text) > QR_MAX_CHARS:
        return f"That's too long for a QR code. Keep it under {QR_MAX_CHARS} characters."
    try:
        import qrcode
    except ImportError:
        return "QR codes need the qrcode package. Run: pip install qrcode"
    path = os.path.join(tempfile.gettempdir(), QR_FILE)
    try:
        img = qrcode.make(text)
        img.save(path)
    except Exception:
        return "Sorry, I couldn't make the QR code."
    try:
        _open_file(path)
    except Exception:
        return f"I made the QR code but couldn't open it. It's saved at {path}."
    what = "what you copied" if from_clip else _short(text)
    return f"Here is the QR code for {what}. Scan it with your phone."


# ---------- entry ----------

_KINDS = {"password": password, "pin": pin, "uuid": new_uuid, "qr": qr}
_ALIASES = {"passcode": "pin", "pin code": "pin", "guid": "uuid", "id": "uuid", "qr code": "qr",
            "qrcode": "qr", "pass": "password", "passphrase": "password"}


def generate(args: dict) -> str:
    kind = str(args.get("kind") or "password").strip().lower()
    kind = _ALIASES.get(kind, kind)
    fn = _KINDS.get(kind)
    if fn is None:
        return "I can make a password, a PIN, a UUID or a QR code."
    return fn(args)


_STR = {"type": "string"}
CATALOG: dict[str, dict] = {
    "generate": {
        "description": ("Make a strong password, a number PIN or a UUID (copied to the clipboard; passwords "
                        "and PINs are never spoken), or show a QR code of a link/text on screen. "
                        "For QR with no text, the clipboard is used."),
        "properties": {
            "kind": {"type": "string", "enum": ["password", "pin", "uuid", "qr"]},
            "text": _STR,
            "length": {"type": "integer"},
        },
        "required": ["kind"],
    },
}
HANDLERS = {"generate": generate}
