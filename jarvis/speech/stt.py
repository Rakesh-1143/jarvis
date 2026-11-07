"""Speech-to-text with faster-whisper (free, offline, runs on CPU)."""

from __future__ import annotations


class Transcriber:
    def __init__(self, model: str = "base.en", language: str = "en"):
        from faster_whisper import WhisperModel

        self.language = language
        self.model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, audio) -> str:
        segments, _ = self.model.transcribe(audio, language=self.language, beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
