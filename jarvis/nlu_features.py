"""Voice rules for the new features (pieces A-K of FEATURES-TODO.md).

parse(t, raw, duration) takes the CLEANED text from nlu (lower case, no filler), the raw text,
and nlu's duration parser (text -> seconds). Returns (intent, args) or None.
No imports from nlu or actions, so there is no import loop and no heavy packages.

nlu.parse calls this right after the yes/no rules, before every other rule, because many
phrases here contain words that older rules catch ("what wifi am I on" has "wifi" and "on",
"speak louder" has "louder", "turn off battery alerts" has "battery").
"""
from __future__ import annotations

import re

# ---------- small helpers ----------

_NUM_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
             r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
             r"thousand|million|a|an|and|half)")
_AMOUNT = r"(\d[\d,]*(?:\.\d+)?|" + _NUM_WORD + r"(?:[\s-]+" + _NUM_WORD + r")*)"
_SMALL = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _int(word: str | None) -> int | None:
    if not word:
        return None
    return int(word) if word.isdigit() else _SMALL.get(word)


def _on_off(t: str, default: str | None = "on") -> str | None:
    if re.search(r"\b(?:off|disable|stop|mute|silence|deactivate|no more)\b", t):
        return "off"
    if re.search(r"\b(?:on|enable|start|unmute|activate)\b", t):
        return "on"
    return default


# ---------- A: lists ----------
_LIST_NAME = r"(?:my\s+|the\s+|our\s+)?(.+?)\s+list|(?:my\s+|the\s+)?(to-?do|to do|shopping|groceries|grocery)"


def _lists(t: str):
    m = re.fullmatch(r"(?:add|put|write)\s+(.+?)\s+(?:to|on|in|into|onto)\s+(?:" + _LIST_NAME + r")", t)
    if m:
        return "list_add", {"list": (m.group(2) or m.group(3)).strip(), "item": m.group(1).strip()}
    m = re.fullmatch(r"(?:remove|delete|take|cross|tick)\s+(.+?)\s+(?:off|from|out of|off of)\s+(?:" + _LIST_NAME + r")", t)
    if m:
        return "list_remove", {"list": (m.group(2) or m.group(3)).strip(), "item": m.group(1).strip()}
    m = re.fullmatch(r"(?:clear|empty|wipe|erase|delete|reset)\s+(?:out\s+)?(?:my\s+|the\s+)?(.+?)\s+list", t)
    if m:
        return "list_clear", {"list": m.group(1).strip()}
    if re.fullmatch(r"(?:what|which) lists (?:do i have|have i got|are there)|(?:show|read|list) (?:me )?(?:all )?my lists|my lists", t):
        return "lists", {}
    m = re.fullmatch(r"(?:what(?:'s| is| do i have)|read|show|tell me|check|open)\s+(?:me\s+)?(?:on\s+|in\s+)?"
                     r"(?:my\s+|the\s+)?(.+?)\s+list", t)
    if m:
        return "list_read", {"list": m.group(1).strip()}
    if re.fullmatch(r"what do i (?:need|have) to buy|what(?:'s| is) on my shopping", t):
        return "list_read", {"list": "shopping"}
    return None


# ---------- B: assistant controls ----------

def _assistant(t: str, duration):
    if re.fullmatch(r"help|help me|what can (?:i|you) (?:say|do)|what can i ask(?: you)?|what do you do"
                    r"|(?:show|list|tell me)(?: me)?(?: the| your| all)? commands|what commands (?:are there|do you know)", t):
        return "help", {}
    m = re.fullmatch(r"(?:help|help me|show me how to use)\s+(?:with\s+|on\s+|for\s+|about\s+)?(.+)"
                     r"|what can i say (?:about|for|to) (.+)|how do i use (?:the )?(timers?|music|lists?|dictation|focus)", t)
    if m:
        return "help", {"topic": next(g for g in m.groups() if g).strip()}

    m = re.fullmatch(r"(?:stop listening|go quiet|be quiet|quiet|pause listening|pause yourself|go to sleep jarvis"
                     r"|don't listen|do not listen|mute yourself)(?:\s+(?:for|during)\s+(.+))?|pause for (.+)", t)
    if m:
        when = m.group(1) or m.group(2)
        if when is None:
            return "pause_listening", {}
        secs = duration(when) or (3600 if re.fullmatch(r"(?:an|one) hour", when) else 0)
        if secs:
            return "pause_listening", {"minutes": max(1, round(secs / 60))}
        if m.group(2):  # "pause for <something else>" is not ours
            return None
        return "pause_listening", {}
    if re.fullmatch(r"(?:start|resume) listening|listen again|wake up|i'm back|i am back|you can listen now", t):
        return "resume_listening", {}
    if re.fullmatch(r"repeat(?: that| it| yourself| the last thing| what you said)?|say (?:that|it) again"
                    r"|what did you (?:just )?say|pardon(?: me)?|come again|sorry what", t):
        return "repeat", {}
    m = re.fullmatch(r"(?:speak|talk|say it)\s+(?:a\s+(?:bit|little)\s+|much\s+)?(slower|faster|louder|quieter|softer|"
                     r"more slowly|more quickly|more softly|more quietly)|(slow down|speed up)", t)
    if m:
        w = m.group(1) or m.group(2)
        change = {"more slowly": "slower", "slow down": "slower", "more quickly": "faster", "speed up": "faster",
                  "softer": "quieter", "more softly": "quieter", "more quietly": "quieter"}.get(w, w)
        return "voice", {"change": change}
    if re.fullmatch(r"(?:normal|default) voice|reset (?:your|the) voice|speak normally|talk normally", t):
        return "voice", {"change": "reset"}
    return None


# ---------- E: dictation and read aloud ----------

def _dictation(t: str):
    if re.fullmatch(r"(?:start|begin|turn on|enable|open)\s+(?:the\s+)?dictation(?: mode)?|dictation(?: mode)?(?: on)?"
                    r"|take dictation|start typing what i say|type what i say", t):
        return "dictation", {"state": "on"}
    if re.fullmatch(r"(?:stop|end|turn off|disable|close)\s+(?:the\s+)?dictation(?: mode)?|dictation off", t):
        return "dictation", {"state": "off"}
    if re.fullmatch(r"stop reading(?: aloud| out loud)?|stop reading (?:this|that|it)|be quiet now", t):
        return "read_aloud", {"action": "stop"}
    m = re.fullmatch(r"read (?:out\s+)?(this|that|it|the selection|the selected text|selected text|what i selected"
                     r"|my clipboard|the clipboard)?\s*(?:aloud|out loud|to me)?", t)
    if m and (m.group(1) or re.search(r"\b(?:aloud|out loud)\b", t)) and not re.fullmatch(r"read (?:my|the) clipboard", t):
        src = "clipboard" if m.group(1) and "clipboard" in m.group(1) else None
        return "read_aloud", {"source": src} if src else {}
    return None


# ---------- J: network ----------

def _network(t: str):
    if re.search(r"\b(?:what|which) (?:wi ?-?fi|wireless|network)(?: network)? (?:am i|are we|is this)\b"
                 r"|\b(?:wi ?-?fi|network) name\b|\bwhich wi ?-?fi\b|\bwi ?-?fi signal\b", t):
        return "network", {"what": "wifi"}
    if re.search(r"\b(?:what(?:'s| is)|tell me|show|find)\s+(?:my|the)\s+(?:public\s+|local\s+)?ip\b|\bmy ip(?: address)?$", t):
        return "network", {"what": "ip"}
    if re.search(r"\b(?:internet|network|wi ?-?fi|download|connection) speed\b|\bspeed ?test\b"
                 r"|\bhow fast is (?:my |the )?(?:internet|connection|wi ?-?fi)\b", t):
        return "network", {"what": "speed"}
    if re.fullmatch(r"(?:am i|are we|is (?:the|my) (?:computer|laptop|pc)) (?:online|connected(?: to the internet)?)"
                    r"|(?:is|check) (?:the |my )?internet(?: connection)?(?: working| up| down| on)?"
                    r"|do (?:i|we) have (?:the )?internet|am i connected|check (?:the |my )?connection", t):
        return "network", {"what": "online"}
    m = re.fullmatch(r"ping\s+(?:the\s+|my\s+)?(.+)", t)
    if m:
        return "network", {"what": "ping", "host": m.group(1).strip()}
    return None


# ---------- G: audio ----------
_NOT_APP = {"the", "my", "system", "master", "computer", "laptop", "pc", "sound", "main", "overall", "whole", "your"}


def _audio(t: str):
    if re.fullmatch(r"what(?:'s| is) (?:this |the )?(?:song|track|music)?\s*(?:that'?s |is )?(?:playing|on)(?: now| right now)?"
                    r"|what song is (?:this|playing|on)|what(?:'s| is) (?:this|the) (?:song|track)|who sings this(?: song)?"
                    r"|now playing|what am i listening to", t):
        return "now_playing", {}
    if re.search(r"\b(?:mic|microphone)\b", t) and not re.search(r"\bsettings?\b", t):
        if re.match(r"(?:is|are) ", t):
            return "mic", {}
        if re.search(r"\b(?:unmute|turn on|enable|on|activate)\b", t):
            return "mic", {"state": "on"}
        if re.search(r"\b(?:mute|turn off|disable|off|silence)\b", t):
            return "mic", {"state": "off"}
    m = re.fullmatch(r"(?:set|turn|change|put)\s+(?:the\s+)?(.+?)(?:'s)?\s+volume\s+(?:to\s+|at\s+)?(\d{1,3}|[a-z]+(?: [a-z]+)?)\s*(?:%|percent)?", t)
    if m and m.group(1) not in _NOT_APP:
        level = m.group(2)
        n = int(level) if level.isdigit() else {"zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
                                                   "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                                                   "ninety": 90, "hundred": 100, "half": 50, "max": 100,
                                                   "full": 100}.get(level)
        if n is not None:
            return "app_volume", {"app": m.group(1).strip(), "level": max(0, min(100, n))}
    m = re.fullmatch(r"(?:turn\s+)?(.+?)(?:'s)?\s+volume\s+(up|down)|turn (up|down) (?:the\s+)?(.+?)(?:'s)?\s+volume", t)
    if m:
        app, change = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        app = re.sub(r"^(?:the|my)\s+", "", app.strip())
        if app and app not in _NOT_APP:
            return "app_volume", {"app": app, "change": change}
    m = re.fullmatch(r"(mute|unmute)\s+(?:the\s+)?(spotify|chrome|edge|firefox|teams|zoom|discord|youtube|vlc|"
                     r"whatsapp|skype|brave|opera|music|games?)", t)
    if m:
        return "app_volume", {"app": m.group(2), "change": m.group(1)}
    if re.fullmatch(r"(?:list|show|what are)(?: me)?(?: my| the)? (?:audio|sound|output) devices|what (?:speakers|outputs) do i have"
                    r"|(?:list|show)(?: my)? (?:speakers|audio outputs)", t):
        return "audio_output", {}
    m = re.fullmatch(r"(?:switch|change|set|move|send)\s+(?:the\s+)?(?:audio|sound|output|audio output|sound output)?\s*"
                     r"(?:output\s+)?(?:to|through|on)\s+(?:my\s+|the\s+)?(.+)", t)
    if m and (re.search(r"\b(?:audio|sound|output)\b", t.split(" to ")[0])
              or re.search(r"\b(?:headphones?|headset|speakers?|earphones|earbuds|airpods|buds|tv|hdmi|monitor speakers)\b",
                           m.group(1))):
        return "audio_output", {"name": m.group(1).strip()}
    return None


# ---------- H: focus and do not disturb ----------

def _focus(t: str, duration):
    m = re.fullmatch(r"(?:start|begin)\s+(?:a\s+|the\s+|my\s+)?(?:focus|pomodoro)(?:\s+(?:session|mode|timer|time))?"
                     r"(?:\s+for\s+(.+))?|(?:let's|lets|time to|help me) focus(?:\s+for\s+(.+))?|focus for (.+)", t)
    if m:
        when = m.group(1) or m.group(2) or m.group(3)
        args = {"action": "start"}
        secs = duration(when) if when else 0
        if secs:
            args["minutes"] = max(1, round(secs / 60))
        return "focus", args
    if re.fullmatch(r"(?:stop|end|cancel|finish|quit)\s+(?:the\s+|my\s+)?(?:focus|pomodoro)(?:\s+(?:session|mode|timer|time))?", t):
        return "focus", {"action": "stop"}
    if re.fullmatch(r"how (?:long|much time)(?: is)? left (?:in|on|for) (?:my |the )?(?:focus|pomodoro|session|round)"
                    r"|how long (?:is )?left|focus status|(?:pomodoro|focus) status|am i (?:in|on) (?:a )?(?:focus|break)", t):
        return "focus", {"action": "status"}
    if re.search(r"\bsettings?\b", t):
        return None  # "open focus settings" / "do not disturb settings" -> Settings page (nlu_control)
    if re.search(r"\b(?:do not disturb|don't disturb|dnd|focus assist|quiet hours)\b", t) or re.fullmatch(
            r"(?:turn|switch) (?:on|off) focus mode|focus mode (?:on|off)|(?:enable|disable) focus mode", t):
        return "dnd", {"state": _on_off(t, "on")}
    if re.fullmatch(r"(?:hide|block|silence|mute|stop) (?:all )?(?:my )?notifications|no notifications", t):
        return "dnd", {"state": "on"}
    if re.fullmatch(r"(?:show|unblock|allow|unmute) (?:all )?(?:my )?notifications(?: again)?", t):
        return "dnd", {"state": "off"}
    return None


# ---------- I: health alerts ----------

def _alerts(t: str):
    m = re.search(r"\b(battery|cpu|processor|disk|storage|health|system)?\s*(?:alerts|warnings|notifications about \w+)\b", t)
    if not m or re.search(r"\b(?:what|which|any)\b.*\balerts\b(?!.*\b(?:on|off)\b)", t):
        return None
    if not re.search(r"\b(?:on|off|enable|disable|stop|start|mute|silence|unmute|no more)\b", t):
        return None
    kind = {"processor": "cpu", "storage": "disk"}.get(m.group(1) or "", m.group(1) or "")
    args = {"state": _on_off(t, "on")}
    if kind in ("battery", "cpu", "disk"):
        args["kind"] = kind
    return "alerts", args


# ---------- K: inbox ----------

def _inbox(t: str):
    if re.match(r"^(?:send|write|compose|draft|create|reply|forward|new e ?-?mail to)\b", t):
        return None
    if not re.search(r"\b(?:e ?-?mails?|mails?|inbox|gmail|outlook)\b", t):
        return None
    if not re.search(r"\b(?:do i have|have i got|did i get|any|check|read|show|what(?:'s| is| are)?|tell me|latest|last|"
                     r"recent|new|unread|who)\b", t):
        return None
    if re.fullmatch(r"(?:open|go to) (?:my )?(?:gmail|outlook|inbox|email)", t):
        return None  # opening the website/app is open_app
    args: dict = {}
    m = re.search(r"\b(?:from|by|sent by)\s+(.+?)(?:\s+(?:today|yesterday|recently|this week))?$", t)
    if m:
        args["from"] = m.group(1).strip()
    m = re.search(r"\b(?:last|latest|recent|top|first)\s+(\d{1,2}|" + "|".join(_SMALL) + r")\b|\b(\d{1,2}|"
                  + "|".join(_SMALL) + r")\s+(?:latest|last|recent|new|unread)?\s*e ?-?mails?\b", t)
    if m:
        n = _int(m.group(1) or m.group(2))
        if n:
            args["count"] = max(1, min(10, n))
    if re.search(r"\b(?:read|latest|last|recent)\b", t) and not re.search(r"\b(?:new|unread)\b", t):
        args["unread_only"] = False
    return "check_email", args


# ---------- D: calendar ----------
_DAY = (r"(today|tonight|tomorrow|this morning|this afternoon|this evening|(?:this |next |on )?(?:monday|tuesday|wednesday|"
        r"thursday|friday|saturday|sunday)|on (?:the )?.+|for (?:the )?.+|this week)")


def _day(text: str | None) -> str:
    if not text:
        return ""
    d = re.sub(r"^(?:on|for)\s+(?:the\s+)?", "", text.strip())
    return {"tonight": "today", "this morning": "today", "this afternoon": "today", "this evening": "today"}.get(d, d)


def _agenda(t: str):
    if re.search(r"\b(?:briefing|brief me|daily summary|morning summary|summary of (?:my|the) day|how does my day look"
                 r"|what does my day look like|plan for (?:the|my) day|start my day)\b", t):
        return "briefing", {}
    if re.search(r"\b(?:when|what)(?:'s| is)? (?:my |the )?next (?:meeting|event|appointment|call|class)\b"
                 r"|^next (?:meeting|event|appointment)$|\bwhen do i have to leave\b", t):
        return "next_event", {}
    m = re.fullmatch(r"(?:am i|are we|will i be) (?:free|busy|available)\s*(today|tomorrow|on \w+)?\s+(?:at|around|from)\s+"
                     r"(.+?)(?:\s+(today|tomorrow|on \w+))?", t)
    if m:
        args = {"time": m.group(2).strip()}
        day = _day(m.group(1) or m.group(3))
        if day:
            args["day"] = day
        return "free_at", args
    m = re.fullmatch(r"(?:what(?:'s| is| do i have)|do i have(?: any)?|any|read|show|tell me|check|what are)\s+"
                     r"(?:on\s+|in\s+)?(?:my\s+|the\s+)?(?:calendar|agenda|schedule|meetings|events|appointments|plans)"
                     r"(?:\s+(?:like|look like|for|on))?\s*(.*)", t)
    if m:
        return "agenda", {"day": _day(m.group(1))} if _day(m.group(1)) else {}
    m = re.fullmatch(r"(?:what(?:'s| is)|do i have (?:anything|any meetings|any events))\s+(?:on\s+|planned\s+|scheduled\s+)?"
                     + _DAY + r"(?:\s+(?:on my calendar|planned|scheduled))?", t)
    if m and re.search(r"\b(?:calendar|meetings?|events?|planned|scheduled|anything)\b", t):
        return "agenda", {"day": _day(m.group(1))}
    return None


# ---------- F: conversions, world time, date maths ----------

def _convert(t: str, raw: str):
    # keep dots and slashes (2.5 km, 15/08/1947) that nlu's cleaner removes
    c = re.sub(r"[^\w\s.,'%°/$€£₹-]", " ", raw.lower())
    c = re.sub(r"\s+", " ", c).strip(" .,")
    c = re.sub(r"^(?:(?:hey|ok|okay|hi)\s+)?(?:jarvis[\s,]*)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?", "", c)
    c = re.sub(r"\s*(?:please|for me|thanks|thank you)$", "", c).strip(" .,")

    # world time (before the plain "what time is it")
    m = re.fullmatch(r"(?:what(?:'s| is)? (?:the )?time|what time is it|current time|time|what time)\s+(?:now\s+|right now\s+)?"
                     r"(?:in|at)\s+([a-z][a-z .'-]+?)(?:\s+(?:now|right now))?", t)
    if m and not re.match(r"(?:\d|a |an |half )", m.group(1)):
        return "world_time", {"city": m.group(1).strip()}

    # date maths
    if (re.search(r"\bhow (?:many|much) (?:days|weeks|months|years|time)\b.*\b(?:until|till|til|to|before|since|from)\b", t)
            or re.search(r"\b(?:days|weeks) (?:until|till|left until|left till|since|to go until)\b", t)
            or re.fullmatch(r"what (?:day|weekday|day of the week) (?:is|was|will be|falls on|is it on)\s+(?!it$|today$|it today$).+", t)
            or re.search(r"\b(?:what(?:'s| is| was| will be)? (?:the )?date|which date)\s+(?:in|after|before)\b", t)
            or re.search(r"\bdate (?:in|after) \S+ (?:days?|weeks?|months?|years?)\b", t)
            or re.search(r"\bwhat (?:date|day) (?:is|was|will it be) \S+ (?:days?|weeks?|months?) (?:from now|ago|later)\b", t)
            or re.search(r"\b(?:\S+) (?:days?|weeks?|months?) (?:from (?:now|today)|ago)\b.*\b(?:date|day)\b", t)):
        return "date_calc", {"question": raw.strip()}

    # unit / currency conversion
    m = re.fullmatch(r"how many\s+([a-z$€£₹°][\w .°-]*?)\s+(?:are\s+)?(?:in|to|make|make up)\s+(?:a\s+|an\s+|one\s+)?"
                     + _AMOUNT + r"?\s*([a-z$€£₹°][\w .°-]*?)", c)
    if m and m.group(3):
        amount = m.group(2) or "1"
        return "convert", {"amount": _amount(amount), "from": m.group(3).strip(), "to": m.group(1).strip()}
    m = re.fullmatch(r"(?:convert|change|what(?:'s| is)|how much is|how much are|how many [a-z]+ (?:is|are))?\s*"
                     r"([$€£₹])?" + _AMOUNT + r"\s*([a-z$€£₹°%][\w .°-]*?)\s+(?:to|in|into|in to|as)\s+([a-z$€£₹°][\w .°-]*?)", c)
    if m and m.group(2):
        unit_from = (m.group(1) or "") + (m.group(3) or "")
        if unit_from and not re.search(r"\b(?:list|timer|reminder|minutes? from now)\b", c):
            return "convert", {"amount": _amount(m.group(2)), "from": unit_from.strip(), "to": m.group(4).strip()}
    return None


def _amount(s: str):
    s = s.strip().replace(",", "")
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return s  # words like "twenty five": convert.py parses them


# ================= Round 2 (pieces L-S) =================

# ---------- M: browser (only phrases that clearly mean the browser; zoom/scroll/back stay generic keys) ----------

def _browser(t: str):
    rules = [
        (r"(?:open |start )?(?:a |an )?(?:new )?(?:incognito|private)(?: browsing)?(?: window| mode| tab)?"
         r"|go incognito", "incognito"),
        (r"(?:open )?(?:a )?new (?:browser )?tab", "new_tab"),
        (r"close (?:the |this |current |that )?(?:browser )?tab", "close_tab"),
        (r"(?:reopen|restore|bring back|undo close)(?: the| that| my)?(?: last)?(?: closed)? tab|reopen (?:the )?closed tab", "reopen_tab"),
        (r"(?:go to |switch to )?(?:the )?next tab|switch tabs?", "next_tab"),
        (r"(?:go to |switch to )?(?:the )?previous tab", "previous_tab"),
        (r"(?:hard|force) (?:refresh|reload)(?: (?:the |this )?page)?", "hard_refresh"),
        (r"(?:refresh|reload) (?:the |this )?(?:web ?)?page", "refresh"),
        (r"bookmark(?: (?:this|the|that))?(?: (?:page|site|tab|website))?|add (?:a |this to )?bookmarks?", "bookmark"),
        (r"(?:show|open)(?: me)?(?: my| the)? (?:browser|browsing|chrome|edge|web|internet|search) history"
         r"|(?:browser|browsing) history|show history|open history", "history"),
        (r"(?:show|open)(?: me)?(?: my| the)? (?:browser )?downloads? (?:page|list|history)|browser downloads|download history", "downloads"),
        (r"(?:go to|click|focus|select)(?: on)? (?:the )?(?:address|url|search) bar", "address_bar"),
        (r"(?:open )?(?:a )?new browser window", "new_window"),
    ]
    for pat, action in rules:
        if re.fullmatch(pat, t):
            return "browser", {"action": action}
    m = re.fullmatch(r"(?:find|search for|look for)\s+(.+?)\s+(?:on|in) (?:this|the) (?:web ?)?page"
                     r"|search (?:this|the) page for\s+(.+)|find on (?:this |the )?page", t)
    if m:
        text = m.group(1) or m.group(2)
        return "browser", {"action": "find", "text": text.strip()} if text else {"action": "find"}
    if re.fullmatch(r"read (?:me )?(?:this|the) (?:web ?)?page(?: (?:out loud|aloud|to me))?", t):
        return "page_text", {"read": True}
    if re.fullmatch(r"(?:summari[sz]e|explain|sum up) (?:this|the) (?:web ?)?(?:page|article|site)"
                    r"|what(?:'s| is) (?:this|the) (?:web ?)?(?:page|article) about|tldr(?: this page)?", t):
        return "page_text", {}
    return None


# ---------- N: dictionary, spelling, synonyms, Wikipedia ----------

def _lookup(t: str):
    m = re.fullmatch(r"(?:define|definition of|what(?:'s| is) the (?:meaning|definition) of|meaning of|what does)\s+"
                     r"(?:the word\s+)?(.+?)(?:\s+mean)?", t)
    if m and (t.startswith("what does") is bool(re.search(r"\bmean$", t))) and len(m.group(1).split()) <= 3 \
            and m.group(1) not in ("life", "my life", "it", "this", "that"):
        return "define", {"word": m.group(1).strip()}
    m = re.fullmatch(r"(?:how do (?:you|i) spell|spell|spelling of|what(?:'s| is) the spelling of)\s+(?:the word\s+)?(.+)", t)
    if m:
        return "spell", {"word": m.group(1).strip()}
    m = re.fullmatch(r"(?:opposite|antonyms?) (?:of|for)\s+(.+)|what(?:'s| is) the opposite of\s+(.+)", t)
    if m:
        return "synonyms", {"word": (m.group(1) or m.group(2)).strip(), "kind": "antonyms"}
    m = re.fullmatch(r"(?:synonyms? (?:of|for)|another word for|other words for|a word for|"
                     r"what(?:'s| is) (?:a |another )?(?:synonym|word) (?:of|for))\s+(.+)", t)
    if m:
        return "synonyms", {"word": m.group(1).strip()}
    m = re.fullmatch(r"(?:search |look up |check )?wikipedia(?: for| about| on)?\s+(.+)|(?:search|look up|check) wikipedia (?:for )?(.+)"
                     r"|(?:tell me about|look up|search for|what does wikipedia say about)\s+(.+?)\s+(?:on|from|in) wikipedia"
                     r"|what does wikipedia say about (.+)", t)
    if m:
        return "wikipedia", {"topic": next(g for g in m.groups() if g).strip()}
    return None


# ---------- O: recent files ----------
_KIND_WORDS = r"(pdfs?|pictures?|photos?|images?|videos?|movies?|songs?|audio|music|docs?|documents?|word files?|zips?|archives?|apps?|installers?|setups?)"


def _recent(t: str):
    if re.match(r"(?:open|show|find)\s+(?:the\s+)?(?:file|document|folder)\b", t):
        return None  # open_file {name} / open_folder
    m = re.fullmatch(r"what did i (?:just )?download(?: (today|yesterday|this week|in the last hour|last hour|recently))?", t)
    if m:
        w = (m.group(1) or "").replace("this ", "").replace("in the last ", "").replace("last ", "")
        return "recent_files", {"when": w} if w and w != "recently" else {}
    if not re.search(r"\b(?:last|latest|newest|recent|recently|most recent|second last|newest)\b", t):
        return None
    if not re.search(r"\b(?:downloads?|downloaded|files?|" + _KIND_WORDS[1:-1] + r")\b", t):
        return None
    if re.search(r"\b(?:note|notes|emails?|mails?|memos?|expenses?|reminders?|lists?|tabs?|songs? on|recordings?)\b", t):
        return None
    if not re.match(r"(?:open|show|list|what|which|play|tell me|read)\b", t):
        return None
    args: dict = {}
    if re.match(r"(?:open|play)\b", t):
        args["action"] = "open"
    m = re.search(r"\b(?:on|in|from) (?:my |the )?(desktop|documents|downloads)\b", t)
    if m:
        args["folder"] = m.group(1)
    elif re.search(r"\brecent(?:ly)? (?:used )?files\b|\bfiles? (?:i|did i) (?:use|used|open|opened)\b|\blast recent file\b", t):
        args["folder"] = "recent"
    elif re.search(r"\b(?:newest|latest|recent) documents\b", t):
        args["folder"] = "documents"
    m = re.search(r"\b" + _KIND_WORDS + r"\b", t)
    if m and not re.fullmatch(r"docs?|documents?", m.group(1)) or (m and args.get("folder") != "documents"
                                                                   and re.fullmatch(r"docs?|word files?", m.group(1))):
        args["kind"] = m.group(1)
    m = re.search(r"\b(second|third|2nd|3rd)\b", t)
    if m:
        args["which"] = {"second": 2, "2nd": 2, "third": 3, "3rd": 3}[m.group(1)]
    m = re.search(r"\b(today|yesterday)\b", t)
    if m:
        args["when"] = m.group(1)
    return "recent_files", args


# ---------- P: expenses ----------
_PERIOD = r"(today|yesterday|this week|last week|this month|last month|this year|in total|overall|so far)"


def _period(p: str | None) -> str | None:
    if not p:
        return None
    return {"this week": "week", "this month": "month", "this year": "year", "in total": "all", "overall": "all",
            "so far": "all"}.get(p, p)


def _raw_amount(raw: str, amount: str) -> str:
    """nlu's cleaner turns '2.5k' into '2 5k'; take the amount from the raw text instead."""
    if " " in amount and re.fullmatch(r"[\d ,k]+", amount):
        m = re.search(r"[$€£₹]?\s*(\d[\d,]*(?:\.\d+)?\s*k?)\b", raw.lower())
        if m:
            return m.group(1).replace(" ", "")
    return amount


def _expenses(t: str, raw: str = ""):
    m = re.fullmatch(r"(?:i\s+)?(?:spent|paid)\s+(.+?)\s+(?:on|for)\s+(.+?)(?:\s+(?:today|just now))?", t)
    if m and re.search(r"\d|\b(?:hundred|thousand|fifty|twenty|thirty|forty|ten|five|k)\b", m.group(1)):
        return "expense_add", {"amount": _raw_amount(raw, m.group(1).strip()), "note": m.group(2).strip()}
    m = re.fullmatch(r"(?:add|log|record|note)\s+(?:an?\s+)?expense(?:\s+of)?\s+(.+?)(?:\s+(?:on|for)\s+(.+))?", t)
    if m:
        args = {"amount": _raw_amount(raw, m.group(1).strip())}
        if m.group(2):
            args["note"] = m.group(2).strip()
        return "expense_add", args
    m = re.fullmatch(r"how much (?:did i|have i|i) (?:spend|spent)(?:\s+(?:on|for)\s+([a-z]+))?\s*" + _PERIOD + r"?"
                     r"(?:\s+(?:on|for)\s+([a-z]+))?|(?:show|read|tell me|what are|what(?:'s| is)) (?:me )?(?:my )?"
                     r"(?:expenses?|spending|expense report)\s*" + _PERIOD + r"?", t)
    if m:
        args = {}
        cat = m.group(1) or m.group(3)
        period = _period(m.group(2) or m.group(4))
        if cat:
            args["category"] = cat
        if period:
            args["period"] = period
        return "expense_report", args
    if re.fullmatch(r"(?:delete|remove|undo|cancel) (?:the |my )?last expense", t):
        return "expense_undo", {}
    return None


# ---------- Q + S: voice memos and screen recording ----------

def _memo_running() -> bool:
    try:
        from jarvis.actions import memos
        return memos.is_recording()
    except Exception:
        return False


def _screen_running() -> bool:
    try:
        from jarvis.actions import recorder
        return bool(recorder._running() or recorder._gamebar)
    except Exception:
        return False


_WHICH = r"(last|latest|newest|first|oldest|previous|\d+|one|two|three|four|five)"


def _memos_recorder(t: str):
    # stop: memo while a memo records, else the screen recording
    if re.fullmatch(r"(?:stop|end|finish|cancel) (?:the |my )?(?:voice )?(?:memo|note)(?: recording)?", t):
        return "memo", {"action": "stop"}
    if re.fullmatch(r"stop playing(?: the| my)? (?:voice )?memo", t):
        return "memo", {"action": "stop"}
    if re.fullmatch(r"(?:stop|end|finish) (?:the )?(?:screen )?recording(?: the screen| my screen)?", t):
        if "screen" not in t and _memo_running() and not _screen_running():
            return "memo", {"action": "stop"}
        return "screen_record", {"action": "stop"}
    # memos
    if re.fullmatch(r"(?:record|take|start|make|new|create)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:voice|audio)\s+(?:memo|note)"
                    r"|(?:record|start|take) (?:a )?memo", t):
        return "memo", {"action": "record"}
    if re.fullmatch(r"(?:list|show|read)(?: me)? (?:all )?my (?:voice )?memos|what (?:voice )?memos do i have"
                    r"|how many (?:voice )?memos (?:do i have|are there)", t):
        return "memo", {"action": "list"}
    if re.fullmatch(r"(?:open|show)(?: me)? (?:my |the )?(?:voice )?memos? folder|show my voice memos", t):
        return "memo", {"action": "open"}
    m = re.fullmatch(r"play (?:my |the )?(?:" + _WHICH + r" )?(?:voice )?memo(?: (?:number )?" + _WHICH + r")?", t)
    if m:
        w = m.group(1) or m.group(2)
        return "memo", {"action": "play", "which": w} if w else {"action": "play"}
    m = re.fullmatch(r"(?:delete|remove|erase) (?:my |the )?(?:" + _WHICH + r" )?(?:voice )?memo(?: (?:number )?" + _WHICH + r")?", t)
    if m:
        w = m.group(1) or m.group(2)
        return "memo", {"action": "delete", "which": w} if w else {"action": "delete"}
    # screen recording
    if re.fullmatch(r"(?:start )?(?:recording|record) (?:my |the )?screen|start (?:a )?(?:screen )?recording"
                    r"|(?:start )?screen record(?:ing)?|record (?:a )?(?:screen )?video of (?:my |the )?screen", t):
        return "screen_record", {"action": "start"}
    if re.fullmatch(r"where are my (?:screen )?recordings|(?:open|show)(?: me)? (?:my |the )?(?:screen )?recordings(?: folder)?", t):
        return "screen_record", {"action": "open"}
    return None


def _recurring(raw: str):
    try:
        from jarvis.actions import recurring
        return recurring.parse(raw)
    except Exception:
        return None


# ================= Round 3 (pieces T-AA) =================

def _orig(raw: str, part: str) -> str:
    """Return `part` with the user's own capital letters from the raw text (for SMS and QR text)."""
    i = raw.lower().find(part)
    return raw[i:i + len(part)] if i >= 0 else part


# ---------- T: phone (KDE Connect) ----------

def _phone(t: str, raw: str):
    if re.fullmatch(r"(?:ring|find|locate|call) my (?:mobile|phone|cell)(?: phone)?|where(?:'s| is) my (?:mobile|phone)"
                    r"|make my phone ring|i can't find my phone|i lost my phone", t):
        return "phone", {"action": "ring"}
    if re.search(r"\b(?:phone|mobile)(?:'s)? (?:battery|charge)\b|\bbattery (?:on|of|in) my (?:phone|mobile)\b"
                 r"|\bhow much (?:battery|charge) (?:does|has) my (?:phone|mobile)\b|\bis my (?:phone|mobile) charg", t):
        return "phone_battery", {}
    m = re.fullmatch(r"(?:send\s+)?(?:a\s+|an\s+)?(?:text|sms|text message)(?:\s+message)?\s+(?:to\s+)?(.+?)\s+"
                     r"(?:saying|that says|that|say)\s+(.+)"
                     r"|(?:message|text)\s+(.+?)\s+(?:on|from|using) my phone\s+(?:saying|that says|that|say)\s+(.+)", t)
    if m:
        to, text = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        return "phone", {"action": "sms", "to": to.strip(), "text": _orig(raw, text.strip())}
    m = re.fullmatch(r"send\s+(.+?)\s+to my (?:phone|mobile)", t)
    if m:
        what = m.group(1).strip()
        if re.fullmatch(r"(?:this|it|that)(?: link| page| text)?|(?:my |the )?clipboard|what i copied|the link", what):
            what = "clipboard"
        elif re.fullmatch(r"(?:my |the )?(?:last|latest) download(?:ed file)?", what):
            what = "last download"
        else:
            c = re.search(r"send\s+(.+?)\s+to my (?:phone|mobile)", raw, re.I)  # keep URL dots and case
            what = c.group(1).strip() if c else what
        return "phone", {"action": "share", "what": what}
    return None


# ---------- U: smart home (Home Assistant), only when it is set up ----------
_LAPTOP_WORDS = (r"\b(?:wi ?-?fi|wireless|blue ?tooth|screen|display|monitor|computer|laptop|pc|volume|sound|audio|brightness|"
                 r"dark mode|light mode|night light|mic|microphone|alerts?|notifications?|do not disturb|dnd|focus|dictation|"
                 r"saver|performance|caps|num lock|keyboard|mouse|airplane|flight mode|hotspot|location|camera|tabs?|"
                 r"windows?|apps?|programs?|music|songs?|spotify|shuffle|repeat|timers?|alarms?|reminders?|dictation|"
                 r"listening|incognito|mode|password|file|folder|clipboard|settings?|control panel)\b")
_HOME_KINDS = r"\b(?:lights?|lamps?|fans?|plugs?|switch|tv|ac|air ?con(?:ditioner)?|heater|thermostat|door|lock|garage|gate|blinds|curtains?|shades?|shutters?|kettle|purifier|speaker)\b"


def _home_ready() -> bool:
    import os

    if os.environ.get("HASS_URL"):
        return True
    try:
        from jarvis.config import load_config
        return bool((load_config().get("home_assistant") or {}).get("url"))
    except Exception:
        return False


def _smarthome(t: str):
    if re.search(_LAPTOP_WORDS, t) or not _home_ready():
        return None
    if re.fullmatch(r"(?:turn|switch|shut) off (?:all (?:the )?devices|everything|all|the whole house)|everything off|all off", t):
        return "device", {"name": "everything", "action": "off"}
    if re.fullmatch(r"(?:turn|switch) (?:off|on) all (?:the )?lights|all (?:the )?lights (?:on|off)|lights (?:on|off)", t):
        return "device", {"name": "all lights", "action": "off" if re.search(r"\boff\b", t) else "on"}
    m = re.fullmatch(r"(?:activate|start|run|set|turn on|switch on)\s+(?:the\s+|my\s+)?(.+?)\s+scene|scene\s+(.+)", t)
    if m:
        return "scene", {"name": (m.group(1) or m.group(2)).strip()}
    m = re.fullmatch(r"(?:turn|switch)\s+(on|off)\s+(?:the\s+|my\s+)?(.+)|(?:turn|switch)\s+(?:the\s+|my\s+)?(.+?)\s+(on|off)", t)
    if m:
        name, action = (m.group(2), m.group(1)) if m.group(1) else (m.group(3), m.group(4))
        return "device", {"name": name.strip(), "action": action}
    m = re.fullmatch(r"toggle\s+(?:the\s+|my\s+)?(.+)", t)
    if m:
        return "device", {"name": m.group(1).strip(), "action": "toggle"}
    m = re.fullmatch(r"(?:set|dim|turn|put|change)\s+(?:the\s+|my\s+)?(.+?)\s+(?:to|at)\s+(\d{1,3}(?:\.\d)?)\s*(?:%|percent|degrees?(?: celsius| c)?)?", t)
    if m and re.search(_HOME_KINDS, m.group(1)):
        v = float(m.group(2))
        return "device", {"name": m.group(1).strip(), "action": "set", "value": int(v) if v.is_integer() else v}
    m = re.fullmatch(r"(?:is|are)\s+(?:the\s+|my\s+)?(.+?)\s+(?:on|off|locked|unlocked|open|closed|shut|running)", t)
    if m and re.search(_HOME_KINDS, m.group(1)):
        return "device", {"name": m.group(1).strip(), "action": "status"}
    m = re.fullmatch(r"what(?:'s| is) the\s+(.+?)\s+(?:temperature|humidity)(?: (?:inside|now))?", t)
    if m:
        return "device", {"name": m.group(0).split("the ", 1)[1], "action": "status"}
    m = re.fullmatch(r"(lock|unlock)\s+(?:the\s+|my\s+)?(.+)", t)
    if m:
        return "device", {"name": m.group(2).strip(), "action": m.group(1)}
    m = re.fullmatch(r"(open|close|shut)\s+(?:the\s+|my\s+)?(.+)", t)
    if m and re.search(r"\b(?:garage|gate|door|blinds|curtains?|shades?|shutters?|cover)\b", m.group(2)):
        return "device", {"name": m.group(2).strip(), "action": "close" if m.group(1) == "shut" else m.group(1)}
    m = re.fullmatch(r"(.+?)\s+(on|off)", t)
    # "the lights are off" is a statement, not an order
    if m and re.search(_HOME_KINDS, m.group(1)) and not re.search(r"\b(?:is|are|was|were|been|be)$", m.group(1)):
        return "device", {"name": re.sub(r"^(?:the|my)\s+", "", m.group(1)).strip(), "action": m.group(2)}
    return None


# ---------- V: software (winget) ----------

def _software(t: str):
    if re.fullmatch(r"(?:update|upgrade) (?:all )?(?:of )?(?:my |the )?(?:apps|programs|software|applications)(?: on this (?:pc|laptop|computer))?"
                    r"|(?:update|upgrade) everything|update all|install (?:the |all )?(?:app |software )?updates", t):
        return "software", {"action": "update_all"}
    if re.fullmatch(r"(?:what|which) (?:apps|programs|software) (?:need|have|has) (?:updates?|updating|to be updated)"
                    r"|check for (?:app |software |program )?updates|any (?:app |software |program )?updates"
                    r"|are there (?:any )?(?:app |software )?updates|(?:list|show) (?:app |software )?updates", t) \
            and "windows" not in t:
        return "software", {"action": "check_updates"}
    m = re.fullmatch(r"uninstall\s+(?:the\s+)?(?:app\s+|program\s+)?(.+?)(?:\s+(?:app|program|software))?"
                     r"|(?:remove|delete)\s+(?:the\s+)?(?:app|program|software)\s+(.+)"
                     r"|(?:remove|delete)\s+(?:the\s+)?(.+?)\s+(?:app|program|software)", t)
    if m:
        return "software", {"action": "uninstall", "name": next(g for g in m.groups() if g).strip()}
    m = re.fullmatch(r"(?:install|download and install|get)\s+(?:the\s+)?(?:app\s+|program\s+)?(.+?)(?:\s+(?:app|program|software))?"
                     r"(?:\s+installed)?(?:\s+on (?:this|my) (?:pc|laptop|computer))?|install", t)
    if m and (t.startswith("install") or t.startswith("download and install") or t.endswith("installed")):
        return "software", {"action": "install", "name": m.group(1).strip()} if m.group(1) else {"action": "install"}
    return None


# ---------- W: read text on screen (OCR) ----------

def _ocr(t: str):
    if not re.search(r"\b(?:screen|window|screenshot|image|picture|photo)\b", t):
        return None
    if not re.search(r"\b(?:read|text|say|says|copy)\b", t):
        return None
    if re.search(r"\b(?:take|record|recording|share|settings?|brightness|turn|off|on my screen\?)\b", t) and "text" not in t:
        return None
    action = "copy" if re.match(r"(?:copy|grab|get)\b", t) else "read"
    if re.search(r"\b(?:last|latest|recent) (?:screenshot|screen shot)\b", t):
        return "ocr", {"source": "last_screenshot", "action": action}
    if re.search(r"\b(?:copied|this|the|that) (?:image|picture|photo)\b|\bimage (?:i copied|on (?:my|the) clipboard)\b", t):
        return "ocr", {"source": "clipboard_image", "action": action}
    if re.search(r"\b(?:this|the|current|active) window\b", t):
        return "ocr", {"source": "window", "action": action}
    if re.fullmatch(r"(?:copy|grab|get) (?:all )?(?:the )?text (?:on|from|off) (?:my |the |this )?screen"
                    r"|read (?:the |all )?(?:text on )?(?:my |the |this )?screen(?: (?:out loud|aloud|to me))?"
                    r"|read (?:the |all )?text (?:on|from) (?:my |the |this )?screen|what does (?:my|the|this) screen say", t):
        return "ocr", {"source": "screen", "action": action}
    return None


# ---------- X: clipboard history ----------
_ORD = {"second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "previous": 2,
        "last": 1, "first": 1}


def _cliphistory(t: str):
    if re.fullmatch(r"(?:clear|delete|erase|wipe|empty) (?:my |the )?clipboard history|forget (?:everything |what )i copied", t):
        return "clip_history", {"action": "clear"}
    if re.fullmatch(r"what (?:did|have) i cop(?:y|ied)(?: before| earlier| last| previously| recently| today)?"
                    r"|(?:show|read|list|open)(?: me)? (?:my |the )?clipboard history|what(?:'s| is) in (?:my |the )?clipboard history", t):
        return "clip_history", {"action": "list"}
    m = re.fullmatch(r"(paste|copy|put)\s+(?:the\s+)?(?:(second|third|fourth|fifth|2nd|3rd|4th|5th|previous)\s+(?:last\s+)?"
                     r"(?:thing|item|copy|one|text)(?: i copied)?|(?:item|number|clip)\s+(\d{1,2})"
                     r"|what i copied (?:before|earlier|previously))(?: again)?(?: back)?(?: on (?:the|my) clipboard)?"
                     r"(?: from (?:my |the )?clipboard history)?(?: again)?", t)
    if m:
        index = int(m.group(3)) if m.group(3) else _ORD.get(m.group(2) or "", 2)
        action = "paste" if m.group(1) == "paste" else "copy"
        if action == "copy" and not re.search(r"\b(?:again|back|history|item|number|clip)\b", t):
            return None  # "copy the second thing" without history words: leave it
        return "clip_history", {"action": action, "index": index}
    return None


# ---------- Y: Spotify (only when Spotify is named, or like/add this song) ----------

def _spotify(t: str):
    m = re.fullmatch(r"(?:open spotify and )?play\s+(.+?)\s+(?:on|in|using|with) spotify|spotify,? play\s+(.+)"
                     r"|open spotify and play\s+(.+)", t)
    if m:
        return "spotify", {"action": "play", "query": next(g for g in m.groups() if g).strip()}
    if re.fullmatch(r"play (?:on )?spotify|resume spotify", t):
        return "spotify", {"action": "play"}
    if re.fullmatch(r"play my liked songs", t):
        return "spotify", {"action": "play", "query": "my liked songs"}
    if re.fullmatch(r"(?:like|save|love|heart) (?:this|the|that) (?:song|track)(?: on spotify)?"
                    r"|add (?:this|the) (?:song|track) to (?:my )?liked songs", t):
        return "spotify", {"action": "like"}
    m = re.fullmatch(r"add (?:this|this song|this track|the song|it) to (?:my |the )?(.+?) playlist(?: on spotify)?", t)
    if m:
        return "spotify", {"action": "add_to_playlist", "playlist": m.group(1).strip()}
    if re.fullmatch(r"(?:turn |set )?shuffle (on|off)(?: on spotify)?|turn (on|off) shuffle(?: on spotify)?|shuffle(?: on)? spotify"
                    r"|shuffle (?:my |this )?(?:playlist|songs)", t):
        return "spotify", {"action": "shuffle", "state": "off" if re.search(r"\boff\b", t) else "on"}
    if re.fullmatch(r"repeat (?:this|the) (?:song|track)|put (?:this|the) song on repeat|loop (?:this|the) song", t):
        return "spotify", {"action": "repeat", "state": "track"}
    if re.fullmatch(r"repeat (?:this|the) (?:playlist|album)", t):
        return "spotify", {"action": "repeat", "state": "playlist"}
    if re.fullmatch(r"(?:turn )?repeat off|turn off repeat|stop repeating (?:the |this )?(?:song|track|playlist)", t):
        return "spotify", {"action": "repeat", "state": "off"}
    if re.fullmatch(r"what(?:'s| is) playing on spotify|what (?:song|track) is (?:this|playing) on spotify", t):
        return "spotify", {"action": "now_playing"}
    return None


# ---------- Z: word / quote of the day, on this day ----------

def _daily(t: str):
    if re.fullmatch(r"daily (?:facts|briefing)|(?:word|quote) and (?:word|quote) of the day", t):
        return "daily", {"what": "all"}
    if re.search(r"\bword of the day\b|^what(?:'s| is) today's word$|^today's word$|^teach me a (?:new )?word$", t):
        return "daily", {"what": "word"}
    if re.fullmatch(r"(?:give me |tell me |teach me )?(?:a |another )?(?:new|random|different) word|another word", t):
        return "daily", {"what": "word", "random": True}
    if re.search(r"\b(?:quote|thought) of the day\b|^today's quote$|^(?:give me|tell me|say) a quote$", t):
        return "daily", {"what": "quote"}
    if re.fullmatch(r"(?:give me |tell me )?(?:another|a random|a new|random) quote|inspire me|motivate me|say something motivating", t):
        return "daily", {"what": "quote", "random": True}
    if re.fullmatch(r"what happened (?:on this day|today)(?: in history)?|(?:on )?this day in history|on this day|today in history", t):
        return "daily", {"what": "on_this_day"}
    return None


# ---------- AA: passwords, PINs, UUIDs, QR codes ----------

def _generate(t: str, raw: str):
    m = re.fullmatch(r"(?:generate|make|create|give me|get me|suggest)(?: me)?(?: a| an)?(?: new)?(?: strong| random| secure| good)*"
                     r"(?: (\S+(?: \S+)?) character)? password(?: (?:with|of) (\S+(?: \S+)?) (?:characters|letters))?"
                     r"|(?:a )?new password|password with (\S+(?: \S+)?) characters|strong password", t)
    if m:
        length = m.group(1) or m.group(2) or m.group(3)
        return "generate", {"kind": "password", "length": length} if length else {"kind": "password"}
    m = re.fullmatch(r"(?:generate|make|create|give me|get me)(?: me)?(?: a| an)?(?: new)?(?: random)?(?: (\S+) digit)? (?:pin|passcode)"
                     r"|(?:a )?random (\S+) digit (?:pin|passcode)|random (?:pin|passcode)", t)
    if m:
        length = m.group(1) or m.group(2)
        return "generate", {"kind": "pin", "length": length} if length else {"kind": "pin"}
    if re.fullmatch(r"(?:generate|make|create|give me|get me)(?: me)?(?: a| an)?(?: new| random)? (?:uuid|guid)|new (?:uuid|guid)", t):
        return "generate", {"kind": "uuid"}
    if re.search(r"\bqr\b", t):
        m = re.search(r"\bqr(?: code)?\s+(?:of|for|from|with)\s+(.+)$", t)
        if m:
            c = re.search(r"\bqr(?: code)?\s+(?:of|for|from|with)\s+(.+?)[\s.?!]*$", raw, re.I)  # keep URL dots and case
            text = c.group(1).strip() if c else m.group(1).strip()
            return "generate", {"kind": "qr", "text": text}
        return "generate", {"kind": "qr"}
    return None


# ================= Round 4 (pieces AB-AI) =================

def _triggers(raw: str):
    try:
        from jarvis.actions import triggers
        return triggers.parse(raw)
    except Exception:
        return None


# ---------- AE: security (Jarvis lock, guest mode). Before the laptop "lock" rule ----------

def _security(t: str, raw: str):
    if re.fullmatch(r"(?:lock (?:jarvis|yourself)|jarvis lock|lock (?:up )?jarvis)", t):
        return "jarvis_lock", {"state": "on"}
    m = re.fullmatch(r"unlock (?:jarvis|yourself)(?:\s+(?:pin\s+|code\s+|with\s+)?(.+))?", t)
    if m:
        return "jarvis_lock", {"state": "off", "pin": m.group(1).strip()} if m.group(1) else {"state": "off"}
    if re.fullmatch(r"(?:are you|is jarvis) locked", t):
        return "jarvis_lock", {"state": "status"}
    if re.fullmatch(r"is guest mode (?:on|off)|am i in guest mode", t):
        return "guest_mode", {"state": "status"}
    if re.fullmatch(r"(?:turn|switch) (?:on|off) guest mode|guest mode (?:on|off)|(?:enable|start|enter|disable|stop|exit|end|leave) guest mode", t):
        return "guest_mode", {"state": "off" if re.search(r"\b(?:off|disable|stop|exit|end|leave)\b", t) else "on"}
    return None


# ---------- AF: command history ----------

def _history(t: str):
    if re.fullmatch(r"(?:do|run|try) (?:that|it|this) again|one more time|repeat (?:the )?last command|again please"
                    r"|do the same(?: thing)? again", t):
        return "history", {"action": "repeat_last"}
    if "clipboard" in t:
        return None
    if re.fullmatch(r"(?:clear|delete|erase|wipe) (?:my |the )?(?:command |voice )?history", t):
        return "history", {"action": "clear"}
    m = re.fullmatch(r"(?:what did i (?:ask|say|tell you)(?: you)?(?: to do)? about|search (?:my )?(?:command )?history for"
                     r"|did i ask(?: you)? about)\s+(.+?)(?:\s+(today|yesterday|day before yesterday|(?:on |last )?"
                     r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|\S+ days? ago))?", t)
    if m:
        args = {"action": "search", "query": m.group(1).strip()}
        if m.group(2):
            args["day"] = m.group(2)
        return "history", args
    m = re.fullmatch(r"what did i (?:ask|say|tell you)(?: you)?(?:\s+(.+))?|(?:show|read|list)(?: me)? my (?:command )?history"
                     r"|my command history", t)
    if m:
        day = m.group(1) if m.lastindex else None
        if day and not re.fullmatch(r"today|yesterday|day before yesterday|(?:on |last |this )?(?:monday|tuesday|wednesday|"
                                    r"thursday|friday|saturday|sunday)|\S+ days? ago|\d{4}-\d\d-\d\d", day):
            return None
        return "history", {"action": "list", "day": day} if day else {"action": "list"}
    return None


# ---------- AG: local AI mode ----------

def _localai(t: str):
    if re.fullmatch(r"(?:use|switch to|change to|turn on) (?:the )?(?:local|offline) (?:ai|model|brain)|use ollama|switch to ollama"
                    r"|(?:ai|brain) mode (?:local|offline)", t):
        return "ai_mode", {"mode": "local"}
    if re.fullmatch(r"(?:use|switch to|change to) (?:the )?(?:cloud|online) (?:ai|model|brain)|use claude|switch to claude"
                    r"|(?:ai|brain) mode (?:cloud|online)", t):
        return "ai_mode", {"mode": "cloud"}
    if re.fullmatch(r"(?:use )?auto(?:matic)? (?:ai|brain)(?: mode)?|(?:ai|brain) mode auto(?:matic)?|use automatic ai", t):
        return "ai_mode", {"mode": "auto"}
    if re.fullmatch(r"is (?:the )?(?:local|offline) (?:ai|model) (?:ready|working|running|on)|(?:local|offline) ai status"
                    r"|is ollama (?:running|ready|working|on)", t):
        return "local_ai_status", {}
    return None


# ---------- AC: meetings ----------

def _meetings(t: str):
    m = re.fullmatch(r"join (?:my |the )?(?:next )?(?:meeting|call|class|zoom|teams meeting|meet)(?:\s+(?:at|for)\s+(.+))?"
                     r"|join (?:my |the )?(.+?)(?:'s)? (?:meeting|call|class)", t)
    if m:
        when = (m.group(1) or m.group(2) or "").strip()
        if when and not re.search(r"\d|\b(?:today|tomorrow|morning|afternoon|evening|noon|one|two|three|four|five|six|"
                                  r"seven|eight|nine|ten|eleven|twelve)\b", when):
            when = ""
        return "meeting", {"action": "join", "when": when} if when else {"action": "join"}
    if re.fullmatch(r"leave (?:the |this )?(?:meeting|call)|hang up|end (?:the |this )?call|drop (?:the |this )?call", t):
        return "meeting", {"action": "leave"}
    if re.fullmatch(r"(?:mute|unmute) me(?: in (?:the )?(?:meeting|call))?|(?:mute|unmute) (?:in|on) (?:the )?(?:meeting|call)"
                    r"|(?:mute|unmute) (?:my )?(?:mic|microphone) (?:in|on) (?:the )?(?:meeting|call)", t):
        return "meeting", {"action": "mute"}
    if re.fullmatch(r"am i (?:in|on) a (?:meeting|call)|am i in a zoom|am i in a teams (?:meeting|call)", t):
        return "meeting", {"action": "status"}
    return None


# ---------- AD: screen time and app limits ----------

def _minutes(text: str, duration) -> int | None:
    if re.search(r"\ban hour and a half\b", text):
        return 90
    secs = duration(text)
    if secs:
        return max(1, round(secs / 60))
    if re.search(r"\b(?:an|one) hour\b", text):
        return 60
    return None


def _screentime(t: str, duration):
    if re.search(r"\bapp limits?\b", t) and re.match(r"(?:what|list|show|read|tell me)", t):
        return "app_limit", {}
    m = re.fullmatch(r"(?:remove|delete|clear|cancel) (?:the |my )?(.+?) limit|no (?:more )?limit (?:for|on) (.+)", t)
    if m:
        return "app_limit", {"app": (m.group(1) or m.group(2)).strip(), "minutes": 0}
    m = (re.fullmatch(r"warn me after (.+?) (?:of|on|using) (.+)", t)
         or re.fullmatch(r"limit (.+?) to (.+)", t)
         or re.fullmatch(r"set (?:a |an )?(.+?) limit (?:for|on) (.+)", t))
    if m:
        a, b = m.group(1), m.group(2)
        when, app = (a, b) if not t.startswith("limit") else (b, a)
        mins = _minutes(when, duration)
        if mins:
            return "app_limit", {"app": re.sub(r"^(?:the|my)\s+", "", app.strip()), "minutes": mins}
    if "screen time" in t or re.fullmatch(r"(?:my |what are my )?top apps(?: today| this week)?|what apps did i use (?:the )?most"
                                          r"(?: today| this week)?", t):
        return "screen_time", {"period": "week"} if re.search(r"\b(?:this |last )?week\b", t) else {}
    m = re.fullmatch(r"how (?:long|much time) (?:did i|have i) (?:use|used|spend|spent|been on|been using)\s+(?:on\s+)?(.+?)"
                     r"(?:\s+(today|this week))?"
                     r"|how much time (?:on|in) (.+?)(?:\s+(today|this week))?", t)
    if m:
        app = (m.group(1) or m.group(3)).strip()
        period = m.group(2) or m.group(4)
        args = {"app": re.sub(r"^(?:the|my)\s+", "", app)}
        if period == "this week":
            args["period"] = "week"
        return "screen_time", args
    return None


# ---------- AH: window layouts ----------

def _layouts(t: str):
    if not re.search(r"\b(?:layouts?|window setup|setup)\b", t):
        return None
    if re.fullmatch(r"(?:list|show)(?: me)?(?: my| the)?(?: window)? layouts|what (?:window )?layouts do i have", t):
        return "layout", {"action": "list"}
    m = re.fullmatch(r"(?:save|store|remember) (?:this |my |the )?(?:window )?(?:layout|setup)(?: (?:as|called|named) (.+))?", t)
    if m:
        return "layout", {"action": "save", "name": m.group(1).strip()} if m.group(1) else {"action": "save"}
    m = re.fullmatch(r"(?:restore|load|apply|set up|open|bring back) (?:my |the )?(?:(.+?) )?(?:window )?layout(?: (.+))?", t)
    if m:
        name = m.group(1) or m.group(2)
        return "layout", {"action": "restore", "name": name.strip()} if name else {"action": "restore"}
    m = re.fullmatch(r"(?:delete|remove|forget) (?:my |the )?(?:(.+?) )?(?:window )?layout(?: (.+))?", t)
    if m:
        name = m.group(1) or m.group(2)
        return "layout", {"action": "delete", "name": name.strip()} if name else {"action": "delete"}
    return None


# ---------- AI: podcasts ----------

def _podcasts(t: str):
    if re.fullmatch(r"(?:list|show)(?: me)? my podcasts|what podcasts do i (?:follow|have|listen to)|my podcasts", t):
        return "podcast", {"action": "list"}
    if re.fullmatch(r"what(?:'s| is) new in my podcasts|any new (?:podcast )?episodes|new podcast episodes|any new podcasts", t):
        return "podcast", {"action": "whats_new"}
    m = re.fullmatch(r"(?:play (?:the )?)?next episode(?: of (.+?))?(?: podcast)?", t)
    if m:
        return "podcast", {"action": "next", "name": m.group(1).strip()} if m.group(1) else {"action": "next"}
    # keep "the" in the name: "the daily" is a show, "daily" finds other shows
    m = re.fullmatch(r"(?:subscribe|follow) to (?:the podcast |podcast )?(.+?)(?: podcast)?|follow (?:the )?podcast (.+)", t)
    if m:
        return "podcast", {"action": "subscribe", "name": (m.group(1) or m.group(2)).strip()}
    m = re.fullmatch(r"unsubscribe (?:from )?(?:the )?(?:podcast )?(.+?)(?: podcast)?|unfollow (?:the )?podcast (.+)", t)
    if m:
        return "podcast", {"action": "unsubscribe", "name": (m.group(1) or m.group(2)).strip()}
    m = re.fullmatch(r"play (?:the )?(?:latest|newest|last|new) episode of (.+?)(?: podcast)?|play (?:the )?podcast (.+)"
                     r"|play (.+?) podcast", t)
    if m:
        return "podcast", {"action": "play_latest", "name": next(g for g in m.groups() if g).strip()}
    return None


# ================= Round 5 (pieces AJ-AO) and the self-check (AP) =================

def _teach(raw: str):
    """'when I say X, do Y' (before every other rule: the sentence holds other commands) and taught list/forget."""
    try:
        from jarvis.actions import teach
        a = teach.parse_teach(raw)
        if a:
            return "teach", a
        a = teach.parse_taught(raw)
        if a and not (a.get("action") == "forget" and (a.get("phrase") or "").strip().lower() in ("", "everything", "all", "my voice", "my voice print",
                                                                          "my voiceprint")):
            return "taught", a
    except Exception:
        return None
    return None


def _city_tail(t: str) -> dict:
    m = re.search(r" (?:in|for|at) ([a-z][a-z ,]+?)(?: today| now| right now| tomorrow)?$", t)
    if m and m.group(1) not in ("the next hour", "next hour", "my area", "here"):
        return {"city": m.group(1)}
    return {}


def _airquality(t: str):
    """Air quality, sunrise/sunset, rain in the next hour, UV. Before the general weather rule."""
    if re.search(r"\bair quality\b|\baqi\b|\bpollution (?:level|index)\b|\bhow is the air\b|\bair (?:ok|okay|safe|good)\b", t) \
            or re.search(r"\b(?:safe to|can i|good time to|ok to|okay to) (?:go )?(?:for )?(?:a )?(?:run|running|jog|jogging|walk)\b.*\b(?:outside|outdoors|air)\b"
                         r"|\bis it safe to (?:go )?(?:for )?(?:a )?(?:run|running|jog|jogging|walk)\b", t):
        return "air_quality", _city_tail(t)
    if re.search(r"\bsun ?(?:rise|set)s?\b", t) and re.search(r"\b(?:when|what time|time of|sunrise and|sunset and)\b|^sun", t):
        return "sun_times", _city_tail(t)
    if re.search(r"\bumbrella\b", t) or (re.search(r"\brain\b", t) and re.search(r"\bnext hour\b|\bsoon\b|\bright now\b", t)):
        return "rain_soon", _city_tail(t)
    if re.search(r"\buv\b|\bsunscreen\b|\bsun ?cream\b", t):
        return "uv", _city_tail(t)
    return None


_MY_MUSIC = r"(?:from |on )?(?:my music|my songs|my music library|my library|local music|my computer|my pc|my laptop)"


def _localmusic(t: str, raw: str):
    """Songs on this PC. Only with 'my music', 'my songs', 'from my computer'...; plain 'play X' stays with YouTube/Spotify."""
    if re.fullmatch(r"(?:update|rescan|refresh|re scan) (?:my )?music(?: library)?", t):
        return "local_music", {"action": "rescan"}
    if re.fullmatch(r"what's in my music library|what is in my music library|how many songs do i have", t):
        return "local_music", {"action": "list"}
    m = re.fullmatch(r"(?:what|which) (?:songs|albums|music) do i have by (.+)", t)
    if m:
        return "local_music", {"action": "list", "artist": _orig(raw, m.group(1))}
    m = re.fullmatch(r"(play|shuffle) (?:my music|my songs|music from my (?:computer|pc|laptop)|songs from my (?:computer|pc|laptop)|local music)", t)
    if m:
        return "local_music", {"action": m.group(1)}
    m = re.fullmatch(r"(play|shuffle) (.+?) " + _MY_MUSIC, t) or re.fullmatch(r"(play|shuffle) my song (.+)", t)
    if not m:
        return None
    action, what = m.group(1), m.group(2)
    if t.startswith(("play my song", "shuffle my song")):
        return "local_music", {"action": action, "song": _orig(raw, what)}
    mm = re.fullmatch(r"(?:the )?album (.+)", what)
    if mm:
        return "local_music", {"action": action, "album": _orig(raw, mm.group(1))}
    mm = re.fullmatch(r"(?:the )?song (.+)", what)
    if mm:
        return "local_music", {"action": action, "song": _orig(raw, mm.group(1))}
    mm = re.fullmatch(r"(?:songs |music )?by (.+)", what)
    if mm:
        return "local_music", {"action": action, "artist": _orig(raw, mm.group(1))}
    what = re.sub(r"^(?:some|any|a bit of|a few|few|something)\s*", "", what)  # "play some local music"
    if not what or what in ("music", "songs", "song", "tunes"):
        return "local_music", {"action": action}
    return "local_music", {"action": action, "query": _orig(raw, what)}


def _radio(t: str, raw: str):
    """Internet radio. Only phrases with radio/station/fm; Wi-Fi/Bluetooth 'radio' words stay with radios.py."""
    if not re.search(r"\b(?:radio|station|stations|fm)\b", t) or re.search(r"\bwi ?fi\b|\bbluetooth\b|\bairplane\b", t):
        return None
    if re.fullmatch(r"(?:next|another|change the|change) station|skip (?:this )?station", t):
        return "radio", {"action": "next"}
    if re.fullmatch(r"(?:stop|turn off|switch off|close) (?:the )?radio", t):
        return "radio", {"action": "stop"}
    if re.fullmatch(r"(?:save|favourite|favorite) (?:this|the) station|add (?:this|the) station to (?:my )?favou?rites", t):
        return "radio", {"action": "save"}
    if re.fullmatch(r"list (?:my )?(?:radio )?stations|what are my favou?rite (?:radio )?stations|my (?:favou?rite )?stations", t):
        return "radio", {"action": "list"}
    m = re.fullmatch(r"play my favou?rite (?:radio )?station(?: (.+))?", t)
    if m:
        return "radio", ({"action": "favourite", "query": m.group(1)} if m.group(1) else {"action": "favourite"})
    m = re.fullmatch(r"play (?:the )?(.*?) ?radio from ([a-z ]+)", t)
    if m:
        args = {"action": "play", "country": _orig(raw, m.group(2))}
        if m.group(1) and m.group(1) not in ("some", "a", "the"):
            args["query"] = m.group(1)
        return "radio", args
    m = re.fullmatch(r"(?:play|put on|tune (?:in )?to) (.+)", t)
    if m:
        return "radio", {"action": "play", "query": m.group(1)}
    return None


def _voiceid(t: str):
    """Voice lock. Only 'voice lock' / 'my voice' phrases: 'lock Jarvis' and 'change your voice' stay as they are."""
    if re.fullmatch(r"(?:learn|remember|train|enrol|enroll|record) my voice", t):
        return "voice_id", {"action": "enrol"}
    if re.fullmatch(r"who am i|do you (?:know|recogni[sz]e) my voice|is this my voice|do you recogni[sz]e me", t):
        return "voice_id", {"action": "check"}
    if re.fullmatch(r"(?:turn on |switch on |enable )?voice lock(?: on)?|only listen to my voice", t):
        return "voice_id", {"action": "on"}
    if re.fullmatch(r"(?:turn off |switch off |disable )voice lock|voice lock off", t):
        return "voice_id", {"action": "off"}
    if re.fullmatch(r"is (?:the )?voice lock on|voice lock status", t):
        return "voice_id", {"action": "status"}
    if re.fullmatch(r"(?:forget|delete|remove) my voice(?: print)?|(?:forget|delete|remove) (?:my |the )?voice ?print", t):
        return "voice_id", {"action": "forget"}
    return None


def _sleeptimer(t: str, duration):
    """'stop the music in 30 minutes', 'shut down in 2 hours'. Needs a duration, so plain 'shut down' stays instant."""
    if re.fullmatch(r"(?:cancel|stop|turn off|remove) (?:the |my )?(?:sleep|shutdown|shut down) timer", t):
        return "sleep_timer_cancel", {}
    if re.fullmatch(r"(?:sleep timer status|how (?:long|much time) is left on (?:the )?sleep timer"
                    r"|when will (?:the )?music stop|is (?:there )?a sleep timer(?: set| on)?)", t):
        return "sleep_timer_status", {}
    m = re.fullmatch(r"(stop|turn off|pause|switch off) (?:the |my )?(?:music|song|songs|audio|video|media|podcast) (?:in|after) (.+)"
                     r"|sleep timer(?: for)? (.+)"
                     r"|(sleep|put) (?:the |my )?(?:laptop|computer|pc)(?: to sleep)? (?:in|after) (.+)"
                     r"|(?:shut ?down|turn off|switch off|power off)(?: the| my)?(?: laptop| computer| pc)? (?:in|after) (.+)", t)
    if not m:
        return None
    when = m.group(2) or m.group(3) or m.group(5) or m.group(6)
    seconds = duration(when)
    if not seconds or not re.search(r"\b(?:minutes?|mins?|hours?|hrs?)\b", when):
        return None
    minutes = max(1, round(seconds / 60))
    action = "stop_media" if (m.group(1) or m.group(3)) else "sleep" if m.group(4) else "shutdown"
    return "sleep_timer", {"minutes": minutes, "action": action}


_DESK_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third|fourth|fifth|last|to)"


def _vdesktops(t: str):
    """Virtual desktops. Needs the word desktop; 'show desktop' stays window show_desktop."""
    if "desktop" not in t or re.search(r"\bshow (?:the |my )?desktop\b|desktop folder|on my desktop|\bdesktop app\b", t):
        return None
    if re.fullmatch(r"(?:new |create (?:a )?(?:new )?(?:virtual )?|add (?:a )?(?:new )?(?:virtual )?|open (?:a )?new )desktop"
                    r"|new virtual desktop", t):
        return "vdesktop", {"action": "new"}
    if re.fullmatch(r"(?:switch to |go to )?(?:the )?next (?:virtual )?desktop", t):
        return "vdesktop", {"action": "next"}
    if re.fullmatch(r"(?:switch to |go to )?(?:the )?previous (?:virtual )?desktop|go back a desktop", t):
        return "vdesktop", {"action": "previous"}
    m = re.fullmatch(r"(?:move|send) (?:this|the) (?:window |app )?to (?:the )?(?:virtual )?desktop (?:number )?" + _DESK_NUM
                     + r"|(?:move|send) (?:this|the) (?:window |app )?to (?:the )?" + _DESK_NUM + r" desktop", t)
    if m:
        return "vdesktop", {"action": "move_window", "number": m.group(1) or m.group(2)}
    m = re.fullmatch(r"(?:go to |switch to )?(?:the )?(?:virtual )?desktop (?:number )?" + _DESK_NUM
                     + r"|(?:go to |switch to )(?:the )?" + _DESK_NUM + r" (?:virtual )?desktop", t)
    if m:
        return "vdesktop", {"action": "go", "number": m.group(1) or m.group(2)}
    if re.fullmatch(r"which (?:virtual )?desktop am i on|how many (?:virtual )?desktops(?: do i have)?", t):
        return "vdesktop", {"action": "which"}
    if re.fullmatch(r"(?:close|delete|remove) (?:this|the|current) (?:virtual )?desktop|close (?:virtual )?desktop", t):
        return "vdesktop", {"action": "close"}
    return None


def _printer(t: str, raw: str):
    """Printing. 'print screen' / 'press print' are keys; bare 'print this' stays Ctrl+P in the open app."""
    if re.search(r"\bprint ?screen\b|^press print|settings", t):
        return None
    if re.fullmatch(r"whats? in the print queue|what's in the print queue|what is in the print queue|(?:show|list) (?:the |my )?print (?:jobs|queue)"
                    r"|what's printing|what is printing|print queue", t):
        return "print_queue", {"action": "list"}
    if re.fullmatch(r"(?:cancel|stop) (?:all )?(?:printing|print jobs|the print jobs?|my print jobs?)|clear the print queue", t):
        return "print_queue", {"action": "cancel"}
    if re.fullmatch(r"(?:what's|what is|which is) my default printer|which printer(?: is (?:set|default))?|printer status"
                    r"|is (?:the|my) printer (?:online|offline|on|working|ready|out of paper|out of ink)", t):
        return "printer_info", {}
    if re.fullmatch(r"print (?:this|the selected|these|the) (?:document|file|files|pdf|picture|photo|selected files?)", t):
        return "print_file", {"name": "this"}
    if re.fullmatch(r"print (?:my |the )?(?:last|latest) download", t):
        return "print_file", {"name": "last download"}
    m = re.fullmatch(r"print (?:my |the )?(.+)", t)
    if m and m.group(1) not in ("this", "it", "that", "page", "this page") and not re.search(r"\b(?:hello|world)\b", t):
        fm = re.search(r"([\w\-]+\.(?:pdf|docx?|txt|jpe?g|png|xlsx?|pptx?))\b", raw, re.I)
        return "print_file", {"name": fm.group(1) if fm else _orig(raw, m.group(1))}
    return None


_RESULT_NUM = r"(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|[4-9]th|10th|one|two|three|four|five)"


def _filesearch(t: str, raw: str):
    """Words INSIDE files (Windows Search index). Plain 'find <name>' stays with the name search."""
    m = re.fullmatch(r"open (?:the )?(?:number )?" + _RESULT_NUM + r"(?: one| result| file)?", t)
    if m:
        try:
            from jarvis.actions import filesearch
            if filesearch.has_results():
                return "open_result", {"number": m.group(1)}
        except Exception:
            pass
        return None
    m = re.fullmatch(r"(?:find|search for|show me|look for) (?:the |my |all )?(files?|documents?|pdfs?|word (?:files|documents)|pictures|photos|images)"
                     r" (?:that )?(?:mentions?|about|containing|contains|with|which mentions?) (.+)", t)
    if m:
        args = {"text": _orig(raw, m.group(2))}
        if not re.fullmatch(r"files?|documents?", m.group(1)):
            args["kind"] = m.group(1)
        return "find_files", args
    m = re.fullmatch(r"search inside (?:my )?files for (.+)|which (?:file|document) (?:mentions|has|contains|talks about) (.+)", t)
    if m:
        return "find_files", {"text": _orig(raw, m.group(1) or m.group(2))}
    m = re.fullmatch(r"(?:show (?:me )?)?(?:the )?files i (?:edited|changed|worked on|modified) (today|yesterday|this week|in the last hour)", t)
    if m:
        return "find_files", {"modified": {"this week": "week", "in the last hour": "hour"}.get(m.group(1), m.group(1))}
    return None


def _round7_modules(raw: str):
    """flashcards.parse runs before fun's quiz rules ("quiz me on spanish" = a flashcard deck, if it exists)."""
    # timetrack before habits ("stop tracking X") and screen time; birthdays before contacts ("Ravi's birthday is ...")
    # devtools before the open_app / close_app / press_keys rules ("run the tests", "push my changes")
    for name in ("flashcards", "timetrack", "birthdays", "contacts", "habits", "recipes", "accessibility",
                 "devtools", "recap", "drives", "hotspot", "display", "webcam", "multilang"):
        try:
            import importlib

            hit = importlib.import_module("jarvis.actions." + name).parse(raw)
        except Exception:
            hit = None
        if hit:
            return hit
    return None


_DOC_WORDS = r"(?:pdf|document|word file|word document|text file|\S+\.(?:pdf|docx|txt|md)|(?:my )?last download|latest download)"


def _doc_open() -> bool:
    try:
        from jarvis.actions import documents
        return documents._STATE.get("doc") is not None
    except Exception:
        return False


def _documents(t: str, raw: str):
    """Read PDFs / Word / text files. Plain 'read this' stays read_aloud; 'continue' only while a document is open."""
    if re.fullmatch(r"continue(?: reading)?|keep reading|next part|read more|go on", t):
        return ("document", {"action": "continue"}) if _doc_open() else None
    m = re.fullmatch(r"read page (\d+)(?: of (.+))?", t)
    if m:
        args = {"action": "page", "page": int(m.group(1))}
        if m.group(2) and m.group(2) not in ("this", "this pdf", "the pdf", "this document", "it"):
            args["name"] = _orig(raw, m.group(2))
        return "document", args
    m = re.fullmatch(r"how many pages (?:does (.+?) have|(?:are )?in (?:this|the) (?:pdf|document)|(?:are )?in (.+))", t)
    if m:
        name = m.group(1) or m.group(2)
        return "document", ({"action": "pages", "name": _orig(raw, name)} if name and name not in ("this", "it") else {"action": "pages"})
    m = re.fullmatch(r"(?:read|open and read|read out) (?:me )?(this|the|my|that)? ?(.+)", t)
    if m and re.search(_DOC_WORDS, m.group(2)) and not re.search(r"\b(?:screen|clipboard|selected|selection|email)\b", t):
        target = m.group(2)
        if (m.group(1) in ("this", "the", "that") and re.fullmatch(r"pdf|document|word file|word document|text file", target)):
            return "document", {"action": "read"}
        name = (m.group(1) + " " if m.group(1) else "") + target
        fm = re.search(r"[\w\-. ]*?([\w\-]+\.(?:pdf|docx|txt|md))\b", raw, re.I)  # nlu text lost the dot
        return "document", {"action": "read", "name": fm.group(1) if fm else _orig(raw, name)}
    return None


def _maps(t: str, raw: str):
    """Travel time and directions (OpenStreetMap / Google Maps). The handler cleans the place text itself."""
    if t in ("take me home", "directions home", "navigate home"):
        return "directions", {"to": "home"}
    m = re.fullmatch(r"(?:walking |driving )?directions? (?:to|from) .+|navigate to .+|take me to .+", t)
    if m:
        args = {"to": _orig(raw, t)}
        if t.startswith("walking "):
            args["mode"] = "walking"
        mm = re.search(r" by (bus|train|metro|transit)$", t)
        if mm:
            args["mode"] = "transit"
        return "directions", args
    if re.fullmatch(r"how (?:long|far) (?:will it take |does it take |would it take )?(?:to )?(?:drive |walk |get |reach |go )?"
                    r"(?:to|from) .+|how far is .+ from .+|how far is (?:the )?[a-z][a-z ]+|distance (?:to|from|between) .+"
                    r"|travel time to .+|how long to (?:drive|walk|get) to .+", t):
        if re.search(r"\b(?:download|timer|alarm|reminder|along|left|it|moon|sun|mars|space|planet|earth)\b", t):
            return None
        args = {"to": _orig(raw, t)}
        if re.search(r"\bwalk(?:ing)?\b|on foot", t):
            args["mode"] = "walking"
        return "travel_time", args
    return None


def _watchers(t: str, raw: str):
    m = re.fullmatch(r"(?:tell me|let me know|notify me|alert me) when (.+)", t)
    if m:
        what = m.group(1)
        if re.search(r"\bdownloads? (?:is |are )?(?:finish|finishes|finished|done|complete|completes)", what):
            return "watch", {"what": "download"}
        mm = re.search(r"battery (?:is|reaches|hits|gets to) (\d+)", what)
        if mm:
            return "watch", {"what": "battery", "value": int(mm.group(1))}
        mm = re.fullmatch(r"(.+?) (?:is back(?: up| online)?|is up|is online|comes back(?: up| online)?)", what)
        if mm and re.search(r"\.| dot ", mm.group(1)):
            return "watch", {"what": "website", "target": _orig(raw, mm.group(1))}
        # "google.com" arrives as "google com" (the dot is removed when cleaning the text)
        tld = re.fullmatch(r"([a-z0-9-]+(?: [a-z0-9-]+)?) (com|org|net|in|io|co|dev|ai|edu|gov|app)", mm.group(1)) if mm else None
        if tld:
            return "watch", {"what": "website", "target": tld.group(1).replace(" ", ".") + "." + tld.group(2)}
        mm = re.fullmatch(r"(?:the )?(.+?) (?:closes|is closed|quits|exits)", what)
        if mm:
            return "watch", {"what": "app_closed", "target": mm.group(1)}
        if re.search(r"\bcpu is idle|render is (?:done|finished)|cpu (?:is )?(?:free|quiet)", what):
            return "watch", {"what": "cpu_idle"}
        return None
    if re.fullmatch(r"what are you watching(?: for)?|list (?:my |the )?watch(?:es|ers)|what are you waiting for", t):
        return "watches", {"action": "list"}
    if re.fullmatch(r"(?:stop watching|cancel all watches|cancel (?:my |the )?watches)", t):
        return "watches", {"action": "cancel"}
    m = re.fullmatch(r"stop watching (?:for )?(?:my |the )?(.+)", t)
    if m:
        return "watches", {"action": "cancel", "target": m.group(1)}
    return None


_FILE_OBJ = r"(?:this|these|that|it|the selected(?: files?)?|selected files?|my last download|my latest download|last download)"
_IMG = r"(?: (?:picture|image|photo|file|document|pictures|images|photos|files))?"


def _fileconvert(t: str, raw: str):
    """Convert files. Unit / money conversions ("convert 5 km to miles") stay with convert.py."""
    m = re.fullmatch(r"(?:convert|turn|make|save|export) (.+?) (?:to|into|as) (?:an? )?(pdf|png|jpg|jpeg|webp|bmp)s?(?: files?)?", t)
    if m and not re.match(r"[\d.]", m.group(1)):
        obj, fmt = m.group(1), m.group(2)
        obj = re.sub(r" (?:picture|image|photo|file|document|pictures|images|photos|files)$", "", obj)
        if re.fullmatch(r"(?:my )?(?:last|latest) download", obj):
            name = "last download"
        else:
            name = "" if re.fullmatch(_FILE_OBJ, obj) else _orig(raw, obj)
        args = {"action": "to_pdf"} if fmt == "pdf" else {"action": "to_format", "format": "jpg" if fmt == "jpeg" else fmt}
        if name:
            args["name"] = name
        return "convert_file", args
    m = re.fullmatch(r"(?:merge|combine|join) (?:these |the selected |my |the )?pdfs?(?: files)?(?: (.+ and .+))?", t)
    if m:
        return "convert_file", ({"action": "merge_pdfs", "name": _orig(raw, m.group(1))} if m.group(1) else {"action": "merge_pdfs"})
    m = re.fullmatch(r"(?:resize|shrink|make smaller) (" + _FILE_OBJ + r"|.+?)" + _IMG + r"(?: to (.+))?", t)
    if m and (re.fullmatch(_FILE_OBJ, m.group(1)) or re.search(r"picture|image|photo|\.(?:png|jpe?g|webp|bmp)", t)):
        args = {"action": "resize"}
        if not re.fullmatch(_FILE_OBJ, m.group(1)):
            args["name"] = _orig(raw, m.group(1))
        if m.group(2):
            size = m.group(2)
            mm = re.search(r"(\d+)\s*%", raw)
            args["size"] = (mm.group(1) + "%") if mm and "percent" not in size else size
        return "convert_file", args
    m = re.fullmatch(r"(?:compress|reduce the size of) (" + _FILE_OBJ + r"|.+?)" + _IMG, t)
    if m and (re.fullmatch(_FILE_OBJ, m.group(1)) or re.search(r"picture|image|photo|\.(?:png|jpe?g|webp|bmp)", t)):
        args = {"action": "compress"}
        if not re.fullmatch(_FILE_OBJ, m.group(1)):
            args["name"] = _orig(raw, m.group(1))
        return "convert_file", args
    return None


def _corrections(raw: str):
    """Word fixes: 'when you hear note pad I mean notepad', 'you misheard', 'list corrections'."""
    try:
        from jarvis.actions import corrections
        return corrections.parse(raw)
    except Exception:
        return None


def _wakeword(t: str):
    if not re.search(r"\bwake\b|\bwaking\b", t):
        return None
    if re.fullmatch(r"(?:make )?(?:the )?wake ?word more sensitive|increase (?:the )?wake(?: ?word)? sensitivity", t):
        return "wake_sensitivity", {"change": "up"}
    if re.fullmatch(r"(?:make )?(?:the )?wake ?word less sensitive|(?:decrease|lower) (?:the )?wake(?: ?word)? sensitivity"
                    r"|you wake up too (?:often|much)|stop waking up by (?:mistake|accident)", t):
        return "wake_sensitivity", {"change": "down"}
    m = re.fullmatch(r"set (?:the )?wake(?: ?word)? sensitivity to (\d+(?:\.\d+)?)(?: percent| %)?", t)
    if m:
        v = m.group(1)
        return "wake_sensitivity", {"value": float(v) if "." in v else int(v)}
    if re.fullmatch(r"how sensitive is (?:the )?wake ?word|(?:what is |what's )?(?:the )?wake ?word sensitivity", t):
        return "wake_sensitivity", {}
    return None


_SETUP_PARTS = [
    (r"(?:run|start|redo|do) (?:the )?setup(?: again)?|set yourself up|set up jarvis(?: again)?", None),
    (r"change my name|call me something else", "name"),
    (r"change my (?:city|location|home city)", "city"),
    (r"change (?:the )?(?:temperature )?units|change (?:the )?temperature units", "units"),
    (r"change (?:the |your )?greeting|beep instead|stop beeping", "greeting"),
    (r"test (?:my |the )?(?:mic|microphone)", "mic"),
    (r"test (?:the |my )?wake ?word", "wake"),
    (r"set up (?:a |my )?pin|create my pin", "pin"),
]


def _setup(t: str):
    """First-run voice setup again, or one part of it. Bare 'call me X' is NOT here (phone calls)."""
    for pat, part in _SETUP_PARTS:
        if re.fullmatch(pat, t):
            return "setup", ({"part": part} if part else {})
    return None


def _notifications(t: str):
    if "notification" not in t:
        return None
    if re.fullmatch(r"(?:clear|dismiss|delete|remove) (?:all )?(?:my |the )?notifications", t):
        return "notifications", {"action": "clear"}
    if re.fullmatch(r"(?:stop|don't|do not|no more) (?:announcing|reading out|reading) (?:my )?notifications"
                    r"|(?:turn off|stop) (?:notification announcements|announcing notifications)", t):
        return "notifications", {"action": "announce_off"}
    if re.fullmatch(r"(?:announce|read out) (?:my )?(?:new )?notifications|tell me when i get (?:a )?notifications?"
                    r"|(?:turn on|start) (?:notification announcements|announcing notifications)", t):
        return "notifications", {"action": "announce_on"}
    if re.fullmatch(r"(?:read|show|check)(?: me)? (?:my |the )?(?:new |latest )?notifications|any (?:new )?notifications"
                    r"|what are my notifications|do i have (?:any )?(?:new )?notifications", t):
        return "notifications", {"action": "read"}
    return None


def _pchealth(t: str):
    if re.search(r"\bbattery (?:health|wear|cycles?|cycle count|condition)\b|\bhow (?:worn|healthy) is (?:my |the )?battery\b", t):
        return "pc_health", {"what": "battery"}
    if re.fullmatch(r"(?:check (?:my |the )?)?(?:pc|computer|laptop|system) health(?: check)?|how healthy is (?:my |the )?(?:pc|computer|laptop)"
                    r"|(?:run a )?health check", t):
        return "pc_health", {"what": "all"}
    if re.fullmatch(r"what (?:starts|runs|opens) (?:with windows|at startup|when i (?:start|log in|turn on))|(?:my |list |show )?startup (?:apps|programs)", t):
        return "pc_health", {"what": "startup"}
    if re.fullmatch(r"(?:any|are there) windows updates|is windows up to date|check for (?:windows )?updates|windows update status", t):
        return "pc_health", {"what": "updates"}
    if re.fullmatch(r"is (?:my |the )?(?:antivirus|defender|windows defender|virus protection) (?:on|running|working)"
                    r"|(?:antivirus|virus protection|defender) status", t):
        return "pc_health", {"what": "antivirus"}
    return None


_CAL_DAY = (r"(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|"
            r"\d{1,2}(?:st|nd|rd|th)? (?:of )?(?:january|february|march|april|may|june|july|august|september|october|"
            r"november|december)|(?:january|february|march|april|may|june|july|august|september|october|november|"
            r"december) \d{1,2}(?:st|nd|rd|th)?)")
_CAL_TIME = r"(?:\d{1,2}(?::\d\d)?\s*(?:am|pm|a m|p m)?|noon|midnight)"


def _calendar_add(t: str, raw: str):
    if re.search(r"\blist\b|\bnote\b|\breminder\b|^remind", t):
        return None
    m = re.fullmatch(r"(?:add|put|create|schedule|book|make)\s+(?:an? )?(?:(?:event|meeting|appointment) (?:called|named) |event )?(.+?)"
                     r"(?:\s+(?:to|in|on|into) (?:my |the )?calendar)?"
                     r"\s+((?:(?:on |at |for )?(?:the )?" + _CAL_DAY + r"|at " + _CAL_TIME + r")(?:\s+(?:at |on )?(?:" + _CAL_DAY
                     + r"|" + _CAL_TIME + r"))*)"
                     r"(?:\s+(?:to|in|on|into) (?:my |the )?calendar)?"
                     r"(?:\s+for\s+(.+?(?:hours?|minutes?|mins?)))?(?:\s+at\s+([a-z][\w' ]+))?", t)
    if not m:
        return None
    title, start = m.group(1).strip(), m.group(2).strip()
    if re.search(r"\bto my\b.*\blist$", title) or not title:
        return None
    if not (re.search(r"\b(?:calendar|event|meeting|appointment)\b", t) or t.startswith(("schedule", "book"))
            or re.search(_CAL_TIME + r"|" + _CAL_DAY, start)):
        return None
    title = re.sub(r"\s+(?:to|in|on) (?:my |the )?calendar$", "", title)
    args = {"title": _orig(raw, title), "start": re.sub(r"^(?:on|for) (?:the )?", "", start)}
    if m.group(3):
        args["minutes"] = m.group(3).strip()
    if m.group(4):
        args["location"] = _orig(raw, m.group(4).strip())
    return "calendar_add", args


def _interpreter(t: str):
    if re.fullmatch(r"stop (?:translating|translation|the interpreter|interpreting|interpreter(?: mode)?)|exit (?:translate|interpreter) mode"
                    r"|(?:translate|interpreter) mode off|turn off (?:translate|interpreter) mode", t):
        return "interpreter", {"state": "off"}
    m = re.fullmatch(r"(?:start |turn on )?(?:translate|translation|interpreter) mode(?: (?:in|to|into|for))?(?: ([a-z]+))?"
                     r"|be my ([a-z]+) (?:interpreter|translator)|start translating (?:to|into) ([a-z]+)"
                     r"|translate everything (?:to|into) ([a-z]+)", t)
    if m:
        lang = next((g for g in m.groups() if g), None)
        return "interpreter", {"state": "on", "language": lang} if lang else {"state": "on"}
    return None


_GENERIC_SCORE_WORDS = {"match", "the match", "game", "the game", "today", "today's match", "today's game",
                        "this match", "this game", "live match", "the live match"}


def _scores(t: str):
    if not re.search(r"\b(?:scores?|results?)\b", t):
        return None
    if re.search(r"\b(?:my score|quiz|credit score|exam|test results?|search results?|screen)\b", t):
        return None
    m = re.fullmatch(r"(?:what(?:'s|s| is| are) (?:the )?)?(?:live |latest |today's )?(cricket|football|soccer|sports?)? ?scores?", t)
    if m:
        sport = {"soccer": "football", "sport": None, "sports": None}.get(m.group(1) or "", m.group(1))
        return "scores", {"sport": sport} if sport else {}
    if re.search(r"\b(?:ipl|t20|test match|odi)\b", t):
        return "scores", {"sport": "cricket"}
    m = re.search(r"\b(premier league|champions league|la liga|serie a|bundesliga|ligue 1|isl|indian super league)\b", t)
    if m:
        return "scores", {"sport": "football", "league": m.group(1)}
    m = re.fullmatch(r"(?:what(?:'s|s| is| are) (?:the )?)?(?:live |latest )?(.+?) (?:match )?(?:score|result)s?(?: today| now)?"
                     r"|(?:live )?(?:score|result)s? (?:of|for) (?:the )?(.+?)(?: match| game)?", t)
    if m:
        team = (m.group(1) or m.group(2)).strip()
        if team in _GENERIC_SCORE_WORDS:  # "score of the match": no team named
            return "scores", {}
        if team and len(team.split()) <= 4:
            return "scores", {"team": team}
    return None


def _doctor(t: str):
    if re.fullmatch(r"(?:run a |do a )?full (?:self[ -]?check|check|diagnostics|self test)|check yourself fully", t):
        return "self_check", {"full": True}
    if re.fullmatch(r"check yourself|(?:run a |do a )?self[ -]?(?:check|test)|diagnose yourself|are you working (?:properly|fine|ok)"
                    r"|check your setup|run (?:a )?diagnostics|test yourself", t):
        return "self_check", {}
    return None


# ---------- entry point ----------

def parse(t: str, raw: str, duration):
    """(intent, args) for the new features, or None. `t` = nlu-cleaned text."""
    hit = _recurring(raw)  # "remind me ... every hour" (before one-time reminders and "repeat that")
    if hit:
        return hit
    hit = _corrections(raw)  # "when I say chrome I mean google chrome" (before teach, which would take it)
    if hit:
        return hit
    hit = _teach(raw)  # "when I say X, do Y": the sentence holds other commands, so first
    if hit:
        return hit
    hit = _round7_modules(raw)  # flashcards (before fun's quiz), contacts, habits: each module's own parse
    if hit:
        return hit
    hit = _sleeptimer(t, duration) or _voiceid(t) or _vdesktops(t) or _printer(t, raw) or _filesearch(t, raw)
    if hit:
        return hit
    hit = _security(t, raw) or _triggers(raw) or _history(t) or _screentime(t, duration)
    if hit:
        return hit
    hit = (_expenses(t, raw) or _phone(t, raw) or _generate(t, raw) or _calendar_add(t, raw) or _interpreter(t)
           or _notifications(t) or _pchealth(t) or _doctor(t) or _wakeword(t) or _setup(t)
           or _documents(t, raw) or _maps(t, raw) or _watchers(t, raw) or _fileconvert(t, raw)
           or _airquality(t) or _localmusic(t, raw) or _radio(t, raw))
    if hit:
        return hit
    for rule in (_localai, _meetings, _layouts, _podcasts, _scores,
                 _cliphistory, _ocr, _memos_recorder, _lists, _browser, _lookup, _daily, _spotify, _software,
                 _dictation, _network, _audio, _alerts, _inbox, _agenda, _recent, _smarthome):
        hit = rule(t)
        if hit:
            return hit
    hit = _assistant(t, duration) or _focus(t, duration) or _convert(t, raw)
    return hit


def fun(raw: str):
    """Fun rules (fun.parse). nlu calls this after the core timer/volume rules."""
    try:
        from jarvis.actions import fun as _fun
        return _fun.parse(raw)
    except Exception:
        return None
