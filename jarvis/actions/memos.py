"""Voice memos: record your own voice, list, play, delete (piece Q).

Says: "record a voice memo" (stops by itself when you go quiet), "play my last memo", "play memo 2",
"list my memos", "delete my last memo" (asks yes first), "open my memos folder".

Recording runs in a background thread, saved as WAV (16 kHz mono) in the memos folder.
It stops when you go quiet (silence_seconds), after max_seconds, or on stop_recording().
The mic is closed as soon as recording ends, so stt can listen again.

Wiring (main.py):
- while memos.is_recording(): do NOT call stt (wait_for_wake_word / listen). Sleep 0.2 s and loop.
- memos.set_notifier(io.say) at start: says "Memo saved, 12 seconds." when recording ends by itself.
- Optional: call memos.begin() right after speaking the "Recording..." reply, so the
  reply is not recorded. Without it, recording starts after `start_delay` seconds.
- `memo` with action "delete" is risky: use risky_text(args); handler never deletes without confirm=True.

Config (all optional), config.yaml:
  memos:
    folder: "~/Documents/Jarvis memos"
    max_seconds: 120       # hard stop
    silence_seconds: 3     # stop after this much quiet (after you started talking)
    no_speech_seconds: 8   # give up if nothing is said at all
    silence_level: 500     # loudness (0-32767) below which counts as quiet
    start_delay: 1.5       # wait before recording, if core does not call begin()
"""
from __future__ import annotations

import array
import math
import os
import queue
import re
import sys
import threading
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

SAMPLE_RATE = 16000
BLOCK_SIZE = 2000  # 0.125 s per chunk (same as stt)
CHUNK_SECONDS = BLOCK_SIZE / SAMPLE_RATE

DEFAULTS = {
    "folder": "~/Documents/Jarvis memos",
    "max_seconds": 120,
    "silence_seconds": 3,
    "no_speech_seconds": 8,
    "silence_level": 500,
    "start_delay": 1.5,
    "play_delay": 1.2,
}
SETTINGS: dict = {}  # empty = read config on first use (tests set this)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_begin = threading.Event()
_quiet_finish = False  # True when stop came from a command (reply already says it)
_last_result: dict = {}
_notify: Callable[[str], None] | None = None

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "first": 1, "second": 2, "third": 3,
                 "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
                 "tenth": 10}


# ---------- settings ----------
def _cfg() -> dict:
    global SETTINGS
    if not SETTINGS:
        try:
            from ..config import load_config

            SETTINGS = {**DEFAULTS, **(load_config().get("memos") or {})}
        except Exception:
            SETTINGS = dict(DEFAULTS)
    return {**DEFAULTS, **SETTINGS}


def folder() -> Path:
    return Path(os.path.expanduser(str(_cfg()["folder"])))


def set_notifier(fn: Callable[[str], None] | None) -> None:
    """Core passes io.say, so 'Memo saved' is spoken when recording ends by itself."""
    global _notify
    _notify = fn


def _say(text: str) -> None:
    if _notify:
        try:
            _notify(text)
        except Exception:
            pass


# ---------- microphone ----------
def _mic_chunks() -> Iterator[bytes]:
    """Yield raw 16-bit mono chunks from the default mic. Closing the generator frees the mic."""
    import sounddevice as sd

    q: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status):
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, dtype="int16",
                           channels=1, callback=callback):
        while True:
            yield q.get()


def _level(chunk: bytes) -> float:
    """Loudness (RMS) of one 16-bit chunk."""
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


# ---------- recording ----------
def _record(path: Path) -> None:
    """Thread body: wait for begin/start_delay, record until quiet/max/stop, save or discard."""
    global _last_result
    cfg = _cfg()
    result = {"path": None, "seconds": 0.0, "reason": ""}
    try:
        _begin.wait(float(cfg["start_delay"]))
        if _stop.is_set():
            result["reason"] = "cancelled"
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        seconds = quiet = 0.0
        heard = False
        chunks = _mic_chunks()
        try:
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                for chunk in chunks:
                    w.writeframes(chunk)
                    seconds += len(chunk) / 2 / SAMPLE_RATE
                    if _level(chunk) >= float(cfg["silence_level"]):
                        heard, quiet = True, 0.0
                    else:
                        quiet += len(chunk) / 2 / SAMPLE_RATE
                    if _stop.is_set():
                        result["reason"] = "stopped"
                        break
                    if seconds >= float(cfg["max_seconds"]):
                        result["reason"] = "max"
                        break
                    if heard and quiet >= float(cfg["silence_seconds"]):
                        result["reason"] = "silence"
                        break
                    if not heard and seconds >= float(cfg["no_speech_seconds"]):
                        result["reason"] = "nothing"
                        break
        finally:
            chunks.close()  # free the mic right away
        if not heard:
            _delete_file(path, trash=False)
            result["reason"] = "nothing"
        else:
            result.update(path=str(path), seconds=seconds)
    except Exception as e:  # no mic, no sounddevice, disk error...
        result["reason"] = f"error: {e}"
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    finally:
        _last_result = result
        if not _quiet_finish:
            msg = _finish_text(result)
            if msg:
                _say(msg)


def _finish_text(result: dict) -> str:
    reason = result.get("reason", "")
    if reason == "cancelled":
        return "Memo cancelled."
    if reason == "nothing":
        return "I didn't hear anything, so I didn't save a memo."
    if reason.startswith("error"):
        return "Sorry, I couldn't record. Please check the microphone."
    if result.get("path"):
        return f"Memo saved, {_say_len(result['seconds'])}."
    return ""


def is_recording() -> bool:
    """True while a memo is being recorded. Core must not use the mic then."""
    return _thread is not None and _thread.is_alive()


def begin() -> None:
    """Start recording now (core calls this right after speaking the 'Recording' reply)."""
    _begin.set()


def start_recording() -> str:
    global _thread, _quiet_finish
    with _lock:
        if is_recording():
            return "I'm already recording a memo."
        _stop.clear()
        _begin.clear()
        _quiet_finish = False
        name = datetime.now().strftime("memo-%Y%m%d-%H%M%S.wav")
        path = folder() / name
        _thread = threading.Thread(target=_record, args=(path,), name="jarvis-memo", daemon=True)
        _thread.start()
    return "Recording. Go ahead, I'll stop when you go quiet."


def stop_recording(timeout: float = 3.0) -> dict:
    """Stop the current recording and wait for the file. Returns the result dict."""
    global _quiet_finish
    t = _thread
    if t is None or not t.is_alive():
        return {}
    _quiet_finish = True
    _stop.set()
    _begin.set()
    t.join(timeout)
    return dict(_last_result)


# ---------- memo files ----------
def _memos() -> list[Path]:
    """All memo files, newest first."""
    f = folder()
    if not f.is_dir():
        return []
    files = [p for p in f.iterdir() if p.is_file() and p.suffix.lower() == ".wav"]
    return sorted(files, key=lambda p: (_when(p), p.name), reverse=True)


def _when(p: Path) -> datetime:
    m = re.match(r"memo-(\d{8}-\d{6})", p.stem)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(p.stat().st_mtime)


def _seconds(p: Path) -> float:
    try:
        with wave.open(str(p), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def _say_len(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} second{'s' if s != 1 else ''}"
    m, s = divmod(s, 60)
    out = f"{m} minute{'s' if m != 1 else ''}"
    return out + (f" {s} second{'s' if s != 1 else ''}" if s else "")


def _say_when(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    clock = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == now.date():
        return f"today at {clock}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"yesterday at {clock}"
    return f"{dt.strftime('%B')} {dt.day} at {clock}"


def _pick(which, files: list[Path]) -> Path | None:
    """'last'/None -> newest, 'first'/'oldest' -> oldest, '2'/'second'/'memo 2' -> 2nd newest."""
    if not files:
        return None
    w = str(which or "last").lower().strip(" .!?")
    w = re.sub(r"^(the|my)\s+", "", w)
    w = re.sub(r"\s+(one|memo)$", "", w)
    w = re.sub(r"^(memo|number)\s+(number\s+)?", "", w).strip()
    if w in ("", "last", "latest", "newest", "recent", "most recent", "new", "this", "that"):
        return files[0]
    if w in ("previous", "one before", "before last", "second last", "second to last"):
        return files[1] if len(files) > 1 else None
    if w in ("first", "oldest", "earliest"):
        return files[-1]
    n = int(w) if w.isdigit() else _NUMBER_WORDS.get(w)
    if n and 1 <= n <= len(files):
        return files[n - 1]
    return None


def _describe(p: Path) -> str:
    return f"your memo from {_say_when(_when(p))}"


def _delete_file(path: Path, trash: bool = True) -> None:
    if trash:
        try:
            from send2trash import send2trash

            send2trash(str(path))
            return
        except ImportError:
            pass
    path.unlink()


# ---------- playback ----------
def _play_file(path: Path) -> None:
    """Play a WAV without a window (winsound), else open in the default player."""
    try:
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    except ImportError:
        pass
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        raise OSError("no audio player")


def _stop_playing() -> bool:
    try:
        import winsound

        winsound.PlaySound(None, 0)
        return True
    except ImportError:
        return False


def _open_folder(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        raise OSError("can't open folders here")


# ---------- handler ----------
def memo(args: dict) -> str:
    action = str(args.get("action") or "record").lower().strip()
    which = args.get("which")

    if action in ("record", "start", "new"):
        return start_recording()

    if action in ("stop", "end", "finish", "cancel"):
        if is_recording():
            res = stop_recording()
            return _finish_text(res) or "Stopped recording."
        if _stop_playing():
            return "Stopped."
        return "I'm not recording a memo."

    if is_recording() and action in ("play", "delete"):
        return "I'm recording a memo right now. It stops when you go quiet."

    files = _memos()

    if action in ("list", "count", "read"):
        if not files:
            return "You have no voice memos."
        n = len(files)
        parts = [f"{i}: {_say_when(_when(p))}, {_say_len(_seconds(p))}" for i, p in enumerate(files[:5], 1)]
        more = f" and {n - 5} older" if n > 5 else ""
        return f"You have {n} voice memo{'s' if n != 1 else ''}. " + "; ".join(parts) + more + "."

    if action == "open":
        f = folder()
        try:
            f.mkdir(parents=True, exist_ok=True)
            _open_folder(f)
        except OSError:
            return f"Your memos are in {f}."
        return "Opening your memos folder."

    if action in ("play", "delete"):
        if not files:
            return "You have no voice memos."
        p = _pick(which, files)
        pinned = str(args.get("path") or "")
        if action == "delete" and pinned:  # the memo named in "are you sure?"
            p = next((f for f in files if str(f) == pinned), None)
        if p is None:
            return f"I couldn't find that memo. You have {len(files)}."
        if action == "play":
            delay = float(_cfg()["play_delay"])
            threading.Timer(delay, _safe_play, args=(p,)).start()  # after the reply is spoken
            return f"Playing {_describe(p)}."
        if not args.get("confirm"):
            return f"Are you sure you want to delete {_describe(p)}?"
        try:
            _delete_file(p)
        except OSError:
            return "Sorry, I couldn't delete that memo."
        return f"Deleted {_describe(p)}."

    return "I can record, play, list, or delete voice memos."


def _safe_play(p: Path) -> None:
    try:
        _play_file(p)
    except Exception:
        _say("Sorry, I couldn't play that memo.")


def needs_confirm(args: dict) -> bool:
    return str(args.get("action") or "").lower() == "delete"


def risky_text(args: dict) -> str | None:
    """Words for 'are you sure you want to ...?' (only for action=delete), else None."""
    if not needs_confirm(args):
        return None
    p = _pick(args.get("which"), _memos())
    if p:
        args["path"] = str(p)  # remember exactly this file, so "yes" deletes it even if a new memo arrives
    return f"delete {_describe(p)}" if p else "delete that memo"


CATALOG: dict[str, dict] = {
    "memo": {
        "description": ("Voice memos in the user's own voice. record = start recording (stops when "
                        "the user goes quiet), stop = stop recording or playback, play = play a memo, "
                        "list = say what memos exist, delete = delete one (Jarvis asks to confirm), "
                        "open = open the memos folder."),
        "properties": {
            "action": {"type": "string", "enum": ["record", "stop", "play", "list", "delete", "open"]},
            "which": {"type": "string",
                      "description": "Which memo: last (default), first, previous, or a number (1 = newest)."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"memo": memo}
