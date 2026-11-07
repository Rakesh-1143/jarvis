"""Command understanding: turn spoken text into a Command.

Rule based (regex), no extra packages, works offline.

Intents and their args (actions.run reads these):
    open_app    {"name": str}                    "open chrome"
    close_app   {"name": str}                    "close notepad"
    web_search  {"query": str}                   "search for python tutorials"
    volume      {"level": int}  (0-100)          "set volume to 40"
             or {"change": "up"|"down"|"mute"|"unmute"}   "volume up", "mute"
    brightness  {"level": int}  (0-100)          "brightness 70"
             or {"change": "up"|"down"}          "dim the screen"
    screenshot  {}                               "take a screenshot"
    type_text   {"text": str}                    "type hello world"
    time        {}                               "what time is it"
    shutdown    {} (always asks first)           "shut down" / "shut down the laptop now"
    restart     {} (always asks first)           "restart" / "reboot the pc"
    lock        {}                               "lock the laptop"
    sleep, empty_recycle_bin {} (+confirm)       "go to sleep", "empty the recycle bin"
    timer       {"seconds": int}                 "set a timer for five minutes"
    reminder    {"seconds": int, "text": str}    "remind me to call mom in 10 minutes"
    timers      {"action": "list"|"cancel"}      "cancel my timers"
    weather     {"city"?: str}                   "what's the weather in London"
    news        {"topic"?: str}                  "latest news", "cricket news"
    system_info {"what": battery|cpu|memory|disk|all}   "how much battery"
    media       {"action": play_pause|next|previous|stop}   "pause", "next song"
    play        {"query": str}                   "play lofi music"
    window      {"action": minimize|maximize|restore|close|switch|show_desktop|snap_left|snap_right|task_view}
    open_folder {"name": str}                    "open downloads"
    open_file   {"name": str}                    "open file budget"
    add_note    {"text": str}                    "take a note buy milk"
    read_notes  {}                               "read my notes"
    email       {"to"?, "subject"?}              "send an email to mom about dinner"
    wifi, bluetooth {"state"?: "on"|"off"}       "turn off wifi", "bluetooth on"
    calculate   {"expression": str}              "what is 15 percent of 2400"
    read_clipboard {}                            "read my clipboard"
    remember    {"fact": str}                    "remember that my sister is Priya"
    recall, forget_memory {}                     "what do you remember about me", "forget everything"
    whatsapp    {"to": str, "text": str}         "whatsapp mom saying I'm on my way"
    reminder with text "alarm" = alarm           "set an alarm for 7 am", "wake me up in 20 minutes"
    New features (rules in nlu_features.py): list_add/list_remove/list_read/list_clear/lists,
    help/pause_listening/resume_listening/repeat/voice, agenda/next_event/free_at/briefing,
    dictation/read_aloud, convert/world_time/date_calc, network, now_playing/mic/app_volume/audio_output,
    focus/dnd, alerts, check_email. Shortcuts and snippets are matched in main.py before nlu.
    confirm     {}                               "yes", "sure", "do it"
    cancel      {}                               "no", "cancel"
    unknown     {"text": str}                    anything else

"confirm" / "cancel" answer the "Are you sure?" that actions.run asks
for shutdown/restart (actions remembers the pending action).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jarvis import calc
from jarvis import nlu_control, nlu_features

__all__ = ["Command", "parse"]


@dataclass
class Command:
    intent: str
    args: dict = field(default_factory=dict)


# Words people say before the real command. Removed first.
_FILLER = re.compile(
    r"^(?:(?:hey|ok|okay|hi)\s+)?(?:jarvis[\s,]*)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?",
)
_TRAIL = re.compile(r"\s*(?:please|for me|now please|thanks|thank you)$")

_NUM_WORDS = {
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "one hundred": 100, "max": 100, "maximum": 100,
    "full": 100, "half": 50, "minimum": 0, "min": 0,
}
_NUM_RE = r"(\d{1,3}|" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True)) + r")"

# Power words must be the whole phrase: "restart chrome" or "press caps lock" must not restart or lock the PC.
_DEVICE = r"(?:\s+(?:the|my|this))?(?:\s+(?:computer|laptop|pc|system|machine|device))?(?:\s+now)?"
_SHUTDOWN_RE = re.compile(r"(?:shut ?down|power off)" + _DEVICE
                          + r"|turn off(?:\s+(?:the|my|this))?\s+(?:computer|laptop|pc|system)(?:\s+now)?")
_RESTART_RE = re.compile(r"(?:restart|reboot)" + _DEVICE)
_LOCK_RE = re.compile(r"lock(?:\s+it)?(?:\s+(?:the|my|this))?(?:\s+(?:computer|laptop|pc|screen|system|device))?(?:\s+now)?")


def _clean(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s'%-]", " ", t)  # drop punctuation
    t = re.sub(r"\s+", " ", t).strip()
    t = _FILLER.sub("", t, count=1).strip()
    t = _TRAIL.sub("", t).strip()
    return t


def _to_level(word: str | None) -> int | None:
    if word is None:
        return None
    if word.isdigit():
        n = int(word)
    else:
        n = _NUM_WORDS.get(word)
        if n is None:
            return None
    return max(0, min(100, n))


def _strip_article(s: str) -> str:
    s = re.sub(r"^(?:the|a|an|my)\s+", "", s.strip())
    s = re.sub(r"\s+(?:app|application|program|window)$", "", s)
    return s.strip()


_SMALL = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER = (r"(\d+|(?:" + "|".join(_TENS) + r")(?:[ -](?:" + "|".join(k for k in _SMALL if len(k) > 2) + r"))?|"
           + "|".join(sorted(_SMALL, key=len, reverse=True)) + r")")
_CLOCK_NUM = _NUMBER.replace("|an|", "|").replace("|a)", ")")  # no "a"/"an" as an hour
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def _word_number(w: str) -> int | None:
    """'5' / 'five' / 'twenty five' -> int."""
    w = w.strip().replace("-", " ")
    if w.isdigit():
        return int(w)
    parts = w.split()
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _SMALL:
        return _TENS[parts[0]] + _SMALL[parts[1]]
    return _TENS.get(w, _SMALL.get(w))


def _duration(t: str) -> int:
    """Seconds in phrases like '5 minutes', 'an hour and ten minutes', 'half an hour'. 0 if none."""
    total = 0
    if re.search(r"\bhalf an hour\b", t):
        total += 1800
    elif re.search(r"\ban hour and a half\b", t):
        return 5400
    for num, unit in re.findall(_NUMBER + r"\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", t):
        n = _word_number(num)
        if n:
            total += n * _UNIT_SECONDS[unit[0]]
    return total


def _clock_seconds(t: str, now=None) -> int:
    """Seconds until a clock time like 'at 5 pm', 'at 5:30 pm', 'at five thirty pm', 'at 17:00'. 0 if none."""
    import datetime as dt

    m = re.search(r"\bat " + _CLOCK_NUM + r"(?:[: ]" + _CLOCK_NUM + r")?\s*(a ?m|p ?m)?\b", t)
    if not m:
        return 0
    h, mi = _word_number(m.group(1)), _word_number(m.group(2)) if m.group(2) else 0
    if h is None or mi is None or h > 23 or mi > 59:
        return 0
    ampm = (m.group(3) or "").replace(" ", "")
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    now = now or dt.datetime.now()
    target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if not ampm and h <= 12:  # "at 5" -> the next 5 o'clock (am or pm)
        while target <= now:
            target += dt.timedelta(hours=12)
    elif target <= now:
        target += dt.timedelta(days=1)
    return int((target - now).total_seconds())


def _strip_when(text: str) -> str:
    """Remove 'in 5 minutes' / 'at 5 pm' parts from a reminder text."""
    text = re.sub(r"\b(?:in|after) (?:half an hour|an hour and a half|(?:" + _NUMBER[1:-1] + r")\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)(?:\s*and\s*(?:" + _NUMBER[1:-1] + r")\s*(?:seconds?|minutes?|mins?))?)\b", "", text)
    text = re.sub(r"\bat " + _CLOCK_NUM + r"(?:[: ]" + _CLOCK_NUM + r")?\s*(?:a ?m|p ?m)?\b", "", text)
    text = re.sub(r"^(?:to|that|about)\s+", "", text.strip())
    return re.sub(r"\s+", " ", text).strip(" ,")


def _early_rules(t: str, raw: str) -> Command | None:
    """New rules that must run before typing / power / close (they contain words those rules catch)."""
    # long-term memory
    if re.search(r"\b(?:forget everything|forget what you (?:know|remember)|clear (?:your|the) memory|erase (?:your|the) memory)\b", t):
        return Command("forget_memory", {})
    if re.search(r"\bwhat (?:do|else do) you (?:remember|know) about me\b|^what do you remember$", t):
        return Command("recall", {})
    m = re.match(r"^remember (?:that )?(.+)$", t)
    if m:
        orig = re.search(r"\bremember\s+(?:that\s+)?(.+)$", raw, re.I)
        return Command("remember", {"fact": (orig.group(1) if orig else m.group(1)).strip(" .")})
    # WhatsApp
    m = (re.match(r"^(?:send\s+)?(?:an?\s+)?(?:whatsapp|whats app|what's app)(?:\s+message)?\s+(?:to\s+)?(.+?)\s+(?:saying|that says|that|say)\s+(.+)$", t)
         or re.match(r"^(?:message|text|send a message to)\s+(.+?)\s+on\s+(?:whatsapp|whats app|what's app)\s+(?:saying|that says|that|say)\s+(.+)$", t))
    if m:
        msg = m.group(2).strip()
        i = raw.lower().rfind(msg)  # keep the user's capital letters when typed
        return Command("whatsapp", {"to": m.group(1).strip(), "text": raw[i:i + len(msg)] if i >= 0 else msg})
    # alarms = reminders with an alarm sound
    if re.match(r"^(?:set\s+(?:an?\s+|the\s+|my\s+)?alarm|wake me(?: up)?)\b", t):
        secs = _clock_seconds(re.sub(r"\b(?:for|to)\s+(?=" + _CLOCK_NUM + r"\b)", "at ", t)) or _duration(t)
        return Command("reminder", {"seconds": secs, "text": "alarm"})
    # reminders
    m = re.match(r"^remind me\s+(.*)$", t)
    if m:
        rest = m.group(1)
        secs = _duration(rest) or _clock_seconds(rest)
        return Command("reminder", {"seconds": secs, "text": _strip_when(rest)})
    # timers
    if re.search(r"\b(?:cancel|stop|delete|remove|clear)\b.*\b(?:timers?|reminders?|alarms?)\b", t):
        return Command("timers", {"action": "cancel"})
    if re.search(r"\b(?:list|show|what|any|check)\b.*\b(?:timers|reminders)\b|\bhow much time is left\b", t):
        return Command("timers", {"action": "list"})
    if re.search(r"\b(?:timer|countdown)\b", t):
        secs = _duration(t)
        if secs:
            return Command("timer", {"seconds": secs})
    # notes
    m = re.match(r"^(?:take|make|add|create|save)\s+(?:a\s+)?note(?:\s+(?:that|saying|of))?\s+(.+)$|^(?:note down|write down|note that|jot down)\s+(.+)$", t)
    if m:
        return Command("add_note", {"text": (m.group(1) or m.group(2)).strip()})
    if re.search(r"\b(?:read|show|tell me|what are|open)\b.*\bnotes\b", t):
        return Command("read_notes", {})
    # email (before "write ..." typing)
    m = re.match(r"^(?:send|write|compose|draft|new|create)\s+(?:an?\s+|new\s+)?(?:e ?-?mail|mail)\b"
                 r"(?:\s+to\s+(.+?))?(?:\s+(?:about|saying|subject|with subject|regarding)\s+(.+))?$", t)
    if m:
        args = {}
        if m.group(1):
            args["to"] = m.group(1).strip()
        if m.group(2):
            args["subject"] = m.group(2).strip()
        return Command("email", args)
    # sleep / recycle bin
    if re.fullmatch(r"(?:go to sleep|sleep|sleep mode|put (?:the )?(?:computer|laptop|pc|system) to sleep)", t):
        return Command("sleep", {})
    if re.search(r"\bempty (?:the |my )?(?:recycle bin|trash|bin)\b", t):
        return Command("empty_recycle_bin", {})
    return None


def _on_off(t: str) -> str | None:
    if re.search(r"\b(?:off|disable|disconnect|stop)\b", t):
        return "off"
    if re.search(r"\b(?:on|enable|connect|start)\b", t):
        return "on"
    return None


_FOLDER_WORDS = r"downloads?|documents?|docs|desktop|pictures|photos|images|music|videos?|home"
_GENERIC_MUSIC = {"music", "some music", "a song", "song", "songs", "the music", "my music", "it", "something"}


def _device_rules(t: str) -> Command | None:
    """Wi-Fi, Bluetooth, windows, media, files, system info."""
    if re.search(r"\b(?:wi ?-?fi|wireless)\b", t):
        return Command("wifi", {"state": s} if (s := _on_off(t)) else {})
    if re.search(r"\bblue ?tooth\b", t):
        return Command("bluetooth", {"state": s} if (s := _on_off(t)) else {})

    # windows
    if re.search(r"\b(?:show (?:the )?desktop|go to (?:the )?desktop|minimi[sz]e (?:all|everything))\b", t):
        return Command("window", {"action": "show_desktop"})
    if re.search(r"\b(?:task view|show (?:all )?(?:my )?windows)\b", t):
        return Command("window", {"action": "task_view"})
    if re.search(r"\b(?:switch (?:the )?windows?|alt tab|next window|change window)\b", t):
        return Command("window", {"action": "switch"})
    m = re.search(r"\bsnap (?:(?:the |this )?window )?(?:to (?:the )?)?(left|right)\b", t)
    if m:
        return Command("window", {"action": f"snap_{m.group(1)}"})
    m = re.search(r"\b(minimi[sz]e|maximi[sz]e|restore|close)\s+(?:this |the |current |active )?window\b|^(minimi[sz]e|maximi[sz]e)(?: it)?$", t)
    if m:
        verb = (m.group(1) or m.group(2)).replace("mise", "mize")
        return Command("window", {"action": verb})

    # media
    if re.fullmatch(r"(?:pause|resume|play|unpause|pause (?:the )?(?:music|song|video)|resume (?:the )?(?:music|song|video)"
                    r"|play (?:the )?(?:music|song|video)|continue (?:the )?(?:music|song|playing))", t):
        return Command("media", {"action": "play_pause"})
    if re.search(r"\b(?:next (?:song|track|video)|skip(?: (?:this|the))?(?: song| track)?$|play next)\b", t):
        return Command("media", {"action": "next"})
    if re.search(r"\b(?:previous (?:song|track|video)|last (?:song|track)|go back a (?:song|track))\b", t):
        return Command("media", {"action": "previous"})
    if re.fullmatch(r"stop (?:the )?(?:music|song|video|playing|playback)", t):
        return Command("media", {"action": "stop"})
    m = re.match(r"^play\s+(.+?)(?:\s+on\s+(?:youtube|spotify))?$", t)
    if m:
        q = m.group(1).strip()
        return Command("media", {"action": "play_pause"}) if q in _GENERIC_MUSIC else Command("play", {"query": q})

    # folders and files
    m = re.match(r"^(?:open|show|go to)\s+(?:my\s+|the\s+)?(" + _FOLDER_WORDS + r")(?:\s+folder)?$", t)
    if m:
        return Command("open_folder", {"name": m.group(1)})
    m = re.match(r"^(?:open|find|show)\s+(?:the\s+|my\s+)?(?:file|document)\s+(?:called\s+|named\s+)?(.+)$", t)
    if m:
        return Command("open_file", {"name": m.group(1).strip()})

    # clipboard
    if re.search(r"\b(?:read|what(?:'s| is))\s+(?:on |in )?(?:my |the )?clipboard\b", t):
        return Command("read_clipboard", {})

    # system info
    if re.search(r"\bbattery\b|\bcharge level\b", t):
        return Command("system_info", {"what": "battery"})
    if re.search(r"\b(?:cpu|processor)\b", t):
        return Command("system_info", {"what": "cpu"})
    if re.search(r"\b(?:ram|memory usage|how much memory)\b", t):
        return Command("system_info", {"what": "memory"})
    if re.search(r"\b(?:disk space|storage|free space|hard drive)\b", t):
        return Command("system_info", {"what": "disk"})
    if re.search(r"\bsystem (?:info|information|status|health)\b", t):
        return Command("system_info", {"what": "all"})
    return None


def _info_rules(t: str) -> Command | None:
    """Weather and news (after explicit 'search for ...')."""
    if re.search(r"\b(?:weather|temperature|forecast|will it rain|is it raining|how hot|how cold)\b", t):
        m = re.search(r"\b(?:in|for|at)\s+([a-z][a-z .'-]*?)(?:\s+(?:today|tomorrow|now|right now|this week))?$", t)
        city = m.group(1).strip() if m else ""
        return Command("weather", {"city": city} if city and city not in ("today", "now") else {})
    if re.search(r"\b(?:news|headlines)\b", t):
        m = re.search(r"\b(?:news|headlines)\s+(?:about|on|for|regarding|in)\s+(.+)$", t)
        topic = m.group(1) if m else ""
        if not topic:
            m = re.match(r"^(?:(?:tell me|read|give me|show me|what(?:'s| is| are)?)\s+)?(?:the\s+)?(.+?)\s+(?:news|headlines)$", t)
            topic = m.group(1) if m else ""
            if re.fullmatch(r"(?:latest|top|today's|todays|recent|current|breaking|any|some|me|the)(?: (?:latest|top|news))?", topic):
                topic = ""
        return Command("news", {"topic": topic.strip()} if topic else {})
    return None


def _level_cmd(t: str, words: str, intent: str, allow_mute: bool) -> Command | None:
    """Shared logic for volume and brightness."""
    if not re.search(words, t):
        return None
    if allow_mute:
        if re.search(r"\bunmute\b", t):
            return Command(intent, {"change": "unmute"})
        if re.search(r"\bmute\b", t):
            return Command(intent, {"change": "mute"})
    m = re.search(r"\b" + _NUM_RE + r"\s*(?:%|percent)?", t)
    level = _to_level(m.group(1)) if m else None
    if level is not None:
        return Command(intent, {"level": level})
    if re.search(r"\b(?:up|increase|raise|higher|louder|brighter|more|turn it up)\b", t):
        return Command(intent, {"change": "up"})
    if re.search(r"\b(?:down|decrease|lower|reduce|quieter|softer|dim|dimmer|less)\b", t):
        return Command(intent, {"change": "down"})
    return None


def parse(text: str) -> Command:
    """Turn recognized speech into a Command. Never raises."""
    if not text or not text.strip():
        return Command("unknown", {"text": ""})
    raw = text.strip()
    t = _clean(raw)
    if not t:
        return Command("unknown", {"text": raw})

    # yes / no (answers to "are you sure?")
    if re.fullmatch(r"(?:yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|i'm sure|i am sure)", t):
        return Command("confirm", {})
    if re.fullmatch(r"(?:no|nope|nah|cancel|stop|never ?mind|don't|do not)", t):
        return Command("cancel", {})

    hit = nlu_features.parse(t, raw, _duration)  # lists, help, calendar, dictation, convert, network, ...
    if hit:
        return Command(*hit)
    cmd = _early_rules(t, raw)
    if cmd:
        return cmd
    hit = nlu_control.parse_early(t)  # "take control and ..." before power words inside the task
    if hit:
        return Command(*hit)

    # type text: keep original casing of what to type
    m = re.match(r"^(?:type|write|dictate)\s+(?:out\s+)?(.+)$", t)
    if m:
        orig = re.search(r"\b(?:type|write|dictate)\s+(?:out\s+)?(.+)$", raw, re.I)
        typed = orig.group(1).strip() if orig else m.group(1)
        return Command("type_text", {"text": typed})

    # power: shutdown / restart / lock
    # Always {} (no confirm): shutdown and restart always ask "are you sure?" first.
    if _SHUTDOWN_RE.fullmatch(t):
        return Command("shutdown", {})
    if _RESTART_RE.fullmatch(t):
        return Command("restart", {})
    if _LOCK_RE.fullmatch(t):
        return Command("lock", {})

    # screenshot
    if re.search(r"\b(?:screenshot|screen shot|screen capture|capture (?:the )?screen|snap (?:the )?screen)\b", t):
        return Command("screenshot", {})

    # time / date
    if (re.search(r"\b(?:what(?:'s| is)? (?:the )?time|time is it|tell me the time|current time)\b", t) or t == "time"
            or re.search(r"\b(?:what(?:'s| is)? (?:the |today's )?date|what day is (?:it|today)|today's date)\b", t)):
        return Command("time", {})

    # volume / brightness
    cmd = _level_cmd(t, r"\b(?:volume|sound|audio|louder|quieter|mute|unmute)\b", "volume", True)
    if cmd:
        return cmd
    cmd = _level_cmd(t, r"\b(?:brightness|bright|brighter|dim|dimmer|screen light)\b", "brightness", False)
    if cmd:
        return cmd

    hit = nlu_control.parse_control(t)  # settings, files, processes, mouse, keys
    if hit:
        return Command(*hit)

    cmd = _device_rules(t)
    if cmd:
        return cmd

    # web search
    m = re.match(
        r"^(?:search|google|look up|find)\s+(?:the web\s+|online\s+|google\s+)?(?:for\s+)?(.+?)"
        r"(?:\s+(?:on|in)\s+(?:google|the web|the internet|chrome|browser))?$",
        t,
    )
    if m:
        return Command("web_search", {"query": m.group(1).strip()})
    hit = nlu_features.fun(raw)  # coin, dice, random number, pick one, rock paper scissors, quiz
    if hit:
        return Command(*hit)
    cmd = _info_rules(t)
    if cmd:
        return cmd
    expr = calc.to_expression(t)
    if expr:
        return Command("calculate", {"expression": expr})
    m = re.match(r"^(?:what is|what's|who is|who's|how to|how do i)\s+(.+)$", t)
    if m:
        return Command("web_search", {"query": t})

    # open / close app
    m = re.match(r"^(?:open|launch|start|run|go to)\s+(?:up\s+)?(.+)$", t)
    if m:
        app = _strip_article(m.group(1))
        if app:
            return Command("open_app", {"name": app})
    m = re.match(r"^(?:close|quit|exit|kill|stop)\s+(.+)$", t)
    if m:
        app = _strip_article(m.group(1))
        if app:
            return Command("close_app", {"name": app})

    return Command("unknown", {"text": raw})


if __name__ == "__main__":  # quick manual test: python -m jarvis.nlu
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        print(parse(line))
