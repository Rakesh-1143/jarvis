"""Custom voice shortcuts and text snippets from config.yaml (piece C).

config.yaml:
    shortcuts:                      # spoken phrase -> what to do
      open my project: {open: "C:/code/myproject"}   # file, folder, app or URL
      open timesheet: {open: "https://example.com/timesheet"}
      mute teams: {keys: "ctrl+shift+m"}             # key combo
      start backup: {run: "robocopy C:/work D:/backup /E"}  # command, ALWAYS asks yes first
      open downloads: "C:/Users/YOU/Downloads"       # plain string = open
    snippets:                       # name -> text ("type my address")
      address: "12 Main Street, Hyderabad"
      signature: "Thanks,\nRakesh"                    # {date} and {time} are filled in

Public:
    load(cfg=None)              read shortcuts/snippets (done on import)
    match(text) -> (intent, args) | None    for main.py, before nlu
    risky_text(args) -> str | None          question words if a shortcut needs a yes
    shortcut(args) / snippet(args) -> str   handlers
    CATALOG, HANDLERS                       merged by actions/__init__.py
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import time
import webbrowser

SHORTCUTS: dict[str, dict] = {}   # phrase (normalised) -> {"open"|"keys"|"run": str}
SNIPPETS: dict[str, str] = {}     # name (normalised) -> text
_KINDS = ("open", "keys", "run")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*:(//)?", re.I)  # http://, ms-settings:, spotify:
_DRIVE = re.compile(r"^[a-z]:[\\/]", re.I)             # C:\ is a path, not a URL scheme


def _norm(text: str) -> str:
    """Lower case, no punctuation, single spaces, no 'jarvis' / 'please'."""
    t = re.sub(r"[^\w\s]", " ", str(text).lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:hey\s+)?jarvis\s+", "", t)
    t = re.sub(r"^please\s+|\s+please$", "", t)
    return t


def _entry(value) -> dict | None:
    """Config value -> {"open"|"keys"|"run": str}, or None if it makes no sense."""
    if isinstance(value, str) and value.strip():
        return {"open": value.strip()}
    if isinstance(value, dict):
        found = [k for k in _KINDS if isinstance(value.get(k), str) and value[k].strip()]
        if len(found) == 1:
            return {found[0]: value[found[0]].strip()}
    return None


def load(cfg: dict | None = None) -> None:
    """Read `shortcuts` and `snippets` from config (default: jarvis.config.load_config())."""
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config() or {}
        except Exception:
            cfg = {}
    SHORTCUTS.clear()
    SNIPPETS.clear()
    for phrase, value in (cfg.get("shortcuts") or {}).items():
        entry = _entry(value)
        if entry and _norm(phrase):
            SHORTCUTS[_norm(phrase)] = entry
    for name, text in (cfg.get("snippets") or {}).items():
        if text is not None and _norm(name):
            SNIPPETS[_norm(name)] = str(text)
    _refresh_catalog()


# ---------- matching (main.py calls this before nlu) ----------
_SNIP_RE = re.compile(r"^(?:type|paste|insert|write|enter)\s+(?:in\s+)?(?:my\s+|the\s+)?(.+?)(?:\s+snippet)?$")
_SHORT_RE = re.compile(r"^(?:run|do|use|start)?\s*(?:the\s+|my\s+)?shortcut\s+(.+)$")


def _snippet_name(said: str) -> str | None:
    said = _norm(said)
    if said in SNIPPETS:
        return said
    said = re.sub(r"^(?:my|the)\s+", "", said)
    return said if said in SNIPPETS else None


def match(text: str) -> tuple[str, dict] | None:
    """'mute teams' -> ('shortcut', {'name': 'mute teams'}); 'type my address' -> ('snippet', {...})."""
    t = _norm(text)
    if not t:
        return None
    if t in SHORTCUTS:
        return "shortcut", {"name": t}
    m = _SHORT_RE.match(t)
    if m and _norm(m.group(1)) in SHORTCUTS:
        return "shortcut", {"name": _norm(m.group(1))}
    m = _SNIP_RE.match(t)
    if m:
        name = _snippet_name(m.group(1))
        if name:
            return "snippet", {"name": name}
    return None


# ---------- confirm ----------
def risky_text(args: dict) -> str | None:
    """Question words if this shortcut runs a command (always asks yes), else None."""
    entry = SHORTCUTS.get(_norm(args.get("name", "")))
    if entry and "run" in entry:
        return f"run the command for {_norm(args.get('name', ''))}: {entry['run']}"
    return None


# ---------- doing ----------
def _open(target: str) -> None:
    target = os.path.expandvars(os.path.expanduser(target))
    if os.name == "nt":
        os.startfile(target)  # files, folders, apps, URLs, ms-settings: (Windows)
    elif _URL.match(target) and not _DRIVE.match(target):
        webbrowser.open(target)
    else:
        subprocess.Popen(["xdg-open", target])


def _keys(combo: str) -> bool:
    from . import inputs

    return inputs.press_keys({"keys": combo}) == "Done."


def _run(command: str) -> None:
    # Only commands written by the user in config.yaml ever get here.
    subprocess.Popen(command, shell=True, cwd=os.path.expanduser("~"))


def _names(d: dict) -> str:
    return ", ".join(sorted(d)) if d else "none yet. Add them in config.yaml"


def shortcut(args: dict) -> str:
    name = _norm(args.get("name", ""))
    if not name:
        return f"Your shortcuts are: {_names(SHORTCUTS)}."
    entry = SHORTCUTS.get(name)
    if not entry:
        return f"I don't have a shortcut called {name}. You have: {_names(SHORTCUTS)}."
    try:
        if "open" in entry:
            _open(entry["open"])
            return f"Opening {name}."
        if "keys" in entry:
            return "Done." if _keys(entry["keys"]) else f"I don't understand the keys {entry['keys']}."
        if args.get("confirm") is not True:  # run: never without a yes
            return f"Are you sure you want to {risky_text({'name': name})}? Say yes to confirm."
        _run(entry["run"])
        return f"Running {name}."
    except Exception as exc:
        return f"Sorry, {name} didn't work: {exc}"


def _fill(text: str) -> str:
    now = dt.datetime.now()
    return text.replace("{date}", now.strftime("%d %B %Y")).replace("{time}", now.strftime("%I:%M %p").lstrip("0"))


def _paste(text: str) -> None:
    """Paste via clipboard (handles new lines and any language), then put the old clipboard back."""
    import pyautogui
    import pyperclip

    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)  # let the app read the clipboard first
    if old is not None:
        pyperclip.copy(old)


def snippet(args: dict) -> str:
    said = str(args.get("name", ""))
    if not _norm(said):
        return f"Your snippets are: {_names(SNIPPETS)}."
    name = _snippet_name(said)
    if not name:
        return f"I don't have a snippet called {_norm(said)}. You have: {_names(SNIPPETS)}."
    try:
        _paste(_fill(SNIPPETS[name]))
    except Exception as exc:
        return f"Sorry, I couldn't type {name}: {exc}"
    return f"Typed your {name}."


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {}


def _refresh_catalog() -> None:
    CATALOG.clear()
    CATALOG["shortcut"] = {
        "description": "Run one of the user's own voice shortcuts from config.yaml (opens a thing, presses keys, "
                       "or runs a command; commands ask to confirm). Empty name lists them. "
                       f"Shortcuts: {_names(SHORTCUTS)}.",
        "properties": {"name": {"type": "string", "description": "Shortcut phrase, lower case."}},
        "required": [],
    }
    CATALOG["snippet"] = {
        "description": "Type one of the user's saved text snippets into the active window. Empty name lists them. "
                       f"Snippets: {_names(SNIPPETS)}.",
        "properties": {"name": {"type": "string", "description": "Snippet name, e.g. address."}},
        "required": [],
    }


HANDLERS = {"shortcut": shortcut, "snippet": snippet}

load()
