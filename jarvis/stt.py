"""Speech input (offline). Uses Vosk + the microphone (sounddevice).

    listen(timeout=5) -> str | None    record one phrase, return text (lowercase)
    wait_for_wake_word("jarvis")       block until the wake word is heard

The Vosk model is downloaded once (~40 MB) to the path in config.yaml (stt.model_path)
if it is missing.
"""
from __future__ import annotations

import array
import json
import queue
import time
import urllib.request
import zipfile
import logging
from pathlib import Path
from typing import Iterator

SAMPLE_RATE = 16000
BLOCK_SIZE = 2000  # 0.125 s of audio per chunk (smaller = reacts faster)
MAX_PHRASE_SECONDS = 15  # hard stop for one command
MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"
log = logging.getLogger("jarvis.stt")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Words Vosk often hears instead of "jarvis" (used only if "jarvis" is not in the model).
# Not "service" / "harvest": common words that woke Jarvis by mistake.
SOUND_ALIKES = {"jarvis": ["jarvis", "jervis", "jarvi", "travis"]}

_model = None


# ---------- model ----------

def _model_path() -> Path:
    try:
        from jarvis.config import load_config

        path = load_config()["stt"]["model_path"]
    except Exception:
        path = "models/vosk-model-small-en-us-0.15"
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def _download_model(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    zip_file = path.parent / (path.name + ".zip.part")
    print(f"Downloading speech model to {path} (one time, ~40 MB)...")
    try:
        urllib.request.urlretrieve(MODEL_URL.format(name=path.name), zip_file)
        with zipfile.ZipFile(zip_file) as z:  # raises BadZipFile if the download was cut off
            z.extractall(path.parent)
    except Exception as e:
        raise RuntimeError(
            f"Could not download the speech model ({e}). Connect to the internet and start Jarvis again, "
            f"or download {MODEL_URL.format(name=path.name)} and unzip it into {path.parent}.") from e
    finally:
        zip_file.unlink(missing_ok=True)  # never leave a broken zip behind


def _short_path(path: Path) -> str:
    """Vosk on Windows can't open paths with non-English letters (e.g. in the user name).
    Use the old 8.3 short path for those."""
    p = str(path)
    if p.isascii():
        return p
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024):  # type: ignore[attr-defined]
            return buf.value
    except Exception:  # not Windows
        pass
    return p


def get_model():
    """Load the Vosk model once and reuse it."""
    global _model
    if _model is None:
        import vosk

        vosk.SetLogLevel(-1)  # hide Vosk debug logs
        path = _model_path()
        if not path.exists():
            _download_model(path)
        _model = vosk.Model(_short_path(path))
    return _model


def _recognizer(grammar: list[str] | None = None):
    import vosk

    model = get_model()
    if grammar:
        return vosk.KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar))
    return vosk.KaldiRecognizer(model, SAMPLE_RATE)


# ---------- microphone ----------

def _mic_rate(sd) -> int:
    """16000 if the mic accepts it. Some Windows mics/drivers only take their own rate (often 48000):
    then we record at that rate and convert to 16000 ourselves."""
    try:
        sd.check_input_settings(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        return SAMPLE_RATE
    except Exception:
        try:
            rate = int(sd.query_devices(kind="input")["default_samplerate"])
            return rate if rate > 0 else SAMPLE_RATE
        except Exception:
            return SAMPLE_RATE


def resample(data: bytes, src_rate: int, dst_rate: int = SAMPLE_RATE) -> bytes:
    """16-bit mono audio from src_rate to dst_rate (simple linear interpolation; good enough for speech)."""
    if src_rate == dst_rate or not data:
        return data
    src = array.array("h")
    src.frombytes(data[: len(data) - len(data) % 2])
    n = len(src)
    if n < 2:
        return data
    out_n = max(1, int(n * dst_rate / src_rate))
    step = (n - 1) / max(1, out_n - 1)
    out = array.array("h", bytes(2 * out_n))
    for i in range(out_n):
        pos = i * step
        j = int(pos)
        frac = pos - j
        a = src[j]
        b = src[j + 1] if j + 1 < n else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


def _mic_chunks() -> Iterator[bytes]:
    """Yield raw 16-bit mono 16 kHz audio chunks from the default microphone."""
    import sounddevice as sd

    q: queue.Queue[bytes] = queue.Queue()
    rate = _mic_rate(sd)
    if rate != SAMPLE_RATE:
        log.info("mic does not take %d Hz; recording at %d Hz and converting", SAMPLE_RATE, rate)

    def callback(indata, frames, time_info, status):
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=rate, blocksize=int(BLOCK_SIZE * rate / SAMPLE_RATE), dtype="int16",
                           channels=1, callback=callback):
        while True:
            chunk = q.get()
            yield chunk if rate == SAMPLE_RATE else resample(chunk, rate)


def _text(result_json: str, key: str = "text") -> str:
    return json.loads(result_json).get(key, "").replace("[unk]", "").strip().lower()


# ---------- public API ----------

last_audio: bytes = b""          # audio of the last listen() (16 kHz 16-bit mono), for voice ID
LAST_AUDIO_MAX = 15 * 16000 * 2  # keep at most the last 15 seconds


def listen(timeout: float = 5) -> str | None:
    """Record one phrase. Returns the text, or None if nothing was said within `timeout` seconds."""
    global last_audio
    rec = _recognizer()
    start = time.monotonic()
    heard_something = False
    buf = bytearray()
    chunks = _mic_chunks()
    try:
        for chunk in chunks:
            buf += chunk
            if len(buf) > 2 * LAST_AUDIO_MAX:
                del buf[:-LAST_AUDIO_MAX]
            now = time.monotonic() - start
            if rec.AcceptWaveform(chunk):  # Vosk found the end of a phrase (a pause)
                text = _text(rec.Result())
                if text:
                    return text
            elif _text(rec.PartialResult(), "partial"):
                heard_something = True
            if not heard_something and now > timeout:
                return None
            if now > timeout + MAX_PHRASE_SECONDS:
                break
        return _text(rec.FinalResult()) or None
    finally:
        last_audio = bytes(buf[-LAST_AUDIO_MAX:])
        chunks.close()  # closes the microphone


def wait_for_wake_word(word: str = "jarvis") -> None:
    """Block until `word` is heard."""
    word = word.lower().strip()
    model = get_model()
    in_vocab = all(model.vosk_model_find_word(w) != -1 for w in word.split())
    if in_vocab:
        # Small grammar: fast and few false wakes.
        rec = _recognizer([word, "hey " + word, "[unk]"])
        targets = [word]
        fallback = False
    else:
        rec = _recognizer()
        targets = SOUND_ALIKES.get(word, [word])
        fallback = True

    chunks = _mic_chunks()
    try:
        for chunk in chunks:
            if rec.AcceptWaveform(chunk):
                text = _text(rec.Result())
            elif fallback:
                continue  # sound-alike words: only trust final results, not guesses mid-word
            else:
                text = _text(rec.PartialResult(), "partial")
            hit = next((t for t in targets if t in text.split()), None)
            if hit:
                log.info("woke on %r (heard %r)", hit, text)
                return
    finally:
        chunks.close()


if __name__ == "__main__":  # quick test: python -m jarvis.stt
    print("Say 'jarvis'...")
    wait_for_wake_word()
    print("Heard it. Now say a command...")
    print("You said:", listen())
