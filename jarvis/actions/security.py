"""Voice PIN, "lock Jarvis" and guest mode.

Anyone near the laptop can talk to Jarvis. This module decides, before each
intent runs, if it may run, needs the PIN, or is blocked.

  "lock Jarvis"              -> only the PIN works until unlocked
  "unlock Jarvis" (+ PIN)    -> back to normal
  "guest mode on" / "off"    -> only safe intents run (off needs the PIN)
  protected intents          -> "Say your PIN." first (shutdown, delete file ...)
  3 wrong PINs               -> PIN refused for 5 minutes (only guest intents run)

The PIN is never stored plain. Make the hash once with:
    python -m jarvis.actions.security set-pin
It asks for the PIN (hidden), saves only a salted PBKDF2 hash to ~/.jarvis-pin,
and prints a `pin_hash:` line you may paste into config.yaml instead.

Settings (optional) in config.yaml:
  security:
    pin_hash: ""            # from set-pin; empty = use pin_file
    pin_file: "~/.jarvis-pin"
    protect: [shutdown, restart, delete_file, "history:clear", ...]   # "intent" or "intent:action"
    guest_mode_intents: [time, weather, ...]
    max_tries: 3
    lockout_minutes: 5
    grace_seconds: 0        # after a right PIN, skip asking again for this long (0 = always ask)

Wiring (main.py, before each intent):
    msg = security.check(cmd)              # None = go ahead
    if msg:
        io.say(msg)
        if not security.pending():
            return ""                      # blocked (guest mode / lockout)
        ok, reply = security.verify(io.listen())
        if not ok:
            return reply
        # right PIN: run cmd as normal
Never log what is heard while a PIN is pending; use security.redact(text) for logs.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import logging
import os
import re
import unicodedata
import secrets
import sys
import threading
import time

log = logging.getLogger("jarvis.security")

_now = time.monotonic  # tests patch this

ITERATIONS = 200_000
PIN_MIN, PIN_MAX = 4, 12
PENDING_SECONDS = 30      # a PIN prompt waits this long
AUTH_SECONDS = 15         # after a right PIN, "unlock"/"guest mode off" may run this long

DEFAULT_PROTECT = [
    "shutdown", "restart", "software", "phone", "device", "scene",
    "delete_file", "move_file", "rename_file", "copy_file", "empty_recycle_bin",
    "kill_process", "computer_use", "whatsapp", "email", "forget_memory", "list_clear",
    "history:clear",
    # these change how Jarvis understands you, forever: a visitor must not set them
    "teach", "taught", "correction", "corrections",
    "setup",  # name, city, a new PIN ... (only once a PIN exists)
    "contact_add", "contact_delete",  # texts, WhatsApp and emails go to these numbers (review Z2)
    "dev:git_push", "dev:git_commit",  # code leaves the PC / history changes (review N2)
    "hotspot:on", "hotspot:password", "webcam:photo",  # shares the internet / shows a secret / a photo (K4, K5)
    "voice_id:enrol", "voice_id:off", "voice_id:forget",  # voice lock changes (= voiceid.PROTECT)
]
DEFAULT_GUEST = [
    "time", "weather", "world_time", "date_calc", "calculate", "convert", "define", "synonyms",
    "spell", "wikipedia", "news", "help", "random_pick", "quiz", "timer", "timers",
    "volume", "media", "play", "now_playing", "repeat",
]
# always allowed (unless Jarvis is locked): answers to a question, and this module's own intents
_ALWAYS = {"confirm", "cancel", "jarvis_lock", "guest_mode"}

_lock = threading.RLock()
_settings: dict | None = None
_locked = False
_guest = False
_wrong = 0
_lockout_until = 0.0
_pending_until = 0.0
_auth_until = 0.0      # right PIN given recently (for jarvis_lock off / guest_mode off)
_grace_until = 0.0     # grace_seconds window


# ---------- settings and hashing ----------

def _list(value, default: list) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return list(default)
    return [str(v).strip().lower() for v in value if str(v).strip()]


def _num(value, default: float, low: float = 0) -> float:
    try:
        return max(low, float(value))
    except (TypeError, ValueError):
        return default


def configure(cfg: dict | None = None) -> None:
    """Load settings. None = read config.yaml. Tests pass a dict."""
    global _settings
    if cfg is None:
        try:
            from jarvis.config import load_config
            cfg = load_config().get("security") or {}
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get("pin") not in (None, ""):
        log.warning("security.pin (plain PIN) in config is ignored. Run "
                    "'python -m jarvis.actions.security set-pin' and delete the plain pin.")
    with _lock:
        _settings = {
            "pin_hash": str(cfg.get("pin_hash") or "").strip(),
            "pin_file": os.path.expanduser(str(cfg.get("pin_file") or "~/.jarvis-pin")),
            "protect": _list(cfg.get("protect"), DEFAULT_PROTECT),
            "guest": _list(cfg.get("guest_mode_intents"), DEFAULT_GUEST),
            "max_tries": int(_num(cfg.get("max_tries"), 3, 1)),
            "lockout": _num(cfg.get("lockout_minutes"), 5) * 60,
            "grace": _num(cfg.get("grace_seconds"), 0),
        }


def _cfg() -> dict:
    if _settings is None:
        configure()
    return _settings  # type: ignore[return-value]


def hash_pin(pin: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    """Salted PBKDF2-SHA256 hash, as 'pbkdf2_sha256$iterations$salt_hex$hash_hex'."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _check_hash(pin: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _stored_hash() -> str:
    cfg = _cfg()
    if cfg["pin_hash"]:
        return cfg["pin_hash"]
    try:
        with open(cfg["pin_file"], encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def has_pin() -> bool:
    return _stored_hash().startswith("pbkdf2_sha256$")


def save_pin(pin: str) -> str:
    """Hash and save a PIN to pin_file (never plain). Returns the hash line."""
    if not (pin.isdigit() and PIN_MIN <= len(pin) <= PIN_MAX):
        raise ValueError(f"PIN must be {PIN_MIN}-{PIN_MAX} digits.")
    stored = hash_pin(pin)
    path = _cfg()["pin_file"]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(stored + "\n")
    return stored


# ---------- spoken digits ----------

_DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "nil": "0", "nought": "0",
    "one": "1", "won": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3", "tree": "3",
    "four": "4", "for": "4", "fore": "4",
    "five": "5", "six": "6", "seven": "7",
    "eight": "8", "ate": "8",
    "nine": "9", "niner": "9",
}
# Hindi and Telugu number words (romanised and script), so a PIN said in Hindi/Telugu is read
# on this PC and never needs translating online (review K1). "do" (= 2) is common English too,
# but spoken_digits only matters while a PIN is asked or a sentence talks about a PIN.
_DIGITS.update({
    "shunya": "0", "shoonya": "0", "ek": "1", "do": "2", "teen": "3", "tin": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "che": "6", "saat": "7", "sat": "7", "aath": "8",
    "ath": "8", "nau": "9", "no": None,
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6", "छः": "6",
    "सात": "7", "आठ": "8", "नौ": "9",
    "sunna": "0", "okati": "1", "okkati": "1", "rendu": "2", "moodu": "3", "mudu": "3", "nalugu": "4",
    "naalugu": "4", "aidu": "5", "ayidu": "5", "aaru": "6", "edu": "7", "yedu": "7", "enimidi": "8",
    "tommidi": "9",
    "సున్నా": "0", "ఒకటి": "1", "రెండు": "2", "మూడు": "3", "నాలుగు": "4", "ఐదు": "5", "ఆరు": "6",
    "ఏడు": "7", "ఎనిమిది": "8", "తొమ్మిది": "9",
})
_DIGITS.pop("no")
_REPEAT = {"double": 2, "triple": 3}


def spoken_digits(text) -> str:
    """'one two three four' / '1234' / 'double five six' -> digits. Other words are skipped."""
    if text is None:
        return ""
    # words in any script (Devanagari/Telugu vowel signs are not \w, so split on spaces and punctuation)
    words = re.findall(r"\d+|[^\s\d,.!?;:।|-]+", str(text).lower())
    out, times = [], 1
    for w in words:
        if w in _REPEAT:
            times = _REPEAT[w]
            continue
        d = "".join(str(unicodedata.digit(c)) for c in w) if w.isdigit() else _DIGITS.get(w)
        if d is None:
            times = 1
            continue
        out.append(d[0] * times + d[1:] if times > 1 else d)
        times = 1
    return "".join(out)


_SECRET_RUN = re.compile(
    r"\b(?:(?:\d+|zero|oh|o|one|won|two|to|too|three|four|for|fore|five|six|seven|eight|ate|nine|"
    r"double|triple)\b[\s,.-]*){3,}", re.I)


def redact(text) -> str:
    """Hide PIN-like parts (4+ digit numbers, runs of 3+ digit words) for logs. While a PIN is pending, hide all."""
    if text is None:
        return ""
    if pending():
        return "<PIN hidden>"
    text = re.sub(r"\d{4,}", "***", str(text))
    return _SECRET_RUN.sub("*** ", text).strip()


# ---------- state ----------

def _intent_args(intent, args) -> tuple[str, dict]:
    if not isinstance(intent, str):  # a Command
        args = args if args is not None else getattr(intent, "args", None)
        intent = getattr(intent, "intent", "") or ""
    return str(intent).lower(), (args if isinstance(args, dict) else {})


def _protected(intent: str, args: dict) -> bool:
    action = str(args.get("action") or args.get("state") or "").lower()
    for p in _cfg()["protect"]:
        name, _, sub = p.partition(":")
        if name == intent and (not sub or sub == action):
            return True
    return False


def _locked_out() -> bool:
    return _now() < _lockout_until


def _minutes_left() -> int:
    return max(1, int((_lockout_until - _now() + 59) // 60))


def _ask() -> str:
    global _pending_until
    _pending_until = _now() + PENDING_SECONDS
    return "Say your PIN."


def ask_pin() -> str | None:
    """Ask for the PIN now (voice ID backup). None = no PIN, or PIN blocked after wrong tries."""
    with _lock:
        if not has_pin() or _locked_out():
            return None
        return _ask()


def cancel_pending() -> None:
    """Stop waiting for a PIN (used when the AI's lookup was refused: there is nobody to ask)."""
    global _pending_until
    _pending_until = 0.0


def pending() -> bool:
    """True while Jarvis waits for a spoken PIN."""
    return _now() < _pending_until


def is_locked() -> bool:
    return _locked


def is_guest() -> bool:
    return _guest


def check(intent, args: dict | None = None) -> str | None:
    """Call before running an intent. None = go ahead.

    Otherwise a sentence to say. If pending() is then True, listen and call verify().
    """
    intent, args = _intent_args(intent, args)
    with _lock:
        if not has_pin():
            return None  # nothing to protect with; lock / guest mode refuse in their handlers
        state = str(args.get("state") or "").lower()

        if _locked:
            if _locked_out():
                return f"Jarvis is locked. Too many wrong PINs. Try again in {_minutes_left()} minutes."
            if intent == "jarvis_lock" and state in ("off", "") and args.get("pin"):
                return None  # the handler checks the PIN in the sentence
            return "Jarvis is locked. " + _ask()

        if intent == "jarvis_lock":
            return None  # locking is free; not locked, so "unlock" just says so
        if intent == "guest_mode":
            if state == "off" and _guest:
                if _locked_out():
                    return f"Too many wrong PINs. Try again in {_minutes_left()} minutes."
                return _ask()
            return None

        restricted = _guest or _locked_out()
        if restricted and intent not in _ALWAYS and intent not in _cfg()["guest"]:
            if _locked_out():
                return f"Too many wrong PINs. I can only do simple things for {_minutes_left()} minutes."
            return "Guest mode is on, so I can't do that."

        if _protected(intent, args):
            if _now() < _grace_until:
                return None
            return _ask()
    return None


def _wrong_pin() -> str:
    global _wrong, _lockout_until
    _wrong += 1
    max_tries = _cfg()["max_tries"]
    log.warning("wrong PIN (%d/%d)", _wrong, max_tries)  # never the PIN itself
    if _wrong >= max_tries:
        _wrong = 0
        _lockout_until = _now() + _cfg()["lockout"]
        return f"Wrong PIN. Too many tries. PIN is blocked for {_minutes_left()} minutes."
    left = max_tries - _wrong
    return f"Wrong PIN. {left} {'try' if left == 1 else 'tries'} left."


def _right_pin() -> None:
    global _wrong, _locked, _auth_until, _grace_until
    _wrong = 0
    _locked = False
    _auth_until = _now() + AUTH_SECONDS
    if _cfg()["grace"]:
        _grace_until = _now() + _cfg()["grace"]
    log.info("PIN accepted")


def _try_pin(spoken) -> tuple[bool, str]:
    if _locked_out():
        return False, f"PIN is blocked. Try again in {_minutes_left()} minutes."
    pin = spoken_digits(spoken)
    if not pin:
        return False, "I didn't hear a PIN. Cancelled."
    if _check_hash(pin, _stored_hash()):
        _right_pin()
        return True, "PIN accepted."
    return False, _wrong_pin()


def verify(spoken) -> tuple[bool, str]:
    """Check the PIN heard after check() asked for it. Returns (ok, reply)."""
    global _pending_until
    with _lock:
        if not pending():
            return False, "I wasn't waiting for a PIN."
        _pending_until = 0.0
        if spoken is None or not str(spoken).strip():
            return False, "I didn't hear a PIN. Cancelled."
        return _try_pin(spoken)


def _authorized() -> bool:
    return _now() < _auth_until


def reset() -> None:
    """Forget all state (tests, or a fresh start)."""
    global _settings, _locked, _guest, _wrong, _lockout_until, _pending_until, _auth_until, _grace_until
    with _lock:
        _settings = None
        _locked = _guest = False
        _wrong = 0
        _lockout_until = _pending_until = _auth_until = _grace_until = 0.0


# ---------- handlers ----------

_NO_PIN = "Set a PIN first: run 'python -m jarvis.actions.security set-pin' on the laptop."


def jarvis_lock(args: dict) -> str:
    global _locked, _auth_until
    state = str(args.get("state") or "on").lower()
    with _lock:
        if state == "status":
            return "Jarvis is locked." if _locked else "Jarvis is not locked."
        if not has_pin():
            return _NO_PIN
        if state == "on":
            _locked = True
            _auth_until = 0.0
            _clear_grace()
            log.info("Jarvis locked")
            return "Jarvis is locked. Say your PIN to unlock."
        # off
        if args.get("pin"):
            ok, reply = _try_pin(args.get("pin"))
            return "Jarvis is unlocked." if ok else reply
        if _locked and not _authorized():
            return "Say 'unlock Jarvis' and then your PIN."
        _locked = False
        _auth_until = 0.0
        return "Jarvis is unlocked."


def _clear_grace() -> None:
    global _grace_until
    _grace_until = 0.0


def guest_mode(args: dict) -> str:
    global _guest, _auth_until
    state = str(args.get("state") or "on").lower()
    with _lock:
        if state == "status":
            return "Guest mode is on." if _guest else "Guest mode is off."
        if state == "on":
            if not has_pin():
                return _NO_PIN
            _guest = True
            _clear_grace()
            log.info("guest mode on")
            return "Guest mode is on. I'll only do simple things like time and weather."
        if not _guest:
            return "Guest mode is already off."
        if not _authorized():
            return "Turning guest mode off needs your PIN."
        _guest = False
        _auth_until = 0.0
        log.info("guest mode off")
        return "Guest mode is off."


_STATE = {"type": "string", "enum": ["on", "off", "status"]}

CATALOG: dict[str, dict] = {
    "jarvis_lock": {"description": "Lock Jarvis so only the owner's spoken PIN works (on), unlock it (off), "
                                   "or say if it is locked (status). Never guess or invent a PIN.",
                    # no "pin" here: a PIN must never go through the AI (it would be sent to the cloud
                    # and kept in the chat memory). Only the offline rules and verify() handle PINs.
                    "properties": {"state": _STATE},
                    "required": ["state"]},
    "guest_mode": {"description": "Guest mode: only safe things (time, weather, music...) work. "
                                  "on, off (needs the owner's PIN), or status.",
                   "properties": {"state": _STATE}, "required": ["state"]},
}

HANDLERS = {"jarvis_lock": jarvis_lock, "guest_mode": guest_mode}


def _main(argv: list[str]) -> int:
    if argv[:1] != ["set-pin"]:
        print("Usage: python -m jarvis.actions.security set-pin")
        return 2
    pin = getpass.getpass(f"New PIN ({PIN_MIN}-{PIN_MAX} digits): ").strip()
    if getpass.getpass("Type it again: ").strip() != pin:
        print("PINs do not match. Nothing saved.")
        return 1
    try:
        stored = save_pin(pin)
    except ValueError as e:
        print(e)
        return 1
    print(f"Saved (hashed) to {_cfg()['pin_file']}.")
    print("Or put this in config.yaml under security:")
    print(f"  pin_hash: \"{stored}\"")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
