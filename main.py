"""Jarvis core: wake word -> listen -> understand -> act -> reply -> repeat.

Run:
    python main.py            # voice mode (mic + speaker)
    python main.py --text     # type commands instead of speaking (for testing)
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import atexit
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jarvis.config import ConfigError, load_config  # noqa: E402

log = logging.getLogger("jarvis")


def setup_logging(log_file: str) -> None:
    path = Path(log_file)
    if not path.is_absolute():
        path = ROOT / path
    # Rotating: the log holds what you said, so keep it small (max about 4 MB in 4 files).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:  # Jarvis folder is read-only (e.g. under Program Files): log in ~/.jarvis instead
        path = Path.home() / ".jarvis" / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[file_handler] + ([logging.StreamHandler()] if sys.stderr is not None else []),  # pythonw: no console
    )


# ---------- input / output backends ----------

class VoiceIO:
    """Real mic + speaker, using the stt and tts modules."""

    def __init__(self, cfg: dict):
        from jarvis import stt, tts

        self.stt, self.tts, self.cfg = stt, tts, cfg
        if hasattr(tts, "configure"):
            v = cfg["voice"]
            tts.configure(rate=v.get("rate"), volume=v.get("volume"), voice=v.get("voice_name") or None)
        self.wake_engine, self._wake_wait = "vosk", None
        try:  # openWakeWord ("hey Jarvis") if set up, else Vosk; choose() never raises, this is extra safety
            from jarvis.actions import wakeword

            self.wake_engine, self._wake_wait = wakeword.choose(cfg)
        except Exception:
            log.exception("wake engine choice failed; using vosk")

    follow_up = True  # after a reply, keep listening a few seconds without the wake word

    def wait_for_wake_word(self) -> None:
        _tray_state("idle")
        if self._wake_wait is not None:
            self._wake_wait()
        else:
            self.stt.wait_for_wake_word(self.cfg["wake_word"])

    def greet(self) -> None:
        """Short beep (fast) or a spoken greeting after the wake word."""
        g = (self.cfg.get("greeting") or "").strip()
        if g.lower() in ("", "beep"):
            try:
                import winsound

                winsound.Beep(1000, 120)
            except Exception:
                print("Jarvis: (listening)")
        else:
            self.say(g)

    def listen(self, timeout: float | None = None) -> str | None:
        _tray_state("listening")
        t = timeout or self.cfg["listen_timeout"]
        multilang = _multilang()
        if multilang is not None and multilang.is_active():  # Hindi / Telugu too: returns English text
            return multilang.listen(timeout=t)
        return self.stt.listen(timeout=t)

    def say(self, text: str) -> None:
        _record(text)  # tts.say prints the line itself
        _tray_state("speaking")
        try:
            multilang = _multilang()
            if multilang is not None and text and multilang.reply_language() != "en" and multilang.say_reply(text):
                return  # already spoken in Hindi / Telugu
            self.tts.say(text)
        finally:
            _tray_state("idle")


class TextIO:
    """Keyboard + screen. No mic or speaker needed."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def wait_for_wake_word(self) -> None:
        pass  # in text mode every line is a command

    def listen(self) -> str | None:
        try:
            return input("You: ").strip() or None
        except EOFError:
            raise KeyboardInterrupt

    def say(self, text: str) -> None:
        print(f"Jarvis: {text}")
        _record(text)


# ---------- "repeat that": remember what Jarvis said ----------

_recorder = None   # assistant.record, set in main()
_status = False    # True while saying status lines ("Jarvis is ready") that "repeat that" should skip


_redactor = None   # security.redact, set in main(): no PIN in logs or in "repeat that"
_last_intent = None  # intent of the last top-level command (setup reloads the config)
_tray = None       # tray module, set in main() when the tray icon is shown (voice mode only)


def _multilang():
    try:
        from jarvis.actions import multilang

        return multilang
    except Exception:
        return None


def _remember_voice(io, actions) -> None:
    """Voice ID: keep the audio of the command just heard (not of a PIN or a yes). Typed text has no voice."""
    voiceid = getattr(actions, "voiceid", None)
    if voiceid is None:
        return
    try:
        stt = getattr(io, "stt", None)
        voiceid.remember_audio(getattr(stt, "last_audio", b"") if stt is not None else b"")
    except Exception:
        log.exception("voice id audio failed")


def _tray_state(state: str) -> None:
    if _tray is not None:
        try:
            _tray.set_state(state)
        except Exception:
            pass


def _apply_corrections(text: str, actions) -> str:
    """The user's own word fixes ("when you hear note pad I mean notepad"), right after listening."""
    corrections = getattr(actions, "corrections", None)
    if corrections is None or not text:
        return text
    security = getattr(actions, "security", None)
    if security is not None and security.pending():  # a spoken PIN is never "corrected"
        return text
    try:
        return corrections.apply(text) or text
    except Exception:
        log.exception("corrections failed")
        return text
_turn_lock = threading.RLock()  # one command at a time: the main loop and background triggers share it


def _redact(text):
    if _redactor is None or not text:
        return text
    try:
        return _redactor(text)
    except Exception:
        return text


def _record(text: str) -> None:
    if _recorder is not None and not _status and text:
        try:
            _recorder(_redact(text))
        except Exception:
            pass


def _say_status(io, text: str) -> None:
    """Say a status line that is not an answer (not kept for "repeat that")."""
    global _status
    _status = True
    try:
        io.say(text)
    finally:
        _status = False


# ---------- core logic ----------

def is_yes(text: str | None, yes_words: list[str]) -> bool:
    if not text:
        return False
    words = f" {text.lower().strip(' .!?').replace(',', ' ')} "
    if any(f" {n} " in words for n in ("no", "not", "don't", "dont", "cancel", "stop")):
        return False
    # YAML reads a bare  yes  as True, so turn True back into "yes"
    words_ok = ["yes" if w is True else str(w).lower() for w in yes_words if w is not False]
    return any(f" {w} " in words for w in words_ok)


def is_exit(text: str, exit_phrases: list[str]) -> bool:
    """True only if the WHOLE phrase is an exit phrase ("goodbye", "goodbye jarvis"),
    so "whatsapp mom saying goodbye" does not quit Jarvis."""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = " ".join(re.sub(r"\b(?:please|ok|okay|hey)\b", " ", t).split())
    for p in exit_phrases:
        p = " ".join(str(p).lower().split())
        if p and t in (p, f"jarvis {p}", f"{p} jarvis"):
            return True
    return False


_QUESTION = re.compile(r"^(?:what|who|whom|whose|why|when|where|which|how)\b")
_EXPLICIT_SEARCH = re.compile(r"^\W*(?:(?:hey|ok|okay|hi)\s+)?(?:jarvis\W*)?(?:please\s+)?(?:search|google|look up|find)\b", re.I)


def _wants_answer(text: str, cmd) -> bool:
    """'what is X' style questions go to the AI (spoken answer) instead of a browser search.
    Also reminders/timers where the rules could not find the time ('alarm for tomorrow morning')."""
    if cmd.intent in ("reminder", "timer") and not cmd.args.get("seconds"):
        return True
    if cmd.intent != "web_search":
        return False
    return bool(_QUESTION.match(cmd.args.get("query", ""))) and not _EXPLICIT_SEARCH.match(text)


def _needs_confirm(cmd, cfg: dict, actions) -> bool:
    if cmd.args.get("confirm"):
        return False
    if cmd.intent in cfg["confirm_intents"]:
        return True
    check = getattr(actions, "needs_confirm", None)
    return bool(check and check(cmd))


# While a quiz question waits: what ends it, what skips it, and which parses count as an answer.
_QUIZ_STOP = {"stop", "stop it", "quit", "end", "enough", "that's enough", "i'm done", "done", "no more", "exit"}
_QUIZ_SKIP = {"skip", "skip it", "pass", "next", "next question", "i don't know", "no idea"}
_QUIZ_ANSWER_INTENTS = {"unknown", "web_search", "calculate", "answer"}


def _ai_question(cmd) -> str | None:
    """Things the AI may only start after a spoken yes (mic/screen recording, opening a recent file)."""
    action = str(cmd.args.get("action") or "")
    if cmd.intent == "memo" and action == "record":
        return "start recording a voice memo with your microphone"
    if cmd.intent == "screen_record" and action == "start":
        return "start recording your screen"
    if cmd.intent == "recent_files" and action == "open":
        return "open that recent file"
    return None


def _security_ok(cmd, io, actions, cfg: dict | None = None) -> str | None:
    """PIN / guest mode check (piece AE). None = go ahead, else the reply to give."""
    security = getattr(actions, "security", None)
    if security is None:
        return None
    voiceid = getattr(actions, "voiceid", None)
    if voiceid is not None:  # voice lock (piece BU): the owner's voice may replace the PIN; lock/guest still win
        risky = _needs_confirm(cmd, cfg, actions) if cfg is not None else bool(actions.needs_confirm(cmd))
        return voiceid.guard(cmd, io, security, risky=risky)
    msg = security.check(cmd)
    if not msg:
        return None
    if not security.pending() or getattr(io, "no_ask", False):
        return msg  # blocked (guest mode / locked out), or a background trigger that can't ask
    io.say(msg)  # "Say your PIN."
    ok, reply = security.verify(_listen_private(io))  # the PIN never goes to the log, history or "repeat that"
    return None if ok else reply


# Replies with private data are spoken in English, never sent to an online translator (review K3).
PRIVATE_REPLIES = {"read_clipboard", "clip_history", "check_email", "notifications", "contact_get", "contacts_list",
                   "generate", "hotspot", "recap", "read_notes"}


def _keep_english(text: str) -> None:
    ml = _multilang()
    if ml is not None:
        try:
            ml.keep_english(text)
        except Exception:
            pass


def _listen_private(io):
    """Listen for a PIN or a yes/no answer: with Hindi/Telugu on, it is never translated online (review K1)."""
    ml = _multilang() if isinstance(io, VoiceIO) else None
    if ml is not None:
        try:
            ml.private_next()
        except Exception:
            pass
    return io.listen()


def _run_one(cmd, io, cfg: dict, actions, nlu=None, brain=None, depth: int = 0, from_ai: bool = False) -> str:
    if cmd.intent == "routine":
        return run_routine(cmd.args.get("name", ""), io, cfg, nlu, actions, brain, depth)
    blocked = _security_ok(cmd, io, actions, cfg)  # before "are you sure?", so a guest can't even hear the question
    if blocked:
        return blocked
    if cmd.intent == "history" and cmd.args.get("action") == "repeat_last":
        history = getattr(actions, "history", None)
        if from_ai:
            return "I won't repeat a command on my own. Say 'do that again' yourself."
        if history is not None and depth < 3:
            again = history.last_command()
            if again is None:
                return "There is nothing to do again yet."
            # saved args never hold confirm, so risky commands ask "are you sure?" again
            return _run_one(again, io, cfg, actions, nlu, brain, depth + 1, from_ai=history.last_was_ai())
    no_ask = getattr(io, "no_ask", False)
    question = _ai_question(cmd) if from_ai and not cmd.args.get("confirm") else None
    if question and no_ask:
        return f"I skipped this because it needs your yes: {question}."
    if question:
        io.say(f"Do you want me to {question}? Say yes to confirm.")
        if not is_yes(_listen_private(io), cfg["yes_words"]):
            return "Okay, cancelled."
    if cmd.intent == "page_text" and not cmd.args.get("read"):
        cmd.args["read"] = True  # no AI here to summarize it: read it out instead
    if _needs_confirm(cmd, cfg, actions):
        if no_ask:  # background trigger: never auto-confirm a risky step
            return f"I skipped {cmd.intent.replace('_', ' ')} because it needs your yes."
        # actions.run without confirm=True only returns the question, it does not act.
        io.say(actions.run(cmd))
        if not is_yes(_listen_private(io), cfg["yes_words"]):
            actions.run(type(cmd)("cancel", {}))  # clear the pending action in actions
            return "Okay, cancelled."
        cmd.args["confirm"] = True
    reply = actions.run(cmd)
    if cmd.intent in PRIVATE_REPLIES and reply:
        _keep_english(reply)
    if cmd.intent == "memo" and cmd.args.get("action") == "record":
        memos = getattr(actions, "memos", None)
        if memos is not None and memos.is_recording():
            if reply:
                io.say(reply)  # say "Recording" first, so it is not in the memo
            memos.begin()
            return ""
    if cmd.intent == "focus":  # a "focus" routine in config.yaml runs when a focus session starts
        focus = getattr(actions, "focus", None)
        name = focus.take_routine() if focus is not None else ""
        if name and nlu is not None:
            if reply:
                io.say(reply)
            run_routine(name, io, cfg, nlu, actions, brain, depth)
            return ""
    return reply


def _routine_name(text: str, cfg: dict) -> str | None:
    routines = cfg.get("routines") or {}
    if not routines:
        return None
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis\s+)?", "", t).strip()
    m = re.match(r"^(?:start|run|begin|activate|turn on|enable|do)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:mode|routine))?$", t)
    for cand in (t, m.group(1) if m else None, (m.group(1) + " mode") if m else None):
        if cand:
            for name in routines:
                if cand == str(name).lower():
                    return name
    return None


def run_routine(name: str, io, cfg: dict, nlu, actions, brain=None, depth: int = 0) -> str:
    """Run each step of a routine from config.yaml, as if the user said them one by one."""
    routines = {str(k).lower(): v for k, v in (cfg.get("routines") or {}).items()}
    key = str(name).lower().strip()
    steps = routines.get(key) or routines.get(key + " mode")
    if not steps:
        return f"I don't have a routine called {name}." + (
            f" You have: {', '.join(routines)}." if routines else " Add routines in config.yaml.")
    if depth > 2 or nlu is None:
        return "That routine calls itself, so I stopped."
    for step in steps:
        reply = handle(str(step), io, cfg, nlu, actions, brain, depth + 1)
        if reply:
            io.say(reply)
    return f"{str(name).capitalize()} is done."


def handle(text: str, io, cfg: dict, nlu, actions, brain=None, depth: int = 0, skip_modes: bool = False) -> str:
    """Turn one spoken sentence into a reply. Asks 'are you sure?' for risky actions.

    Dictation first (types everything), then routines, your shortcuts, then rules (nlu): fast and offline.
    Anything they don't understand goes to the AI brain.
    """
    global _last_intent
    if depth == 0:  # only what the user said; routine, taught and trigger steps are used as written
        _last_intent = None
        text = _apply_corrections(text, actions)
    # skip_modes: trigger steps are commands, never words to type, translate or answer a quiz with
    dictation = None if skip_modes else getattr(actions, "dictation", None)
    if dictation is not None and dictation.is_active():
        security = getattr(actions, "security", None)
        msg = security.check("dictation") if security is not None else None
        if msg:  # locked or guest mode: don't type
            return msg
        return dictation.process(text)  # "" = say nothing (and never saved to history)

    interpreter = None if skip_modes else getattr(actions, "interpreter", None)
    if interpreter is not None and interpreter.is_active():  # translate mode: skip nlu and the AI brain
        security = getattr(actions, "security", None)
        msg = security.check("interpreter") if security is not None else None
        if msg:
            return msg
        return interpreter.process(text)  # "" = already spoken in that language

    flashcards = None if skip_modes else getattr(actions, "flashcards", None)
    if flashcards is not None and flashcards.is_active():  # flashcard quiz: answers, skip, stop go to the quiz
        fcmd = nlu.parse(text)
        if flashcards.takes(text, fcmd.intent):
            return flashcards.process(text)
        # any other clear command ("open chrome", "what time is it") runs normally; the quiz keeps waiting

    fun = None if skip_modes else getattr(actions, "fun", None)
    if fun is not None and fun.quiz_pending():  # a quiz question is waiting: these words are the answer
        cmd = nlu.parse(text)
        t = " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())
        if cmd.intent == "cancel" or t in _QUIZ_STOP:
            cmd = type(cmd)("quiz", {"action": "stop"})
        elif t in _QUIZ_SKIP:
            cmd = type(cmd)("quiz", {"action": "skip"})
        elif cmd.intent in _QUIZ_ANSWER_INTENTS:
            cmd = type(cmd)("quiz", {"action": "answer", "answer": text})
        # any other clear command ("open chrome", "what time is it") runs normally; the quiz keeps waiting
        if cmd.intent == "quiz":
            return _run_one(cmd, io, cfg, actions, nlu, brain, depth)

    recipes = None if skip_modes else getattr(actions, "recipes", None)
    if recipes is not None and recipes.is_active():  # cook mode: "next", "repeat", "ingredients", "start a timer"
        hit = recipes.match_cook(text)
        if hit is not None:
            from jarvis.nlu import Command

            cmd = Command(*hit)
            return _log_history(text, cmd, _run_one(cmd, io, cfg, actions, nlu, brain, depth), actions, depth)
        # anything else ("what time is it", "set a timer for 5 minutes") runs normally; cook mode stays on

    # Locked: no routines, shortcuts or taught phrases (a taught answer would skip the PIN check).
    # The sentence goes to the rules below, and _run_one asks for the PIN.
    sec = getattr(actions, "security", None)
    locked = bool(sec is not None and sec.is_locked())
    name = None if locked else _routine_name(text, cfg)
    # a routine called "focus" belongs to focus sessions: "start focus" starts a session, which runs it
    if name is not None and not (str(name).lower() == "focus" and getattr(actions, "focus", None) is not None):
        reply = run_routine(name, io, cfg, nlu, actions, brain, depth)
        return _log_history(text, _make_cmd(nlu, "routine", {"name": name}), reply, actions, depth)

    shortcuts = getattr(actions, "shortcuts", None)
    hit = shortcuts.match(text) if shortcuts is not None and not locked else None
    if hit:
        from jarvis.nlu import Command

        cmd = Command(*hit)
        log.info("heard=%r shortcut=%s args=%s", _redact(text), cmd.intent, _safe_args(cmd))
        reply = _run_one(cmd, io, cfg, actions, nlu, brain, depth)
        return _log_history(text, cmd, reply, actions, depth)

    teach = None if locked else getattr(actions, "teach", None)
    if teach is not None:  # "when I say study time, open notes and start focus"
        reply = teach.run(text, lambda s: handle(s, io, cfg, nlu, actions, brain, depth + 1), io.say, depth)
        if reply is not None:
            return _log_history(text, None, reply, actions, depth)

    cmd = nlu.parse(text)
    log.info("heard=%r intent=%s args=%s", _redact(text), cmd.intent, _safe_args(cmd))

    ai_cfg = cfg.get("ai") or {}
    from_ai = False
    if brain is not None and (cmd.intent == "unknown"
                              or (cmd.intent == "page_text" and not cmd.args.get("read") and brain.available)
                              or (ai_cfg.get("answer_questions", True) and _ai_ready(brain, actions)
                                  and _wants_answer(text, cmd))):
        blocked = _ai_blocked(text, io, nlu, actions)
        if blocked:
            return blocked
        cmds = brain.ask(text, on_sentence=io.say)  # "summarize this page": the AI reads it and answers
        from_ai = True
    elif cmd.intent == "unknown":
        return "Sorry, I did not understand that."
    else:
        cmds = [cmd]

    replies = [_run_one(c, io, cfg, actions, nlu, brain, depth, from_ai=from_ai) for c in cmds]
    reply = " ".join(r for r in replies if r)
    return _log_history(text, cmds[0] if cmds else cmd, reply, actions, depth, from_ai)


_PIN_TALK = re.compile(r"\b(?:pin|passcode|unlock)\b.*?(?:\d\D{0,3}){4}|(?:\d\D{0,3}){4}.*?\b(?:pin|passcode|unlock)\b", re.I)


def _says_pin(text: str, security) -> bool:
    """A sentence about a PIN/unlock that holds 4+ digits, as digits or words ("one two three four")."""
    t = text or ""
    if _PIN_TALK.search(t):
        return True
    if not re.search(r"\b(?:pin|passcode|pass code|unlock|code)\b", t, re.I):
        return False
    try:
        return len(security.spoken_digits(t)) >= 4
    except Exception:
        return False


def _ai_blocked(text: str, io, nlu, actions) -> str | None:
    """Reply instead of calling the AI, or None. The AI's lookups (email, screen, clipboard...) must follow
    lock and guest mode too, and a PIN must never be sent to the cloud."""
    security = getattr(actions, "security", None)
    if security is None:
        return None
    if security.pending() or _says_pin(text, security):
        return "Please say just the PIN, or say unlock Jarvis first."
    if security.is_locked() or security.is_guest():
        return _security_ok(_make_cmd(nlu, "answer", {}), io, actions)
    return None


def guarded_runner(actions):
    """runner for the AI's info tools: same PIN / guest rules as spoken commands. Never asks for a PIN
    (nobody is listening for it mid-answer); the AI just hears that it is protected."""
    security = getattr(actions, "security", None)

    def run(cmd):
        if security is not None:
            msg = security.check(cmd)
            if msg:
                security.cancel_pending()
                return "Not allowed: this needs the owner's PIN. Tell the user to ask again after unlocking."
        return actions.run(cmd)

    return run


def _make_cmd(nlu, intent: str, args: dict):
    try:
        return nlu.Command(intent, args)
    except Exception:
        from jarvis.nlu import Command

        return Command(intent, args)


def _safe_args(cmd) -> dict:
    """Args for the log, without a PIN."""
    return {k: v for k, v in (cmd.args or {}).items() if k not in ("pin", "password", "code")}


def _ai_ready(brain, actions) -> bool:
    """Claude has a key, or the local AI (Ollama) will answer instead."""
    if brain.available:
        return True
    localai = getattr(actions, "localai", None)
    try:
        return bool(localai is not None and localai.use_local(False))
    except Exception:
        return False


def _log_history(text: str, cmd, reply: str, actions, depth: int, from_ai: bool = False) -> str:
    """Save the top-level command to history (piece AF). history.log never raises and never saves PINs."""
    global _last_intent
    if depth == 0:
        _last_intent = getattr(cmd, "intent", None)
    history = getattr(actions, "history", None)
    security = getattr(actions, "security", None)
    pin_asked = bool(security is not None and security.pending())
    if depth == 0 and history is not None and not pin_asked:
        try:
            history.log(_redact(text), cmd, _redact(reply), from_ai=from_ai)
        except Exception:
            log.exception("history log failed")
    return reply


DICTATION_IDLE_LISTENS = 30  # while dictating, keep listening through this many silent gaps


def _dictating(actions) -> bool:
    d = getattr(actions, "dictation", None)
    return bool(d is not None and d.is_active())


def _paused(text: str, cfg: dict, actions) -> bool:
    """True if Jarvis is paused ("stop listening for 10 minutes") and this phrase must be ignored."""
    a = getattr(actions, "assistant", None)
    return bool(a is not None and a.is_paused() and not a.allowed_while_paused(text)
                and not is_exit(text, cfg["exit_phrases"]))


def _wait_for_memo(io, actions) -> None:
    """Never open the mic while a voice memo is recording (it stops by itself after a quiet gap)."""
    memos = getattr(actions, "memos", None)
    if memos is None or isinstance(io, TextIO):  # typing does not use the mic
        return
    while memos.is_recording():
        time.sleep(0.2)


def _next_phrase(io, follow: float, actions) -> str | None:
    """Follow-up listening. While dictating, keep listening through short silences."""
    if not follow:
        return None
    _wait_for_memo(io, actions)
    text = io.listen(timeout=follow)
    tries = 0
    while not text and _dictating(actions) and tries < DICTATION_IDLE_LISTENS:
        text = io.listen(timeout=follow)
        tries += 1
    return text


MIC_RETRY_SECONDS = 5


def run(io, cfg: dict, nlu, actions, once: bool = False, brain=None) -> None:
    _say_status(io, "Jarvis is ready.")
    follow = float(cfg.get("follow_up_seconds") or 0) if getattr(io, "follow_up", False) else 0
    assistant = getattr(actions, "assistant", None)
    mic_error = False  # say the mic problem once, not every 5 seconds
    while True:
        try:
            _wait_for_memo(io, actions)
            io.wait_for_wake_word()
            paused = assistant is not None and assistant.is_paused()
            if not isinstance(io, TextIO) and not paused:
                greet = getattr(io, "greet", None)
                greet() if greet else _say_status(io, cfg["greeting"])
            text = io.listen()
            if not text:
                if not isinstance(io, TextIO) and not paused:
                    _say_status(io, "I did not hear anything.")
                continue
            while text:  # follow-up mode: keep talking without the wake word
                _remember_voice(io, actions)  # the command's own audio, before any PIN or yes is heard
                if _paused(text, cfg, actions):
                    break  # ignore everything except "start listening" (and exit phrases)
                if not _dictating(actions) and is_exit(text, cfg["exit_phrases"]):
                    _stop_recordings(actions)
                    _say_status(io, "Goodbye.")
                    return
                if assistant is not None:
                    assistant.new_turn()
                try:
                    _tray_state("thinking")
                    with _turn_lock:  # a background trigger waits until this command is done
                        reply = handle(text, io, cfg, nlu, actions, brain)
                    if _last_intent == "setup":  # "change my city": use the new name/city/greeting now
                        cfg.update(load_config(cfg.get("_config_file"), reload=True))
                except Exception as e:  # one bad command must not crash Jarvis
                    log.exception("command failed")
                    reply = f"Sorry, something went wrong: {e}"
                if reply:
                    io.say(reply)
                text = _next_phrase(io, follow, actions)
        except KeyboardInterrupt:
            _stop_recordings(actions)
            _say_status(io, "Goodbye.")
            return
        except Exception:  # mic unplugged, audio driver error...: wait and try again, never quit
            log.exception("listening failed")
            if once:
                return
            if not mic_error:
                _say_status(io, "I can't hear the microphone. I'll keep trying.")
            mic_error = True
            time.sleep(MIC_RETRY_SECONDS)
            continue
        mic_error = False
        if once:
            return


def _stop_recordings(actions) -> None:
    """On exit: save a running screen recording and today's screen time, stop the triggers."""
    for name, fn in (("recorder", "stop_all"), ("screentime", "stop"), ("triggers", "stop"), ("notifications", "stop"),
                     ("tray", "stop"), ("habits", "stop"), ("watchers", "stop"),
                     ("birthdays", "stop"), ("radio", "stop_all"),
                     ("recap", "stop")):
        mod = getattr(actions, name, None)
        if mod is not None:
            try:
                getattr(mod, fn)()
            except Exception:
                log.exception("could not stop %s", name)


class _NoAskIO:
    """io for background triggers: speaks, but never listens, so risky steps are skipped, never auto-confirmed."""
    no_ask = True

    def __init__(self, io):
        self._io = io

    def say(self, text: str) -> None:
        self._io.say(text)

    def listen(self, timeout=None):
        return None


def _trigger_runner(io, cfg: dict, nlu, actions, brain):
    """Run one trigger step (from config.yaml) like a routine step, on the trigger thread."""
    quiet = _NoAskIO(io)

    def run_step(phrase: str) -> str:
        with _turn_lock:  # wait while the user's own command runs
            return handle(str(phrase), quiet, cfg, nlu, actions, brain, depth=1, skip_modes=True)
    return run_step


def _unlocked_say(say, generic: str):
    """Background voice that keeps private details quiet while Jarvis is locked or in guest mode
    (review Z4/E3/N3): a visitor hears only `generic`."""
    def _say(text, *a, **k):
        try:
            from jarvis.actions import security

            private = security.is_locked() or security.is_guest()
        except Exception:
            private = False
        if not private:
            _keep_english(text)  # background voices hold private data: never translated online (K3)
        return say(generic if private else text, *a, **k)
    return _say


def _wire_features(io, actions) -> None:
    """Background voices and hooks of the new features. Each one is optional and must not stop Jarvis."""
    steps = [
        ("assistant", lambda m: globals().__setitem__("_recorder", m.record)),  # "repeat that"
        ("focus", lambda m: m.set_notifier(io.say)),          # focus/break changes are spoken
        ("monitor", lambda m: m.start(io.say)),               # battery / CPU / disk alerts
        ("agenda", lambda m: m.start_alerts(_unlocked_say(io.say, "You have a calendar alert. Unlock to hear it."))),         # "Meeting X starts in 5 minutes"
        ("recurring", lambda m: m.start(io.say)),             # repeating reminders
        ("memos", lambda m: m.set_notifier(io.say)),          # "Memo saved, 12 seconds."
        ("recorder", lambda m: atexit.register(m.stop_all)),  # save a screen recording even on a crash exit
        ("software", lambda m: m.set_notifier(io.say)),       # "VLC is installed." when winget finishes
        ("cliphistory", lambda m: m.start()),                 # clipboard history (kept in memory)
        ("security", lambda m: (m.configure(), globals().__setitem__("_redactor", m.redact))),  # PIN lock
        ("screentime", lambda m: m.start(io.say)),            # app usage + "you used YouTube for an hour"
        ("notifications", lambda m: m.start(_unlocked_say(io.say, "You have a new notification."))),        # reads new notifications out, if announce is on
        ("habits", lambda m: m.start(_unlocked_say(io.say, "Habit check: some habits are not done today."))),               # evening habit nudge, only if habits.remind_at is set
        ("birthdays", lambda m: m.start(_unlocked_say(io.say, "You have a birthday reminder today."))),            # "Today is Ravi's birthday" once a day
        ("sleeptimer", lambda m: m.set_notifier(io.say)),     # "The laptop sleeps in 1 minute. Say cancel sleep timer"
        ("recap", lambda m: m.start(_unlocked_say(io.say, "Your evening recap is ready. Unlock to hear it."))),                # evening recap, only if recap.at is set
        ("watchers", lambda m: m.set_notifier(_unlocked_say(io.say, "One of your watches has finished."))),      # "Your download finished."
    ]
    for name, step in steps:
        mod = getattr(actions, name, None)
        if mod is None:
            continue
        try:
            step(mod)
        except Exception:
            log.exception("could not start %s", name)


def _start_tray(io, actions, args, cfg: dict) -> None:
    """System tray icon: pause, open config/log, self-check, restart, quit. Missing pystray = no icon, no crash."""
    global _tray
    tray = getattr(actions, "tray", None)
    if tray is None:
        return

    def _quit_from_tray():
        _stop_recordings(actions)
        os._exit(0)  # the main loop is blocked in the mic; a normal return can't reach it

    log_file = Path(cfg["log_file"])
    if not log_file.is_absolute():
        log_file = ROOT / log_file  # same place setup_logging writes to
    try:
        if tray.start(on_quit=_quit_from_tray, say=io.say, config_file=args.config or None, log_file=log_file):
            _tray = tray
    except Exception:
        log.exception("could not start the tray icon")


def _failsafe_off() -> None:
    """pyautogui stops every key press when the mouse rests in a screen corner. Normal commands should still work,
    so it is off; screen control (agent.py) turns it on while it runs, where the corner is the stop button."""
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
    except Exception:  # not installed, or no display
        pass


def _config_problem(msg: str) -> None:
    """Show, save and say a config.yaml mistake (Jarvis may run hidden, with no window)."""
    print(msg)
    try:
        with open(ROOT / "jarvis-crash.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{msg}\n")
    except OSError:
        pass
    try:
        from jarvis import tts

        tts.say("I can't start. " + msg.split(" Tip:")[0] + " Please fix config.yaml.")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument("--text", action="store_true", help="type commands instead of speaking")
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--doctor", action="store_true", help="check mic, model, voice, packages, config and exit")
    parser.add_argument("--full", action="store_true", help="with --doctor: also test the AI key with one tiny call")
    parser.add_argument("--setup", action="store_true", help="run the voice setup again (name, city, mic, PIN...)")
    args = parser.parse_args(argv)
    from jarvis import winutil

    winutil.fix_console()  # a reply with a rupee sign or emoji must not crash print() in a Windows console
    if args.doctor:  # before the mic or speech model start, so a broken one cannot crash the check
        from jarvis.actions import doctor

        return doctor.run_cli(["--full"] if args.full else [])

    try:
        cfg = load_config(args.config)
    except ConfigError as e:  # e.g. a Windows path in double quotes: tell the user, don't crash 5 times
        _config_problem(str(e))
        return 1
    setup_logging(cfg["log_file"])
    if not args.text and not winutil.single_instance():  # auto-start + a manual start = two Jarvis answering
        log.warning("Jarvis is already running; this copy stops.")
        print("Jarvis is already running (look for the tray icon, or use packaging\\uninstall.bat to stop it).")
        return 0

    from jarvis import actions, nlu

    _failsafe_off()
    io = TextIO(cfg) if args.text else VoiceIO(cfg)
    if hasattr(actions, "set_notifier"):
        actions.set_notifier(io.say)  # timers and reminders speak when they finish
    if hasattr(actions, "control"):
        actions.control.set_io(io.say, io.listen)  # screen control asks questions mid-task
    if hasattr(actions, "start_reminders"):
        actions.start_reminders(cfg.get("reminders_file") or "")
    _wire_features(io, actions)
    if not args.text:
        _start_tray(io, actions, args, cfg)
    onboarding = getattr(actions, "onboarding", None)
    if onboarding is not None:  # first start (or --setup): name, city, greeting, mic test, PIN, self-check
        try:
            onboarding.set_io(io.say, io.listen, voice=not args.text)
            if getattr(actions, "voiceid", None) is not None:
                actions.voiceid.set_io(io.say, voice=not args.text)  # "learn my voice" talks and records
            if args.setup or onboarding.needs_setup():
                io.say(onboarding.run(io.say, io.listen, cfg, voice=not args.text))
                cfg.update(load_config(args.config, reload=True))  # new name, city, greeting
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("setup failed")
    cfg["_config_file"] = args.config

    brain = None
    if (cfg.get("ai") or {}).get("enabled", True):
        from jarvis.brain import Brain

        brain = Brain(cfg, getattr(actions, "CATALOG", {}), runner=guarded_runner(actions),
                      look=getattr(actions, "look_at_screen", None), memory=getattr(actions, "memories", None))
        if not brain.available:
            log.warning("AI is off: %s", brain.error)
            localai = getattr(actions, "localai", None)
            if localai is not None and localai.use_local(False):
                log.info("Claude is off, using local AI")
    triggers = getattr(actions, "triggers", None)
    if triggers is not None:  # "when Zoom opens, do X" from config.yaml
        try:
            triggers.start(runner=_trigger_runner(io, cfg, nlu, actions, brain), notify=io.say)
        except Exception:
            log.exception("could not start triggers")
    run(io, cfg, nlu, actions, brain=brain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
