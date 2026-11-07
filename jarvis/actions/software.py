"""Piece V: install, update and uninstall apps with winget.

Intent: software {action: install|uninstall|update_all|check_updates, name?}
- check_updates: info, lists apps with updates (`winget upgrade`).
- install / uninstall / update_all: risky. The handler never acts without confirm=True.
  risky_text(args) finds the exact package first and stores its id in args, so the "yes"
  acts on exactly the app that was named in the question.
- The real work runs in a background thread (timeout 15 min) and speaks when done
  through the notifier (main.py: software.set_notifier(io.say)).
Safety: commands are argument lists (never shell=True); names and ids are checked first.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time

JOB_TIMEOUT = 15 * 60       # install / uninstall / update all
QUICK_TIMEOUT = 90          # search / list / upgrade list
CACHE_SECONDS = 120         # reuse a search between the question and the "yes"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
_AGREE = ["--accept-source-agreements", "--disable-interactivity"]
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+_#&'-]{0,59}$")
_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-\\{}]{0,199}$")
_ACTIONS = ("install", "uninstall", "update_all", "check_updates")

notify = None                 # function(text) that speaks; set by main.py
_job: dict | None = None      # running background job: {"what": str, "thread": Thread}
_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}


def set_notifier(fn) -> None:
    global notify
    notify = fn


def _say(text: str) -> None:
    if notify:
        try:
            notify(text)
        except Exception:
            pass


# ---------- winget helpers ----------

def _winget() -> str | None:
    return shutil.which("winget")


def _run(args: list[str], timeout: float) -> tuple[int, str]:
    exe = _winget()
    if not exe:
        return -1, ""
    out = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def _lines(text: str) -> list[str]:
    """Output lines, with spinner/progress parts (before a carriage return) removed."""
    return [ln.split("\r")[-1].rstrip() for ln in text.split("\n")]


def parse_table(text: str) -> list[dict]:
    """Parse a winget table (search / list / upgrade). Returns rows as {name, id, version, available?}."""
    lines = _lines(text)
    dash = next((i for i, ln in enumerate(lines) if ln.strip() and set(ln.strip()) <= {"-"}
                 and len(ln.strip()) > 10), None)
    if dash is None or dash == 0:
        return []
    header = lines[dash - 1]
    starts = [m.start() for m in re.finditer(r"(?:(?<=\s)|^)\S", header)]
    if len(starts) < 2:
        return []
    names = ["name", "id", "version", "available", "source"]
    has_available = len(starts) >= 5  # list / upgrade: Name Id Version Available Source
    rows = []
    for ln in lines[dash + 1:]:
        if not ln.strip():
            break
        cells = []
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else None
            cells.append(ln[s:e].strip() if e else ln[s:].strip())
        row = {"name": cells[0], "id": cells[1]}
        if len(cells) > 2:
            row["version"] = cells[2]
        if has_available and len(cells) > 3:
            row["available"] = cells[3]
        # Real rows have an id with no spaces and a version; this skips "2 upgrades available."
        if row["id"] and " " not in row["id"] and row.get("version") and not row["id"].endswith("…"):
            rows.append(row)
    return rows


def _clean_name(name) -> str | None:
    name = re.sub(r"\s+", " ", str(name or "")).strip(" .")
    return name if _NAME_OK.match(name) else None


def _pick(rows: list[dict], name: str) -> dict | None:
    """Best row: exact name, then exact id, then name starting with the words, then the first."""
    if not rows:
        return None
    low = name.lower()
    for test in (lambda r: r["name"].lower() == low,
                 lambda r: r["id"].lower() == low or r["id"].lower().split(".")[-1] == low,
                 lambda r: r["name"].lower().startswith(low)):
        for r in rows:
            if test(r) and _ID_OK.match(r["id"]):
                return r
    # Last try: a row that has one of the spoken words. Never just "the first row" (that names a random package).
    words = [w for w in re.findall(r"\w+", low) if len(w) > 2]
    return next((r for r in rows if _ID_OK.match(r["id"])
                 and any(w in r["name"].lower() or w in r["id"].lower() for w in words)), None)


def find(name: str, installed: bool = False) -> dict | None:
    """Find the package for a spoken name. installed=True searches installed apps (for uninstall)."""
    key = ("list" if installed else "search", name.lower())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    args = ["list", "--name", name] if installed else ["search", name, "--source", "winget"]
    _, out = _run(args + _AGREE, QUICK_TIMEOUT)
    row = _pick(parse_table(out), name)
    _cache[key] = (time.monotonic(), row)
    return row


def _resolve(args: dict) -> dict | None:
    """Fill args['id'] / args['pkg'] for install/uninstall (in place). Returns the row or None."""
    if args.get("id") and _ID_OK.match(str(args["id"])):
        return {"id": args["id"], "name": args.get("pkg") or args["id"]}
    name = _clean_name(args.get("name"))
    if not name or not _winget():
        return None
    try:
        row = find(name, installed=args.get("action") == "uninstall")
    except (OSError, subprocess.SubprocessError):
        return None
    if row:
        args["id"], args["pkg"] = row["id"], row["name"]
    return row


# ---------- confirm hooks (for actions/__init__._risky_text) ----------

def needs_confirm(args: dict) -> bool:
    return (args or {}).get("action") in ("install", "uninstall", "update_all")


def risky_text(args: dict) -> str | None:
    """Words for 'are you sure you want to ...?'. None = not risky, or nothing to confirm
    (the handler then explains why, e.g. app not found)."""
    action = (args or {}).get("action")
    if action == "update_all":
        return "update all your apps (this can take a while and may close them)"
    if action not in ("install", "uninstall"):
        return None
    row = _resolve(args)
    if not row:
        return None
    return f"{action} {row['name']} ({row['id']})"


# ---------- background jobs ----------

def busy() -> str | None:
    """What is running now, or None."""
    with _lock:
        if _job and _job["thread"].is_alive():
            return _job["what"]
    return None


def _job_body(what: str, args: list[str], done: str) -> None:
    try:
        code, out = _run(args, JOB_TIMEOUT)
    except subprocess.TimeoutExpired:
        _say(f"Stopped waiting: {what} took more than 15 minutes.")
        return
    except OSError as e:
        _say(f"Could not {what}: {e}")
        return
    if code == 0:
        _say(done)
    else:
        last = next((ln.strip() for ln in reversed(_lines(out)) if ln.strip()), "")
        _say(f"Could not {what}. {last[:120]}".strip())


def _start(what: str, args: list[str], done: str) -> str:
    global _job
    running = busy()
    if running:
        return f"Please wait, I'm still busy: {running}."
    t = threading.Thread(target=_job_body, args=(what, args, done), daemon=True, name="jarvis-winget")
    with _lock:
        _job = {"what": what, "thread": t}
    t.start()
    return f"Okay, I'll {what} in the background and tell you when it's done."


# ---------- handler ----------

def _no_winget() -> str:
    return "Winget is not available. Install 'App Installer' from the Microsoft Store, then try again."


def check_updates() -> str:
    try:
        _, out = _run(["upgrade", "--include-unknown"] + _AGREE, QUICK_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return "I couldn't check for updates right now."
    rows = parse_table(out)
    if not rows:
        return "All your apps are up to date."
    names = ", ".join(r["name"] for r in rows[:5])
    more = f", and {len(rows) - 5} more" if len(rows) > 5 else ""
    n = len(rows)
    return f"{n} app{'s' if n != 1 else ''} can be updated: {names}{more}."


def software(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "").strip().lower().replace(" ", "_")
    if action not in _ACTIONS:
        return "Say install, uninstall, update all apps, or check for updates."
    args = {**args, "action": action}
    if not _winget():
        return _no_winget()
    if action == "check_updates":
        return check_updates()

    if action == "update_all":
        if args.get("confirm") is not True:
            return "Are you sure you want to update all your apps? Say yes to confirm."
        return _start("update all your apps",
                      ["upgrade", "--all", "--silent", "--accept-package-agreements"] + _AGREE,
                      "All your apps are updated.")

    if not _clean_name(args.get("name")) and not args.get("id"):
        return f"Which app should I {action}?"
    row = _resolve(args)
    if not row:
        where = "installed on this PC" if action == "uninstall" else "in winget"
        return f"I couldn't find {args.get('name') or 'that app'} {where}."
    if args.get("confirm") is not True:
        return f"Are you sure you want to {action} {row['name']} ({row['id']})? Say yes to confirm."
    pkg = ["--id", row["id"], "--exact"]
    if action == "install":
        return _start(f"install {row['name']}",
                      ["install", *pkg, "--silent", "--accept-package-agreements"] + _AGREE,
                      f"{row['name']} is installed.")
    return _start(f"uninstall {row['name']}", ["uninstall", *pkg, "--silent"] + _AGREE,
                  f"{row['name']} is uninstalled.")


CATALOG: dict[str, dict] = {
    "software": {
        "description": ("Install, uninstall or update Windows apps with winget. check_updates = say which "
                        "apps have updates. install / uninstall / update_all ask the user to confirm and "
                        "then run in the background."),
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "name": {"type": "string", "description": "App name, e.g. VLC, Zoom, 7-Zip (install/uninstall)."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"software": software}
