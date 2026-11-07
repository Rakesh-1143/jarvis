"""Wake word detection.

- "openwakeword": free offline model that listens for "Hey Jarvis".
- "text": fallback. Transcribes short clips and checks for the word "jarvis".
"""

from __future__ import annotations

import re


class OpenWakeWord:
    def __init__(self, threshold: float = 0.5):
        import openwakeword
        from openwakeword.model import Model

        if not hasattr(openwakeword.utils, "download_models"):
            raise RuntimeError("openwakeword 0.6 or newer is needed")
        try:
            openwakeword.utils.download_models(["hey_jarvis"])
        except Exception:
            pass  # already downloaded, or offline
        self.model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.threshold = threshold

    def wait(self, mic) -> str:
        """Block until "Hey Jarvis" is heard. Returns '' (command follows)."""
        self.model.reset()
        while True:
            scores = self.model.predict(mic.read())
            if max(scores.values()) >= self.threshold:
                self.model.reset()
                return ""


class TextWakeWord:
    def __init__(self, transcriber, word: str = "jarvis", silence_seconds: float = 0.7):
        self.stt = transcriber
        self.pattern = re.compile(rf"\b{re.escape(word)}\b[\s,.!?]*(.*)", re.I)
        self.silence = silence_seconds

    def wait(self, mic) -> str:
        """Block until a phrase containing the wake word. Returns the words after it."""
        while True:
            audio = mic.record_command(silence_seconds=self.silence, max_seconds=8, start_timeout=30)
            if audio is None:
                continue
            m = self.pattern.search(self.stt.transcribe(audio))
            if m:
                return m.group(1).strip()
