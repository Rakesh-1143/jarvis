"""Text-to-speech. Uses pyttsx3 (offline), else the OS voice, else prints."""

from __future__ import annotations

import platform
import queue
import shutil
import subprocess
import threading


class Speaker:
    """Speaks text on one background thread, so reminders and replies never overlap."""

    def __init__(self, engine: str = "pyttsx3", rate: int = 180, on_print=print):
        self.engine_name = engine
        self.rate = rate
        self.on_print = on_print
        self._q: queue.Queue = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        threading.Thread(target=self._worker, daemon=True, name="jarvis-tts").start()

    def say(self, text: str, wait: bool = True) -> None:
        self.on_print(text)
        if self.engine_name == "print" or not text:
            return
        self._idle.clear()
        self._q.put(text)
        if wait:
            self.wait()

    def wait(self) -> None:
        self._idle.wait()

    def _system_say(self, text: str) -> bool:
        osname = platform.system()
        if osname == "Darwin":
            cmd = ["say", "-r", str(self.rate), text]
        elif osname == "Windows":
            safe = text.replace("'", "''")
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"]
        elif shutil.which("espeak-ng") or shutil.which("espeak"):
            cmd = [shutil.which("espeak-ng") or shutil.which("espeak"), "-s", str(self.rate), text]
        elif shutil.which("spd-say"):
            cmd = ["spd-say", "-w", text]
        else:
            return False
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def _worker(self) -> None:
        engine = None
        if self.engine_name == "pyttsx3":
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                # Prefer a male English voice if available (more "Jarvis").
                for v in engine.getProperty("voices"):
                    name = (v.name or "").lower()
                    if any(n in name for n in ("david", "daniel", "george", "male", "en-gb")):
                        engine.setProperty("voice", v.id)
                        break
            except Exception:
                engine = None
        while True:
            text = self._q.get()
            try:
                if engine is not None:
                    engine.say(text)
                    engine.runAndWait()
                else:
                    self._system_say(text)
            except Exception:
                pass
            finally:
                if self._q.empty():
                    self._idle.set()
