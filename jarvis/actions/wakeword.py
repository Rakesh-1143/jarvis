"""Piece AQ: wake word engine choice + sensitivity.

Two engines:
  vosk          - the old one (stt.wait_for_wake_word). Always works, no extra package.
  openwakeword  - pre-trained "hey_jarvis" neural model (ONNX runtime). Fewer false wakes
                  and misses. Say "hey Jarvis". Needs `pip install openwakeword`.
If openwakeword (or its model) is missing or breaks, Jarvis falls back to Vosk by itself.

Intent:
  wake_sensitivity {change?: up|down, value?}   (no args = say the current level)
    Saved to a small wake.json (not config.yaml). Used on the next wake.

Hooks for main.py:
  name, wait = wakeword.choose(cfg)   # once at start; logs which engine is used
  wait()                              # in VoiceIO.wait_for_wake_word

Config (all optional):
  stt:
    wake_engine: vosk            # vosk | openwakeword
    wake_sensitivity: 0.5        # 0.1 (few wakes) .. 0.9 (wakes easily); wake.json wins
    wake_model: ""               # path to your own .onnx/.tflite model (else built-in by word)
  wake_file: ~/.jarvis/wake.json
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis.wakeword")

DEFAULT_FILE = "~/.jarvis/wake.json"
DEFAULT_SENSITIVITY = 0.5
MIN_S, MAX_S, STEP = 0.1, 0.9, 0.1
FRAME = 1280  # openWakeWord wants 80 ms frames at 16 kHz
ENGINES = ("vosk", "openwakeword")
# Wake word -> built-in openWakeWord model name.
BUILTIN_MODELS = {"jarvis": "hey_jarvis", "hey jarvis": "hey_jarvis", "alexa": "alexa",
                  "mycroft": "hey_mycroft", "hey mycroft": "hey_mycroft"}

# ---------- catalog for the AI brain ----------

CATALOG: dict[str, dict] = {
    "wake_sensitivity": {
        "description": "Make the wake word more or less sensitive, set it to a level, or say the current level. "
                       "More sensitive = wakes more easily (more false wakes).",
        "properties": {
            "change": {"type": "string", "enum": ["up", "down"],
                       "description": "up = more sensitive, down = less sensitive. Leave out with value or to ask."},
            "value": {"type": "number", "description": "Level 0.1-0.9, or 1-9, or 10-90 percent."},
        },
        "required": [],
    },
}


# ---------- config + saved state ----------

def _config() -> dict:
    try:
        from jarvis.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _stt_cfg(cfg: dict | None) -> dict:
    stt = (cfg if cfg is not None else _config()).get("stt") or {}
    return stt if isinstance(stt, dict) else {}


def _state_path(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else _config()
    return Path(os.path.expanduser(str(cfg.get("wake_file") or DEFAULT_FILE)))


def _load_state(cfg: dict | None = None) -> dict:
    try:
        data = json.loads(_state_path(cfg).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict, cfg: dict | None = None) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _clamp(x: float) -> float:
    return round(min(MAX_S, max(MIN_S, x)), 2)


def _as_level(value) -> float | None:
    """0.6 / 6 / 60 / "60%" -> 0.6. None if not a number."""
    try:
        x = float(str(value).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return None
    if x < 0:
        return None
    if x > 10:
        x /= 100
    elif x > 1:
        x /= 10
    return _clamp(x)


def sensitivity(cfg: dict | None = None) -> float:
    """wake.json value, else config stt.wake_sensitivity, else 0.5."""
    for raw in (_load_state(cfg).get("sensitivity"), _stt_cfg(cfg).get("wake_sensitivity")):
        if raw is not None:
            level = _as_level(raw)
            if level is not None:
                return level
    return DEFAULT_SENSITIVITY


def threshold(level: float) -> float:
    """Higher sensitivity -> lower score needed to wake."""
    return round(1.0 - _clamp(level), 2)


def engine_name(cfg: dict | None = None) -> str:
    name = str(_stt_cfg(cfg).get("wake_engine") or "vosk").strip().lower().replace("_", "").replace(" ", "")
    return "openwakeword" if name in ("openwakeword", "oww") else "vosk"


# ---------- openWakeWord ----------

def _model_ref(word: str, cfg: dict | None) -> str | None:
    """Model path or built-in name for this wake word, or None if there is none."""
    custom = str(_stt_cfg(cfg).get("wake_model") or "").strip()
    if custom:
        return str(Path(custom).expanduser())
    return BUILTIN_MODELS.get(word.lower().strip())


def _load_oww(ref: str):
    """Load an openWakeWord model (downloads the built-in one the first time)."""
    import openwakeword  # noqa: F401  (ImportError -> fallback)
    from openwakeword.model import Model

    if not os.path.exists(ref):
        try:
            from openwakeword.utils import download_models
            download_models(model_names=[ref])
        except Exception as e:  # already there, or no internet: Model() below decides
            log.info("openwakeword download skipped: %s", e)
    try:
        return Model(wakeword_models=[ref], inference_framework="onnx")
    except TypeError:  # other package versions
        return Model(wakeword_models=[ref])


def _frames(chunks) -> "iter":
    """Re-cut stt mic chunks (bytes, int16) into 1280-sample numpy frames."""
    import numpy as np

    buf = b""
    size = FRAME * 2
    for chunk in chunks:
        buf += chunk
        while len(buf) >= size:
            yield np.frombuffer(buf[:size], dtype=np.int16)
            buf = buf[size:]


class MicStreamEnded(OSError):
    """The microphone stopped giving audio (unplugged, driver error). Not a wake."""


def wait_oww(model, level: float, mic_chunks: Callable | None = None) -> float:
    """Block until the model's score passes the threshold. Returns the score."""
    if mic_chunks is None:
        from jarvis import stt
        mic_chunks = stt._mic_chunks  # same mic settings as stt
    limit = threshold(level)
    try:
        model.reset()
    except Exception:
        pass
    chunks = mic_chunks()
    try:
        for frame in _frames(chunks):
            scores = model.predict(frame) or {}
            best = max(scores.values(), default=0.0)
            if best >= limit:
                log.info("woke (openwakeword score %.2f, need %.2f)", best, limit)
                try:
                    model.reset()  # don't wake again on the same sound next time
                except Exception:
                    pass
                return float(best)
    finally:
        close = getattr(chunks, "close", None)
        if close:
            close()  # closes the microphone
    raise MicStreamEnded("microphone stream ended")  # main's mic-error path waits and tries again


# ---------- public API ----------

def _vosk_wait(word: str) -> None:
    from jarvis import stt
    stt.wait_for_wake_word(word)


def choose(cfg: dict | None = None) -> tuple[str, Callable[[], None]]:
    """Pick the wake engine once at start. Returns (engine name, wait function).

    The wait function reads the sensitivity on every call, so voice changes apply at once.
    If openWakeWord fails later (mic or model error), it switches to Vosk for good.
    """
    cfg = cfg if cfg is not None else _config()
    word = str(cfg.get("wake_word") or "jarvis")

    def vosk_wait() -> None:
        _vosk_wait(word)

    if engine_name(cfg) != "openwakeword":
        log.info("wake engine: vosk")
        return "vosk", vosk_wait
    ref = _model_ref(word, cfg)
    if not ref:
        log.warning("openwakeword has no model for %r (set stt.wake_model); using vosk", word)
        return "vosk", vosk_wait
    try:
        model = _load_oww(ref)
    except Exception as e:
        log.warning("openwakeword not usable (%s); using vosk. Fix: pip install openwakeword", e)
        return "vosk", vosk_wait

    state = {"broken": False}

    def oww_wait() -> None:
        if not state["broken"]:
            try:
                wait_oww(model, sensitivity(cfg))
                return
            except MicStreamEnded:
                raise  # a mic problem, not an openwakeword problem: keep using it after the mic is back
            except Exception as e:
                state["broken"] = True
                log.warning("openwakeword failed (%s); switching to vosk", e)
        vosk_wait()

    log.info("wake engine: openwakeword (%s)", ref)
    return "openwakeword", oww_wait


def wait(word: str = "jarvis", level: float | None = None, cfg: dict | None = None) -> None:
    """One-off wait with the configured engine (loads the model each call; main should use choose())."""
    cfg = dict(cfg if cfg is not None else _config())
    cfg["wake_word"] = word
    if level is not None:
        ref = _model_ref(word, cfg)
        if engine_name(cfg) == "openwakeword" and ref:
            try:
                wait_oww(_load_oww(ref), _clamp(level))
                return
            except Exception as e:
                log.warning("openwakeword failed (%s); using vosk", e)
        _vosk_wait(word)
        return
    choose(cfg)[1]()


# ---------- intent ----------

def _pct(level: float) -> str:
    return f"{round(level * 100)} percent"


def wake_sensitivity(args: dict) -> str:
    cfg = _config()
    args = args or {}
    change = str(args.get("change") or "").strip().lower()
    current = sensitivity(cfg)
    if args.get("value") not in (None, ""):
        new = _as_level(args.get("value"))
        if new is None:
            return "Say a level from 1 to 9, like 'set wake word sensitivity to 6'."
    elif change in ("up", "more", "higher", "increase"):
        new = _clamp(current + STEP)
    elif change in ("down", "less", "lower", "decrease"):
        new = _clamp(current - STEP)
    else:
        return f"Wake word sensitivity is {_pct(current)}, using the {engine_name(cfg)} engine."

    note = ""
    if engine_name(cfg) != "openwakeword":
        note = " This only matters with the openWakeWord engine. Set stt wake_engine to openwakeword in config."
    if new == current:
        edge = "most" if new >= MAX_S else "least" if new <= MIN_S else ""
        if edge and change:
            return f"Wake word is already at the {edge} sensitive level, {_pct(new)}.{note}"
        return f"Wake word sensitivity is already {_pct(new)}.{note}"
    state = _load_state(cfg)
    state["sensitivity"] = new
    try:
        _save_state(state, cfg)
    except OSError as e:
        return f"I couldn't save the wake word setting: {e}"
    return f"Wake word sensitivity is now {_pct(new)}.{note}"


HANDLERS = {"wake_sensitivity": wake_sensitivity}


if __name__ == "__main__":  # quick test: python -m jarvis.actions.wakeword
    logging.basicConfig(level=logging.INFO)
    name, fn = choose()
    print(f"Engine: {name}, sensitivity {sensitivity()}. Say the wake word...")
    fn()
    print("Heard it.")
