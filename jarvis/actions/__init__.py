"""Laptop actions for Jarvis (Windows).

Public API:  run(cmd) -> str   (cmd has .intent and .args)
Optional:    configure(...), set_notifier(fn), start_reminders(path), needs_confirm(cmd),
             CATALOG (for the AI brain), look_at_screen() -> PNG bytes, memories() -> list[str]
"""
from __future__ import annotations

from jarvis.winutil import com_init as _com_init
import os
import logging
import time

from .. import calc
from . import apps, control, desktop, files, info, keyboard, radios, screen, system, timers, web
# New feature modules (pieces A-K of FEATURES-TODO.md)
from . import (agenda, assistant, audio, convert, dictation, focus, inbox, lists, monitor,  # noqa: F401
               network, shortcuts)
# Round 2 modules (pieces L-S)
from . import browser, expenses, fun, lookup, memos, recent, recorder, recurring  # noqa: F401
# Round 3 modules (pieces T-AA)
from . import cliphistory, daily, generate, ocr, phone, smarthome, software, spotify  # noqa: F401
# Round 4 modules (pieces AB-AI)
from . import history, layouts, localai, meetings, podcasts, screentime, security, triggers  # noqa: F401
# Round 5 modules (pieces AJ-AO) and the self-check (AP)
from . import calendar_add, doctor, interpreter, notifications, pchealth, scores, teach  # noqa: F401
from . import corrections, fuzzy, onboarding, tray, wakeword  # noqa: F401  (tray, fuzzy: no intents)
# Round 7 modules (pieces AV-BC) and BA birthdays
from . import contacts, documents, fileconvert, flashcards, habits, maps, watchers  # noqa: F401
# Round 8 modules (pieces BD-BI)
from . import accessibility, airquality, localmusic, radio, recipes, timetrack  # noqa: F401
from . import birthdays  # noqa: F401
# Round 9 modules (pieces BJ-BO)
from . import devtools, filesearch, printer, recap, sleeptimer, vdesktops  # noqa: F401
# Round 10-11 modules (pieces BP-BU)
from . import display, drives, hotspot, multilang, voiceid, webcam  # noqa: F401
from .catalog import CATALOG  # noqa: F401  (intent -> description + args schema)

# Pending risky action waiting for "yes": (intent, args).
_pending: tuple[str, dict] | None = None
_pending_at = 0.0
PENDING_SECONDS = 30  # a "yes" later than this does nothing

# Always risky intents -> words for the question.
_DANGEROUS = {
    "shutdown": "shut down",
    "restart": "restart",
    "sleep": "put the computer to sleep",
    "empty_recycle_bin": "empty the recycle bin",
    "forget_memory": "forget everything I remember about you",
}


def _risky_text(intent: str, args: dict) -> str | None:
    """Question words if this command needs a yes first, else None."""
    if intent in _DANGEROUS:
        return _DANGEROUS[intent]
    if intent == "wifi" and args.get("state") == "off":
        return "turn off Wi-Fi (I will lose internet)"
    if intent == "whatsapp" and files.whatsapp_needs_confirm(args):
        return f"send this WhatsApp message to {files.contact_name(args.get('to', '')) or 'them'}: {args.get('text', '')}"
    if intent in control.RISKY:  # delete_file, kill_process, computer_use
        return control.risky_question(intent, args)
    if intent == "list_clear":
        return lists.risky_text(args)
    if intent == "shortcut":  # only shortcuts that run a command
        return shortcuts.risky_text(args)
    if intent == "repeat_reminders" and recurring.needs_confirm(args):  # "stop all repeating reminders"
        return recurring.risky_text(args)
    if intent == "memo":  # only action=delete
        return memos.risky_text(args)
    if intent == "phone":  # only action=sms
        return phone.risky_text(args)
    if intent == "device":  # unlock, open a garage/door, "turn off everything"
        return smarthome.risky_text(args)
    if intent == "software":  # install, uninstall, update_all (also stores the found package in args)
        return software.risky_text(args)
    if intent == "history" and history.needs_confirm(args):  # clear
        return history.risky_text(args)
    if intent == "layout":  # delete only
        return layouts.risky_text(args)
    if intent == "notifications" and notifications.needs_confirm(args):  # clear
        return notifications.risky_text(args)
    if intent == "taught":  # forget a taught command
        return teach.risky_text(args)
    if intent in ("print_file", "print_queue") and printer.needs_confirm(intent, args):  # print / cancel jobs
        return printer.risky_text(intent, args)
    if intent == "sleep_timer" and sleeptimer.needs_confirm(args):  # sleep / shutdown later (music stop never asks)
        return sleeptimer.risky_text(args)
    if intent == "dev" and devtools.needs_confirm(args):  # git commit / push
        return devtools.risky_text(args)
    if intent == "voice_id" and voiceid.needs_confirm(args):  # forget the voice print
        return voiceid.risky_text(args)
    if intent == "track_undo":  # delete the last time tracking session
        return timetrack.risky_text(args)
    if intent == "contact_add":  # only when it would CHANGE a saved phone number or email (review Z2)
        return contacts.change_text(args)
    if intent in ("contact_delete", "habit_remove", "deck_delete"):  # delete saved data (None = nothing to delete)
        mod = {"contact_delete": contacts, "habit_remove": habits, "deck_delete": flashcards}[intent]
        return mod.risky_text(args)
    if intent == "calendar_add":  # always asks (None only when the title or time is missing: the handler asks for it)
        return calendar_add.risky_text(args)
    if intent == "clip_history" and cliphistory.needs_confirm(args):  # clear
        return cliphistory.risky_text(args)
    if intent == "podcast" and podcasts.needs_confirm(args):  # subscribe: say the show found, ask yes
        return podcasts.risky_text(args)
    return None


def needs_confirm(cmd) -> bool:
    """True if run(cmd) will only ask 'are you sure?' until args has confirm=True."""
    return _risky_text(getattr(cmd, "intent", ""), getattr(cmd, "args", None) or {}) is not None


def configure(app_paths: dict | None = None, screenshot_dir: str | None = None,
              search_url: str | None = None, **extra) -> None:
    """Optional settings (normally read from config.yaml automatically)."""
    if app_paths:
        apps.APP_PATHS.update({str(k).lower(): str(v) for k, v in app_paths.items()})
    if screenshot_dir:
        screen.SCREENSHOT_DIR = os.path.expanduser(screenshot_dir)
    if search_url:
        web.SEARCH_URL = search_url
    if extra.get("notes_file"):
        files.NOTES_FILE = os.path.expanduser(extra["notes_file"])
    if extra.get("contacts"):
        files.CONTACTS.update({str(k).lower(): v for k, v in extra["contacts"].items()})
    if extra.get("websites"):
        apps.WEBSITES.update({str(k).lower(): str(v) for k, v in extra["websites"].items()})
    if extra.get("memory_file"):
        files.MEMORY_FILE = os.path.expanduser(extra["memory_file"])
    wa = extra.get("whatsapp") or {}
    if "auto_send" in wa:
        files.WHATSAPP_AUTO_SEND = bool(wa["auto_send"])
    if wa.get("send_delay"):
        files.WHATSAPP_SEND_DELAY = float(wa["send_delay"])
    if extra.get("music_url"):
        desktop.MUSIC_URL = extra["music_url"]
    w = extra.get("weather") or {}
    if w.get("city") is not None:
        info.WEATHER_CITY = str(w["city"] or "")
    if w.get("units"):
        info.WEATHER_UNITS = w["units"]
    n = extra.get("news") or {}
    if n.get("feed"):
        info.NEWS_FEED = n["feed"]
    if n.get("search"):
        info.NEWS_SEARCH = n["search"]


look_at_screen = desktop.capture_screen_png
memories = files.memories


def set_notifier(fn) -> None:
    """fn(text) is called when a timer or reminder goes off (core passes tts.say)."""
    timers.notify = fn


def start_reminders(path: str) -> None:
    """Save reminders to `path` and restore the ones from last time (core calls this once)."""
    timers.STORE_FILE = os.path.expanduser(path) if path else ""
    timers.load_saved()


def _load_config() -> None:
    """Read settings via core's jarvis.config."""
    try:
        from jarvis.config import load_config

        cfg = load_config() or {}
    except Exception:
        return
    configure(cfg.get("apps"), cfg.get("screenshot_folder"), cfg.get("search_url"),
              notes_file=cfg.get("notes_file"), contacts=cfg.get("contacts"),
              music_url=cfg.get("music_url"), weather=cfg.get("weather"), news=cfg.get("news"),
              websites=cfg.get("websites"), memory_file=cfg.get("memory_file"),
              whatsapp=cfg.get("whatsapp"))


_load_config()


def _do_risky(intent: str, args: dict) -> str:
    if intent == "shutdown":
        return system.shutdown()
    if intent == "restart":
        return system.restart()
    if intent == "sleep":
        return system.sleep()
    if intent == "empty_recycle_bin":
        return system.empty_recycle_bin()
    if intent == "forget_memory":
        return files.forget_memory(args)
    if intent == "whatsapp":
        return files.whatsapp(args)
    if intent in control.RISKY:
        return control.do_risky(intent, args)
    if intent == "list_clear":
        return lists.list_clear(args)
    if intent == "shortcut":
        return shortcuts.shortcut(args)
    if intent in ("repeat_reminders", "memo", "phone", "device", "software", "clip_history", "history", "layout",
                  "notifications", "taught", "calendar_add", "podcast", "contact_add", "contact_delete", "habit_remove",
                  "deck_delete", "track_undo", "print_file", "print_queue", "sleep_timer", "dev",
                  "voice_id"):
        return _HANDLERS[intent](args)
    return radios.radio("wifi", args)


def _risky(intent: str, args: dict, question: str) -> str:
    global _pending, _pending_at
    if args.get("confirm") is True:
        _pending = None
        return _do_risky(intent, args)
    _pending, _pending_at = (intent, dict(args)), time.monotonic()
    return f"Are you sure you want to {question}? Say yes to confirm."


# intent -> function(args) for normal (not risky) actions
_HANDLERS = {
    "open_app": lambda a: apps.open_app(a.get("name", "")),
    "close_app": lambda a: apps.close_app(a.get("name", "")),
    "web_search": lambda a: web.search(a.get("query", "")),
    "volume": system.volume,
    "brightness": system.brightness,
    "screenshot": lambda a: screen.screenshot(),
    "type_text": lambda a: keyboard.type_text(a.get("text", "")),
    "time": lambda a: system.tell_time(),
    "lock": lambda a: system.lock(),
    "timer": timers.timer,
    "reminder": timers.reminder,
    "timers": timers.timers,
    "weather": info.weather,
    "news": info.news,
    "system_info": info.system_info,
    "media": desktop.media,
    "play": desktop.play,
    "window": desktop.window,
    "open_folder": files.open_folder,
    "open_file": files.open_file,
    "add_note": files.add_note,
    "read_notes": files.read_notes,
    "email": files.email,
    "wifi": lambda a: radios.radio("wifi", a),
    "bluetooth": lambda a: radios.radio("bluetooth", a),
    "calculate": calc.calculate,
    "read_clipboard": desktop.read_clipboard,
    "copy_text": desktop.copy_text,
    "get_selected_text": desktop.get_selected_text,
    "whatsapp": files.whatsapp,
    "remember": files.remember,
    "recall": files.recall,
    "answer": lambda a: "" if a.get("spoken") else (a.get("text") or "I don't have an answer."),
}

# Full system control: settings, files, processes, mouse/keys, screen control (actions/control.py).
_HANDLERS.update(control.HANDLERS)
CATALOG.update(control.CATALOG)

# New features: lists, help/pause/repeat/voice, shortcuts, calendar, dictation, conversions,
# network, audio, focus/DND, health alerts, email.
for _mod in (lists, assistant, shortcuts, agenda, dictation, convert, network, audio, focus, monitor, inbox,
             recurring, browser, lookup, recent, expenses, memos, fun, recorder,
             phone, smarthome, software, ocr, cliphistory, spotify, daily, generate,
             triggers, meetings, screentime, security, history, localai, layouts, podcasts,
             notifications, pchealth, teach, calendar_add, interpreter, scores, doctor,
             wakeword, corrections, onboarding,
             maps, documents, contacts, habits, flashcards, watchers, fileconvert,
             airquality, recipes, accessibility, radio, localmusic, timetrack, birthdays,
             printer, vdesktops, sleeptimer, filesearch, devtools, recap,
             drives, hotspot, display, webcam, multilang, voiceid):
    _HANDLERS.update(_mod.HANDLERS)
    CATALOG.update(_mod.CATALOG)
assistant.set_catalog(CATALOG)  # "what can I say" lists only features that exist


def run(cmd) -> str:
    """Do the action for a parsed command and return a short reply."""
    global _pending
    _com_init()  # triggers, the tray and the AI can call this from helper threads (pycaw, Outlook, WinRT need COM)
    intent = getattr(cmd, "intent", "unknown") or "unknown"
    args = getattr(cmd, "args", None) or {}

    if _pending and time.monotonic() - _pending_at > PENDING_SECONDS:
        _pending = None

    if intent == "confirm":
        if not _pending:
            return "There is nothing to confirm."
        p_intent, p_args = _pending
        return _risky(p_intent, {**p_args, "confirm": True}, "")
    if intent == "cancel":
        had = _pending
        _pending = None
        return "Okay, cancelled." if had else "Nothing to cancel."

    question = _risky_text(intent, args)
    if question is None:
        _pending = None  # any other command drops a pending risky action

    try:
        if question is not None:
            return _risky(intent, args, question)
        handler = _HANDLERS.get(intent)
        if handler:
            return handler(args)
    except Exception as e:  # never crash the main loop
        logging.getLogger("jarvis.actions").exception("action %s failed", intent)
        if type(e).__name__ == "FailSafeException":
            return "Move the mouse away from the screen corner, then try again."
        msg = str(e).split("\n")[0][:120]  # speak a short message; the full error is in jarvis.log
        return f"Sorry, that failed: {msg}" if msg else "Sorry, that failed."
    return "Sorry, I didn't understand that."
