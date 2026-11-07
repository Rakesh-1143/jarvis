"""Load config.yaml. Any module can use: from jarvis.config import load_config"""
from __future__ import annotations

import copy
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

DEFAULTS: dict = {
    "wake_word": "jarvis",
    "listen_timeout": 5,
    "greeting": "Yes?",
    "exit_phrases": ["goodbye", "exit jarvis", "quit jarvis"],  # "stop listening" now pauses Jarvis
    "confirm_intents": ["shutdown", "restart", "sleep", "empty_recycle_bin", "list_clear"],
    "yes_words": ["yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay"],
    "voice": {"rate": 180, "volume": 1.0, "voice_name": ""},
    "stt": {"engine": "vosk", "model_path": "models/vosk-model-small-en-us-0.15",
            "wake_engine": "vosk", "wake_sensitivity": 0.5, "wake_model": ""},
    "wake_file": "~/.jarvis/wake.json",
    "user_name": "",  # set by the voice setup (user.json)
    "apps": {},
    "search_url": "https://www.google.com/search?q={query}",
    "screenshot_folder": "~/Pictures/Jarvis",
    "log_file": "jarvis.log",
    "ai": {"enabled": True, "api_key": "", "model": "claude-opus-5-5", "effort": "low",
           "web_search": True, "answer_questions": True, "history_turns": 6},
    "weather": {"city": "", "units": "metric"},
    "news": {},
    "notes_file": "~/Documents/Jarvis notes.txt",
    "contacts": {},
    "follow_up_seconds": 6,
    "whatsapp": {"auto_send": False, "send_delay": 6},
    "memory_file": "~/Documents/Jarvis memory.txt",
    "reminders_file": "~/Documents/Jarvis reminders.json",
    "routines": {},
    "websites": {},
    # new features (see config.yaml for comments)
    "lists_file": "~/Documents/Jarvis lists.json",
    "shortcuts": {},
    "snippets": {},
    "calendars": [],
    "calendar": {},        # empty = each module uses its own defaults
    "focus": {},
    "alerts": {},
    "email_account": {},
    # Round 2 features
    "recurring_file": "~/Documents/Jarvis repeating.json",
    "expenses_file": "~/Documents/Jarvis expenses.csv",
    "currency": "₹",
    "downloads_folder": "",
    "lookup": {},
    "memos": {},
    "recorder": {},
    # Round 3 features
    "phone": {},
    "home_assistant": {},
    "clipboard_history": {},
    "spotify": {},
    "daily": {},
    "generate": {},
    # Round 4 features (empty = each module uses its own defaults; no triggers by default)
    "security": {},
    "history": {},
    "local_ai": {},
    "layouts": {},
    "screentime": {},
    "app_limits": {},
    "podcasts": {},
    # Round 5 features
    "notifications": {},
    "scores": {},
    "google_calendar": {},
    "taught_file": "~/.jarvis/taught.json",
    "maps": {},
    "habits": {"file": "~/.jarvis/habits.json", "remind_at": ""},
    "contacts_file": "~/.jarvis/contacts.json",
    "flashcards_file": "~/.jarvis/flashcards.json",
    "timetrack": {"file": "~/.jarvis/timetrack.json", "export_file": "~/Documents/Jarvis time tracking.csv"},
    "music_folders": [],
    "birthdays": {"file": "~/.jarvis/birthdays.json", "remind_at": "09:00", "day_before": True},
    "devtools": {"projects": {}, "log_file": "~/.jarvis/devtools.log", "timeout": 120},
    "recap": {"at": ""},
    "webcam": {"camera": 0, "open_after": True},
    "multilang": {"file": "~/.jarvis/multilang.json", "hindi_model_path": "models/vosk-model-small-hi-0.22",
                  "whisper_model": "small", "min_confidence": 0.6},
    "voiceid": {"threshold": 0.75, "file": "~/.jarvis/voiceid.json", "samples": 5},
    "corrections_file": "~/.jarvis/corrections.json",
    "misheard_file": "~/.jarvis/misheard.jsonl",
}

_cache: dict | None = None


class ConfigError(Exception):
    """config.yaml can't be read. The message says where and how to fix it (simple English)."""


def _yaml_problem(file: Path, e: Exception) -> str:
    mark = getattr(e, "problem_mark", None)
    where = f" near line {mark.line + 1}" if mark is not None else ""
    what = getattr(e, "problem", None) or str(e).splitlines()[0]
    return (f"{file.name} has a mistake{where}: {what}. "
            "Tip: put Windows paths in single quotes, like 'C:\\Users\\me\\Music', and use spaces, not tabs.")


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None, reload: bool = False) -> dict:
    """Return settings as a dict. Missing file or keys fall back to DEFAULTS."""
    global _cache
    if _cache is not None and path is None and not reload:
        return _cache
    file = Path(path) if path else DEFAULT_PATH
    data: dict = {}
    if file.exists():
        import yaml  # PyYAML

        try:  # utf-8-sig: old Notepad saves a hidden BOM mark at the start
            data = yaml.safe_load(file.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(_yaml_problem(file, e)) from None
        if not isinstance(data, dict):
            raise ConfigError(f"{file.name} must hold settings like  wake_word: jarvis  (one per line).")
    cfg = _merge(DEFAULTS, data)
    try:  # name, city, units, greeting said in the voice setup (~/.jarvis/user.json) win over config.yaml
        from jarvis.actions import onboarding

        cfg = _merge(cfg, onboarding.config_overrides())
    except Exception:
        pass
    if path is None:
        _cache = cfg
    return cfg
