"""Fun: coin, dice, random number, pick one, rock-paper-scissors, quick quiz.

All offline. Says:
  "flip a coin", "roll a dice", "roll 2 dice", "roll a 20 sided die",
  "random number between 1 and 50", "pick one: pizza or pasta",
  "rock paper scissors" / "I choose rock",
  "quiz me" / "ask me a question", then the answer ("Paris", "42"),
  "skip", "what's my score", "stop the quiz".

Intents:
  random_pick {kind: coin|dice|number|choice|rps, sides?, count?, low?, high?, options?, move?}
  quiz {action?: start|answer|skip|score|stop, answer?}

Wiring (one thread does this):
  - merge CATALOG and HANDLERS; nothing is risky.
  - nlu: `fun.parse(text)` returns (intent, args) or None; call it with the other
    early feature rules.
  - core: while `fun.quiz_pending()` is True, send the next heard text as
    Command("quiz", {"action": "answer", "answer": text}) unless nlu matched
    "stop"/"skip"/"score" itself (parse() already handles those words).
"""
from __future__ import annotations

import random
import re
import threading
import time

_rng = random.SystemRandom()
_lock = threading.Lock()

MAX_DICE = 10
MAX_SIDES = 1000
MAX_OPTIONS = 20
QUIZ_TIMEOUT = 120  # seconds a question stays open

_NUM_WORDS = {
    "zero": 0, "a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "pair of": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "a hundred": 100, "one hundred": 100, "thousand": 1000,
    "a thousand": 1000, "one thousand": 1000,
}


def _num(value, default: int | None = None) -> int | None:
    """Int from 5, "5", "five", "d20"; default if not a number."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().lstrip("d")
    try:
        return int(float(text))
    except ValueError:
        pass
    if text in _NUM_WORDS:
        return _NUM_WORDS[text]
    parts = text.replace("-", " ").split()
    if len(parts) == 2 and parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS:
        tens, ones = _NUM_WORDS[parts[0]], _NUM_WORDS[parts[1]]
        if tens % 10 == 0 and tens >= 20 and 0 < ones < 10:
            return tens + ones
    return default


def _clamp(n: int, low: int, high: int) -> int:
    return max(low, min(high, n))


# ---------- random picks ----------
def _coin(args: dict) -> str:
    count = _clamp(_num(args.get("count"), 1) or 1, 1, MAX_DICE)
    flips = [_rng.choice(("heads", "tails")) for _ in range(count)]
    if count == 1:
        return f"It's {flips[0]}."
    heads = flips.count("heads")
    return f"{', '.join(flips).capitalize()}. That's {heads} heads and {count - heads} tails."


def _dice(args: dict) -> str:
    sides = _clamp(_num(args.get("sides"), 6) or 6, 2, MAX_SIDES)
    count = _clamp(_num(args.get("count"), 1) or 1, 1, MAX_DICE)
    rolls = [_rng.randint(1, sides) for _ in range(count)]
    if count == 1:
        return f"You rolled a {rolls[0]}."
    return f"You rolled {', '.join(map(str, rolls))}. Total {sum(rolls)}."


def _number(args: dict) -> str:
    low = _num(args.get("low"), 1)
    high = _num(args.get("high"), 100)
    if low is None:
        low = 1
    if high is None:
        high = 100
    if low > high:
        low, high = high, low
    return f"{_rng.randint(low, high)}."


def split_options(text) -> list[str]:
    """'pizza, pasta or burger' -> ['pizza', 'pasta', 'burger']."""
    if isinstance(text, (list, tuple)):
        items = [str(i) for i in text]
    else:
        items = re.split(r"\s*(?:,|;|/|\bor\b|\band\b|\bversus\b|\bvs\.?)\s*", str(text or ""), flags=re.I)
    out, seen = [], set()
    for item in items:
        item = item.strip(" .?!'\"").strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out[:MAX_OPTIONS]


def _choice(args: dict) -> str:
    options = split_options(args.get("options"))
    if len(options) < 2:
        return "Give me at least two things to pick from, like 'pick one: pizza or pasta'."
    return f"I pick {_rng.choice(options)}."


_RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
_RPS_ALIASES = {"rock": "rock", "stone": "rock", "paper": "paper", "scissor": "scissors",
                "scissors": "scissors", "sissors": "scissors"}


def _rps(args: dict) -> str:
    mine = _rng.choice(list(_RPS_BEATS))
    move = _RPS_ALIASES.get(str(args.get("move") or "").strip().lower())
    if not move:
        return f"I choose {mine}."
    if move == mine:
        return f"I chose {mine} too. It's a tie."
    if _RPS_BEATS[move] == mine:
        return f"I chose {mine}. {move.capitalize()} beats {mine}, you win!"
    return f"I chose {mine}. {mine.capitalize()} beats {move}, I win!"


_KINDS = {"coin": _coin, "dice": _dice, "die": _dice, "number": _number,
          "choice": _choice, "rps": _rps}


def random_pick(args: dict) -> str:
    kind = str(args.get("kind") or "").strip().lower()
    if not kind:
        kind = "choice" if args.get("options") else "number"
    fn = _KINDS.get(kind)
    if fn is None:
        return "I can flip a coin, roll dice, pick a number, or pick one from a list."
    return fn(args)


# ---------- quiz ----------
# (question, accepted answers). First answer is the one spoken.
GK_QUESTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("What is the capital of France?", ("Paris",)),
    ("What is the capital of Japan?", ("Tokyo",)),
    ("What is the capital of Australia?", ("Canberra",)),
    ("What is the capital of India?", ("New Delhi", "Delhi")),
    ("What is the capital of Canada?", ("Ottawa",)),
    ("What is the capital of Italy?", ("Rome",)),
    ("Which planet is known as the red planet?", ("Mars",)),
    ("What is the largest planet in our solar system?", ("Jupiter",)),
    ("Which planet is closest to the sun?", ("Mercury",)),
    ("How many continents are there?", ("7", "seven")),
    ("How many days are in a leap year?", ("366",)),
    ("How many legs does a spider have?", ("8", "eight")),
    ("What is the largest ocean on Earth?", ("Pacific", "Pacific Ocean")),
    ("What is the tallest mountain in the world?", ("Mount Everest", "Everest")),
    ("What is the longest river in the world?", ("Nile", "the Nile", "Amazon")),
    ("What gas do plants take in from the air?", ("carbon dioxide", "CO2")),
    ("What is the chemical symbol for gold?", ("Au",)),
    ("What is the chemical symbol for water?", ("H2O", "h 2 o")),
    ("What is the boiling point of water in Celsius?", ("100", "one hundred")),
    ("What is the freezing point of water in Celsius?", ("0", "zero")),
    ("Who wrote Romeo and Juliet?", ("Shakespeare", "William Shakespeare")),
    ("Who painted the Mona Lisa?", ("Leonardo da Vinci", "da Vinci", "Leonardo")),
    ("Who developed the theory of relativity?", ("Albert Einstein", "Einstein")),
    ("What is the hardest natural substance?", ("diamond",)),
    ("What is the largest mammal?", ("blue whale", "whale")),
    ("What is the fastest land animal?", ("cheetah",)),
    ("How many colours are in a rainbow?", ("7", "seven")),
    ("How many sides does a hexagon have?", ("6", "six")),
    ("How many minutes are in an hour?", ("60", "sixty")),
    ("How many hours are in a day?", ("24", "twenty four")),
    ("What is the smallest prime number?", ("2", "two")),
    ("Which organ pumps blood around the body?", ("heart", "the heart")),
    ("What is the largest organ of the human body?", ("skin", "the skin")),
    ("How many bones are in the adult human body?", ("206",)),
    ("Which country has the largest population?", ("India",)),
    ("Which is the largest country by area?", ("Russia",)),
    ("What currency is used in Japan?", ("yen", "Japanese yen")),
    ("What is the main language spoken in Brazil?", ("Portuguese",)),
    ("In which country are the pyramids of Giza?", ("Egypt",)),
    ("What is the national animal of India?", ("tiger", "Bengal tiger")),
    ("Which planet has the most famous rings?", ("Saturn",)),
    ("What do bees make?", ("honey",)),
    ("What is the square root of 81?", ("9", "nine")),
    ("How many players are on a football team on the field?", ("11", "eleven")),
    ("How many players are in a cricket team?", ("11", "eleven")),
]

_QUIZ_STATE: dict = {"question": None, "answers": (), "asked_at": 0.0, "right": 0, "asked": 0}


def _maths_question() -> tuple[str, tuple[str, ...]]:
    op = _rng.choice("+-x")
    if op == "+":
        a, b = _rng.randint(2, 99), _rng.randint(2, 99)
        return f"What is {a} plus {b}?", (str(a + b),)
    if op == "-":
        a, b = _rng.randint(10, 99), _rng.randint(1, 9)
        a, b = max(a, b), min(a, b)
        return f"What is {a} minus {b}?", (str(a - b),)
    a, b = _rng.randint(2, 12), _rng.randint(2, 12)
    return f"What is {a} times {b}?", (str(a * b),)


def _norm(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\b(it's|it is|is it|the answer is|answer is|i think|maybe|i guess|um+|uh+)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"^\s*(the|a|an)\s+", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def _is_right(heard: str, answers: tuple[str, ...]) -> bool:
    said = _norm(heard)
    if not said:
        return False
    words = said.split()
    num = _num(said) if len(words) <= 2 else None
    for ans in answers:
        a = _norm(ans)
        if said == a or (num is not None and str(num) == a):
            return True
        if a.isdigit():
            # numbers: match a whole word, e.g. "I think 42"
            if a in words:
                return True
        elif re.search(rf"\b{re.escape(a)}\b", said):
            return True
    return False


def quiz_pending() -> bool:
    """True while a quiz question waits for an answer (and has not timed out)."""
    q = _QUIZ_STATE
    return bool(q["question"]) and time.time() - q["asked_at"] < QUIZ_TIMEOUT


def _new_question(kind: str | None = None) -> str:
    if kind == "maths" or (kind != "gk" and _rng.random() < 0.3):
        question, answers = _maths_question()
    else:
        question, answers = _rng.choice(GK_QUESTIONS)
    _QUIZ_STATE.update(question=question, answers=answers, asked_at=time.time())
    _QUIZ_STATE["asked"] += 1
    return question


def _score() -> str:
    q = _QUIZ_STATE
    return f"You got {q['right']} out of {q['asked']}."


def quiz(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower()
    answer = args.get("answer")
    if not action:
        action = "answer" if answer and quiz_pending() else "start"
    kind = str(args.get("topic") or "").strip().lower() or None
    if kind in ("math", "mathematics", "maths", "sums"):
        kind = "maths"
    elif kind:
        kind = "gk"
    with _lock:
        if action == "score":
            return _score() if _QUIZ_STATE["asked"] else "We haven't played a quiz yet."
        if action == "stop":
            done = _score() if _QUIZ_STATE["asked"] else ""
            _QUIZ_STATE.update(question=None, answers=(), right=0, asked=0)
            return f"Quiz over. {done}".strip()
        if action == "skip":
            if not quiz_pending():
                return "Here's one. " + _new_question(kind)
            told = _QUIZ_STATE["answers"][0]
            return f"The answer was {told}. Next: " + _new_question(kind)
        if action == "answer":
            if not quiz_pending():
                _QUIZ_STATE.update(question=None)
                return "There's no question waiting. Say 'quiz me' to start."
            answers = _QUIZ_STATE["answers"]
            if _is_right(str(answer or ""), answers):
                _QUIZ_STATE["right"] += 1
                head = "Correct!"
            else:
                head = f"Not quite. It's {answers[0]}."
            return f"{head} {_score()} Next: " + _new_question(kind)
        # start
        if not quiz_pending():
            _QUIZ_STATE.update(right=0, asked=0)
        return "Quiz time. Say 'stop the quiz' to end. " + _new_question(kind)


# ---------- phrase parser (for nlu wiring) ----------
_N = r"(\d+|[a-z]+(?: of)?)"


def parse(text: str) -> tuple[str, dict] | None:
    """Spoken text -> (intent, args) for fun commands, else None."""
    t = re.sub(r"\s+", " ", str(text or "").lower()).strip(" .?!")
    t = re.sub(r"^(jarvis,? |hey jarvis,? |please |can you |could you |let's |lets )+", "", t)
    if not t:
        return None

    # quiz control first, so "stop" works while a quiz runs
    if re.search(r"\b(stop|end|quit|exit|finish|cancel)\b.*\bquiz\b|^(stop|quit|end) (the )?(game|quiz)$", t):
        return "quiz", {"action": "stop"}
    if re.search(r"\b(my )?score\b", t) and ("quiz" in t or quiz_pending() or "my score" in t):
        return "quiz", {"action": "score"}
    if quiz_pending() and re.fullmatch(r"(skip|pass|next|next question|i don't know|i dont know|no idea|skip (it|this|this one|this question))", t):
        return "quiz", {"action": "skip"}
    m = re.search(r"\b(quiz me|start (a |the )?quiz|give me a quiz|play (a )?quiz|ask me (a )?(question|quiz)|"
                  r"(math|maths) quiz|general knowledge quiz|gk quiz|trivia)\b", t)
    if m:
        topic = "maths" if re.search(r"\b(math|maths|sums)\b", t) else ("gk" if re.search(r"\b(gk|general knowledge|trivia)\b", t) else None)
        args: dict = {"action": "start"}
        if topic:
            args["topic"] = topic
        return "quiz", args

    if re.search(r"\b(flip|toss) (a |the |\w+ )?coins?\b|\bheads or tails\b", t):
        m = re.search(rf"\b(flip|toss) {_N} coins\b", t)
        return "random_pick", {"kind": "coin", "count": _num(m.group(2), 1) if m else 1}

    if re.search(r"\b(roll|throw|toss)\b.*\b(dice|dies|die|d\d+|\d+d\d+)\b|^roll( the| a)?( dice| die)?$|\bdice roll\b", t):
        args = {"kind": "dice"}
        m = re.search(r"\bd(\d+)\b", t) or re.search(rf"\b{_N}[- ]sided\b", t)
        if m:
            args["sides"] = _num(m.group(1), 6)
        m = re.search(rf"\broll {_N} (?:\w+[- ]sided )?(?:dice|dies|die)\b", t)
        if m and m.group(1) not in ("a", "the", "an"):
            args["count"] = _num(m.group(1), 1)
        m = re.search(r"\b(\d+)d(\d+)\b", t)
        if m:
            args["count"], args["sides"] = int(m.group(1)), int(m.group(2))
        return "random_pick", args

    if re.search(r"\brock,? paper,? (and )?scissors?\b", t):
        return "random_pick", {"kind": "rps"}
    m = re.fullmatch(r"(i (choose|pick|play|go with|throw)|my move is) (rock|paper|scissors?|stone)", t)
    if m:
        return "random_pick", {"kind": "rps", "move": m.group(3)}

    if re.search(r"\brandom number\b|\bpick a number\b|\bnumber between\b", t):
        args = {"kind": "number"}
        m = re.search(r"\b(?:between|from)\s+(-?\d+)\s+(?:and|to)\s+(-?\d+)", t)
        if m:
            args["low"], args["high"] = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r"\b(?:up to|to|under|below)\s+(\d+)", t)
            if m:
                args["low"], args["high"] = 1, int(m.group(1))
        return "random_pick", args

    m = re.match(r"(?:pick|choose|select) (?:one|for me|one for me|between|from|either)\s*:?\s*(.+)", t) \
        or re.match(r"(?:help me )?(?:decide|choose) between (.+)", t) \
        or re.match(r"should i (?:have|get|eat|watch|play|do|pick|choose|go with) (.+ or .+)", t)
    if m:
        options = split_options(m.group(1))
        if len(options) >= 2:
            return "random_pick", {"kind": "choice", "options": options}
    return None


# ---------- catalog ----------
_INT = {"type": "integer"}

CATALOG: dict[str, dict] = {
    "random_pick": {
        "description": "Random fun: flip coin(s), roll dice (any sides/count), random number in a range, "
                       "pick one option from a list, or play rock-paper-scissors.",
        "properties": {
            "kind": {"type": "string", "enum": ["coin", "dice", "number", "choice", "rps"]},
            "sides": {**_INT, "description": "Dice sides, default 6."},
            "count": {**_INT, "description": "How many dice or coins, default 1, max 10."},
            "low": {**_INT, "description": "Lowest number, default 1."},
            "high": {**_INT, "description": "Highest number, default 100."},
            "options": {"type": "array", "items": {"type": "string"}, "description": "Things to pick from (kind=choice)."},
            "move": {"type": "string", "enum": ["rock", "paper", "scissors"], "description": "User's move (kind=rps)."},
        },
        "required": ["kind"],
    },
    "quiz": {
        "description": "Offline quiz game (general knowledge and maths). start asks a question; answer checks "
                       "the user's answer and asks the next; skip, score, stop.",
        "properties": {
            "action": {"type": "string", "enum": ["start", "answer", "skip", "score", "stop"]},
            "answer": {"type": "string", "description": "User's answer (action=answer)."},
            "topic": {"type": "string", "enum": ["gk", "maths"], "description": "Optional question type."},
        },
        "required": [],
    },
}

HANDLERS = {
    "random_pick": random_pick,
    "quiz": quiz,
}
