"""Load settings from config.toml, with safe defaults."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore

DEFAULTS: dict[str, dict[str, Any]] = {
    "assistant": {"name": "Jarvis", "user_name": "Sir", "data_dir": "data"},
    "llm": {
        "provider": "ollama",
        "model": "llama3.2",
        "base_url": "http://localhost:11434",
        "api_key_env": "OPENAI_API_KEY",
        "temperature": 0.6,
        "use_tools": True,
        "history_turns": 10,
        "timeout": 120,
    },
    "voice": {
        "stt_model": "base.en",
        "language": "en",
        "tts_engine": "pyttsx3",
        "tts_rate": 180,
        "wake_engine": "openwakeword",
        "wake_word": "jarvis",
        "wake_threshold": 0.5,
        "silence_seconds": 1.0,
    },
    "weather": {"city": ""},
    "web": {"host": "127.0.0.1", "port": 5050},
}


class Config:
    """Nested settings with attribute-free dict access: cfg["llm"]["model"]."""

    def __init__(self, data: dict[str, dict[str, Any]], path: Path | None = None):
        self.data = data
        self.path = path

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]

    @property
    def data_dir(self) -> Path:
        d = Path(self.data["assistant"]["data_dir"]).expanduser()
        if not d.is_absolute() and self.path is not None:
            d = self.path.parent / d
        d.mkdir(parents=True, exist_ok=True)
        return d


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Read config.toml (or the given path). Missing file -> defaults."""
    candidates = [Path(path)] if path else [Path("config.toml"), Path.home() / ".jarvis" / "config.toml"]
    for p in candidates:
        if p.is_file():
            with open(p, "rb") as f:
                return Config(_merge(DEFAULTS, tomllib.load(f)), p.resolve())
    return Config(copy.deepcopy(DEFAULTS), None)
