"""Assistant controls: help, pause/resume listening, repeat, voice speed/volume.

Intents: help {topic?} (info), pause_listening {minutes?}, resume_listening, repeat,
         voice {change: slower|faster|louder|quieter|reset}.

Hooks for main.py (core):
- is_paused() -> bool, and allowed_while_paused(text) -> bool: while paused, ignore every
  phrase except "start listening" style phrases (and exit phrases).
- new_turn() before handling each user phrase, record(text) each time Jarvis speaks.
  record() replaces the last reply on the first sentence of a turn and appends after that,
  so streamed AI answers are kept whole. set_last_reply(text) replaces it directly.
- set_catalog(catalog) once at start with the merged CATALOG, so help lists every feature.
"""
from __future__ import annotations

import re
import threading
import time

# ---------- catalog for the AI brain ----------

CATALOG: dict[str, dict] = {
    "help": {"description": "Tell the user what they can say. Optional topic, e.g. timers, music, windows.",
             "properties": {"topic": {"type": "string", "description": "Feature to explain. Leave out for the overview."}},
             "required": [], "info": True},
    "pause_listening": {"description": "Stop reacting to the wake word for some minutes (or until the user says 'start listening').",
                        "properties": {"minutes": {"type": "integer", "description": "Leave out to pause until resumed."}},
                        "required": []},
    "resume_listening": {"description": "Start listening to the wake word again after a pause.",
                         "properties": {}, "required": []},
    "repeat": {"description": "Say Jarvis's last reply again.", "properties": {}, "required": []},
    "voice": {"description": "Change how Jarvis speaks for this session.",
              "properties": {"change": {"type": "string", "enum": ["slower", "faster", "louder", "quieter", "reset"]}},
              "required": ["change"]},
}

# ---------- help ----------

# group name -> (intents that must exist, short words for the overview, example phrases)
_GROUPS: list[tuple[str, tuple[str, ...], str, list[str]]] = [
    ("apps", ("open_app", "close_app"), "open and close apps", ["open chrome", "close notepad", "open youtube"]),
    ("search", ("web_search",), "search the web", ["search for cheap flights", "google python lists"]),
    ("timers", ("timer", "reminder", "timers"), "timers, alarms and reminders",
     ["set a timer for five minutes", "remind me to call mom in 10 minutes", "set an alarm for 7 am",
      "what timers do I have", "cancel all timers"]),
    ("weather", ("weather",), "weather", ["what's the weather", "weather in London"]),
    ("news", ("news",), "news", ["latest news", "cricket news"]),
    ("music", ("media", "play"), "music and media", ["play lofi beats", "pause", "next song", "stop the music"]),
    ("volume", ("volume", "brightness"), "volume and brightness",
     ["volume up", "set volume to 30", "mute", "set brightness to 50"]),
    ("windows", ("window",), "windows", ["minimize this window", "snap window left", "switch window", "show desktop"]),
    ("files", ("open_folder", "open_file"), "files and folders", ["open downloads", "open file budget report"]),
    ("notes", ("add_note", "read_notes"), "notes", ["take a note buy milk", "read my notes"]),
    ("lists", ("list_add", "list_read"), "to-do and shopping lists",
     ["add milk to my shopping list", "what's on my to-do list", "what lists do I have"]),
    ("email", ("email",), "email drafts", ["send an email to mom about dinner"]),
    ("whatsapp", ("whatsapp",), "WhatsApp messages", ["whatsapp mom saying I'm on my way"]),
    ("system", ("system_info",), "battery and system status", ["how much battery", "cpu usage", "disk space"]),
    ("wifi", ("wifi", "bluetooth"), "Wi-Fi and Bluetooth", ["turn off wifi", "bluetooth on"]),
    ("power", ("lock", "shutdown"), "lock, sleep and shut down", ["lock", "go to sleep", "restart", "shut down"]),
    ("calculator", ("calculate",), "maths", ["what is 15 percent of 2400", "square root of 81"]),
    ("clipboard", ("read_clipboard",), "clipboard and selected text",
     ["read my clipboard", "summarize the selected text"]),
    ("memory", ("remember", "recall"), "remembering things about you",
     ["remember that my sister is Priya", "what do you remember about me"]),
    ("screen", ("screenshot", "look_at_screen"), "screenshots and your screen",
     ["take a screenshot", "what's on my screen"]),
    ("routines", ("routine",), "routines", ["good morning", "start work mode"]),
    ("calendar", ("agenda", "next_event"), "your calendar and a daily briefing",
     ["what's on my calendar today", "when is my next meeting", "am I free at 3 pm", "good morning briefing"]),
    ("dictation", ("dictation", "read_aloud"), "dictation and reading aloud",
     ["start dictation", "new line", "delete that", "stop dictation", "read this aloud", "stop reading"]),
    ("convert", ("convert", "world_time", "date_calc"), "conversions, world time and dates",
     ["5 miles in km", "10 dollars in rupees", "time in Tokyo", "how many days until 25 December"]),
    ("network", ("network",), "internet checks",
     ["am I online", "what's my IP", "what Wi-Fi am I on", "internet speed", "ping google"]),
    ("audio", ("now_playing", "mic", "app_volume", "audio_output"), "mic, app volume and speakers",
     ["what's playing", "mute my mic", "set spotify volume to 30", "switch to headphones"]),
    ("focus", ("focus", "dnd"), "focus sessions and do not disturb",
     ["start focus for 25 minutes", "how long left", "stop focus", "turn on do not disturb"]),
    ("alerts", ("alerts",), "battery and system alerts", ["turn off battery alerts", "turn on alerts"]),
    ("inbox", ("check_email",), "checking your email",
     ["do I have new emails", "read my latest emails", "any email from mom"]),
    ("shortcuts", ("shortcut", "snippet"), "your own shortcuts and snippets",
     ["type my address", "say any shortcut phrase from config.yaml"]),
    ("repeating", ("repeat_reminder", "repeat_reminders"), "repeating reminders",
     ["remind me to drink water every hour", "every weekday at 9 take medicine", "list repeating reminders",
      "stop the water reminder"]),
    ("browser", ("browser", "page_text"), "the web browser",
     ["new tab", "close this tab", "reopen closed tab", "find price on this page", "summarize this page"]),
    ("dictionary", ("define", "spell", "synonyms", "wikipedia"), "words and Wikipedia",
     ["define serendipity", "how do you spell necessary", "another word for happy", "wikipedia Albert Einstein"]),
    ("recent", ("recent_files",), "recent downloads and files",
     ["open my last download", "open the last pdf", "what did I download today", "show recent files"]),
    ("expenses", ("expense_add", "expense_report"), "tracking expenses",
     ["I spent 250 on lunch", "how much did I spend this month", "how much did I spend on food this week",
      "delete the last expense"]),
    ("memos", ("memo",), "voice memos",
     ["record a voice memo", "play my last memo", "list my memos", "delete my last memo"]),
    ("fun", ("random_pick", "quiz"), "games and random picks",
     ["flip a coin", "roll a dice", "pick one: pizza or pasta", "rock paper scissors", "quiz me"]),
    ("recording", ("screen_record",), "screen recording",
     ["record my screen", "stop recording", "where are my recordings"]),
    ("phone", ("phone", "phone_battery"), "your phone",
     ["ring my phone", "text mom saying I'm late", "send this link to my phone", "phone battery"]),
    ("smart home", ("device", "scene"), "lights and smart home",
     ["turn on the bedroom light", "set AC to 24", "is the front door locked", "activate movie night scene"]),
    ("software", ("software",), "installing and updating apps",
     ["install VLC", "uninstall Zoom", "what apps need updates", "update all my apps"]),
    ("ocr", ("ocr",), "reading text on the screen",
     ["copy the text on my screen", "read the text in this window", "read the text in my last screenshot"]),
    ("clipboard history", ("clip_history",), "clipboard history",
     ["what did I copy before", "paste the second last thing I copied", "copy item 3 again"]),
    ("spotify", ("spotify",), "Spotify",
     ["play shape of you on spotify", "like this song", "add this song to my gym playlist", "shuffle on"]),
    ("daily", ("daily",), "word and quote of the day",
     ["word of the day", "quote of the day", "what happened on this day", "inspire me"]),
    ("generate", ("generate",), "passwords and QR codes",
     ["generate a password", "give me a PIN", "make a QR code of this link"]),
    ("triggers", ("triggers",), "automatic triggers",
     ["list my triggers", "pause triggers", "resume triggers"]),
    ("meetings", ("meeting",), "joining meetings",
     ["join my next meeting", "join the 3 pm meeting", "mute me", "leave the call"]),
    ("screen time", ("screen_time", "app_limit"), "screen time and app limits",
     ["my screen time today", "how long did I use chrome today", "warn me after 1 hour of youtube"]),
    ("security", ("jarvis_lock", "guest_mode"), "PIN lock and guest mode",
     ["lock Jarvis", "unlock Jarvis", "guest mode on", "guest mode off"]),
    ("history", ("history",), "your command history",
     ["what did I ask you yesterday", "what did I ask about weather", "do that again", "clear my history"]),
    ("local ai", ("ai_mode", "local_ai_status"), "offline AI",
     ["use local AI", "use Claude", "is local AI ready"]),
    ("layouts", ("layout",), "window layouts",
     ["save this layout as coding", "restore my coding layout", "list my layouts"]),
    ("podcasts", ("podcast",), "podcasts",
     ["play the daily podcast", "next episode", "subscribe to hard fork", "what's new in my podcasts"]),
    ("notifications", ("notifications",), "notifications",
     ["read my notifications", "clear my notifications", "announce my notifications"]),
    ("pc health", ("pc_health",), "PC health",
     ["check my pc health", "how hot is my cpu", "how is my disk"]),
    ("teach", ("teach", "taught"), "teaching me new commands",
     ["when I say movie time, open netflix and dim the screen", "what have you learned", "forget the command movie time"]),
    ("calendar add", ("calendar_add",), "adding calendar events",
     ["add meeting with Ravi on Friday at 10", "put gym in my calendar tomorrow at 7 am"]),
    ("interpreter", ("interpreter",), "live translation",
     ["start interpreter mode in spanish", "stop translating"]),
    ("scores", ("scores",), "live scores",
     ["what's the cricket score", "India score", "premier league results"]),
    ("self check", ("self_check",), "checking myself",
     ["run a self check", "check yourself"]),
    ("wake word", ("wake_sensitivity",), "the wake word",
     ["make the wake word more sensitive", "you wake up too often", "set wake word sensitivity to 6"]),
    ("corrections", ("correction", "corrections", "misheard"), "fixing words I mishear",
     ["when you hear note pad I mean notepad", "you misheard", "list corrections", "remove correction note pad"]),
    ("setup", ("setup",), "setting me up",
     ["run setup", "change my name", "change my city", "test my mic", "set up a PIN"]),
    ("maps", ("travel_time", "directions"), "travel time and directions",
     ["how long to drive to Hyderabad", "how far is the airport", "directions to Charminar"]),
    ("documents", ("document",), "reading PDFs and Word files",
     ["read my last download", "read this pdf", "continue", "read page 3", "how many pages in this pdf"]),
    ("contacts", ("contact_add", "contact_get", "contacts_list"), "contacts",
     ["add contact Ravi phone 98765 43210", "what's Ravi's number", "list my contacts"]),
    ("habits", ("habit_done", "habit_status"), "habits and streaks",
     ["I did my workout", "my workout streak", "habits this week"]),
    ("flashcards", ("flashcard_add", "flashcard_quiz", "flashcard_status"), "flashcards",
     ["add flashcard to Spanish hello means hola", "quiz me on Spanish", "how many flashcards are due"]),
    ("watchers", ("watch", "watches"), "telling you when something happens",
     ["tell me when my download finishes", "tell me when battery is 80 percent", "tell me when Zoom closes"]),
    ("file convert", ("convert_file",), "converting files",
     ["convert this to pdf", "merge these pdfs", "resize this picture to 50 percent", "convert this image to png"]),
    ("air quality", ("air_quality", "sun_times", "rain_soon", "uv"), "air, sun and rain",
     ["what's the air quality", "is it safe to go running", "when is sunset", "will it rain in the next hour", "UV index today"]),
    ("recipes", ("recipe", "cook"), "recipes and cook mode",
     ["recipe for butter chicken", "what can I make with eggs and tomatoes", "cook pasta", "next step", "start a timer"]),
    ("accessibility", ("accessibility",), "magnifier, narrator, captions",
     ["turn on the magnifier", "magnifier zoom in", "turn on narrator", "turn on live captions", "turn on grayscale"]),
    ("radio", ("radio",), "internet radio",
     ["play Radio Mirchi", "play jazz radio", "next station", "save this station", "stop the radio"]),
    ("local music", ("local_music",), "songs on this PC",
     ["play my music", "shuffle my music", "play Arijit Singh from my music", "rescan my music library"]),
    ("time tracking", ("track", "track_report"), "tracking time on projects",
     ["start tracking college project", "stop tracking", "how long did I work on thesis this week", "export my time report"]),
    ("birthdays", ("birthday_add", "birthday_get"), "birthdays and anniversaries",
     ["mom's birthday is 12 March", "when is mom's birthday", "birthdays this month", "our anniversary is 10 June"]),
    ("printing", ("print_file", "print_queue", "printer_info"), "printing",
     ["print this document", "print my last download", "what's printing", "cancel printing", "is the printer online"]),
    ("desktops", ("vdesktop",), "virtual desktops",
     ["new desktop", "next desktop", "go to desktop 2", "move this window to desktop 3", "close this desktop"]),
    ("sleep timer", ("sleep_timer", "sleep_timer_cancel"), "sleep timer",
     ["stop the music in 30 minutes", "shut down in 2 hours", "sleep the laptop in 1 hour", "cancel sleep timer"]),
    ("file search", ("find_files", "open_result"), "searching inside files",
     ["find the file that mentions invoice", "find pdfs about tax", "files I edited today", "open the first one"]),
    ("developer", ("dev",), "code projects and git",
     ["open jarvis project in vs code", "git status", "run the tests", "commit with message fix bug", "push my changes"]),
    ("recap", ("recap",), "day recap",
     ["how was my day", "what does tomorrow look like"]),
    ("drives", ("drives",), "pen drives and disks",
     ["what drives are connected", "how much space on D drive", "open my pen drive", "eject my pen drive"]),
    ("hotspot", ("hotspot",), "mobile hotspot",
     ["turn on hotspot", "how many devices are on my hotspot", "what's my hotspot password", "turn off hotspot"]),
    ("display", ("display",), "second screen and projector",
     ["extend my screen", "duplicate screen", "second screen only", "laptop screen only", "what's my resolution"]),
    ("webcam", ("webcam",), "webcam photos",
     ["take a photo", "take a photo in 3 seconds", "is my camera on"]),
    ("languages", ("language",), "Hindi and Telugu commands",
     ["understand Hindi", "I will speak Telugu", "reply in Hindi", "English only"]),
    ("voice lock", ("voice_id",), "voice lock",
     ["learn my voice", "who am I", "voice lock on", "voice lock off", "forget my voice"]),
    ("assistant", ("pause_listening", "voice"), "controlling me",
     ["stop listening for 10 minutes", "start listening", "repeat that", "speak slower", "speak louder"]),
]

# extra words that point to a group
_ALIASES = {
    "timer": "timers", "alarm": "timers", "alarms": "timers", "reminder": "timers", "reminders": "timers",
    "app": "apps", "programs": "apps", "program": "apps", "websites": "apps", "website": "apps",
    "media": "music", "songs": "music", "song": "music", "youtube": "music",
    "sound": "volume", "brightness": "volume", "window": "windows",
    "file": "files", "folder": "files", "folders": "files", "note": "notes",
    "list": "lists", "shopping": "lists", "todo": "lists", "to-do": "lists",
    "mail": "email", "battery": "system", "cpu": "system",
    "bluetooth": "wifi", "wi-fi": "wifi", "internet": "wifi",
    "shutdown": "power", "lock": "power", "sleep": "power", "restart": "power",
    "maths": "calculator", "math": "calculator", "calculate": "calculator",
    "voice": "assistant", "listening": "assistant", "pause": "assistant", "repeat": "assistant",
    "remember": "memory", "screenshot": "screen", "routine": "routines",
    "agenda": "calendar", "meetings": "calendar", "meeting": "calendar", "schedule": "calendar",
    "briefing": "calendar", "dictate": "dictation", "typing": "dictation", "reading": "dictation",
    "conversion": "convert", "conversions": "convert", "units": "convert", "currency": "convert",
    "dates": "convert", "date": "convert", "world time": "convert", "ip": "network", "speed": "network",
    "online": "network", "mic": "audio", "microphone": "audio", "speakers": "audio", "headphones": "audio",
    "pomodoro": "focus", "do not disturb": "focus", "dnd": "focus", "inbox": "inbox", "emails": "inbox",
    "check email": "inbox", "shortcut": "shortcuts", "snippet": "shortcuts", "snippets": "shortcuts",
    "repeating reminders": "repeating", "recurring": "repeating", "tabs": "browser", "tab": "browser",
    "web page": "browser", "page": "browser", "words": "dictionary", "spelling": "dictionary",
    "wikipedia": "dictionary", "define": "dictionary", "downloads": "recent", "recent files": "recent",
    "expense": "expenses", "money": "expenses", "spending": "expenses", "memo": "memos",
    "voice memos": "memos", "games": "fun", "quiz": "fun", "coin": "fun", "dice": "fun",
    "screen recording": "recording", "recordings": "recording", "record": "recording",
    "mobile": "phone", "sms": "phone", "text": "phone", "texting": "phone", "lights": "smart home",
    "light": "smart home", "smarthome": "smart home", "home": "smart home", "home assistant": "smart home",
    "devices": "smart home", "install": "software", "apps update": "software", "updates": "software",
    "winget": "software", "read text": "ocr", "screen text": "ocr",
    "copy": "clipboard history", "paste": "clipboard history", "word of the day": "daily", "quote": "daily",
    "quotes": "daily", "history": "daily", "password": "generate", "passwords": "generate", "qr": "generate",
    "qr code": "generate", "pin": "generate",
    "trigger": "triggers", "automations": "triggers", "automation": "triggers", "meeting join": "meetings",
    "zoom": "meetings", "teams": "meetings", "screentime": "screen time", "app limits": "screen time",
    "limits": "screen time", "lock jarvis": "security", "guest": "security", "guest mode": "security",
    "command history": "history", "do that again": "history", "ollama": "local ai", "offline ai": "local ai",
    "layout": "layouts", "windows layout": "layouts", "podcast": "podcasts", "episodes": "podcasts",
    "notification": "notifications", "health": "pc health", "pc health": "pc health", "learn": "teach",
    "taught": "teach", "add event": "calendar add", "translate": "interpreter", "translation": "interpreter",
    "map": "maps", "directions": "maps", "travel": "maps", "pdf": "documents", "document": "documents",
    "contact": "contacts", "habit": "habits", "streak": "habits", "flashcard": "flashcards", "cards": "flashcards",
    "watch": "watchers", "notify me": "watchers", "convert file": "file convert", "convert pdf": "file convert",
    "resize": "file convert", "merge": "file convert",
    "aqi": "air quality", "pollution": "air quality", "sunset": "air quality", "sunrise": "air quality",
    "uv": "air quality", "umbrella": "air quality", "recipe": "recipes", "cook": "recipes", "cooking": "recipes",
    "magnifier": "accessibility", "narrator": "accessibility", "captions": "accessibility", "station": "radio",
    "stations": "radio", "fm": "radio", "my music": "local music", "songs": "local music", "tracking": "time tracking",
    "timesheet": "time tracking", "birthday": "birthdays", "anniversary": "birthdays", "anniversaries": "birthdays",
    "print": "printing", "printer": "printing", "desktop": "desktops", "virtual desktop": "desktops",
    "sleep timer": "sleep timer", "shutdown timer": "sleep timer", "search files": "file search",
    "git": "developer", "code": "developer", "tests": "developer", "dev server": "developer", "evening": "recap",
    "pen drive": "drives", "usb": "drives", "eject": "drives", "hot spot": "hotspot", "projector": "display",
    "monitor": "display", "screens": "display", "camera": "webcam", "photo": "webcam", "selfie": "webcam",
    "hindi": "languages", "telugu": "languages", "language": "languages", "voice id": "voice lock",
    "wake": "wake word", "sensitivity": "wake word", "misheard": "corrections", "correction": "corrections",
    "mishear": "corrections", "set up": "setup", "onboarding": "setup", "my name": "setup",
    "score": "scores", "cricket": "scores", "football": "scores", "doctor": "self check", "self check": "self check",
}

_catalog: dict | None = None


def set_catalog(catalog: dict) -> None:
    """Core passes the full merged CATALOG so help only lists features that exist."""
    global _catalog
    _catalog = dict(catalog)


def _known() -> set[str]:
    if _catalog is not None:
        return set(_catalog)
    try:
        from .catalog import CATALOG as base
        return set(base) | set(CATALOG)
    except Exception:
        return set(CATALOG)


def help(args: dict) -> str:  # noqa: A001  (intent name)
    known = _known()
    groups = [g for g in _GROUPS if any(i in known for i in g[1])]
    topic = re.sub(r"[^\w\s-]", "", str(args.get("topic") or "")).lower().strip()
    topic = re.sub(r"^(?:with|for|on|about)\s+", "", topic)
    topic = re.sub(r"^(?:the|my)\s+", "", topic).strip()
    if topic:
        key = _ALIASES.get(topic, topic)
        if key not in {g[0] for g in groups}:  # try each word, e.g. "setting timers"
            key = next((_ALIASES.get(w, w) for w in topic.split()
                        if _ALIASES.get(w, w) in {g[0] for g in groups}), key)
        for name, _, words, examples in groups:
            if name == key:
                return f"For {words}, try: " + "; ".join(f"'{e}'" for e in examples[:4]) + "."
        # fall back to a catalog description
        cat = _catalog or {}
        for intent, spec in cat.items():
            if topic.replace(" ", "_") == intent or topic in intent.replace("_", " "):
                return spec.get("description", "") or f"I can do {topic}."
        return f"I don't have help for {topic}. Say 'what can I say' for the full list."
    shown = [g for g in groups if g[0] != "assistant"][:8]
    if not shown:
        return "Ask me anything."
    example = "timers" if any(g[0] == "timers" for g in shown) else shown[0][0]
    return ("I can do " + ", ".join(g[2] for g in shown) + ", and more. Ask me anything else and I'll try. "
            f"Say 'help with {example}', for example, to hear what to say.")


# ---------- pause / resume ----------

_lock = threading.Lock()
_paused_until: float | None = None  # epoch seconds; float("inf") = until resumed
MAX_PAUSE_MINUTES = 24 * 60

_RESUME = re.compile(
    r"\b(?:start|resume|begin|continue)\s+listening\b|\bwake\s+up\b|\bi'?m\s+back\b|\bun\s?pause\b|\byou\s+can\s+listen\b",
    re.I)


def is_paused() -> bool:
    global _paused_until
    with _lock:
        if _paused_until is None:
            return False
        if time.time() >= _paused_until:
            _paused_until = None
            return False
        return True


def seconds_left() -> float | None:
    """Seconds until the pause ends, inf if until resumed, None if not paused."""
    if not is_paused():
        return None
    return _paused_until - time.time() if _paused_until != float("inf") else float("inf")


def allowed_while_paused(text: str | None) -> bool:
    """True for phrases that end a pause ('start listening', 'wake up', 'I'm back')."""
    return bool(text and _RESUME.search(text))


def pause_listening(args: dict) -> str:
    global _paused_until
    minutes = args.get("minutes")
    try:
        minutes = float(minutes) if minutes not in (None, "") else None
    except (TypeError, ValueError):
        minutes = None
    with _lock:
        if minutes is None or minutes <= 0:
            _paused_until = float("inf")
            return "Okay, I'll stop listening. Say 'Jarvis, start listening' when you need me."
        minutes = min(minutes, MAX_PAUSE_MINUTES)
        _paused_until = time.time() + minutes * 60
    m = int(minutes) if minutes == int(minutes) else round(minutes, 1)
    unit = "minute" if m == 1 else "minutes"
    return f"Okay, I'll stop listening for {m} {unit}. Say 'Jarvis, start listening' to wake me sooner."


def resume_listening(args: dict) -> str:
    global _paused_until
    with _lock:
        was = _paused_until is not None
        _paused_until = None
    return "I'm listening again." if was else "I'm already listening."


# ---------- repeat ----------

_last_reply = ""
_turn_started = True  # next record() replaces instead of appends


def set_last_reply(text: str) -> None:
    global _last_reply, _turn_started
    if text and text.strip():
        _last_reply = text.strip()
        _turn_started = False


def new_turn() -> None:
    """Call before handling each user phrase."""
    global _turn_started
    _turn_started = True


def record(text: str) -> None:
    """Call for each spoken sentence. First one in a turn replaces, later ones append."""
    global _last_reply, _turn_started
    if not text or not text.strip():
        return
    text = text.strip()
    if _turn_started or not _last_reply:
        _last_reply = text
    elif not _last_reply.endswith(text):
        _last_reply = f"{_last_reply} {text}"
    _turn_started = False


def last_reply() -> str:
    return _last_reply


def repeat(args: dict) -> str:
    return _last_reply or "I haven't said anything yet."


# ---------- voice ----------

RATE_STEP, RATE_MIN, RATE_MAX = 30, 90, 330
VOLUME_STEP, VOLUME_MIN = 0.2, 0.2
_start_voice: dict | None = None  # values before the first change, for "reset"


def _tts():
    from .. import tts
    return tts


def _current(tts) -> tuple[int, float]:
    s = getattr(tts, "_settings", None) or {}
    return int(s.get("rate") or 180), float(s.get("volume") if s.get("volume") is not None else 1.0)


def voice(args: dict) -> str:
    global _start_voice
    change = str(args.get("change") or "").lower().strip()
    change = {"slow": "slower", "fast": "faster", "loud": "louder", "quiet": "quieter", "softer": "quieter",
              "normal": "reset", "default": "reset"}.get(change, change)
    try:
        tts = _tts()
    except Exception:
        return "I can't change my voice right now."
    if not hasattr(tts, "configure"):
        return "I can't change my voice right now."
    rate, vol = _current(tts)
    if _start_voice is None:
        _start_voice = {"rate": rate, "volume": vol}
    if change == "slower":
        if rate <= RATE_MIN:
            return "I'm already speaking as slowly as I can."
        tts.configure(rate=max(RATE_MIN, rate - RATE_STEP))
        return "Okay, I'll speak slower."
    if change == "faster":
        if rate >= RATE_MAX:
            return "I'm already speaking as fast as I can."
        tts.configure(rate=min(RATE_MAX, rate + RATE_STEP))
        return "Okay, I'll speak faster."
    if change == "louder":
        if vol >= 1.0:
            return "My voice is already at full volume. Say 'volume up' to turn up the speakers."
        tts.configure(volume=min(1.0, round(vol + VOLUME_STEP, 2)))
        return "Okay, I'll speak louder."
    if change == "quieter":
        if vol <= VOLUME_MIN:
            return "I'm already as quiet as I go. Say 'volume down' to turn down the speakers."
        tts.configure(volume=max(VOLUME_MIN, round(vol - VOLUME_STEP, 2)))
        return "Okay, I'll speak more quietly."
    if change == "reset":
        tts.configure(rate=_start_voice["rate"], volume=_start_voice["volume"])
        return "Okay, my voice is back to normal."
    return "I can speak slower, faster, louder or quieter."


HANDLERS = {
    "help": help,
    "pause_listening": pause_listening,
    "resume_listening": resume_listening,
    "repeat": repeat,
    "voice": voice,
}
