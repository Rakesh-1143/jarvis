"""Notes, to-do list, timers, reminders and personal memory."""

from __future__ import annotations

import datetime as dt
import re
import threading
import time

from . import skill

UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400}
NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
             "forty five": 45, "fifty": 50, "sixty": 60, "half an": 0.5, "half a": 0.5}


def parse_duration(text: str) -> float | None:
    """'10 minutes', 'an hour and 30 minutes', '1.5 hours' -> seconds."""
    total, found = 0.0, False
    words = "|".join(sorted(map(re.escape, NUM_WORDS), key=len, reverse=True))
    for num, unit in re.findall(rf"(\d+(?:\.\d+)?|{words})\s*(second|sec|minute|min|hour|hr|day)s?\b", text.lower()):
        n = float(num) if num[0].isdigit() else NUM_WORDS[num]
        total += n * UNITS[unit]
        found = True
    return total if found else None


def parse_clock(text: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """'5 pm', '17:30', '7:15 am', 'tomorrow at 9 am' -> next matching datetime."""
    now = now or dt.datetime.now()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b", text.lower())
    if not m or (m.group(2) is None and m.group(3) is None):
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "tomorrow" in text.lower():
        when += dt.timedelta(days=1)
    elif when <= now:
        when += dt.timedelta(days=1)
    return when


def _say_when(due: float) -> str:
    when = dt.datetime.fromtimestamp(due)
    day = "today" if when.date() == dt.date.today() else when.strftime("%A")
    return f"{day} at {when.strftime('%I:%M %p').lstrip('0')}"


# ---------- reminders & timers ----------

@skill("set_reminder", "Set a reminder. 'when' is a duration like '10 minutes' or a clock time like '5 pm'.",
       patterns=[r"remind me (?P<when>(in|after|at|tomorrow) .+?) (to |about )(?P<text>.+)",
                 r"remind me (to |about )?(?P<text>.+?) (?P<when>(in|after|at|tomorrow) .+)"],
       params={"text": "What to remind about", "when": "e.g. 'in 10 minutes' or 'at 5 pm'"},
       required=["text", "when"])
def set_reminder(ctx, text: str, when: str):
    seconds = parse_duration(when)
    if seconds is not None:
        due = time.time() + seconds
    else:
        clock = parse_clock(when)
        if clock is None:
            return f"I didn't understand the time '{when}'. Try 'in 10 minutes' or 'at 5 pm'."
        due = clock.timestamp()
    ctx.memory.add_reminder(text, due)
    return f"Okay, I'll remind you to {text} {_say_when(due)}."


@skill("set_timer", "Start a countdown timer, e.g. '5 minutes'.",
       patterns=[r"(set |start )?(a )?timer (for )?(?P<duration>.+)", r"(set |start )?(a )?(?P<duration>.+?) timer"],
       params={"duration": "e.g. '5 minutes'"}, required=["duration"])
def set_timer(ctx, duration: str):
    seconds = parse_duration(duration)
    if not seconds:
        return f"I didn't understand '{duration}'. Try 'set a timer for 5 minutes'."
    ctx.memory.add_reminder(f"Your {duration} timer is done", time.time() + seconds)
    return f"Timer set for {duration}."


@skill("list_reminders", "List upcoming reminders and timers.",
       patterns=[r"(list|show|what are) (my )?(reminders|timers)", r"(do i have )?any reminders"])
def list_reminders(ctx):
    items = ctx.memory.pending_reminders()
    if not items:
        return "You have no reminders."
    return "Your reminders: " + "; ".join(f"{t} {_say_when(d)}" for _, t, d in items) + "."


def start_scheduler(ctx, interval: float = 1.0) -> threading.Thread:
    """Background thread that speaks reminders when they are due."""

    def loop():
        while not ctx.state.get("stop"):
            now = time.time()
            for rid, text, due in ctx.memory.pending_reminders():
                if due <= now:
                    ctx.memory.mark_fired(rid)
                    msg = text if text.lower().startswith("your ") else f"Reminder: {text}."
                    ctx.notify(msg)
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True, name="jarvis-reminders")
    t.start()
    return t


# ---------- notes ----------

@skill("add_note", "Save a note.",
       patterns=[r"(take|make|write|add) (a )?note( that)?:? (?P<text>.+)", r"note( that)?:? (?P<text>.+)"],
       params={"text": "The note text"}, required=["text"])
def add_note(ctx, text: str):
    ctx.memory.add_note(text)
    return "Noted."


@skill("read_notes", "Read all saved notes.", patterns=[r"(read|show|list) (me )?(my )?notes", r"what are my notes"])
def read_notes(ctx):
    notes = ctx.memory.notes()
    if not notes:
        return "You have no notes."
    return "Your notes: " + " ... ".join(f"{i + 1}. {n}" for i, n in enumerate(notes))


@skill("clear_notes", "Delete all notes.", patterns=[r"(clear|delete|remove) (all )?(my )?notes"])
def clear_notes(ctx):
    ctx.memory.clear_notes()
    return "All notes deleted."


# ---------- to-do list ----------

@skill("add_todo", "Add a task to the to-do list.",
       patterns=[r"add (?P<text>.+?) to (my |the )?(to ?do|task|todo) list", r"(new|add a) (task|to ?do):? (?P<text>.+)"],
       params={"text": "The task"}, required=["text"])
def add_todo(ctx, text: str):
    ctx.memory.add_todo(text)
    return f"Added '{text}' to your to-do list."


@skill("list_todos", "Read the to-do list.",
       patterns=[r"(read|show|list|what('s| is) on) (me )?(my |the )?(to ?do|task|todo)( list)?s?", r"what are my tasks"])
def list_todos(ctx):
    items = ctx.memory.todos()
    if not items:
        return "Your to-do list is empty."
    return "Your to-do list: " + "; ".join(t for _, t in items) + "."


@skill("finish_todo", "Mark a to-do task as done.",
       patterns=[r"mark (?P<text>.+?) as (done|complete|completed|finished)",
                 r"(i )?(finished|done|completed?) (with )?(task )?(?P<text>.+?)",
                 r"(remove|cross off|tick off) (?P<text>.+?) from (my |the )?(to ?do|task|todo) list"],
       params={"text": "Words from the task"}, required=["text"])
def finish_todo(ctx, text: str):
    n = ctx.memory.finish_todo(text)
    return f"Marked {n} task{'s' if n != 1 else ''} as done." if n else f"I couldn't find a task matching '{text}'."


# ---------- personal memory ----------

@skill("remember", "Remember a fact about the user for later.",
       patterns=[r"remember( that)? (?P<fact>.+)", r"(please )?don'?t forget( that)? (?P<fact>.+)"],
       params={"fact": "The fact to remember"}, required=["fact"])
def remember(ctx, fact: str):
    fact = re.sub(r"\bmy\b", "your", re.sub(r"\bi am\b|\bi'm\b", "you are", fact, flags=re.I), flags=re.I)
    ctx.memory.add_fact(fact)
    return f"I'll remember that {fact}."


@skill("recall", "Say everything Jarvis remembers about the user.",
       patterns=[r"what do you (remember|know) about me", r"what did i (tell|ask) you to remember"])
def recall(ctx):
    facts = ctx.memory.facts()
    return ("I remember that " + "; ".join(facts) + ".") if facts else "You haven't told me anything to remember yet."


@skill("forget", "Forget remembered facts that contain a word.",
       patterns=[r"forget (about )?(?P<keyword>.+)"], params={"keyword": "Word in the fact"}, required=["keyword"])
def forget(ctx, keyword: str):
    n = ctx.memory.forget(keyword)
    return f"Forgotten {n} thing{'s' if n != 1 else ''}." if n else f"I don't remember anything about {keyword}."
