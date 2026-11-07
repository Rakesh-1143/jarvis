"""Expense tracker, saved in a CSV file (open it in Excel any time).

Says: "I spent 250 on lunch", "add expense 500 for petrol",
"how much did I spend today / this week / this month",
"how much on food this month", "delete last expense".

File: config `expenses_file` (default "~/Documents/Jarvis expenses.csv").
Columns: date, amount, category, note. Date is local time "YYYY-MM-DD HH:MM".
Currency: config `currency` (default "₹").
Wiring: merge CATALOG and HANDLERS. Nothing is risky.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import threading

DEFAULT_FILE = "~/Documents/Jarvis expenses.csv"
DEFAULT_CURRENCY = "₹"
EXPENSES_FILE = ""  # empty = read config on first use
CURRENCY = ""       # empty = read config on first use
FIELDS = ["date", "amount", "category", "note"]
CATEGORIES = ("food", "travel", "shopping", "bills", "other")
_lock = threading.Lock()

# Word -> category (used to guess the category from the note).
_WORDS = {
    "food": "food lunch dinner breakfast brunch snack snacks coffee tea chai juice pizza burger biryani "
            "restaurant cafe hotel meal meals groceries grocery vegetables veggies fruit fruits milk "
            "swiggy zomato dominos mcdonalds kfc sweets icecream ice-cream drinks bakery",
    "travel": "travel uber ola rapido taxi cab auto rickshaw bus train metro flight ticket tickets "
              "petrol diesel fuel gas-station parking toll trip",
    "shopping": "shopping clothes shirt shirts jeans shoes dress amazon flipkart myntra gift gifts "
                "gadget phone-case headphones book books watch bag",
    "bills": "bill bills rent electricity current water wifi internet broadband recharge mobile "
             "emi loan insurance fees fee subscription netflix spotify maintenance gas",
}
_GUESS = {w: cat for cat, words in _WORDS.items() for w in words.split()}
_CAT_ALIASES = {"bill": "bills", "groceries": "food", "grocery": "food", "transport": "travel",
                "fuel": "travel", "petrol": "travel", "shop": "shopping", "misc": "other",
                "others": "other", "miscellaneous": "other"}


# ---------- config + storage ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        return load_config() or {}
    except Exception:
        return {}


def _path() -> str:
    global EXPENSES_FILE
    if not EXPENSES_FILE:
        EXPENSES_FILE = _cfg().get("expenses_file") or DEFAULT_FILE
    return os.path.expanduser(EXPENSES_FILE)


def _cur() -> str:
    global CURRENCY
    if not CURRENCY:
        CURRENCY = str(_cfg().get("currency") or DEFAULT_CURRENCY)
    return CURRENCY


def _load() -> list[dict]:
    rows: list[dict] = []
    try:
        with open(_path(), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    amount = float(r.get("amount") or "")
                    when = dt.datetime.strptime((r.get("date") or "").strip()[:16], "%Y-%m-%d %H:%M")
                except ValueError:
                    continue  # skip broken lines (e.g. edited by hand)
                rows.append({"date": when, "amount": amount,
                             "category": _unsafe_cell((r.get("category") or "other").strip().lower()) or "other",
                             "note": _unsafe_cell((r.get("note") or "").strip())})
    except OSError:
        pass
    return rows


def _safe_cell(text: str) -> str:
    """Excel runs a cell that starts with = + - @ as a formula. A leading ' makes it plain text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _unsafe_cell(text: str) -> str:
    return text[1:] if text[:1] == "'" and text[1:2] in ("=", "+", "-", "@", "\t", "\r") else text


def _row_out(r: dict) -> dict:
    return {"date": r["date"].strftime("%Y-%m-%d %H:%M"), "amount": _num(r["amount"]),
            "category": _safe_cell(r["category"]), "note": _safe_cell(r["note"])}


def _append(row: dict) -> None:
    path = _path()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    # A new file starts with a BOM so Excel shows Hindi and other letters correctly.
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(_row_out(row))


# ---------- text helpers ----------
def _num(x: float) -> str:
    """250.0 -> '250', 12.5 -> '12.50'."""
    return str(int(round(x))) if abs(x - round(x)) < 0.005 else f"{x:.2f}"


def money(x: float) -> str:
    """250 -> '₹250', 1500 -> '₹1,500', 12.5 -> '₹12.50'."""
    s = f"{x:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return _cur() + s


def parse_amount(value) -> float | None:
    """250, '250', '₹1,500', 'rs 250', '2.5k', 'two hundred and fifty' -> float. None if no number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).lower().replace("-", " ")
    try:
        from ..calc import words_to_digits

        text = words_to_digits(text)
    except Exception:
        pass
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\b", text)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    n *= {"k": 1000, "thousand": 1000, "lakh": 100000, "lakhs": 100000}.get(m.group(2) or "", 1)
    return n if n > 0 else None


def category_of(word: str | None) -> str | None:
    """'Food' -> 'food', 'groceries' -> 'food', 'lunch' -> 'food', 'gym' -> 'gym'."""
    w = (word or "").lower().strip(" .,!?'\"")
    w = re.sub(r"^(on|for|the|my)\s+", "", w).strip()
    if not w:
        return None
    if w in CATEGORIES:
        return w
    return _CAT_ALIASES.get(w) or _GUESS.get(w) or w


def guess_category(note: str | None) -> str:
    """Guess from words in the note: 'lunch with Ravi' -> 'food'. Unknown -> 'other'."""
    for w in re.findall(r"[a-z]+", (note or "").lower()):
        cat = _CAT_ALIASES.get(w) or _GUESS.get(w)
        if cat:
            return cat
        if w.endswith("s") and _GUESS.get(w[:-1]):
            return _GUESS[w[:-1]]
    return "other"


def _period(name: str | None, now: dt.datetime) -> tuple[dt.datetime, dt.datetime, str]:
    """Return (start, end, words) for today/yesterday/week/month/year/all."""
    p = (name or "month").lower().strip()
    p = re.sub(r"^(this|the|current)\s+", "", p)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    far = dt.datetime.max
    if p in ("today", "day"):
        return day, far, "today"
    if p == "yesterday":
        return day - dt.timedelta(days=1), day, "yesterday"
    if p in ("week", "weekly"):
        return day - dt.timedelta(days=day.weekday()), far, "this week"
    if p in ("last week",):
        start = day - dt.timedelta(days=day.weekday() + 7)
        return start, start + dt.timedelta(days=7), "last week"
    if p in ("last month",):
        first = day.replace(day=1)
        prev = (first - dt.timedelta(days=1)).replace(day=1)
        return prev, first, "last month"
    if p in ("year", "yearly"):
        return day.replace(month=1, day=1), far, "this year"
    if p in ("all", "all time", "ever", "total"):
        return dt.datetime.min, far, "in total"
    return day.replace(day=1), far, "this month"  # default + "month"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------- handlers ----------
def expense_add(args: dict, now: dt.datetime | None = None) -> str:
    amount = parse_amount(args.get("amount"))
    if amount is None:
        return "How much did you spend?"
    note = str(args.get("note") or "").strip()
    category = category_of(args.get("category")) or guess_category(note)
    if not note and args.get("category") and category_of(args["category"]) != str(args["category"]).lower().strip():
        note = str(args["category"]).strip()  # "on lunch" -> category food, note lunch
    row = {"date": (now or dt.datetime.now()).replace(second=0, microsecond=0),
           "amount": amount, "category": category, "note": note}
    with _lock:
        try:
            _append(row)
        except PermissionError:
            return _EXCEL_LOCKED
        today = _total(_load(), *_period("today", now or dt.datetime.now())[:2])
    what = f" on {note}" if note and note.lower() != category else ""
    return f"Added {money(amount)}{what} under {category}. Today's total is {money(today)}."


def _total(rows: list[dict], start: dt.datetime, end: dt.datetime, category: str | None = None) -> float:
    return sum(r["amount"] for r in rows
               if start <= r["date"] < end and (not category or r["category"] == category))


def expense_report(args: dict, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    start, end, words = _period(args.get("period"), now)
    category = category_of(args.get("category"))
    with _lock:
        rows = [r for r in _load() if start <= r["date"] < end]
    if category:
        picked = [r for r in rows if r["category"] == category]
        if not picked:
            return f"You spent nothing on {category} {words}."
        total = sum(r["amount"] for r in picked)
        n = len(picked)
        return f"You spent {money(total)} on {category} {words}, in {n} expense{'s' if n != 1 else ''}."
    if not rows:
        return f"You haven't spent anything {words}."
    total = sum(r["amount"] for r in rows)
    by_cat: dict[str, float] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    top = sorted(by_cat.items(), key=lambda kv: -kv[1])
    reply = f"You spent {money(total)} {words}."
    if len(top) > 1:
        reply += " " + _join([f"{money(v)} on {k}" for k, v in top[:4]]).capitalize() + "."
    return reply


_EXCEL_LOCKED = "I can't change the expenses file while it is open in Excel. Close it there, then try again."


def _remove_last_line() -> dict | None:
    """Delete only the last data line of the file, keeping every other line exactly as it is
    (lines edited by hand and extra columns too). Returns the removed expense, or None."""
    path = _path()
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw[3 if bom else 0:].decode("utf-8", errors="replace").splitlines(keepends=True)
    idx = next((i for i in range(len(lines) - 1, 0, -1) if lines[i].strip()), None)  # line 0 is the header
    if idx is None:
        return None
    header = next(csv.reader([lines[0]]))
    values = next(csv.reader([lines[idx]]), [])
    r = dict(zip(header, values))
    try:
        last = {"amount": float(r.get("amount") or ""),
                "category": _unsafe_cell((r.get("category") or "other").strip().lower()) or "other",
                "note": _unsafe_cell((r.get("note") or "").strip())}
    except ValueError:
        return {}  # last line is not an expense: don't touch it
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + "".join(lines[:idx]).encode("utf-8"))
    os.replace(tmp, path)
    return last


def expense_undo(args: dict) -> str:
    try:
        with _lock:
            last = _remove_last_line()
    except PermissionError:
        return _EXCEL_LOCKED
    if last is None:
        return "There are no expenses to delete."
    if not last:
        return "The last line of the expenses file is not an expense I understand. Please fix it by hand."
    what = f" on {last['note']}" if last["note"] else f" for {last['category']}"
    return f"Deleted the last expense: {money(last['amount'])}{what}."


_PERIOD = {"type": "string", "enum": ["today", "yesterday", "week", "last week", "month", "last month", "year", "all"],
           "description": "Time range. 'week' = since Monday, 'month' = since the 1st. Default month."}

CATALOG: dict[str, dict] = {
    "expense_add": {
        "description": "Save money the user spent, e.g. 'I spent 250 on lunch'.",
        "properties": {
            "amount": {"type": "number", "description": "Amount spent, a plain number like 250."},
            "category": {"type": "string",
                         "description": "food, travel, shopping, bills, other (or any word). Optional: guessed from the note."},
            "note": {"type": "string", "description": "What it was for, e.g. lunch, uber, rent."},
        },
        "required": ["amount"]},
    "expense_report": {
        "description": "Say how much the user spent in a time range, in total or for one category.",
        "properties": {"period": _PERIOD,
                       "category": {"type": "string", "description": "Optional category, e.g. food."}},
        "required": [], "info": True},
    "expense_undo": {
        "description": "Delete the last expense the user added (fix a mistake).",
        "properties": {}, "required": []},
}

HANDLERS = {
    "expense_add": expense_add,
    "expense_report": expense_report,
    "expense_undo": expense_undo,
}
