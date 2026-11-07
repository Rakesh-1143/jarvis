"""Voice replies (offline). Uses pyttsx3, which uses Windows SAPI on Windows."""
import queue
import sys
import threading

try:
    import pyttsx3
except ImportError:  # still works without speech: prints the reply
    pyttsx3 = None

_settings = {"rate": 180, "volume": 1.0, "voice": None}  # voice: part of a voice name, e.g. "Zira"

# All speech runs on ONE worker thread. pyttsx3 uses Windows COM (SAPI), and COM must be started in the
# thread that uses it. Timers, reminders and alerts call say() from their own threads; they hand the text
# to this worker instead of starting SAPI themselves. It also means only one voice speaks at a time.
_jobs: "queue.Queue[tuple]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _com_init() -> None:
    try:
        import comtypes  # installed with pyttsx3 on Windows

        comtypes.CoInitialize()
    except Exception:  # not Windows, or already started
        pass


def _work() -> None:
    _com_init()
    while True:
        fn, done, box = _jobs.get()
        try:
            box["result"] = fn()
        except Exception as e:  # never let the worker die
            box["error"] = e
        finally:
            done.set()


def _run(fn, timeout: float):
    """Run fn() on the speech thread and wait for it. Raises what fn raised."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="jarvis-tts", daemon=True)
            _worker.start()
    done, box = threading.Event(), {}
    _jobs.put((fn, done, box))
    if not done.wait(timeout):
        raise TimeoutError("speech took too long")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def configure(rate: int | None = None, volume: float | None = None, voice: str | None = None) -> None:
    """Optional. Change speed (words/min), volume (0.0-1.0) or voice name."""
    if rate is not None:
        _settings["rate"] = rate
    if volume is not None:
        _settings["volume"] = max(0.0, min(1.0, volume))
    if voice is not None:
        _settings["voice"] = voice


def list_voices() -> list[str]:
    """Names of installed voices."""
    if pyttsx3 is None:
        return []

    def names():
        engine = pyttsx3.init()
        try:
            return [v.name for v in engine.getProperty("voices")]
        finally:
            engine.stop()

    return _run(names, 30)


def _speak(text: str) -> None:
    # New engine each call: avoids a known pyttsx3 bug where the 2nd runAndWait hangs.
    engine = pyttsx3.init()
    engine.setProperty("rate", _settings["rate"])
    engine.setProperty("volume", _settings["volume"])
    if _settings["voice"]:
        for v in engine.getProperty("voices"):
            if _settings["voice"].lower() in v.name.lower():
                engine.setProperty("voice", v.id)
                break
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def _speak_sapi(text: str) -> None:
    """Backup voice for Windows: talk to SAPI directly (no pyttsx3 event loop). Runs on the speech thread."""
    import math

    import comtypes.client

    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    # words/minute -> SAPI rate -10..10 (same formula pyttsx3 uses)
    voice.Rate = max(-10, min(10, round(math.log(max(1, _settings["rate"]) / 156.63) / math.log(1.11))))
    voice.Volume = int(_settings["volume"] * 100)
    if _settings["voice"]:
        tokens = voice.GetVoices()
        for i in range(tokens.Count):
            if _settings["voice"].lower() in tokens.Item(i).GetDescription().lower():
                voice.Voice = tokens.Item(i)
                break
    voice.Speak(text, 0)  # 0 = wait until done


def _speak_any(text: str) -> None:
    """pyttsx3 first; on Windows, if it breaks, SAPI directly."""
    try:
        _speak(text)
    except Exception:
        if sys.platform != "win32":
            raise
        _speak_sapi(text)


def say(text: str) -> None:
    """Speak text and wait until done. Safe from any thread. Never raises."""
    if not text or not text.strip():
        return
    print(f"Jarvis: {text}")
    if pyttsx3 is None and sys.platform != "win32":
        return
    try:
        # Long texts (read aloud) need time: about 2 words per second, plus a margin.
        _run(lambda: _speak_any(text) if pyttsx3 is not None else _speak_sapi(text), 30 + len(text.split()))
    except Exception as e:  # no audio device, driver error, etc.
        print(f"[tts error] {e}")


if __name__ == "__main__":
    print("Voices:", list_voices())
    say("Hello, I am Jarvis. Voice replies are working.")
