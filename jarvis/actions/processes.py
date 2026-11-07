"""See what is running and force close programs (Task Manager by voice)."""
from __future__ import annotations

import os
import time

# Never killed: Windows needs these, and Jarvis itself.
PROTECTED = {
    "system", "system idle process", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass",
    "svchost", "dwm", "fontdrvhost", "memory compression", "explorer", "sihost", "ctfmon", "spoolsv",
    "taskhostw", "searchhost", "startmenuexperiencehost", "runtimebroker", "securityhealthservice",
    "msmpeng", "audiodg", "conhost", "python", "pythonw", "py", "lsaiso", "wudfhost", "dllhost",
}


def _base(name: str) -> str:
    n = (name or "").lower().strip()
    return n[:-4] if n.endswith(".exe") else n


def _pretty(name: str) -> str:
    return _base(name).replace("_", " ").title()


def _size(b: float) -> str:
    return f"{b / 1e9:.1f} gigabytes" if b >= 1e9 else f"{int(b / 1e6)} megabytes"


def processes(args: dict) -> str:
    """Top 5 programs by memory (default) or CPU."""
    import psutil

    by = args.get("sort", "memory")
    procs = list(psutil.process_iter(["name", "memory_info"]))
    if by == "cpu":
        for p in procs:
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        time.sleep(0.5)
    totals: dict[str, float] = {}
    for p in procs:
        try:
            name = p.info.get("name") or ""
            if not name or _base(name) in ("system idle process", "idle"):
                continue
            val = p.cpu_percent(None) if by == "cpu" else (p.info.get("memory_info").rss if p.info.get("memory_info") else 0)
        except Exception:
            continue
        totals[name] = totals.get(name, 0) + val
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    if not top:
        return "I couldn't read the running programs."
    if by == "cpu":
        cores = psutil.cpu_count() or 1
        parts = [f"{_pretty(n)} {round(v / cores)} percent" for n, v in top]
        return "Using the most CPU: " + ", ".join(parts) + "."
    return "Using the most memory: " + ", ".join(f"{_pretty(n)} {_size(v)}" for n, v in top) + "."


def find(name: str) -> tuple[str, list[int]]:
    """(process name, pids) of programs matching a spoken name. ('', []) if none or only protected."""
    import psutil

    want = _base(name).replace(" ", "")
    if not want:
        return "", []
    mine = {os.getpid(), os.getppid()}
    exact: dict[str, list[int]] = {}
    partial: dict[str, list[int]] = {}
    for p in psutil.process_iter(["name", "pid"]):
        n = p.info.get("name") or ""
        b = _base(n)
        if not b or b in PROTECTED or p.info["pid"] in mine:
            continue
        key = b.replace(" ", "")
        if key == want:
            exact.setdefault(n, []).append(p.info["pid"])
        elif want in key:
            partial.setdefault(n, []).append(p.info["pid"])
    pick = exact or partial
    if not pick:
        return "", []
    n = max(pick, key=lambda k: len(pick[k]))  # most common match
    return n, pick[n]


def kill_question(args: dict) -> str | None:
    name, pids = find(str(args.get("name") or ""))
    if not pids:
        return None
    return f"force close {_pretty(name)} (unsaved work will be lost)"


def kill_process(args: dict) -> str:
    """Only kills when args has confirm=True (actions asks first)."""
    import psutil

    spoken = str(args.get("name") or "")
    name, pids = find(spoken)
    if not pids:
        if _base(spoken) in PROTECTED:
            return f"I won't close {spoken}. Windows needs it."
        return f"I couldn't find {spoken or 'that'} running."
    if args.get("confirm") is not True:
        return f"Say yes to force close {_pretty(name)}."
    killed = 0
    for pid in pids:
        try:
            psutil.Process(pid).kill()
            killed += 1
        except Exception:
            pass
    return f"Closed {_pretty(name)}." if killed else f"I couldn't close {_pretty(name)}. It may need admin rights."
