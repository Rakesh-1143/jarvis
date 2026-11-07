"""Offline calculator: safe maths from spoken words ("15 percent of 2400", "square root of 81")."""
from __future__ import annotations

import ast
import math
import operator
import re

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "million": 10**6, "crore": 10**7, "billion": 10**9}


def words_to_digits(text: str) -> str:
    """'two hundred and fifty plus three point five' -> '250 plus 3.5'."""
    out: list[str] = []
    total = cur = 0
    in_num = False
    decimals: str | None = None

    def flush():
        nonlocal total, cur, in_num, decimals
        if in_num:
            s = str(total + cur)
            if decimals:
                s += "." + decimals
            out.append(s)
        total = cur = 0
        in_num = False
        decimals = None

    words = text.split()
    for i, w in enumerate(words):
        if decimals is not None and w in _ONES and _ONES[w] < 10:
            decimals += str(_ONES[w])
            continue
        if w in _ONES:
            cur += _ONES[w]
            in_num = True
        elif w in _TENS:
            cur += _TENS[w]
            in_num = True
        elif w in _SCALES and in_num:
            if _SCALES[w] == 100:
                cur *= 100
            else:
                total += cur * _SCALES[w]
                cur = 0
        elif w == "and" and in_num and i + 1 < len(words) and (words[i + 1] in _ONES or words[i + 1] in _TENS):
            continue
        elif w == "point" and in_num and decimals is None:
            decimals = ""
        else:
            flush()
            out.append(w)
    flush()
    return " ".join(out)


# spoken phrase -> python operator (longest first)
_PHRASES = [
    (r"\bto the power of\b|\braised to\b|\bpower\b", "**"),
    (r"\bmultiplied by\b|\btimes\b|\binto\b|\bx\b", "*"),
    (r"\bdivided by\b|\bover\b|/", "/"),
    (r"\bplus\b|\badd\b|\band\b", "+"),
    (r"\bminus\b|\bless\b|\bsubtract\b", "-"),
    (r"\bmod(?:ulo)?\b", "%"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
]

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("too big")
        out = _OPS[type(node.op)](left, right)
        if isinstance(out, int) and abs(out) > 10 ** 1000:  # stops ((9**99)**99)**99 from freezing Jarvis
            raise ValueError("too big")
        return out
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
        return _FUNCS[node.func.id](_eval(node.args[0]))
    raise ValueError("not maths")


def to_expression(text: str) -> str | None:
    """Spoken maths -> python expression, or None if it isn't maths."""
    t = words_to_digits(text.lower().replace(",", ""))
    t = re.sub(r"^(?:what(?:'s| is)|calculate|compute|how much is|solve)\s+", "", t).strip(" ?")
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+", r"(\1/100)*", t)
    t = re.sub(r"\bsquare root of\s+(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    for pat, op in _PHRASES:
        t = re.sub(pat, f" {op} ", t)
    t = re.sub(r"\s+", "", t)
    if not re.fullmatch(r"[\d.+\-*/%()]+", t.replace("sqrt(", "(")) or not re.search(r"\d", t) or not re.search(r"[+\-*/%]|sqrt", t):
        return None
    return t


def evaluate(expression: str) -> float:
    return _eval(ast.parse(expression, mode="eval"))


def _fmt(n: float) -> str:
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, int):
        return f"{n:,}".replace(",", " ") if abs(n) >= 10000 else str(n)
    return f"{n:.4f}".rstrip("0").rstrip(".")


def calculate(args: dict) -> str:
    expr = args.get("expression") or ""
    try:
        result = evaluate(expr)
    except ZeroDivisionError:
        return "You can't divide by zero."
    except Exception:
        return "I couldn't work that out."
    return f"The answer is {_fmt(result)}."
