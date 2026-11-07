"""First-run voice setup (piece AU).

On the first start (no user.json yet) Jarvis talks the user through setup:

  1. name        "What should I call you?"            -> user.json "name"
  2. city        "Which city are you in?"             -> weather.city
  3. units       "Celsius or Fahrenheit?"             -> weather.units (metric | imperial)
  4. greeting    "After 'Jarvis', beep or 'Yes?'"     -> greeting ("beep" | "Yes?")
  5. mic test    "Say: good morning Jarvis."          (voice mode only)
  6. wake test   "Say just: Jarvis."                  (voice mode only)
  7. PIN         optional, saved by security.save_pin (hash only, never in user.json)
  8. self-check  doctor.run_checks (packages, model, voice, config, AI key, internet, files)

Any question: "skip" skips it, silence twice skips it, "stop setup" ends setup early.
Later: "run setup again", "change my name", "change my city", "set up a PIN", "test my mic".

Saved in ~/.jarvis/user.json (env JARVIS_USER_FILE changes it), never config.yaml.
The PIN is never saved here and never spoken back.

Public:
    USER_FILE, load_user(), save_user(data), needs_setup()
    config_overrides(user=None) -> dict     for config.py: merge over config.yaml values
    user_name(default="") -> str
    parse_name / parse_city / parse_units / parse_greeting / parse_yes_no   (helpers, tested)
    run(say, listen, cfg=None, voice=True, parts=None) -> str      the voice flow
    first_run(say, listen, cfg=None, voice=True) -> str | None     main: runs only when needs_setup()
    set_io(say, listen, voice=True)                                 so the `setup` intent can talk
    setup(args) -> str                                              intent handler
    CATALOG, HANDLERS
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jarvis.onboarding")

VERSION = 1
USER_FILE = Path(os.path.expanduser(os.environ.get("JARVIS_USER_FILE") or "~/.jarvis/user.json"))
PARTS = ["name", "city", "units", "greeting", "mic", "wake", "pin", "check"]
VOICE_ONLY = {"mic", "wake"}
MAX_TRIES = 2

_SKIP = {"skip", "skip it", "skip this", "next", "pass", "later", "not now", "no thanks", "none",
         "nothing", "i don't know", "dont know", "don't know"}
_STOP = {"stop", "stop setup", "cancel", "cancel setup", "exit setup", "quit setup", "end setup",
         "finish setup", "that's enough", "enough", "never mind"}
_NO = {"no", "nope", "nah", "no thanks", "not now", "don't", "dont", "negative", "skip"}
_YES = {"yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay", "yes please", "correct",
        "right", "that's right", "go ahead", "please"}


class _Stop(Exception):
    """User said 'stop setup'."""


# ---------- user.json ----------

def _path() -> Path:
    return Path(USER_FILE)


def load_user() -> dict:
    """user.json as a dict ({} when missing or broken)."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user(data: dict) -> Path:
    """Write user.json safely (temp file, then replace)."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in data.items() if k not in ("pin", "pin_hash")}  # never store a PIN here
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".user-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def needs_setup() -> bool:
    """True on first start: no user.json, or setup was cut off before the end."""
    return not load_user().get("done")


def config_overrides(user: dict | None = None) -> dict:
    """Settings from user.json in config.yaml shape. config.py merges this over config.yaml."""
    user = load_user() if user is None else (user or {})
    out: dict = {}
    name = str(user.get("name") or "").strip()
    if name:
        out["user_name"] = name
    weather = {}
    if str(user.get("city") or "").strip():
        weather["city"] = str(user["city"]).strip()
    if user.get("units") in ("metric", "imperial"):
        weather["units"] = user["units"]
    if weather:
        out["weather"] = weather
    greeting = user.get("greeting")
    if isinstance(greeting, str) and greeting.strip():
        out["greeting"] = greeting.strip()
    return out


def user_name(default: str = "") -> str:
    return str(load_user().get("name") or "").strip() or default


# ---------- parsing answers ----------

def _norm(text) -> str:
    if text is None:
        return ""
    t = str(text).strip().lower()
    t = re.sub(r"^(?:hey |ok |okay )?jarvis[,.!]?\s+", "", t)
    return re.sub(r"[.!?,]+$", "", t).strip()


def _is(text, words: set) -> bool:
    t = _norm(text)
    return t in words or re.sub(r"\s+please$", "", t) in words


_NAME_LEAD = re.compile(
    r"^(?:(?:you can |please |just )?call me|my name is|my name's|i am|i'm|im|it's|it is|this is|"
    r"name is|the name is|they call me)\s+", re.I)
_CITY_LEAD = re.compile(
    r"^(?:i (?:live|stay|am|'m) in|i'm in|im in|i live at|my city is|the city is|city is|"
    r"it's|it is|in|from|i'm from|i am from)\s+", re.I)
_NAME_OK = re.compile(r"^[^\W\d_][^\W\d_' .-]*(?:[ '.-][^\W\d_]+)*$")


def _title(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in text.split())


def parse_name(text) -> str | None:
    """'my name is rakesh' / 'call me Rakesh please' / 'Rakesh' -> 'Rakesh'. None if it does not look like a name."""
    t = _norm(text)
    t = _NAME_LEAD.sub("", t)
    t = re.sub(r"\s+(?:please|thanks|thank you)$", "", t).strip(" .,'\"")
    if not t or len(t) > 40 or len(t.split()) > 3 or not _NAME_OK.match(t):
        return None
    if t in _SKIP or t in _STOP or t in _YES or t in _NO:
        return None
    return _title(t)


def parse_city(text) -> str | None:
    """'I live in New Delhi' / 'hyderabad' -> 'New Delhi' / 'Hyderabad'."""
    t = _norm(text)
    t = _CITY_LEAD.sub("", t)
    t = re.sub(r"\s+(?:please|thanks|thank you)$", "", t).strip(" .,'\"")
    if not t or len(t) > 60 or len(t.split()) > 5 or re.search(r"\d", t):
        return None
    if t in _SKIP or t in _STOP or t in _YES or t in _NO:
        return None
    return _title(t)


def parse_units(text) -> str | None:
    t = _norm(text)
    if re.search(r"\b(?:celsius|celcius|centigrade|metric|c)\b", t):
        return "metric"
    if re.search(r"\b(?:fahrenheit|farenheit|imperial|f)\b", t):
        return "imperial"
    return None


def parse_greeting(text) -> str | None:
    """'beep' -> 'beep'; 'say yes' / 'voice' / 'speak' -> 'Yes?'."""
    t = _norm(text)
    if re.search(r"\b(?:beep|sound|tone|ding|quick|fast)\b", t):
        return "beep"
    if re.search(r"\b(?:yes|voice|speak|say|talk|words?|spoken)\b", t):
        return "Yes?"
    return None


def parse_yes_no(text, yes_words=None) -> bool | None:
    t = _norm(text)
    if not t:
        return None
    yes = set(_YES)
    for w in yes_words or []:
        yes.add("yes" if w is True else str(w).strip().lower())  # YAML may read a bare yes as True
    if t in _NO or re.match(r"^(?:no|nope|nah)\b", t):
        return False
    if t in yes or re.match(r"^(?:yes|yeah|yep|sure|ok|okay)\b", t):
        return True
    return None


# ---------- the voice flow ----------

class _Flow:
    def __init__(self, say, listen, cfg: dict, voice: bool):
        self.say, self._listen, self.cfg, self.voice = say, listen, cfg or {}, voice

    def listen(self, quiet: bool = False):
        """One answer. quiet=True: never log what was heard (PIN)."""
        text = self._listen()
        if not quiet and text:
            log.info("setup heard %r", text)
        if _is(text, _STOP):
            raise _Stop()
        return text

    def ask(self, question: str, parse, retry: str):
        """Ask, parse, retry once. Returns the parsed value or None (skipped)."""
        self.say(question)
        for attempt in range(MAX_TRIES):
            text = self.listen()
            if _is(text, _SKIP):
                self.say("Skipped.")
                return None
            value = parse(text)
            if value is not None:
                return value
            if attempt + 1 < MAX_TRIES:
                self.say(retry)
        self.say("Let's skip that for now.")
        return None

    def yes_no(self, question: str) -> bool | None:
        self.say(question)
        for attempt in range(MAX_TRIES):
            ans = parse_yes_no(self.listen(), self.cfg.get("yes_words"))
            if ans is not None:
                return ans
            if attempt + 1 < MAX_TRIES:
                self.say("Please say yes or no.")
        return None


def _step_name(f: _Flow, user: dict) -> None:
    name = f.ask("What should I call you?", parse_name, "Sorry, just say your name. For example: call me Rakesh.")
    if name:
        user["name"] = name
        f.say(f"Nice to meet you, {name}.")


def _step_city(f: _Flow, user: dict) -> None:
    city = f.ask("Which city are you in? I use it for the weather.", parse_city,
                 "Just say the city name, for example Hyderabad.")
    if city:
        user["city"] = city
        f.say(f"Got it, {city}.")


def _step_units(f: _Flow, user: dict) -> None:
    units = f.ask("Celsius or Fahrenheit?", parse_units, "Please say Celsius or Fahrenheit.")
    if units:
        user["units"] = units
        f.say("Celsius it is." if units == "metric" else "Fahrenheit it is.")


def _step_greeting(f: _Flow, user: dict) -> None:
    g = f.ask("When you say Jarvis, should I beep, or say 'Yes?'", parse_greeting, "Please say beep, or say yes.")
    if g:
        user["greeting"] = g
        f.say("I'll beep." if g == "beep" else "I'll say yes.")


def _step_mic(f: _Flow, user: dict) -> None:
    f.say("Let's test your microphone. After this, say: good morning Jarvis.")
    text = f.listen()
    if text and not _is(text, _SKIP):
        user["mic_ok"] = True
        f.say(f"I heard: {text}. Your microphone works.")
    else:
        user["mic_ok"] = False
        f.say("I heard nothing. Check that the mic is on and not muted in Windows sound settings. "
              "Say 'test my mic' to try again later.")


def _step_wake(f: _Flow, user: dict) -> None:
    word = str(f.cfg.get("wake_word") or "jarvis").lower()
    f.say(f"Now say just the wake word: {word}.")
    text = _norm(f.listen())
    if word in text.split() or word in text:
        user["wake_ok"] = True
        f.say("I heard the wake word.")
    else:
        user["wake_ok"] = False
        f.say(f"I didn't hear {word}. Speak a little closer to the mic. If I miss it often, "
              "say 'make wake word more sensitive'.")


def _step_pin(f: _Flow, user: dict) -> None:
    from jarvis.actions import security

    try:
        if security.has_pin():
            f.say("You already have a PIN. To change it, run the set-pin command on the laptop.")
            return
    except Exception as e:  # broken security config must not stop setup
        log.warning("PIN check failed: %s", e)
        return
    ans = f.yes_no("Do you want a PIN? I'll ask for it before risky things like shutdown or deleting files.")
    if not ans:
        f.say("No PIN. You can set one later: say 'set up a PIN'.")
        return
    for _ in range(MAX_TRIES):
        f.say(f"Say your PIN, {security.PIN_MIN} to {security.PIN_MAX} digits, one digit at a time.")
        first = security.spoken_digits(f.listen(quiet=True))
        if not (security.PIN_MIN <= len(first) <= security.PIN_MAX):
            f.say(f"That was not {security.PIN_MIN} to {security.PIN_MAX} digits.")
            continue
        f.say("Say it again.")
        second = security.spoken_digits(f.listen(quiet=True))
        if second != first:
            f.say("The two PINs did not match.")
            continue
        try:
            security.save_pin(first)
        except (OSError, ValueError) as e:
            log.warning("could not save PIN: %s", e)
            f.say("I could not save the PIN. Run the set-pin command on the laptop.")
            return
        user["pin_set"] = True
        f.say("PIN saved.")
        return
    f.say("Let's skip the PIN. You can set one later: say 'set up a PIN'.")


def _step_check(f: _Flow, user: dict) -> None:
    from jarvis.actions import doctor

    f.say("Last step: I'm checking my setup. This takes a few seconds.")
    try:
        results = doctor.run_checks(f.cfg or None, mic=False)  # mic was just tested by voice
        doctor.write_report(results)
        text = doctor.summary(results)
        problems = sum(r.status == doctor.PROBLEM for r in results)
    except Exception as e:
        log.warning("self-check failed: %s", e)
        f.say("I could not run the self-check. Run 'python main.py --doctor' later.")
        return
    user["check_problems"] = problems
    if problems:
        text += " Details and fixes are in doctor-report.txt."
    f.say(text)


_STEPS = {"name": _step_name, "city": _step_city, "units": _step_units, "greeting": _step_greeting,
          "mic": _step_mic, "wake": _step_wake, "pin": _step_pin, "check": _step_check}


def _load_cfg() -> dict:
    try:
        from jarvis.config import load_config

        return load_config()
    except Exception:
        return {}


def run(say, listen, cfg: dict | None = None, voice: bool = True, parts: list[str] | None = None) -> str:
    """Run the setup questions. Returns the last line for main to speak. Saves user.json."""
    cfg = _load_cfg() if cfg is None else cfg
    full = not parts
    parts = [p for p in (parts or PARTS) if p in _STEPS and (voice or p not in VOICE_ONLY)]
    f = _Flow(say, listen, cfg, voice)
    user = load_user()
    if full:
        say("Hi, I'm Jarvis. Let's set me up. It takes about a minute. "
            "Say skip to skip a question, or stop setup to finish early.")
    stopped = False
    try:
        for p in parts:
            _STEPS[p](f, user)
    except _Stop:
        stopped = True
    except KeyboardInterrupt:
        user.setdefault("done", False)
        _save(user)
        raise
    if full or user.get("done"):
        user["done"] = True
        user["version"] = VERSION
        user.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    user["updated"] = datetime.now().isoformat(timespec="seconds")
    _save(user)
    name = user.get("name")
    if stopped:
        return "Setup stopped. Say 'run setup again' any time."
    if full:
        hi = f", {name}" if name else ""
        return f"Setup done{hi}. Say Jarvis, then a command. Say 'what can I say' for ideas."
    return "Done."


def _save(user: dict) -> None:
    try:
        save_user(user)
    except OSError as e:
        log.warning("could not save %s: %s", _path(), e)


def first_run(say, listen, cfg: dict | None = None, voice: bool = True) -> str | None:
    """For main.py at start: run setup once. None when setup was already done."""
    if not needs_setup():
        return None
    return run(say, listen, cfg, voice=voice)


# ---------- intent ----------

_io: dict = {"say": None, "listen": None, "voice": True}


def set_io(say, listen, voice: bool = True) -> None:
    """main.py: onboarding.set_io(io.say, io.listen, voice=not args.text)."""
    _io.update(say=say, listen=listen, voice=voice)


_PART_ALIASES = {
    "all": None, "everything": None, "again": None,
    "name": ["name"], "city": ["city", "units"], "weather": ["city", "units"], "units": ["units"],
    "greeting": ["greeting"], "beep": ["greeting"], "mic": ["mic"], "microphone": ["mic"],
    "wake": ["wake"], "wake_word": ["wake"], "pin": ["pin"], "check": ["check"],
}


def _has_pin() -> bool:
    try:
        from jarvis.actions import security

        return bool(security.has_pin())
    except Exception:
        return True  # unknown: don't offer a voice PIN


def setup(args: dict) -> str:
    """'run setup again' / 'change my name' / 'change my city' / 'set up a PIN' / 'test my mic'."""
    part = str((args or {}).get("part") or "all").strip().lower().replace(" ", "_")
    if part not in _PART_ALIASES:
        return f"I can set up: {', '.join(k for k in _PART_ALIASES if k not in ('everything', 'again'))}."
    if not (_io["say"] and _io["listen"]):
        return "Setup needs the microphone. Restart Jarvis and try again."
    parts = _PART_ALIASES[part]
    if parts and not _io["voice"] and all(p in VOICE_ONLY for p in parts):
        return "The mic and wake word tests only work in voice mode."
    if _io["voice"] and "pin" in (parts or PARTS) and not _has_pin():
        # By voice, anyone in the room could set the FIRST PIN and lock the owner out of protected things.
        if parts == ["pin"]:
            return ("For safety, the first PIN is set on the laptop: run python main.py --setup, "
                    "or use text mode, then say set up a PIN.")
        parts = [p for p in (parts or PARTS) if p != "pin"]
    return run(_io["say"], _io["listen"], voice=_io["voice"], parts=parts)


CATALOG: dict[str, dict] = {
    "setup": {"description": "Voice setup: asks the user's name, city, temperature units, beep or spoken "
                             "greeting, tests the mic and wake word, offers a PIN, and runs a self-check. "
                             "part picks one step (e.g. 'change my name' -> name); default all.",
              "properties": {"part": {"type": "string",
                                      "enum": ["all", "name", "city", "units", "greeting", "mic", "wake",
                                               "pin", "check"]}},
              "required": []},
}
HANDLERS = {"setup": setup}
