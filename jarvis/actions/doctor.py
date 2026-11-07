"""Piece AP: self-check. Intent: self_check {full?: bool} (info). Also `python main.py --doctor`.

Checks, each OK / problem / optional, with a fix hint:
Python version, packages from requirements.txt, Vosk model, microphone (1 s sound level), TTS voices,
config.yaml (loads + known keys have the right type), API key (one tiny API call only on a full check),
internet, writable data files, Windows-only extras (pycaw, winrt, KDE Connect, winget, ffmpeg, Outlook).

Writes doctor-report.txt in the project folder and returns a short spoken summary.
Nothing here changes settings, installs anything or starts Outlook.
"""
from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
REPORT_FILE = PROJECT_ROOT / "doctor-report.txt"
MIN_PYTHON = (3, 11)
MIC_SECONDS = 1.0
MIC_MIN_LEVEL = 0.002  # RMS of float samples; below this the mic is muted or dead

OK, PROBLEM, OPTIONAL, SKIPPED = "ok", "problem", "optional", "skipped"

# pip name -> import name, where they differ
IMPORT_NAMES = {
    "pyyaml": "yaml", "screen-brightness-control": "screen_brightness_control", "pillow": "PIL",
    "send2trash": "send2trash", "recurring-ical-events": "recurring_ical_events", "pywin32": "win32com",
    "winrt-runtime": "winrt", "winrt-windows.devices.radios": "winrt.windows.devices.radios",
    "winrt-windows.media.control": "winrt.windows.media.control", "winrt-windows.media.ocr": "winrt.windows.media.ocr",
    "winrt-windows.graphics.imaging": "winrt.windows.graphics.imaging",
    "winrt-windows.storage.streams": "winrt.windows.storage.streams",
    "winrt-windows.foundation": "winrt.windows.foundation",
    "winrt-windows.foundation.collections": "winrt.windows.foundation.collections",
}
# config keys holding a file Jarvis writes to
DATA_FILE_KEYS = ["log_file", "notes_file", "memory_file", "reminders_file", "lists_file",
                  "recurring_file", "expenses_file"]


@dataclass
class Check:
    name: str
    status: str          # ok | problem | optional | skipped
    detail: str = ""
    fix: str = ""
    short: str = ""      # few words for the spoken summary, e.g. "no microphone sound"


def _ok(name: str, detail: str = "") -> Check:
    return Check(name, OK, detail)


def _bad(name: str, detail: str, fix: str, short: str) -> Check:
    return Check(name, PROBLEM, detail, fix, short)


def _opt(name: str, detail: str, fix: str, short: str) -> Check:
    return Check(name, OPTIONAL, detail, fix, short)


def _is_windows() -> bool:
    return sys.platform == "win32"


# ---------- checks ----------

def check_python(version: tuple = None) -> Check:
    v = tuple(version or sys.version_info[:3])
    text = ".".join(str(x) for x in v)
    if v[:2] >= MIN_PYTHON:
        return _ok("Python", text)
    return _bad("Python", f"{text} is too old", "Install Python 3.11 or newer from python.org, then run install.bat.",
                "Python too old")


def parse_requirements(text: str, windows: bool | None = None) -> list[tuple[str, str]]:
    """[(pip name, import name)] for lines that apply to this OS."""
    windows = _is_windows() if windows is None else windows
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        spec, _, marker = line.partition(";")
        if "win32" in marker and not windows:
            continue
        name = re.split(r"[<>=!~\[ ]", spec.strip(), maxsplit=1)[0].strip()
        if not name:
            continue
        key = name.lower()
        out.append((name, IMPORT_NAMES.get(key, key.replace("-", "_"))))
    return out


def _importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


def check_packages(req_file: Path = REQUIREMENTS) -> Check:
    try:
        reqs = parse_requirements(Path(req_file).read_text(encoding="utf-8"))
    except OSError:
        return _bad("Packages", f"{req_file} not found", "Put requirements.txt back in the Jarvis folder.",
                    "requirements file missing")
    missing = [pip for pip, mod in reqs if not _importable(mod)]
    if not missing:
        return _ok("Packages", f"all {len(reqs)} installed")
    return _bad("Packages", "missing: " + ", ".join(missing),
                "Run: pip install -r requirements.txt  (or run packaging\\install.bat again).",
                f"{len(missing)} package{'s' if len(missing) > 1 else ''} missing")


def _model_path(cfg: dict) -> Path:
    path = (cfg.get("stt") or {}).get("model_path") or "models/vosk-model-small-en-us-0.15"
    p = Path(str(path)).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def check_vosk_model(cfg: dict) -> Check:
    p = _model_path(cfg)
    if not p.is_dir():
        return _bad("Speech model", f"not found at {p}",
                    "Start Jarvis once with internet (it downloads ~40 MB), or unzip a Vosk model there "
                    "and set stt.model_path in config.yaml.", "speech model missing")
    if not any((p / sub).exists() for sub in ("am", "conf", "graph")):
        return _bad("Speech model", f"{p} does not look like a Vosk model (no am/conf folder)",
                    "Delete the folder and start Jarvis again so it downloads a fresh copy.", "speech model broken")
    return _ok("Speech model", str(p))


def _record_level(seconds: float) -> float:
    """RMS level of `seconds` of mic sound (0..1)."""
    import sounddevice as sd

    frames = int(16000 * seconds)
    data = sd.rec(frames, samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    total = 0.0
    for row in data:
        total += float(row[0]) ** 2
    return (total / max(1, len(data))) ** 0.5


def _default_input_name() -> str | None:
    import sounddevice as sd

    try:
        dev = sd.query_devices(kind="input")
    except Exception:
        return None
    return (dev or {}).get("name") or None


def check_microphone() -> Check:
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return _bad("Microphone", "sounddevice not installed", "Run: pip install sounddevice", "sounddevice missing")
    name = _default_input_name()
    if not name:
        return _bad("Microphone", "no input device found",
                    "Plug in a mic, then Settings > System > Sound > Input: pick it and allow mic access "
                    "(Settings > Privacy > Microphone).", "no microphone")
    try:
        level = _record_level(MIC_SECONDS)
    except Exception as e:
        return _bad("Microphone", f"{name}: could not record ({e})",
                    "Allow desktop apps to use the mic: Settings > Privacy > Microphone.", "microphone blocked")
    if level < MIC_MIN_LEVEL:
        return _bad("Microphone", f"{name}: no sound (level {level:.4f})",
                    "Unmute the mic, raise its input volume in Sound settings, or pick another input device.",
                    "no microphone sound")
    return _ok("Microphone", f"{name} (level {level:.3f})")


def _voices() -> list[str]:
    from jarvis import tts

    if getattr(tts, "pyttsx3", None) is None:
        raise ImportError("pyttsx3 not installed")
    return tts.list_voices()


def check_tts(cfg: dict) -> Check:
    try:
        voices = _voices()
    except ImportError:
        return _bad("Voice (TTS)", "pyttsx3 not installed", "Run: pip install pyttsx3", "speech voice missing")
    except Exception as e:
        return _bad("Voice (TTS)", f"could not start speech ({e})",
                    "Run: pip install --force-reinstall pyttsx3 comtypes", "speech engine broken")
    if not voices:
        return _bad("Voice (TTS)", "no voices installed",
                    "Settings > Time & language > Speech > Add voices.", "no speech voices")
    wanted = str((cfg.get("voice") or {}).get("voice_name") or "").strip()
    if wanted and not any(wanted.lower() in v.lower() for v in voices):
        return _bad("Voice (TTS)", f"voice '{wanted}' not found; have: {', '.join(voices)}",
                    "Fix voice.voice_name in config.yaml (part of a name above) or leave it empty.",
                    "chosen voice not found")
    return _ok("Voice (TTS)", f"{len(voices)} voice{'s' if len(voices) != 1 else ''}: {', '.join(voices[:3])}")


def _type_name(v) -> str:
    if isinstance(v, bool):
        return "yes/no"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "section"
    return "empty" if v is None else type(v).__name__


def config_type_errors(data: dict, defaults: dict, prefix: str = "") -> list[str]:
    """Known keys whose value has the wrong type, e.g. 'voice.rate should be number, got text'."""
    errors = []
    for key, default in defaults.items():
        if key not in data:
            continue
        value, want, got = data[key], _type_name(default), _type_name(data[key])
        if isinstance(default, dict) and isinstance(value, dict):
            errors += config_type_errors(value, default, f"{prefix}{key}.")
        elif value is None and want == "section":
            continue  # "phone:" with nothing under it means "use defaults"
        elif want != got:
            errors.append(f"{prefix}{key} should be {want}, got {got}")
    return errors


def check_config(path: Path | None = None) -> Check:
    from jarvis import config as config_mod

    file = Path(path) if path else config_mod.DEFAULT_PATH
    if not file.exists():
        return _ok("Config", f"{file.name} not found, using defaults")
    try:
        import yaml

        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except ImportError:
        return _bad("Config", "PyYAML not installed", "Run: pip install PyYAML", "PyYAML missing")
    except Exception as e:
        where = getattr(e, "problem_mark", None)
        line = f" near line {where.line + 1}" if where is not None else ""
        return _bad("Config", f"config.yaml has a mistake{line}: {getattr(e, 'problem', e)}",
                    "Open config.yaml and check spaces/indents and quotes on that line.", "config.yaml broken")
    if not isinstance(data, dict):
        return _bad("Config", "config.yaml is not a list of settings", "Restore config.yaml from the download.",
                    "config.yaml broken")
    errors = config_type_errors(data, config_mod.DEFAULTS)
    if errors:
        return _bad("Config", "; ".join(errors[:5]) + (" ..." if len(errors) > 5 else ""),
                    "Fix those values in config.yaml (put text in quotes, numbers without quotes).",
                    f"{len(errors)} config setting{'s' if len(errors) > 1 else ''} wrong")
    return _ok("Config", f"{file.name} loads, {len(data)} settings")


def _api_key(cfg: dict) -> str:
    ai = cfg.get("ai") or {}
    return str(ai.get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _tiny_call(cfg: dict, key: str) -> None:
    import anthropic

    model = (cfg.get("ai") or {}).get("model") or "claude-opus-5-5"
    client = anthropic.Anthropic(api_key=key, timeout=20.0, max_retries=0)
    client.messages.create(model=model, max_tokens=1, messages=[{"role": "user", "content": "hi"}])


def check_api_key(cfg: dict, full: bool = False) -> Check:
    ai = cfg.get("ai") or {}
    if ai.get("enabled", True) is False:
        return Check("AI key", SKIPPED, "AI is turned off in config (ai.enabled: false)")
    key = _api_key(cfg)
    if not key:
        return _opt("AI key", "no Claude API key, so only fixed commands work",
                    "Put your key in config.yaml under ai: api_key: or set ANTHROPIC_API_KEY.", "no AI key")
    if not full:
        return _ok("AI key", "key is set (say 'full check' to test it)")
    try:
        _tiny_call(cfg, key)
    except Exception as e:
        msg = str(e).split("\n", 1)[0][:160]
        return _bad("AI key", f"test call failed: {msg}",
                    "Check the key at console.anthropic.com (and that it has credit), and the internet.",
                    "AI key not working")
    return _ok("AI key", "test call worked")


def _online() -> bool:
    from jarvis.actions import network

    return network.is_online()


def check_internet() -> Check:
    try:
        online = _online()
    except Exception:
        online = False
    if online:
        return _ok("Internet", "online")
    return _bad("Internet", "offline", "Connect to Wi-Fi. Offline commands still work.", "no internet")


def _writable(path: Path) -> bool:
    """True when the file can be written (or created) without creating anything now."""
    if path.exists():
        return path.is_file() and os.access(path, os.W_OK)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def _data_path(value: str) -> Path:
    p = Path(os.path.expanduser(str(value)))
    return p if p.is_absolute() else PROJECT_ROOT / p


def check_data_files(cfg: dict) -> Check:
    bad = []
    count = 0
    for key in DATA_FILE_KEYS:
        value = cfg.get(key)
        if not value or not isinstance(value, str):
            continue
        count += 1
        if not _writable(_data_path(value)):
            bad.append(f"{key} ({_data_path(value)})")
    if bad:
        return _bad("Data files", "cannot write: " + ", ".join(bad),
                    "Point these settings to a folder you own (e.g. Documents) in config.yaml, "
                    "or close the program that has the file locked.", "cannot save some files")
    return _ok("Data files", f"{count} writable")


def _outlook_installed() -> bool:
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application"))
        return True
    except OSError:
        return False


def _find_kdeconnect(cfg: dict) -> str | None:
    from jarvis.actions import phone

    return phone.find_cli({**phone.DEFAULTS, **(cfg.get("phone") or {})})


def _find_ffmpeg(cfg: dict) -> str | None:
    from jarvis.actions import recorder

    return recorder.find_ffmpeg(recorder.settings(cfg))


def check_windows_extras(cfg: dict) -> list[Check]:
    """Optional tools. Missing ones only turn off a few features."""
    if not _is_windows():
        return [Check("Windows extras", SKIPPED, "not Windows")]
    items = [
        ("Volume control (pycaw)", lambda: _importable("pycaw"), "Run: pip install pycaw", "pycaw missing"),
        ("Wi-Fi / media / OCR (winrt)", lambda: _importable("winrt"),
         "Run: pip install -r requirements.txt", "winrt missing"),
        ("Phone (KDE Connect)", lambda: bool(_find_kdeconnect(cfg)),
         "winget install KDE.KDEConnect  (only for phone commands)", "KDE Connect missing"),
        ("winget", lambda: bool(shutil.which("winget")),
         "Install 'App Installer' from the Microsoft Store (for install/update apps).", "winget missing"),
        ("ffmpeg", lambda: bool(_find_ffmpeg(cfg)),
         "winget install Gyan.FFmpeg  (for full-screen recording; Game Bar is used without it)", "ffmpeg missing"),
        ("Outlook", _outlook_installed, "Only needed for Outlook email/calendar.", "Outlook missing"),
    ]
    out = []
    for name, test, fix, short in items:
        try:
            found = bool(test())
        except Exception:
            found = False
        out.append(_ok(name, "found") if found else _opt(name, "not found", fix, short))
    return out


# ---------- run all ----------

def _load_cfg() -> dict:
    try:
        from jarvis.config import load_config

        return load_config()
    except Exception:
        from jarvis.config import DEFAULTS

        return dict(DEFAULTS)


def run_checks(cfg: dict | None = None, full: bool = False, mic: bool = True) -> list[Check]:
    cfg = _load_cfg() if cfg is None else cfg
    steps = [
        check_python,
        check_packages,
        lambda: check_config(),
        lambda: check_vosk_model(cfg),
        check_microphone if mic else (lambda: Check("Microphone", SKIPPED, "not tested")),
        lambda: check_tts(cfg),
        lambda: check_api_key(cfg, full),
        check_internet,
        lambda: check_data_files(cfg),
    ]
    results: list[Check] = []
    for step in steps:
        try:
            results.append(step())
        except Exception as e:  # one broken check must not stop the rest
            results.append(_bad("Check", f"a check crashed: {e}", "Send doctor-report.txt to the developer.",
                                "a check crashed"))
    try:
        results += check_windows_extras(cfg)
    except Exception as e:
        results.append(Check("Windows extras", SKIPPED, f"could not check ({e})"))
    return results


def summary(results: list[Check]) -> str:
    ok = sum(r.status == OK for r in results)
    problems = [r.short or r.name for r in results if r.status == PROBLEM]
    optional = [r.short or r.name for r in results if r.status == OPTIONAL]
    if problems:
        text = f"{ok} OK, {len(problems)} problem{'s' if len(problems) > 1 else ''}: {', '.join(problems)}."
    else:
        text = f"All {ok} checks OK."
    if optional:
        text += f" Optional, not set up: {', '.join(optional)}."
    return text


def report_text(results: list[Check]) -> str:
    marks = {OK: "OK  ", PROBLEM: "FAIL", OPTIONAL: "OPT ", SKIPPED: "SKIP"}
    lines = [f"Jarvis self-check  {datetime.now():%Y-%m-%d %H:%M}",
             f"Python {sys.version.split()[0]} on {sys.platform}", "", summary(results), ""]
    for r in results:
        lines.append(f"[{marks.get(r.status, r.status)}] {r.name}: {r.detail}".rstrip(": "))
        if r.fix and r.status in (PROBLEM, OPTIONAL):
            lines.append(f"       Fix: {r.fix}")
    return "\n".join(lines) + "\n"


def write_report(results: list[Check], path: Path = None) -> Path | None:
    path = Path(path or REPORT_FILE)
    try:
        path.write_text(report_text(results), encoding="utf-8")
        return path
    except OSError:
        return None


# ---------- intent + CLI ----------

def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "full", "1")
    return bool(v)


def self_check(args: dict) -> str:
    """'check yourself' / 'run a self check' / 'full check'. Info intent: the summary goes to the AI or is spoken."""
    results = run_checks(full=_as_bool((args or {}).get("full")))
    saved = write_report(results)
    text = summary(results)
    if saved and any(r.status in (PROBLEM, OPTIONAL) for r in results):
        text += f" Details and fixes are in {saved.name}."
    return text


def run_cli(argv: list[str] | None = None) -> int:
    """`python main.py --doctor [--full]`: print the report. Exit code 1 when there are problems."""
    argv = sys.argv[1:] if argv is None else argv
    full = "--full" in argv
    print("Checking Jarvis... (say something during the 1 second mic test)")
    results = run_checks(full=full)
    text = report_text(results)
    print(text)
    saved = write_report(results)
    if saved:
        print(f"Saved to {saved}")
    return 1 if any(r.status == PROBLEM for r in results) else 0


CATALOG: dict[str, dict] = {
    "self_check": {"description": "Jarvis checks itself: mic, speech model, voice, packages, config, AI key, "
                                  "internet, files. Use full=true only when the user asks for a full check "
                                  "(it makes one tiny AI call).",
                   "properties": {"full": {"type": "boolean"}}, "required": [], "info": True},
}
HANDLERS = {"self_check": self_check}


if __name__ == "__main__":
    sys.exit(run_cli())
