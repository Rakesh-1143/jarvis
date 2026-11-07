"""Piece AG: offline AI answers with a local Ollama server.

Use it when there is no Claude key, no internet, or the user says "use local AI".
Ollama runs on the laptop (https://ollama.com), so it is free and works offline.

Public API (for brain / main wiring):
  available() -> bool                      server is up AND the model is downloaded
  ask(text, on_sentence=None) -> str       answer; with on_sentence each sentence is passed on as it arrives
  get_mode() -> "local" | "cloud" | "auto"
  set_mode(mode)
  use_local(claude_ready: bool) -> bool    should this question go to the local AI?

Intents:
  ai_mode {mode: local|cloud|auto}         "use local AI", "use cloud AI", "auto AI mode"
  local_ai_status {}                       (info) "is local AI ready"

Optional config (defaults work without it):
  local_ai: {url: "http://localhost:11434", model: "llama3.2:3b", mode: auto, timeout: 60, history_turns: 4}

No new packages: plain urllib (stdlib).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request

DEFAULTS = {
    "url": "http://localhost:11434",
    "model": "llama3.2:3b",
    "mode": "auto",          # auto = Claude first, local AI when Claude is missing or offline
    "timeout": 60,           # seconds for one answer (small laptops can be slow)
    "history_turns": 4,      # past question/answer pairs kept for follow-ups
}
MODES = ("local", "cloud", "auto")
STATUS_CACHE_SECONDS = 10    # do not ping the server on every question

SYSTEM_PROMPT = (
    "You are Jarvis, a voice assistant on the user's Windows laptop. Your answer is spoken aloud. "
    "Answer in two or three short sentences of plain, simple English. Start with the answer. "
    "No lists, no markdown, no code, no links. "
    "You are running offline: you cannot use the internet or control the laptop. "
    "If the question needs live data (news, weather, prices, today's events), say you are offline and "
    "cannot check that right now. If you do not know, say so."
)

_lock = threading.Lock()
_state: dict = {"mode": None, "history": [], "status": None, "status_at": 0.0}


# ---------- settings ----------

def _settings() -> dict:
    try:
        from jarvis.config import load_config
        cfg = load_config().get("local_ai") or {}
    except Exception:
        cfg = {}
    s = {**DEFAULTS, **{k: v for k, v in cfg.items() if v not in (None, "")}}
    s["url"] = str(s["url"]).rstrip("/")
    s["model"] = str(s["model"]).strip()
    s["mode"] = s["mode"] if s["mode"] in MODES else "auto"
    try:
        s["timeout"] = max(5, int(s["timeout"]))
    except (TypeError, ValueError):
        s["timeout"] = DEFAULTS["timeout"]
    try:
        s["history_turns"] = max(0, int(s["history_turns"]))
    except (TypeError, ValueError):
        s["history_turns"] = DEFAULTS["history_turns"]
    return s


# ---------- HTTP (kept small so tests can fake it) ----------

def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_stream(url: str, body: dict, timeout: float):
    """POST JSON and yield one decoded JSON object per line (Ollama streams NDJSON)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if line:
                yield json.loads(line.decode("utf-8"))


# ---------- status ----------

def _same_model(wanted: str, have: str) -> bool:
    """'llama3.2' matches 'llama3.2:latest'; 'llama3.2:3b' must match exactly."""
    wanted, have = wanted.lower(), have.lower()
    if wanted == have:
        return True
    if ":" not in wanted:
        return have == wanted + ":latest"
    return False


def status(force: bool = False) -> dict:
    """{'server': bool, 'model_ready': bool, 'model': str, 'models': [...]}. Cached for a few seconds."""
    now = time.monotonic()
    with _lock:
        cached = _state["status"]
        if cached is not None and not force and now - _state["status_at"] < STATUS_CACHE_SECONDS:
            return dict(cached)
    s = _settings()
    result = {"server": False, "model_ready": False, "model": s["model"], "models": []}
    try:
        data = _get_json(s["url"] + "/api/tags", timeout=2)
        names = [m.get("name") or m.get("model") or "" for m in (data.get("models") or [])]
        result["server"] = True
        result["models"] = [n for n in names if n]
        result["model_ready"] = any(_same_model(s["model"], n) for n in result["models"])
    except Exception:
        pass
    with _lock:
        _state["status"], _state["status_at"] = dict(result), now
    return result


def available() -> bool:
    st = status()
    return st["server"] and st["model_ready"]


# ---------- mode ----------

def get_mode() -> str:
    with _lock:
        mode = _state["mode"]
    return mode or _settings()["mode"]


def set_mode(mode: str) -> None:
    mode = str(mode or "").strip().lower()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    with _lock:
        _state["mode"] = mode


def use_local(claude_ready: bool) -> bool:
    """Brain/main helper: True = answer with the local AI.

    local -> always local (if it is available)
    cloud -> never local
    auto  -> local only when Claude is not ready (no key / offline) and local is available
    """
    mode = get_mode()
    if mode == "cloud":
        return False
    if mode == "auto" and claude_ready:
        return False
    return available()


# ---------- answering ----------

_END = re.compile(r"([.!?])\s+")


def _clean(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*(?:[-•]|\d+\.)\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def _messages(text: str, turns: int) -> list[dict]:
    with _lock:
        hist = list(_state["history"][-2 * turns:]) if turns else []
    return [{"role": "system", "content": SYSTEM_PROMPT}, *hist, {"role": "user", "content": text}]


def _remember(question: str, answer: str, turns: int) -> None:
    if not turns or not answer:
        return
    with _lock:
        _state["history"] += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        _state["history"] = _state["history"][-2 * turns:]


def clear_history() -> None:
    with _lock:
        _state["history"] = []


def _error_text(e: Exception) -> str:
    if (isinstance(e, urllib.error.HTTPError) and e.code == 404) or "not found" in str(e).lower():
        return f"The local AI model is not downloaded. Run: ollama pull {_settings()['model']}"
    if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
        return "The local AI took too long to answer. Try a shorter question or a smaller model."
    return "The local AI is not running. Start Ollama and try again."


def ask(text: str, on_sentence=None) -> str:
    """Ask the local model. Returns the full answer (cleaned for speech).

    With on_sentence, each finished sentence is passed to it while the model is still writing,
    so Jarvis starts speaking sooner. Errors return a short spoken message (never raise).
    """
    text = str(text or "").strip()
    if not text:
        if on_sentence:
            on_sentence("What should I ask the local AI?")
        return "What should I ask the local AI?"
    s = _settings()
    body = {"model": s["model"], "messages": _messages(text, s["history_turns"]), "stream": True,
            "options": {"temperature": 0.4, "num_predict": 200}}
    full, buf, spoken = "", "", False

    def emit(sentence: str) -> None:
        nonlocal spoken
        sentence = _clean(sentence)
        if sentence and on_sentence:
            spoken = True
            on_sentence(sentence)

    try:
        for chunk in _post_stream(s["url"] + "/api/chat", body, s["timeout"]):
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            piece = (chunk.get("message") or {}).get("content") or ""
            full += piece
            buf += piece
            while True:
                m = _END.search(buf)
                if not m:
                    break
                sentence, buf = buf[:m.end(1)], buf[m.end():]
                emit(sentence)
            if chunk.get("done"):
                break
        emit(buf)
    except Exception as e:
        with _lock:
            _state["status"] = None  # re-check the server next time
        msg = _error_text(e)
        if on_sentence and not spoken:
            on_sentence(msg)
        return msg
    answer = _clean(full)
    if not answer:
        answer = "The local AI gave no answer."
        if on_sentence and not spoken:
            on_sentence(answer)
    _remember(text, answer, s["history_turns"])
    return answer


# ---------- intent handlers ----------

def ai_mode(args: dict) -> str:
    raw = str(args.get("mode") or "").strip().lower()
    mode = {"offline": "local", "ollama": "local", "claude": "cloud", "online": "cloud",
            "automatic": "auto"}.get(raw, raw)
    if mode not in MODES:
        return "Say use local AI, use cloud AI, or auto AI mode."
    set_mode(mode)
    if mode == "cloud":
        return "Okay, I'll use the cloud AI for answers."
    if mode == "auto":
        return "Okay, auto mode. I'll use the cloud AI, and the local AI when the cloud is not available."
    if available():
        return "Okay, I'll use the local AI for answers."
    st = status(force=True)
    if not st["server"]:
        return "Okay, local AI mode is on, but Ollama is not running. Start Ollama first."
    return f"Okay, local AI mode is on, but the model is not downloaded. Run: ollama pull {st['model']}"


def local_ai_status(args: dict) -> str:
    st = status(force=True)
    mode = get_mode()
    if not st["server"]:
        return (f"Local AI is not ready: Ollama is not running. Install it from ollama.com and start it. "
                f"AI mode is {mode}.")
    if not st["model_ready"]:
        return (f"Ollama is running, but the model {st['model']} is not downloaded. "
                f"Run: ollama pull {st['model']}. AI mode is {mode}.")
    return f"Local AI is ready with {st['model']}. AI mode is {mode}."


CATALOG: dict[str, dict] = {
    "ai_mode": {
        "description": ("Choose which AI answers questions: local (offline Ollama on this laptop), "
                        "cloud (Claude), or auto (Claude, local when Claude is not available)."),
        "properties": {"mode": {"type": "string", "enum": list(MODES)}},
        "required": ["mode"],
    },
    "local_ai_status": {
        "description": "Check if the offline local AI (Ollama) is running and its model is downloaded.",
        "properties": {},
        "required": [],
        "info": True,
    },
}
HANDLERS = {"ai_mode": ai_mode, "local_ai_status": local_ai_status}
