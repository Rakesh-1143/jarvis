"""Piece AK: PC health check. Intent: pc_health {what: all|battery|startup|updates|antivirus}.

Read only. Nothing here changes the PC.
- battery:   `powercfg /batteryreport /xml` -> design vs full charge capacity, cycle count.
- startup:   HKCU/HKLM Run keys + Startup folders (skips apps turned off in Task Manager).
- updates:   last installed update (Get-HotFix) + pending count (Windows Update COM search).
- antivirus: Defender `Get-MpComputerStatus`; if that fails, Windows Security Center (any antivirus).

No extra packages (subprocess, winreg, xml.etree, json). Windows only; other systems get a short reply.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no black cmd box
MAX_NAMES = 6  # startup app names spoken
NEVER = 65535  # Defender gives a huge number (UInt32 max) for "never scanned"


# ---------- OS calls (tests replace these) ----------
def _run(cmd: list[str], timeout: float = 30) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                         creationflags=_NO_WINDOW, errors="replace")
    return out.stdout or ""


def _ps(script: str, timeout: float = 30) -> str:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", script], timeout=timeout)


def _ps_json(script: str, timeout: float = 30):
    """Run PowerShell that prints JSON. None if it fails or prints nothing."""
    try:
        text = _ps(script, timeout).strip()
        return json.loads(text) if text else None
    except Exception:
        return None


# ---------- battery ----------
def _tag(el) -> str:
    return el.tag.split("}")[-1]  # drop XML namespace


def parse_battery_xml(text: str) -> list[dict]:
    """powercfg battery report XML -> [{design, full, cycles}] (mWh). Empty list = no battery."""
    root = ET.fromstring(text)
    out = []
    for el in root.iter():
        if _tag(el) != "Battery":
            continue
        vals = {_tag(c): (c.text or "").strip() for c in el}

        def num(key):
            try:
                return int(float(vals.get(key, "")))
            except ValueError:
                return None
        design, full = num("DesignCapacity"), num("FullChargeCapacity")
        if design or full:
            out.append({"design": design, "full": full, "cycles": num("CycleCount")})
    return out


def battery_report() -> list[dict] | None:
    """Make the report in a temp file and read it. None if powercfg failed."""
    path = os.path.join(tempfile.gettempdir(), "jarvis_battery_report.xml")
    try:
        _run(["powercfg", "/batteryreport", "/xml", "/output", path], timeout=30)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        return parse_battery_xml(text)
    except ET.ParseError:
        return None


def battery_text(batteries: list[dict] | None) -> str:
    if batteries is None:
        return "I couldn't read the battery report."
    if not batteries:
        return "No battery found on this PC."
    parts = []
    for i, b in enumerate(batteries):
        name = "Battery" if len(batteries) == 1 else f"Battery {i + 1}"
        if not b["design"] or not b["full"]:
            parts.append(f"{name}: capacity not reported.")
            continue
        pct = round(100 * b["full"] / b["design"])
        msg = f"{name} health is {min(pct, 100)} percent of its original capacity"
        if b["cycles"]:
            msg += f", {b['cycles']} charge cycles"
        if pct < 60:
            msg += ". It is badly worn, think about replacing it"
        elif pct < 80:
            msg += ". It is getting worn"
        parts.append(msg + ".")
    return " ".join(parts)


# ---------- startup apps ----------
RUN_KEYS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
]
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
APPROVED_SUBKEYS = ("Run", "Run32", "StartupFolder")


def _reg_values(hive: str, path: str) -> dict:
    """All values of one registry key as {name: data}. Empty if missing."""
    try:
        import winreg
    except ImportError:
        return {}
    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    out = {}
    try:
        with winreg.OpenKey(root, path) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = data
                i += 1
    except OSError:
        pass
    return out


def _startup_folders() -> list[str]:
    return [os.path.join(os.environ.get(v, ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
            for v in ("APPDATA", "PROGRAMDATA") if os.environ.get(v)]


def _folder_items(folder: str) -> list[str]:
    try:
        return [f for f in os.listdir(folder) if f.lower() != "desktop.ini"]
    except OSError:
        return []


def _disabled_names() -> set[str]:
    """Apps turned off in Task Manager > Startup. First byte odd (e.g. 03) = off."""
    off = set()
    for hive in ("HKCU", "HKLM"):
        for sub in APPROVED_SUBKEYS:
            for name, data in _reg_values(hive, APPROVED + "\\" + sub).items():
                if isinstance(data, (bytes, bytearray)) and data and data[0] & 1:
                    off.add(name.lower())
    return off


def startup_apps() -> list[str]:
    """Names of apps that start with Windows (on only), sorted, no duplicates."""
    off = _disabled_names()
    names: dict[str, str] = {}
    for hive, path in RUN_KEYS:
        for name in _reg_values(hive, path):
            if name and name.lower() not in off:
                names.setdefault(name.lower(), name)
    for folder in _startup_folders():
        for f in _folder_items(folder):
            if f.lower() in off:
                continue
            nice = os.path.splitext(f)[0]
            names.setdefault(nice.lower(), nice)
    return sorted(names.values(), key=str.lower)


def startup_text(apps: list[str]) -> str:
    if not apps:
        return "No apps start with Windows."
    n = len(apps)
    shown = ", ".join(apps[:MAX_NAMES])
    more = f", and {n - MAX_NAMES} more" if n > MAX_NAMES else ""
    word = "app starts" if n == 1 else "apps start"
    msg = f"{n} {word} with Windows: {shown}{more}."
    if n > 10:
        msg += " That's a lot; turning some off in Task Manager can speed up boot."
    return msg


# ---------- Windows Update ----------
UPDATES_PS = (
    "$h = Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1;"
    "$last = ''; if ($h) { $last = $h.InstalledOn.ToString('yyyy-MM-dd') };"
    "$n = -1; try { $s = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher();"
    "$n = $s.Search(\"IsInstalled=0 and IsHidden=0 and Type='Software'\").Updates.Count } catch {};"
    "@{last=$last; pending=$n} | ConvertTo-Json -Compress"
)


def updates_status() -> dict | None:
    """{last: 'YYYY-MM-DD' or '', pending: int (-1 = unknown)}. The search can take up to a minute."""
    data = _ps_json(UPDATES_PS, timeout=120)
    return data if isinstance(data, dict) else None


def updates_text(data: dict | None, today: date | None = None) -> str:
    if data is None:
        return "I couldn't check Windows Update."
    today = today or date.today()
    parts = []
    try:
        pending = int(data.get("pending", -1))
    except (TypeError, ValueError):
        pending = -1
    if pending == 0:
        parts.append("Windows is up to date, no updates waiting.")
    elif pending > 0:
        parts.append(f"{pending} Windows {'update is' if pending == 1 else 'updates are'} waiting to install.")
    else:
        parts.append("I couldn't count waiting updates.")
    try:
        last = datetime.strptime(str(data.get("last") or ""), "%Y-%m-%d").date()
        days = (today - last).days
        when = "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"
        parts.append(f"Last update installed {when}.")
        if days > 45:
            parts.append("That's a while; check Settings > Windows Update.")
    except ValueError:
        pass
    return " ".join(parts)


# ---------- antivirus ----------
DEFENDER_PS = ("Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,"
               "AntivirusSignatureAge,QuickScanAge,FullScanAge | ConvertTo-Json -Compress")
SECCENTER_PS = ("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | "
                "Select-Object displayName,productState | ConvertTo-Json -Compress")


def antivirus_status() -> dict | None:
    """{'defender': {...}} or {'products': [{displayName, productState}]} or None."""
    d = _ps_json(DEFENDER_PS)
    if isinstance(d, dict) and d.get("AntivirusEnabled") is not None:
        return {"defender": d}
    p = _ps_json(SECCENTER_PS)
    if isinstance(p, dict):
        p = [p]
    if isinstance(p, list) and p:
        return {"products": [x for x in p if isinstance(x, dict)]}
    return None


def _days(n) -> str | None:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n < 0 or n >= NEVER:
        return "never"
    return "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago"


def antivirus_text(data: dict | None) -> str:
    if data is None:
        return "I couldn't check the antivirus."
    if "defender" in data:
        d = data["defender"]
        if not d.get("AntivirusEnabled"):
            return "Microsoft Defender antivirus is off. Another antivirus may be in charge; check Windows Security."
        parts = ["Microsoft Defender is on"]
        if d.get("RealTimeProtectionEnabled") is False:
            parts[0] += ", but real-time protection is off"
        msg = parts[0] + "."
        sig = d.get("AntivirusSignatureAge")
        try:
            if int(sig) > 7:
                msg += f" Virus definitions are {int(sig)} days old, update them."
            else:
                msg += " Virus definitions are up to date."
        except (TypeError, ValueError):
            pass
        quick, full = _days(d.get("QuickScanAge")), _days(d.get("FullScanAge"))
        if quick:
            msg += f" Last quick scan {quick}." if quick != "never" else " No quick scan yet."
        if full and full != "never":
            msg += f" Last full scan {full}."
        return msg
    out = []
    for p in data.get("products", []):
        name = str(p.get("displayName") or "Unknown antivirus")
        try:
            state = int(p.get("productState"))
        except (TypeError, ValueError):
            out.append(f"{name} is installed.")
            continue
        on = bool(state & 0x1000)
        old = bool(state & 0x10)
        msg = f"{name} is {'on' if on else 'off'}"
        msg += ", definitions out of date." if old else "."
        out.append(msg)
    return " ".join(out) or "No antivirus found."


# ---------- intent ----------
PARTS: dict[str, Callable[[], str]] = {
    "battery": lambda: battery_text(battery_report()),
    "startup": lambda: startup_text(startup_apps()),
    "updates": lambda: updates_text(updates_status()),
    "antivirus": lambda: antivirus_text(antivirus_status()),
}
ORDER = ("battery", "antivirus", "updates", "startup")


def pc_health(args: dict) -> str:
    what = str((args or {}).get("what") or "all").lower().strip()
    if not IS_WINDOWS:
        return "PC health check works only on Windows."
    keys = ORDER if what == "all" else (what,)
    if what != "all" and what not in PARTS:
        return "I can check battery, startup apps, updates or antivirus."
    out = []
    for k in keys:
        try:
            out.append(PARTS[k]())
        except Exception:
            out.append(f"I couldn't check {k}.")
    return " ".join(out)


CATALOG: dict[str, dict] = {
    "pc_health": {
        "description": "Read-only PC health check: battery wear and cycle count, apps that start with Windows, "
                       "Windows Update status, antivirus (Defender) status. Use 'all' for a full check-up.",
        "properties": {
            "what": {"type": "string", "enum": ["all", "battery", "startup", "updates", "antivirus"],
                     "description": "Which check. Default all."},
        },
        "required": [],
        "info": True,
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"pc_health": pc_health}
