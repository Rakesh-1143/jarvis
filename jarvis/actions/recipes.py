"""Recipes and hands-free cook mode (piece BE).

Intents:
  recipe {action: find|random|by_ingredients, query?}                (info)
  cook   {action: start|next|previous|repeat|ingredients|stop|timer|status|goto, name?, step?}

Data: TheMealDB free API (no key). Only urllib + json, no new packages.

Cook mode works like dictation, but other commands still work while cooking:
  "cook butter chicken" -> reads the ingredients, then each "next step", "repeat",
  "previous step", "go to step 3", "ingredients", "stop cooking".
  If a step says "for 10 minutes", Jarvis offers a timer: "start a timer" (or "yes") sets it.

Core wiring (main.py, see wiring-notes/BE-recipes.md):
    if recipes.is_active():
        hit = recipes.match_cook(text)     # ("cook", {...}) for short phrases like "next", else None
"""
from __future__ import annotations

import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 8
API = "https://www.themealdb.com/api/json/v1/1/"
USER_AGENT = "jarvis-assistant/1.0 (personal voice assistant)"
NO_NET = "I can't reach the recipe site right now."
MAX_STEP_CHARS = 260  # long paragraphs are split into steps of about this size

_active = False
_recipe: dict | None = None   # {"name", "ingredients": [str], "steps": [str]}
_index = -1                   # step being read; -1 = ingredients only so far
_timer_offer = 0              # seconds offered for the current step (0 = none)
_last_found: dict | None = None  # last meal from "recipe" (for "cook it")


# ---------- network ----------

def _fetch(endpoint: str, **params) -> dict | None:
    """GET API + endpoint. Returns parsed JSON or None on 404. Other errors raise. Tests replace this."""
    url = API + endpoint + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _meals(data) -> list[dict]:
    meals = (data or {}).get("meals") if isinstance(data, dict) else None
    return [m for m in meals if isinstance(m, dict)] if isinstance(meals, list) else []


_STOP_WORDS = {"a", "an", "the", "some", "recipe", "recipes", "of", "for", "with", "and", "style", "homemade", "easy"}


def _clean_query(text: str) -> str:
    t = re.sub(r"[^\w\s'-]", " ", (text or "").lower())
    t = re.sub(r"^(?:a|an|the|some|me|my)\s+", "", " ".join(t.split()))
    t = re.sub(r"\s+(?:recipe|recipes|please)$", "", t)
    return t.strip()


def search(query: str) -> tuple[dict | None, bool]:
    """Find one meal. Returns (meal, exact). exact=False means a close match was used."""
    q = _clean_query(query)
    if not q:
        return None, False
    found = _meals(_fetch("search.php", s=q))
    if found:
        best = max(found, key=lambda m: difflib.SequenceMatcher(None, q, str(m.get("strMeal", "")).lower()).ratio())
        return best, True
    # nothing for the full name: try single words (longest first), keep the closest name
    words = sorted({w for w in q.split() if w not in _STOP_WORDS and len(w) > 2}, key=len, reverse=True)
    best, score = None, 0.0
    for w in words[:3]:
        for m in _meals(_fetch("search.php", s=w)):
            name = str(m.get("strMeal", "")).lower()
            r = difflib.SequenceMatcher(None, q, name).ratio() + (0.3 if w in name.split() else 0)
            if r > score:
                best, score = m, r
    return (best, False) if best is not None and score >= 0.45 else (None, False)


def _full(meal: dict) -> dict:
    """filter.php gives only id/name; look up the full meal when needed."""
    if meal.get("strInstructions") is not None or not meal.get("idMeal"):
        return meal
    got = _meals(_fetch("lookup.php", i=meal["idMeal"]))
    return got[0] if got else meal


# ---------- recipe parts ----------

def ingredients_of(meal: dict) -> list[str]:
    out = []
    for i in range(1, 21):
        ing = str(meal.get(f"strIngredient{i}") or "").strip()
        if not ing:
            continue
        measure = str(meal.get(f"strMeasure{i}") or "").strip()
        out.append(f"{measure} {ing}".strip() if measure else ing)
    return out


_STEP_LABEL = re.compile(r"^\s*(?:step\s*\d+\s*[:.)-]?|\d+\s*[.)]|[-*•]+)\s*", re.I)


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text) if p.strip()]


def split_steps(instructions: str) -> list[str]:
    """Instructions text -> list of short spoken steps."""
    lines = []
    for line in re.split(r"[\r\n]+", instructions or ""):
        line = _STEP_LABEL.sub("", line).strip()
        if line and re.search(r"[a-zA-Z]{2}", line):  # drop "STEP 1" / "1." only lines
            lines.append(line)
    steps: list[str] = []
    for line in lines:
        if len(line) <= MAX_STEP_CHARS:
            steps.append(line)
            continue
        chunk = ""
        for s in _sentences(line):
            if chunk and len(chunk) + 1 + len(s) > MAX_STEP_CHARS:
                steps.append(chunk)
                chunk = s
            else:
                chunk = f"{chunk} {s}".strip()
        if chunk:
            steps.append(chunk)
    return steps


_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "twenty-five": 25, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True)) + r")"
_TIME = re.compile(
    rf"\b(?:{_NUM}\s*(?:-|to|or|–)\s*)?{_NUM}\s*(?:more\s+)?(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b", re.I)
_HALF_HOUR = re.compile(r"\b(?:half an hour|half hour)\b", re.I)


def _num(word: str | None) -> float | None:
    if word is None:
        return None
    w = word.lower()
    return float(w) if re.match(r"^\d", w) else _NUM_WORDS.get(w)


def step_seconds(step: str) -> int:
    """'simmer for 10-15 minutes' -> 600 (the lower number, so you can check early). 0 = no time."""
    if _HALF_HOUR.search(step or ""):
        return 1800
    m = _TIME.search(step or "")
    if m:
        low, high, unit = _num(m.group(1)), _num(m.group(2)), m.group(3).lower()
        n = low if low is not None else high
        if n:
            size = 3600 if unit.startswith("h") else 1 if unit.startswith("s") else 60
            return int(n * size)
    return 0


def _spoken(seconds: int) -> str:
    if seconds % 3600 == 0:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''}"
    if seconds >= 60 and seconds % 60 == 0:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''}"
    return f"{seconds} seconds"


def _summary(meal: dict) -> str:
    bits = [str(meal.get(k) or "").strip() for k in ("strArea", "strCategory")]
    kind = " ".join(b for b in bits if b and b.lower() != "unknown")
    return f"{meal.get('strMeal', 'That recipe')}" + (f", a {kind} dish" if kind else "")


# ---------- recipe intent (info) ----------

def _remember(meal: dict) -> None:
    global _last_found
    _last_found = meal


def recipe(args: dict) -> str:
    action = str(args.get("action") or "find").lower()
    query = str(args.get("query") or args.get("name") or "").strip()
    try:
        if action == "random":
            got = _meals(_fetch("random.php"))
            if not got:
                return "I couldn't get a recipe right now."
            meal = got[0]
            _remember(meal)
            return f"How about {_summary(meal)}? Say cook it to start."
        if action == "by_ingredients":
            return _by_ingredients(query)
        if not query:
            return "Which recipe should I find?"
        meal, exact = search(query)
        if meal is None:
            return f"I couldn't find a recipe for {query}."
        meal = _full(meal)
        _remember(meal)
        n_ing, n_steps = len(ingredients_of(meal)), len(split_steps(meal.get("strInstructions") or ""))
        lead = "" if exact else f"I couldn't find {query} exactly. The closest is "
        text = f"{lead}{_summary(meal)}." if lead else f"Found {_summary(meal)}."
        return f"{text} It has {n_ing} ingredients and {n_steps} steps. Say cook it to start cook mode."
    except (urllib.error.URLError, OSError, ValueError):
        return NO_NET


def _ingredient_list(text: str) -> list[str]:
    t = re.sub(r"[^\w\s,'-]", " ", (text or "").lower())
    parts = re.split(r"\s*(?:,|\band\b|\bplus\b|&)\s*", t)
    out = []
    for p in parts:
        p = re.sub(r"^(?:some|a|an|the|my|few|of)\s+", "", " ".join(p.split()))
        if p and p not in out:
            out.append(p)
    return out


def _by_ingredient(name: str) -> list[dict]:
    meals = _meals(_fetch("filter.php", i=name.replace(" ", "_")))
    if not meals and name.endswith("s"):  # "eggs" -> "egg", "tomatoes" -> "tomato"
        single = name[:-2] if name.endswith("oes") else name[:-1]
        meals = _meals(_fetch("filter.php", i=single.replace(" ", "_")))
    return meals


def _by_ingredients(text: str) -> str:
    items = _ingredient_list(text)
    if not items:
        return "Which ingredients do you have?"
    lists = [(i, _by_ingredient(i)) for i in items[:4]]
    found = [(i, m) for i, m in lists if m]
    if not found:
        return f"I couldn't find recipes with {_join(items)}."
    ids = set.intersection(*(set(str(x.get("idMeal")) for x in m) for _, m in found))
    first = found[0][1]
    both = [m for m in first if str(m.get("idMeal")) in ids]
    names = [str(m.get("strMeal")) for m in (both or first)][:5]
    if len(both) == 1:
        _remember(both[0])
    if both and len(found) == len(items):
        lead = "You can make" if len(items) > 1 else f"With {items[0]} you can make"
    elif both:
        missing = [i for i, m in lists if not m]
        lead = f"I don't know {_join(missing)}, but with {_join([i for i, _ in found])} you can make"
    else:
        lead = f"Nothing uses all of them. With {found[0][0]} you can make"
    return f"{lead}: {_join(names)}. Say cook and the name to start."


def _join(items: list[str]) -> str:
    items = [str(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


# ---------- cook mode ----------

COOK_TIMEOUT = 45 * 60  # seconds with no cook phrase -> cook mode ends by itself (words like "next" are freed)
_last_use = 0.0
_timed_out = False


def _touch() -> None:
    global _last_use
    _last_use = time.monotonic()


def is_active() -> bool:
    """True while cooking. Ends by itself after COOK_TIMEOUT with no cook phrase."""
    global _active, _recipe, _index, _timer_offer, _timed_out
    if _active and time.monotonic() - _last_use > COOK_TIMEOUT:
        _active, _recipe, _index, _timer_offer = False, None, -1, 0
        _timed_out = True
    return _active


def _ingredients_text() -> str:
    ings = _recipe["ingredients"] if _recipe else []
    return ("You need: " + "; ".join(ings) + ".") if ings else "This recipe has no ingredient list."


def _say_step() -> str:
    global _timer_offer
    steps = _recipe["steps"]
    step = steps[_index]
    head = f"Step {_index + 1} of {len(steps)}: "
    secs = step_seconds(step)
    _timer_offer = secs
    tail = f" Say start a timer for {_spoken(secs)}." if secs else ""
    if _index == len(steps) - 1:
        tail += " That is the last step."
    return head + step + tail


def _start(name: str) -> str:
    global _active, _recipe, _index, _timer_offer
    meal = None
    if name and name.lower() not in ("it", "this", "that", "this one", "that one"):
        try:
            meal, _ = search(name)
            if meal is not None:
                meal = _full(meal)
        except (urllib.error.URLError, OSError, ValueError):
            return NO_NET
        if meal is None:
            return f"I couldn't find a recipe for {name}."
    else:
        meal = _last_found
        if meal is None:
            return "Which dish should we cook?"
        try:
            meal = _full(meal)
        except (urllib.error.URLError, OSError, ValueError):
            return NO_NET
    steps = split_steps(meal.get("strInstructions") or "")
    if not steps:
        return f"{meal.get('strMeal', 'That recipe')} has no steps I can read."
    _remember(meal)
    _recipe = {"name": str(meal.get("strMeal") or name), "ingredients": ingredients_of(meal), "steps": steps}
    _active, _index, _timer_offer = True, -1, 0
    _touch()
    return (f"Cook mode on for {_recipe['name']}. {len(steps)} steps. {_ingredients_text()} "
            "Say next step when you are ready, or stop cooking to finish.")


def stop() -> str:
    global _active, _recipe, _index, _timer_offer
    was = _active
    _active, _recipe, _index, _timer_offer = False, None, -1, 0
    return "Cook mode off. Enjoy your food!" if was else "Cook mode is not on."


def _goto(n: int) -> str:
    global _index
    steps = _recipe["steps"]
    if n < 1 or n > len(steps):
        return f"There are only {len(steps)} steps."
    _index = n - 1
    return _say_step()


def _start_timer() -> str:
    global _timer_offer
    secs = _timer_offer or (step_seconds(_recipe["steps"][_index]) if _index >= 0 else 0)
    if not secs:
        return "This step has no time in it. Say set a timer for, and the minutes."
    from jarvis.actions import timers

    _timer_offer = 0
    return timers.timer({"seconds": secs, "label": f"step {_index + 1}"})


def cook(args: dict) -> str:
    global _index
    action = str(args.get("action") or "start").lower()
    if action == "start":
        return _start(str(args.get("name") or args.get("query") or "").strip())
    if action == "stop":
        return stop()
    if action == "timed_out":
        return "Cook mode ended because it was quiet for a while. Say cook and a dish name to start again."
    if not _active or not _recipe:
        return "Cook mode is not on. Say cook and a dish name to start."
    steps = _recipe["steps"]
    if action == "ingredients":
        return _ingredients_text()
    if action == "next":
        if _index >= len(steps) - 1:
            stop()  # "next" / "done" after the last step: finished, so free everyday words again
            return "That was the last step. Cook mode off. Enjoy your food!"
        _index += 1
        return _say_step()
    if action == "previous":
        if _index <= 0:
            return "This is the first step." if _index == 0 else "We have not started yet. Say next step."
        _index -= 1
        return _say_step()
    if action == "repeat":
        return _say_step() if _index >= 0 else _ingredients_text()
    if action == "goto":
        try:
            return _goto(int(args.get("step")))
        except (TypeError, ValueError):
            return "Which step number?"
    if action == "timer":
        if _index < 0:
            return "We have not started the steps yet. Say next step."
        return _start_timer()
    if action == "status":
        if _index < 0:
            return f"Cooking {_recipe['name']}. Not started yet, {len(steps)} steps to go."
        left = len(steps) - _index - 1
        return f"Cooking {_recipe['name']}. You are on step {_index + 1} of {len(steps)}, {left} left."
    return "Say next step, repeat, previous step, ingredients, or stop cooking."


# ---------- phrases ----------

def _plain(text: str) -> str:
    t = " ".join(re.sub(r"[^\w\s'-]", " ", (text or "").lower()).split())
    t = re.sub(r"^(?:(?:hey\s+)?jarvis|ok(?:ay)?|alright|right|so|and|now|please)\s+", "", t)
    t = re.sub(r"^(?:ok(?:ay)?|alright|now|please)\s+", "", t)
    return re.sub(r"\s+(?:please|jarvis)$", "", t).strip()


_NEXT = {"next", "next step", "next one", "continue", "go on", "go ahead", "carry on", "what's next", "whats next",
         "what next", "then what", "and then", "done", "i'm done", "im done", "finished", "next instruction",
         "move on", "what now", "what do i do next", "and next"}
_PREV = {"previous", "previous step", "go back", "back", "step back", "last one", "one step back", "before that"}
_REPEAT = {"repeat", "repeat that", "repeat step", "repeat the step", "repeat this step", "again", "say again",
           "say that again", "what was that", "come again", "pardon", "once more", "what", "sorry"}
_INGREDIENTS = {"ingredients", "what do i need", "read ingredients", "read the ingredients", "list ingredients",
                "list the ingredients", "what are the ingredients", "ingredient list", "repeat the ingredients"}
_STOP = {"stop cooking", "exit cook mode", "end cook mode", "stop cook mode", "quit cook mode", "end cooking",
         "finish cooking", "i'm done cooking", "im done cooking", "quit cooking", "cook mode off",
         "turn off cook mode", "close the recipe", "stop the recipe"}
_TIMER = {"start a timer", "start the timer", "start timer", "set a timer", "set the timer", "set timer",
          "timer", "timer for this step", "start a timer for this step", "set a timer for this step",
          "time it", "time this", "time this step"}
_STATUS = {"which step", "which step am i on", "what step am i on", "what step is this", "how many steps left",
           "how many steps are left", "where am i", "where was i"}
_YES = {"yes", "yeah", "yep", "sure", "yes please", "do it", "ok", "okay"}
_GOTO = re.compile(r"^(?:go to |jump to |skip to |read )?step (?:number )?(\d+|" + "|".join(
    k for k in _NUM_WORDS if k not in ("a", "an")) + r")$")


def match_cook(text: str) -> tuple[str, dict] | None:
    """While cook mode is on: short cooking phrases -> ("cook", args). Anything else -> None (run normally)."""
    global _timed_out
    t = _plain(text)
    if not is_active():
        if _timed_out and t in (_NEXT | _PREV | _REPEAT):  # say once why "next" did nothing
            _timed_out = False
            return "cook", {"action": "timed_out"}
        return None
    _touch()
    if t in _STOP:
        return "cook", {"action": "stop"}
    if t in _NEXT:
        return "cook", {"action": "next"}
    if t in _PREV:
        return "cook", {"action": "previous"}
    if t in _REPEAT:
        return "cook", {"action": "repeat"}
    if t in _INGREDIENTS:
        return "cook", {"action": "ingredients"}
    if t in _TIMER or (t in _YES and _timer_offer):
        return "cook", {"action": "timer"}
    if t in _STATUS:
        return "cook", {"action": "status"}
    m = _GOTO.match(t)
    if m:
        n = _num(m.group(1))
        return "cook", {"action": "goto", "step": int(n or 0)}
    return None


_DISH = r"(?P<q>[a-z][\w\s'-]{1,60}?)"
_PARSE = [
    (re.compile(r"^(?:start |begin |enter )?cook(?:ing)? mode(?: for " + _DISH + r")?$"), "cook", "start"),
    (re.compile(r"^(?:let's |lets |let us |help me |i want to |i wanna )?cook (?:it|this|that|this one|that one)$"),
     "cook", "start_last"),
    (re.compile(r"^(?:let's |lets |let us |help me |i want to |i wanna )?(?:cook|bake) (?:some |a |an |me )?" + _DISH
                + r"(?: with me)?(?: step by step)?$"), "cook", "start"),
    (re.compile(r"^(?:walk me through|guide me through) (?:making |cooking )?(?:the )?" + _DISH + r"(?: recipe)?$"),
     "cook", "start"),
    (re.compile(r"^(?:give me |suggest |find me |tell me |show me )?(?:a )?random recipe$"), "recipe", "random"),
    (re.compile(r"^(?:suggest|recommend) (?:a recipe|something to cook|a dish|what to cook)$"), "recipe", "random"),
    (re.compile(r"^what should i (?:cook|make) (?:today|tonight|for dinner|for lunch)$"), "recipe", "random"),
    (re.compile(r"^what (?:can|could|should) i (?:make|cook) (?:with|using|from) (?P<q>.+)$"), "recipe",
     "by_ingredients"),
    (re.compile(r"^(?:find |show me |give me )?(?:a )?recipes? (?:with|using) (?P<q>.+)$"), "recipe", "by_ingredients"),
    (re.compile(r"^how (?:do i|do you|to|can i) make " + _DISH + r" recipe$"), "recipe", "find"),
    (re.compile(r"^(?:find |show me |give me |get |search |look up |search for )?(?:me )?(?:a |the )?recipe (?:for|of) "
                + _DISH + r"$"), "recipe", "find"),
    (re.compile(r"^(?:find |show me |give me |get |search |look up |search for )?(?:me )?(?:a |the )?" + _DISH
                + r" recipe$"), "recipe", "find"),
    (re.compile(r"^how (?:do i|do you|to|can i) (?:cook|bake) (?:a |an |some )?" + _DISH + r"$"), "recipe", "find"),
]
# "cook" alone or words that are not dishes
_CMD_VERBS = {"open", "close", "delete", "remove", "save", "print", "copy", "share", "send", "play", "read", "my"}
_NOT_DISH = {"mode", "it", "this", "that", "something", "dinner", "lunch", "breakfast", "food", "the", "a", "now", "today"}


def parse(text: str) -> tuple[str, dict] | None:
    """Phrases for nlu_features (outside cook mode too). Returns (intent, args) or None."""
    t = _plain(text)
    for rx, intent, action in _PARSE:
        m = rx.match(t)
        if not m:
            continue
        q = (m.groupdict().get("q") or "").strip()
        if action == "start_last":
            return "cook", {"action": "start"}
        if intent == "cook":
            if q in _NOT_DISH or (q and q.split()[0] in _CMD_VERBS):
                return None if q not in ("it", "this", "that") else ("cook", {"action": "start"})
            return "cook", ({"action": "start", "name": q} if q else {"action": "start"})
        if action == "random":
            return "recipe", {"action": "random"}
        if not q or q in _NOT_DISH or q.split()[0] in _CMD_VERBS:
            return None
        return "recipe", {"action": action, "query": q}
    return None


# ---------- for the wiring thread ----------

CATALOG: dict[str, dict] = {
    "recipe": {
        "description": "Find a cooking recipe (by dish name), a random recipe idea, or dishes you can make with "
                       "given ingredients. Info only; does not start cooking.",
        "properties": {"action": {"type": "string", "enum": ["find", "random", "by_ingredients"]},
                       "query": {"type": "string", "description": "dish name, or ingredients like 'eggs and tomatoes'"}},
        "required": ["action"],
    },
    "cook": {
        "description": "Hands-free cook mode: start a recipe (reads ingredients), then next/previous/repeat step, "
                       "go to a step, read ingredients, start a timer for the current step, status, or stop cooking.",
        "properties": {"action": {"type": "string", "enum": ["start", "next", "previous", "repeat", "ingredients",
                                                             "stop", "timer", "status", "goto"]},
                       "name": {"type": "string", "description": "dish to cook (start only); empty = last found"},
                       "step": {"type": "integer", "description": "step number (goto only)"}},
        "required": ["action"],
    },
}

HANDLERS = {"recipe": recipe, "cook": cook}
