"""Everyday skills that work fully offline."""

from __future__ import annotations

import ast
import datetime as dt
import math
import operator
import random
import re

from . import skill

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "Why did the computer go to the doctor? It had a virus.",
    "I told my computer I needed a break, and it said: no problem, I'll go to sleep.",
    "Why was the robot so bad at football? It kept kicking up errors.",
]


@skill("get_time", "Tell the current local time.",
       patterns=[r"(what('s| is) the )?time( is it)?( now)?", r"what time is it( now)?", r"tell me the time", r"current time"])
def get_time(ctx):
    return "It's " + dt.datetime.now().strftime("%I:%M %p").lstrip("0") + "."


@skill("get_date", "Tell today's date and day of the week.",
       patterns=[r"(what('s| is) )?(today'?s? )?(the )?date( today)?", r"what day is (it|today)"])
def get_date(ctx):
    return "Today is " + dt.datetime.now().strftime("%A, %d %B %Y") + "."


@skill("greet", "Reply to a greeting.",
       patterns=[r"(hi|hello|hey|good (morning|afternoon|evening))( there)?( jarvis)?",
                 r"how are you( doing)?( today)?"])
def greet(ctx):
    hour = dt.datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    user = ctx.config["assistant"]["user_name"]
    return f"Good {part}, {user}. All systems are running. How can I help?"


@skill("tell_joke", "Tell a short joke.", patterns=[r"(tell me )?(a )?joke", r"make me laugh"])
def tell_joke(ctx):
    return random.choice(JOKES)


@skill("flip_coin", "Flip a coin or roll a dice.",
       patterns=[r"(flip|toss) a coin", r"roll (a )?(dice|die)"],
       params={"kind": "'coin' or 'dice'"})
def flip_coin(ctx, kind: str = "coin"):
    if "dic" in kind or "die" in kind:
        return f"You rolled a {random.randint(1, 6)}."
    return "It's " + random.choice(["heads", "tails"]) + "."


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
          "log": math.log10, "ln": math.log, "abs": abs, "round": round}
_NAMES = {"pi": math.pi, "e": math.e}
_WORDS = [("plus", "+"), ("minus", "-"), ("times", "*"), ("multiplied by", "*"), ("x", "*"),
          ("divided by", "/"), ("over", "/"), ("to the power of", "**"), ("power", "**"),
          ("mod", "%"), ("square root of", "sqrt"), ("percent of", "/100*")]


def safe_eval(expr: str) -> float:
    """Evaluate a math expression without running any code."""

    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("power too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, ast.Name) and node.id in _NAMES:
            return _NAMES[node.id]
        raise ValueError("unsupported expression")

    return ev(ast.parse(expr, mode="eval").body)


@skill("calculate", "Calculate a math expression, e.g. '12 * (3 + 4)' or 'sqrt(16)'.",
       patterns=[r"(calculate|compute|what('s| is)|solve) (the )?(?=.*\d)(?P<expression>(?:[\d\s.,()+\-*/^%]|pi|sqrt|sin|cos|tan|log|ln|abs|round"
                 r"|plus|minus|times|multiplied by|x|divided by|over|to the power of|power|mod|square root of|percent of)+)"],
       params={"expression": "The math expression"}, required=["expression"])
def calculate(ctx, expression: str):
    expr = " " + expression.lower() + " "
    for word, sym in _WORDS:
        expr = expr.replace(f" {word} ", f" {sym} ")
    expr = expr.replace("^", "**").replace(",", "").strip()
    expr = re.sub(r"\b(sqrt|sin|cos|tan|log|ln|abs|round)\s+([\d.]+)", r"\1(\2)", expr)
    try:
        value = safe_eval(expr)
    except Exception:
        return f"I couldn't calculate '{expression}'."
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 6)
    return f"The answer is {value}."


@skill("help", "List what Jarvis can do.", patterns=[r"help", r"what can you do", r"(list )?(your )?(skills|commands)"])
def help_skill(ctx):
    return (
        "I can: tell the time and date, do math, check the weather, search Wikipedia and the web, "
        "read the news, open apps and websites, play music on YouTube, take screenshots, show system info, "
        "control volume, take notes, keep a to-do list, set timers and reminders, remember facts about you, "
        "tell jokes, and chat about anything using a free local AI."
    )
