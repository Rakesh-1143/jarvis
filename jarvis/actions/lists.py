"""To-do, shopping and any other named lists, saved in a JSON file.

Says: "add milk to my shopping list", "remove milk from shopping list",
"what's on my to-do list", "clear my shopping list" (asks yes first),
"what lists do I have".

File format: {"to-do": ["call mom"], "shopping": ["milk", "eggs"]}
Path: config `lists_file` (default "~/Documents/Jarvis lists.json").
Wiring: merge CATALOG and HANDLERS; treat `list_clear` as risky (see risky_text).
"""
from __future__ import annotations

import json
import os
import re
import threading

DEFAULT_FILE = "~/Documents/Jarvis lists.json"
DEFAULT_LISTS = ("to-do", "shopping")
LISTS_FILE = ""  # empty = read config on first use
_lock = threading.Lock()

# Spoken list name -> saved name.
_ALIASES = {
    "todo": "to-do", "to do": "to-do", "to-do": "to-do", "to dos": "to-do", "todos": "to-do",
    "to-dos": "to-do", "task": "to-do", "tasks": "to-do", "things to do": "to-do",
    "shopping": "shopping", "shop": "shopping", "grocery": "shopping", "groceries": "shopping",
    "shopping cart": "shopping",
}
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1}


# ---------- storage ----------
def _path() -> str:
    global LISTS_FILE
    if not LISTS_FILE:
        try:
            from ..config import load_config

            LISTS_FILE = load_config().get("lists_file") or DEFAULT_FILE
        except Exception:
            LISTS_FILE = DEFAULT_FILE
    return os.path.expanduser(LISTS_FILE)


def _load() -> dict[str, list[str]]:
    data: dict = {}
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {str(k): [str(i) for i in v] for k, v in data.items() if isinstance(v, list)}
    for name in DEFAULT_LISTS:
        out.setdefault(name, [])
    return out


def _save(data: dict[str, list[str]]) -> None:
    path = _path()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # never leaves a half-written file


# ---------- text helpers ----------
def list_name(spoken: str | None) -> str:
    """'my To Do list' -> 'to-do', 'groceries' -> 'shopping', '' -> 'to-do'."""
    name = (spoken or "").lower().strip()
    name = re.sub(r"^(my|the|our)\s+", "", name)
    name = re.sub(r"\s+list$", "", name).strip(" .,!?'\"")
    if not name:
        return "to-do"
    return _ALIASES.get(name, name)


def _say_list(name: str) -> str:
    return f"{name} list"


def _split_items(text: str) -> list[str]:
    """'milk, eggs and bread' -> ['milk', 'eggs', 'bread']."""
    parts = re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", (text or "").strip())
    items = []
    for p in parts:
        p = re.sub(r"^(some|a|an)\s+", "", p.strip(" .!?"), flags=re.I).strip()
        if p:
            items.append(p)
    return items


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _key(text: str) -> str:
    """Compare key: lower case, no 's' at the end ('Eggs' == 'egg')."""
    t = re.sub(r"\s+", " ", text.lower().strip(" .!?"))
    return t[:-1] if t.endswith("s") and len(t) > 3 else t


def _find(items: list[str], spoken: str) -> int | None:
    """Index of the item the user means: by number ('item 2', 'the first one') or by name."""
    s = spoken.lower().strip(" .!?")
    m = (re.fullmatch(r"(?:item|number)\s+(?:number\s+)?(\d+|\w+)", s)
         or re.fullmatch(r"(\d+)", s)
         or re.fullmatch(r"(?:the\s+)?(first|second|third|fourth|fifth|last)(?:\s+(?:one|item))?", s))
    if m:
        word = m.group(1)
        n = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        if n == -1:
            return len(items) - 1 if items else None
        if n and 1 <= n <= len(items):
            return n - 1
    k = _key(spoken)
    for i, it in enumerate(items):
        if _key(it) == k:
            return i
    matches = [i for i, it in enumerate(items) if k and k in _key(it)]
    return matches[0] if len(matches) == 1 else None


# ---------- handlers ----------
def list_add(args: dict) -> str:
    name = list_name(args.get("list"))
    items = _split_items(args.get("item") or "")
    if not items:
        return f"What should I add to your {_say_list(name)}?"
    with _lock:
        data = _load()
        lst = data.setdefault(name, [])
        added, already = [], []
        for it in items:
            if any(_key(x) == _key(it) for x in lst):
                already.append(it)
            else:
                lst.append(it)
                added.append(it)
        if added:
            _save(data)
    if not added:
        return f"{_join(already).capitalize()} {'is' if len(already) == 1 else 'are'} already on your {_say_list(name)}."
    reply = f"Added {_join(added)} to your {_say_list(name)}."
    if already:
        reply += f" {_join(already).capitalize()} {'was' if len(already) == 1 else 'were'} already there."
    return reply


def list_remove(args: dict) -> str:
    name = list_name(args.get("list"))
    items = _split_items(args.get("item") or "") or ([args["item"]] if args.get("item") else [])
    if not items:
        return f"What should I remove from your {_say_list(name)}?"
    with _lock:
        data = _load()
        lst = data.get(name)
        if lst is None:
            return f"You don't have a {_say_list(name)}."
        removed, missing = [], []
        for it in items:
            i = _find(lst, it)
            if i is None:
                missing.append(it)
            else:
                removed.append(lst.pop(i))
        if removed:
            _save(data)
    if not removed:
        return f"I couldn't find {_join(missing)} on your {_say_list(name)}."
    reply = f"Removed {_join(removed)} from your {_say_list(name)}."
    if missing:
        reply += f" I couldn't find {_join(missing)}."
    return reply


def list_read(args: dict) -> str:
    name = list_name(args.get("list"))
    with _lock:
        data = _load()
    if name not in data:
        return f"You don't have a {_say_list(name)}."
    items = data[name]
    if not items:
        return f"Your {_say_list(name)} is empty."
    n = len(items)
    return f"Your {_say_list(name)} has {n} item{'s' if n != 1 else ''}: {_join(items)}."


def list_clear(args: dict) -> str:
    name = list_name(args.get("list"))
    if not args.get("confirm"):
        return f"Are you sure you want to clear your {_say_list(name)}?"
    with _lock:
        data = _load()
        if name not in data:
            return f"You don't have a {_say_list(name)}."
        n = len(data[name])
        if name in DEFAULT_LISTS:
            data[name] = []
        else:
            del data[name]  # custom list: remove it completely
        _save(data)
    return f"Cleared your {_say_list(name)}." if n else f"Your {_say_list(name)} was already empty."


def lists(args: dict) -> str:
    with _lock:
        data = _load()
    parts = [f"{name} ({len(items)} item{'s' if len(items) != 1 else ''})" for name, items in data.items()]
    return "Your lists: " + _join(parts) + "."


def risky_text(args: dict) -> str:
    """Words for the 'are you sure you want to ...?' question (for actions._risky_text)."""
    return f"clear your {_say_list(list_name(args.get('list')))}"


_LIST = {"type": "string", "description": "List name, e.g. to-do, shopping, packing. Default to-do."}

CATALOG: dict[str, dict] = {
    "list_add": {"description": "Add one or more items to a named list (to-do, shopping, or any name).",
                 "properties": {"list": _LIST,
                                "item": {"type": "string", "description": "Item(s); several can be joined with commas or 'and'."}},
                 "required": ["list", "item"]},
    "list_remove": {"description": "Remove an item from a list (by name, or by number like 'item 2').",
                    "properties": {"list": _LIST, "item": {"type": "string"}}, "required": ["list", "item"]},
    "list_read": {"description": "Read out what is on a list.",
                  "properties": {"list": _LIST}, "required": ["list"], "info": True},
    "list_clear": {"description": "Remove everything from a list (Jarvis asks the user to confirm).",
                   "properties": {"list": _LIST}, "required": ["list"]},
    "lists": {"description": "Say which lists the user has and how many items each has.",
              "properties": {}, "required": [], "info": True},
}

HANDLERS = {
    "list_add": list_add,
    "list_remove": list_remove,
    "list_read": list_read,
    "list_clear": list_clear,
    "lists": lists,
}
