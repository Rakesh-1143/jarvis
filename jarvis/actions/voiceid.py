"""Owner voice check (piece BU): know who is speaking before risky actions.

  "learn my voice"       -> needs your PIN; you say 5 short sentences; a voice print is saved on this PC
  "who am I"             -> "You sound like my owner." / "I don't know this voice."
  "voice lock on"        -> risky commands need the owner's voice (the PIN still works as a backup)
  "voice lock off"       -> needs the owner's voice or the PIN
  "forget my voice"      -> risky: asks "are you sure?", then deletes the voice print (lock turns off)

Rules (work WITH security.py, never around it):
- A PIN must exist first. The first PIN is never set by voice here; "learn my voice" without a PIN says
  how to make one. Enrolling (also re-enrolling) always needs the PIN, never just a voice match.
- The owner's voice only replaces the PIN prompt for protected intents. It never unlocks a locked Jarvis,
  never turns guest mode off and never runs setup. Lockout after wrong PINs still applies.
- The voice print (256 numbers, not a recording) stays in ~/.jarvis/voiceid.json. It is never uploaded.
  No recording is kept on disk; the last command's audio lives in memory for AUDIO_SECONDS only.

Needs `pip install resemblyzer` (CPU, pulls in numpy + torch). Without it, the intents say so.

Settings (optional) in config.yaml:
  voiceid:
    threshold: 0.75          # 0..1; higher = stricter
    file: "~/.jarvis/voiceid.json"
    samples: 5               # sentences said when enrolling

main.py wiring (see wiring-notes/BU-voiceid.md):
    voiceid.set_io(io.say, voice=not args.text)   # so "learn my voice" can talk
    voiceid.remember_audio(pcm)                   # after each command is heard (16 kHz 16-bit mono)
    blocked = voiceid.guard(cmd, io, security, risky)   # instead of _security_ok(cmd, io, actions)
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time

log = logging.getLogger("jarvis.voiceid")

_now = time.monotonic  # tests patch this

SAMPLE_RATE = 16000
DEFAULT_FILE = "~/.jarvis/voiceid.json"
DEFAULT_THRESHOLD = 0.75
DEFAULT_SAMPLES = 5
MIN_SECONDS = 1.0        # shorter audio can't be checked reliably
SAMPLE_SECONDS = 4.0     # each enrolment sentence is recorded this long
AUDIO_SECONDS = 30       # the last command's audio is only trusted this long
OWNER_SECONDS = 15       # after a voice match, "voice lock off" may run this long
SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Jarvis, open my email and check the weather.",
    "I would like a cup of tea at four o'clock.",
    "Please remind me to call my family tomorrow.",
    "Seven bright stars shine above the quiet city.",
    "Turn up the music and play something relaxing.",
    "My laptop battery is low, so plug in the charger.",
]

# the voice must never replace the PIN for these (security.py decides them alone)
# The PIN is still needed for these, even when the owner's voice matches: a recording of the owner
# (voice note, video) also matches, and these do the most harm (review K2).
_PIN_ONLY = {"jarvis_lock", "guest_mode", "setup", "voice_id", "software", "empty_recycle_bin", "delete_file",
             "contact_add"}
_PIN_ONLY_ACTIONS = {("voice_id", "enrol"), ("device", "unlock"), ("device", "open"), ("phone", "sms"),
                     ("dev", "git_push")}
MAX_VOICE_FAILS = 3  # failed voice matches in a row -> the PIN is needed until a right PIN is given
_voice_fails = 0
# intent:action list for security.protect (the wiring thread adds these to DEFAULT_PROTECT)
PROTECT = ["voice_id:enrol", "voice_id:off", "voice_id:forget"]

NOT_INSTALLED = "Voice ID needs the resemblyzer package. Run: pip install resemblyzer"
NO_PIN = "Set a PIN first: run 'python -m jarvis.actions.security set-pin' on the laptop. Then say 'learn my voice'."
NOT_ENROLLED = "I don't know your voice yet. Say 'learn my voice' first."

_lock = threading.RLock()
_settings: dict | None = None
_lock_on = False
_audio: bytes = b""
_audio_at = -1e18
_owner_until = 0.0
_encoder = None
_say = print
_voice = True

# tests replace these
_record = None   # (seconds) -> bytes ; None = microphone


# ---------- settings and storage ----------

def configure(cfg: dict | None = None) -> None:
    """Load settings. None = read config.yaml. Tests pass a dict."""
    global _settings
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config().get("voiceid") or {}
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    try:
        threshold = float(cfg.get("threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    if not 0.5 <= threshold <= 0.99:  # a very low threshold lets anyone in
        log.warning("voiceid.threshold %r out of range 0.5-0.99; using %s", cfg.get("threshold"), DEFAULT_THRESHOLD)
        threshold = DEFAULT_THRESHOLD
    try:
        samples = max(3, min(len(SENTENCES), int(cfg.get("samples", DEFAULT_SAMPLES))))
    except (TypeError, ValueError):
        samples = DEFAULT_SAMPLES
    with _lock:
        _settings = {
            "threshold": threshold,
            "file": os.path.expanduser(str(cfg.get("file") or DEFAULT_FILE)),
            "samples": samples,
        }


def _cfg() -> dict:
    if _settings is None:
        configure()
    return _settings  # type: ignore[return-value]


def _load_print() -> list[float] | None:
    try:
        with open(_cfg()["file"], encoding="utf-8") as f:
            data = json.load(f)
        emb = [float(x) for x in data["embedding"]]
        return emb if len(emb) >= 16 and all(math.isfinite(x) for x in emb) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_print(emb: list[float], samples: int) -> None:
    path = _cfg()["file"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # biometric data: owner only
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"embedding": [round(x, 6) for x in emb], "samples": samples,
                   "created": time.strftime("%Y-%m-%d %H:%M")}, f)
    os.replace(tmp, path)


def enrolled() -> bool:
    return _load_print() is not None


def is_on() -> bool:
    """Voice lock is on and a voice print exists."""
    return _lock_on and enrolled()


def reset() -> None:
    """Forget all state (tests, or a fresh start). Does not delete the voice print."""
    global _settings, _lock_on, _audio, _audio_at, _owner_until, _encoder, _say, _voice, _record
    with _lock:
        _settings = None
        _lock_on = False
        _audio, _audio_at, _owner_until = b"", -1e18, 0.0
        globals()["_voice_fails"] = 0
        _encoder = None
        _say, _voice, _record = print, True, None


def set_io(say, voice: bool = True) -> None:
    """main.py: voiceid.set_io(io.say, voice=not args.text). Text mode can't enrol (no mic)."""
    global _say, _voice
    _say, _voice = say, bool(voice)


# ---------- audio and embeddings ----------

def remember_audio(pcm: bytes | None) -> None:
    """main.py: the audio of the command just heard (16 kHz, 16-bit, mono). None/b'' clears it."""
    global _audio, _audio_at
    with _lock:
        _audio = bytes(pcm or b"")
        _audio_at = _now() if _audio else -1e18


def clear_audio() -> None:
    remember_audio(None)


def _last_audio() -> bytes:
    with _lock:
        if _now() - _audio_at > AUDIO_SECONDS:
            return b""
        return _audio


def _seconds(pcm: bytes) -> float:
    return len(pcm) / 2 / SAMPLE_RATE


def _get_encoder():
    """resemblyzer VoiceEncoder, loaded once. Raises ImportError if not installed."""
    global _encoder
    if _encoder is None:
        from resemblyzer import VoiceEncoder  # type: ignore

        _encoder = VoiceEncoder("cpu", verbose=False)
    return _encoder


def embed(pcm: bytes) -> list[float]:
    """Voice print of one recording (unit length). Raises ImportError if resemblyzer is missing."""
    import numpy as np  # comes with resemblyzer
    from resemblyzer import preprocess_wav  # type: ignore

    wav = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16).astype(np.float32) / 32768.0
    wav = preprocess_wav(wav, source_sr=SAMPLE_RATE)  # trims silence, normalises volume
    return [float(x) for x in _get_encoder().embed_utterance(wav)]


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity, -1..1."""
    if not a or len(a) != len(b):
        return 0.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def verify(pcm: bytes | None) -> tuple[bool, float]:
    """(is_owner, score). False when not enrolled, audio too short, or resemblyzer missing."""
    owner = _load_print()
    if owner is None or not pcm or _seconds(pcm) < MIN_SECONDS:
        return False, 0.0
    try:
        score = similarity(embed(pcm), owner)
    except ImportError:
        log.warning("resemblyzer not installed; voice check fails closed")
        return False, 0.0
    except Exception as e:  # a broken mic buffer must not crash the command loop
        log.warning("voice check failed: %s", e)
        return False, 0.0
    ok = score >= _cfg()["threshold"]
    log.info("voice check: %s (score %.2f)", "owner" if ok else "not owner", score)  # never the audio
    return ok, score


def owner_spoke() -> bool:
    """True if the last command's audio is the owner's voice. Opens the short 'owner' window.
    After MAX_VOICE_FAILS failed matches in a row, always False until a right PIN (pin_ok)."""
    global _owner_until, _voice_fails
    if _voice_fails >= MAX_VOICE_FAILS:
        return False
    ok, score = verify(_last_audio())
    with _lock:
        if ok:
            _owner_until = _now() + OWNER_SECONDS
            _voice_fails = 0
        elif score > 0:  # a real voice that did not match (no audio = not a try)
            _voice_fails += 1
    return ok


def pin_ok() -> None:
    """A right PIN was given: voice matches count again."""
    global _voice_fails
    _voice_fails = 0


def _record_mic(seconds: float) -> bytes:
    """Record `seconds` of 16 kHz mono audio from the default mic."""
    from jarvis import stt

    out = bytearray()
    need = int(seconds * SAMPLE_RATE) * 2
    chunks = stt._mic_chunks()
    try:
        for chunk in chunks:
            out += chunk
            if len(out) >= need:
                break
    finally:
        chunks.close()
    return bytes(out)


def _rec(seconds: float) -> bytes:
    return (_record or _record_mic)(seconds)


# ---------- security helpers ----------

def _security():
    try:
        from jarvis.actions import security

        return security
    except Exception:
        return None


def _pin_recent(security) -> bool:
    """A right PIN was given a moment ago (security.check asked it just before this handler)."""
    if security is None:
        return False
    try:
        now = security._now()
        return now < getattr(security, "_auth_until", 0.0) or now < getattr(security, "_grace_until", 0.0)
    except Exception:
        return False


def _has_pin(security) -> bool:
    try:
        return bool(security is not None and security.has_pin())
    except Exception:
        return False


def _intent_args(cmd) -> tuple[str, dict]:
    intent = str(getattr(cmd, "intent", "") or "").lower()
    args = getattr(cmd, "args", None)
    return intent, (args if isinstance(args, dict) else {})


def _voice_may_replace_pin(intent: str, args: dict, security) -> bool:
    if not is_on() or intent in _PIN_ONLY:
        return False
    if (intent, str(args.get("action") or "").lower()) in _PIN_ONLY_ACTIONS:
        return False
    try:
        if security.is_locked():  # a locked Jarvis opens only with the PIN
            return False
    except Exception:
        return False
    return True


def guard(cmd, io, security, risky: bool = False) -> str | None:
    """Replaces main._security_ok when voice ID is wired. None = go ahead, else the reply to give.

    risky: main.py's _needs_confirm(cmd, ...) (commands that ask "are you sure?").
    Order: security.check first (lock, guest mode and lockout always win). Then:
      - security wants the PIN and voice lock is on -> the owner's voice may replace it
      - voice lock is on and the command is risky -> the owner's voice, or the PIN as a backup
    """
    if security is None:
        return None
    intent, args = _intent_args(cmd)
    msg = security.check(cmd)
    pin_prompt = bool(msg) and security.pending()
    if msg and not pin_prompt:
        return msg  # blocked: guest mode / lockout
    no_ask = getattr(io, "no_ask", False)

    if pin_prompt:
        if not no_ask and _voice_may_replace_pin(intent, args, security) and owner_spoke():
            security.cancel_pending()
            return None
    elif risky and is_on() and intent not in ("confirm", "cancel"):
        if not no_ask and owner_spoke():
            return None
        ask = getattr(security, "ask_pin", None)  # added to security.py by the wiring thread
        prompt = ask() if (ask is not None and not no_ask) else None
        if not prompt:
            return "That needs the owner's voice."
        msg, pin_prompt = "I don't know this voice. " + prompt, True

    if not msg:
        return None
    if no_ask:  # background trigger: nobody to ask
        security.cancel_pending()
        return msg
    io.say(msg)  # "Say your PIN."
    ok, reply = security.verify(io.listen())  # the PIN never goes to the log or history
    if ok:
        pin_ok()
    return None if ok else reply


# ---------- confirm step (actions/__init__.py _risky_text) ----------

def needs_confirm(args: dict) -> bool:
    return str((args or {}).get("action") or "").lower() == "forget" and enrolled()


def risky_text(args: dict) -> str | None:
    if not needs_confirm(args):
        return None  # nothing to forget: the handler says so
    return "forget your voice print (voice lock turns off)"


# ---------- handler ----------

def _enrol(security) -> str:
    global _lock_on
    if not _has_pin(security):
        return NO_PIN  # the first PIN is never set by voice
    if not _pin_recent(security):
        return "Learning your voice needs your PIN. Say 'learn my voice' again and then your PIN."
    if not _voice:
        return "Learning your voice needs the microphone. Start Jarvis without --text."
    try:
        _get_encoder()
    except ImportError:
        return NOT_INSTALLED
    except Exception as e:
        log.warning("voice encoder failed to load: %s", e)
        return "I couldn't load the voice model. Check the log."
    n = _cfg()["samples"]
    _say(f"I'll learn your voice. Read {n} sentences after me, one at a time, in your normal voice.")
    prints = []
    for i, sentence in enumerate(SENTENCES[:n], 1):
        _say(f"Sentence {i}: {sentence}")
        try:
            pcm = _rec(SAMPLE_SECONDS)
            if _seconds(pcm) < MIN_SECONDS:
                raise ValueError("too short")
            prints.append(embed(pcm))
        except Exception as e:
            log.warning("enrol sample %d failed: %s", i, e)
            return "I couldn't record that. Check the microphone and say 'learn my voice' again."
    mean = _unit([sum(col) / len(prints) for col in zip(*prints)])
    # a sample far from the others means noise or a different speaker: don't save a weak print
    if min(similarity(p, mean) for p in prints) < 0.6:
        return "The recordings didn't match each other. Find a quiet place and say 'learn my voice' again."
    try:
        _save_print(mean, len(prints))
    except OSError as e:
        log.warning("could not save voice print: %s", e)
        return "I couldn't save your voice print."
    with _lock:
        _lock_on = True
    log.info("voice print saved (%d samples)", len(prints))
    return "Got it. I know your voice now, and voice lock is on. Say 'voice lock off' to stop it."


def voice_id(args: dict) -> str:
    global _lock_on, _owner_until
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "check").lower()
    security = _security()

    if action == "enrol":
        return _enrol(security)

    if action == "check":
        if not enrolled():
            return NOT_ENROLLED
        pcm = _last_audio()
        if not pcm:
            return "I need to hear you say it. Ask me by voice."
        ok, score = verify(pcm)
        if score == 0.0 and not ok:
            try:
                _get_encoder()
            except ImportError:
                return NOT_INSTALLED
            except Exception:
                pass
        return "You sound like my owner." if ok else "I don't know this voice."

    if action == "status":
        if not enrolled():
            return NOT_ENROLLED
        return "Voice lock is on." if _lock_on else "Voice lock is off. I know your voice."

    if action == "on":
        if not enrolled():
            return NOT_ENROLLED
        if not _has_pin(security):
            return NO_PIN  # the PIN is the backup; without it the owner could be locked out
        with _lock:
            _lock_on = True
        log.info("voice lock on")
        return "Voice lock is on. Risky commands need your voice, or your PIN."

    if action == "off":
        if not _lock_on:
            return "Voice lock is already off."
        with _lock:
            owner = _now() < _owner_until
        if not (owner or _pin_recent(security)):
            return "Turning voice lock off needs your voice or your PIN."
        with _lock:
            _lock_on = False
            _owner_until = 0.0
        log.info("voice lock off")
        return "Voice lock is off."

    if action == "forget":
        if not enrolled():
            return "I don't have a voice print to forget."
        if not args.get("confirm"):
            return f"Do you want me to {risky_text(args)}? Say yes to confirm."
        try:
            os.remove(_cfg()["file"])
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("could not delete voice print: %s", e)
            return "I couldn't delete the voice print file."
        with _lock:
            _lock_on = False
            _owner_until = 0.0
        clear_audio()
        log.info("voice print deleted")
        return "I forgot your voice. Voice lock is off."

    return "I can learn your voice, check who is speaking, turn voice lock on or off, or forget your voice."


CATALOG: dict[str, dict] = {
    "voice_id": {
        "description": "Owner voice check. enrol = learn the owner's voice (needs the PIN); check = 'who am I', "
                       "is the speaker the owner; on/off = voice lock (risky commands need the owner's voice); "
                       "status; forget = delete the voice print (Jarvis asks the user to confirm).",
        "properties": {"action": {"type": "string",
                                  "enum": ["enrol", "check", "on", "off", "status", "forget"]}},
        "required": ["action"],
        "info": False,  # changes security settings: the AI must not run it during a lookup
    },
}

HANDLERS = {"voice_id": voice_id}
