"""Voice rules for full system control (settings, files, processes, mouse, keys, screen control).

parse_control(t) takes the CLEANED text from nlu (lower case, no filler) and returns
(intent, args) or None. No imports from nlu, so there is no import loop.

Call parse_early(t) right after nlu._early_rules, and parse_control(t) after the
volume/brightness rules and before _device_rules.
"""
from __future__ import annotations

import re

_FOLDER = r"(?:the\s+|my\s+)?(desktop|documents?|downloads?|pictures|photos|music|videos?|home)(?:\s+folder)?"

# exact phrases -> keys
_SHORTCUTS = [
    (r"copy(?: (?:that|this|it|the text|the selection))?", "ctrl+c"),
    (r"paste(?: (?:that|this|it|here))?", "ctrl+v"),
    (r"cut(?: (?:that|this|it))?", "ctrl+x"),
    (r"undo(?: (?:that|this|it))?", "ctrl+z"),
    (r"redo(?: (?:that|this|it))?", "ctrl+y"),
    (r"select (?:all|everything)", "ctrl+a"),
    (r"save(?: (?:it|this|that|the file|this file|my work))?", "ctrl+s"),
    (r"(?:open )?(?:a )?new tab", "ctrl+t"),
    (r"close (?:the |this )?tab", "ctrl+w"),
    (r"(?:reopen|restore|open) (?:the )?(?:last )?closed tab|reopen (?:the )?(?:last )?tab", "ctrl+shift+t"),
    (r"(?:go to (?:the )?)?next tab", "ctrl+tab"),
    (r"(?:go to (?:the )?)?previous tab", "ctrl+shift+tab"),
    (r"(?:open )?(?:a )?new window", "ctrl+n"),
    (r"refresh|reload|refresh (?:the |this )?page|reload (?:the |this )?page", "f5"),
    (r"zoom in", "ctrl+="),
    (r"zoom out", "ctrl+-"),
    (r"(?:reset zoom|normal zoom|actual size)", "ctrl+0"),
    (r"go back|back", "alt+left"),
    (r"go forward|forward", "alt+right"),
    (r"find on (?:this |the )?page|search (?:on )?this page", "ctrl+f"),
    (r"print(?: (?:this|it|this page))?", "ctrl+p"),
    (r"full ?screen|exit full ?screen", "f11"),
    (r"scroll to (?:the )?top|go to (?:the )?top", "ctrl+home"),
    (r"scroll to (?:the )?bottom|go to (?:the )?bottom", "ctrl+end"),
    (r"page down", "pagedown"),
    (r"page up", "pageup"),
    (r"(?:open )?(?:the )?start menu", "win"),
    (r"(?:open |show )?(?:the )?clipboard(?: history)?", "win+v"),
    (r"(?:open )?(?:the )?emoji(?: panel| picker| keyboard)?", "win+."),
    (r"(?:open )?(?:the )?(?:notification center|notifications panel|action center|quick settings)", "win+a"),
    (r"(?:open )?(?:the )?file explorer|open explorer", "win+e"),
    (r"(?:open )?(?:the )?run (?:box|dialog)", "win+r"),
    (r"lock (?:the )?(?:screen|computer|laptop|pc)", None),  # let the lock rule handle it
]

_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "once": 1, "twice": 2}


def _times(s: str | None) -> int | None:
    if not s:
        return None
    return int(s) if s.isdigit() else _NUM.get(s)


def _amount(rest: str) -> dict:
    if re.search(r"\b(?:a lot|lots|much|more|far|all the way)\b", rest):
        return {"amount": "a lot"}
    if re.search(r"\b(?:a little|a bit|slightly|little)\b", rest):
        return {"amount": "a little"}
    m = re.search(r"\b(\d+)\b", rest)
    return {"amount": int(m.group(1))} if m else {}


def _settings(t: str):
    if re.search(r"\b(?:dark (?:mode|theme))\b", t):
        off = re.search(r"\b(?:off|disable|turn off|stop|remove)\b", t)
        return "dark_mode", {"state": "off" if off else "on"}
    if re.search(r"\blight (?:mode|theme)\b", t) and not re.search(r"\bnight light\b", t):
        off = re.search(r"\b(?:off|disable)\b", t)
        return "dark_mode", {"state": "on" if off else "off"}
    if re.search(r"\bnight light\b|\bblue light\b", t):
        return "open_settings", {"page": "night light"}
    if re.search(r"\b(?:power saver|battery saver|power saving|save (?:power|battery)|low power mode)\b", t):
        off = re.search(r"\b(?:off|disable|stop)\b", t)
        return "power_plan", {"plan": "balanced" if off else "power_saver"}
    if re.search(r"\b(?:high performance|performance mode|best performance|max(?:imum)? performance|full power)\b", t):
        return "power_plan", {"plan": "high_performance"}
    if re.search(r"\bbalanced (?:mode|power|plan)\b|\bpower plan (?:to )?balanced\b", t):
        return "power_plan", {"plan": "balanced"}
    if re.fullmatch(r"(?:turn|switch|shut) off (?:the )?(?:screen|display|monitor)|(?:screen|display|monitor) off", t):
        return "screen_off", {}
    # Turning DND / focus on and off is the dnd and focus intents (nlu_features). Only the settings page is here.
    if re.search(r"\b(?:do not disturb|don't disturb|focus(?: mode| assist| session)?|notifications?)\b", t) \
            and re.search(r"\bsettings?\b", t):
        return "open_settings", {"page": "notifications"}
    m = re.fullmatch(r"(?:open|show|go to|change|launch)\s+(?:the\s+|my\s+)?(.+?)\s+settings|settings for (.+)", t)
    if m:
        page = (m.group(1) or m.group(2)).strip()
        if not re.search(r"\b(?:wi ?-?fi|wireless|blue ?tooth)\b", page):  # wifi/bluetooth have their own rules
            return "open_settings", {"page": page}
    m = re.fullmatch(r"(?:open|show|launch)\s+(?:the\s+)?(control panel|device manager)", t)
    if m:
        return "open_settings", {"page": m.group(1)}
    return None


def _processes(t: str):
    if re.search(r"\b(?:what(?:'s| is)?|which)\b.*\b(?:using|eating|hogging|slowing)\b.*\b(?:cpu|processor)\b", t):
        return "processes", {"sort": "cpu"}
    if re.search(r"\b(?:what(?:'s| is)?|which)\b.*\b(?:using|eating|hogging)\b.*\b(?:ram|memory)\b", t):
        return "processes", {"sort": "memory"}
    if re.search(r"\b(?:what(?:'s| is)? slowing (?:down )?(?:my|the) (?:computer|laptop|pc))\b", t):
        return "processes", {"sort": "cpu"}
    if re.search(r"\b(?:what|which|list|show)\b.*\b(?:apps|programs|processes)\b.*\b(?:running|open)\b", t):
        return "processes", {"sort": "memory"}
    m = re.fullmatch(r"(?:kill|end|terminate|force (?:close|quit|stop))\s+(?:the\s+)?(?:process|task|program)\s+(.+)"
                     r"|end task (?:on |for )?(.+)|force (?:close|quit) (.+)", t)
    if m:
        return "kill_process", {"name": next(g for g in m.groups() if g).strip()}
    return None


def _files(t: str):
    m = re.fullmatch(r"(?:create|make)\s+(?:a\s+)?(?:new\s+)?(folder|directory|file|text file|document)"
                     r"(?:\s+(?:called|named))?\s+(.+?)(?:\s+(?:on|in)\s+" + _FOLDER + r")?", t)
    if m:
        kind = "folder" if m.group(1) in ("folder", "directory") else "file"
        args = {"kind": kind, "name": m.group(2).strip()}
        if m.group(3):
            args["where"] = m.group(3)
        return "create_item", args
    m = re.fullmatch(r"(copy|move)\s+(?:the\s+|my\s+)?(?:file|folder|document)\s+(?:called\s+|named\s+)?(.+?)"
                     r"\s+(?:to|into)\s+(?:the\s+|my\s+)?(.+?)(?:\s+folder)?", t)
    if m:
        return ("copy_file" if m.group(1) == "copy" else "move_file"), {"name": m.group(2).strip(), "to": m.group(3).strip()}
    m = re.fullmatch(r"rename\s+(?:the\s+|my\s+)?(?:file|folder|document)?\s*(?:called\s+|named\s+)?(.+?)\s+(?:to|as)\s+(.+)", t)
    if m:
        return "rename_file", {"name": m.group(1).strip(), "new_name": m.group(2).strip()}
    m = re.fullmatch(r"(?:delete|remove|trash|bin)\s+(?:the\s+|my\s+)?(?:file|folder|document)\s+(?:called\s+|named\s+)?(.+)", t)
    if m:
        return "delete_file", {"name": m.group(1).strip()}
    return None


def _input(t: str):
    m = re.fullmatch(r"(?:press|hit|push|tap)\s+(?:the\s+)?(.+?)(?:\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
                     r"\s+times|\s+(once|twice))?", t)
    if m:
        args = {"keys": re.sub(r"\s+(?:key|keys|button)$", "", m.group(1))}
        n = _times(m.group(2) or m.group(3))
        if n and n > 1:
            args["times"] = n
        return "press_keys", args
    for pattern, keys in _SHORTCUTS:
        if re.fullmatch(pattern, t):
            return ("press_keys", {"keys": keys}) if keys else None
    m = re.fullmatch(r"(left |right |double |middle )?click(?:\s+(?:on\s+)?(?:the\s+)?(.+?))?(?:\s+button)?", t)
    if m:
        kind = (m.group(1) or "").strip()
        target = (m.group(2) or "").strip()
        if target in ("", "here", "it", "this", "that", "there", "mouse", "the mouse"):
            return "mouse", {"action": {"": "click", "left": "click", "right": "right_click", "double": "double_click",
                                        "middle": "middle_click"}[kind]}
        args = {"text": target}
        if kind in ("right", "double"):
            args["button"] = kind
        return "click_text", args
    m = re.fullmatch(r"scroll(?:\s+(up|down|left|right))?(.*)", t)
    if m:
        return "mouse", {"action": "scroll", "direction": m.group(1) or "down", **_amount(m.group(2))}
    m = re.fullmatch(r"move (?:the )?(?:mouse|cursor|pointer)(?: to the)? (center|centre|middle)(?: of the screen)?", t)
    if m:
        return "mouse", {"action": "center"}
    m = re.fullmatch(r"move (?:the )?(?:mouse|cursor|pointer) (up|down|left|right)(.*)", t)
    if m:
        return "mouse", {"action": "move", "direction": m.group(1), **_amount(m.group(2))}
    return None


def _screen_control(t: str):
    m = re.fullmatch(r"(?:take (?:control|over)|control (?:my|the) (?:screen|computer|pc|laptop))"
                     r"(?: of (?:my|the) (?:screen|computer|pc|laptop))?(?:\s+and|\s+to)?\s+(.+)"
                     r"|(?:use|on) (?:my|the) screen (?:to|and)\s+(.+)|do (?:this|it) on (?:my|the) screen\s*(.+)", t)
    if m:
        return "computer_use", {"task": next(g for g in m.groups() if g).strip()}
    return None


def parse_early(t: str):
    """'take control and ...' -> computer_use. Call right after nlu._early_rules, so words like
    'restart' or 'lock' inside the task don't trigger the power rules."""
    return _screen_control(t) if t else None


def parse_control(t: str):
    """(intent, args) or None."""
    if not t:
        return None
    for rule in (_screen_control, _settings, _processes, _files, _input):
        hit = rule(t)
        if hit:
            return hit
    return None
