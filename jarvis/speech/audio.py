"""Microphone input as 16 kHz mono int16 frames of 80 ms."""

from __future__ import annotations

import queue

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms; the size openWakeWord expects


class Microphone:
    def __init__(self, device=None):
        import numpy as np  # noqa: F401  (fail early with a clear error)
        import sounddevice as sd

        self._q: queue.Queue = queue.Queue()
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                     blocksize=FRAME, device=device, callback=self._cb)
        self.stream.start()

    def _cb(self, data, frames, time_info, status):
        self._q.put(data[:, 0].copy())

    def read(self, timeout: float | None = None):
        return self._q.get(timeout=timeout)

    def flush(self) -> None:
        """Drop buffered audio (e.g. Jarvis's own voice)."""
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def record_command(self, silence_seconds: float = 1.0, max_seconds: float = 15.0,
                       start_timeout: float = 5.0):
        """Record until the user stops talking. Returns float32 audio or None."""
        import numpy as np

        frames, started, silent, waited = [], False, 0.0, 0.0
        frame_s = FRAME / SAMPLE_RATE
        noise = None
        while True:
            f = self.read(timeout=5)
            level = float(np.sqrt(np.mean(f.astype(np.float32) ** 2)))
            if noise is None:
                noise = level
            threshold = max(500.0, noise * 3)
            if level > threshold:
                started, silent = True, 0.0
            elif started:
                silent += frame_s
            else:
                waited += frame_s
                noise = 0.9 * noise + 0.1 * level
                frames = frames[-3:]  # keep a little audio before speech starts
            frames.append(f)
            if started and silent >= silence_seconds:
                break
            if not started and waited >= start_timeout:
                return None
            if len(frames) * frame_s >= max_seconds:
                break
        return np.concatenate(frames).astype(np.float32) / 32768.0
