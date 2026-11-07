"""Phone link through KDE Connect (piece T).

Needs KDE Connect for Windows (`winget install KDE.KDEConnect`) on the PC and the
KDE Connect app on the phone, paired once. Jarvis calls `kdeconnect-cli` (no shell).

Intents:
- `phone {action: ring|sms|share, to?, text?, what?}` -> acts. `sms` is risky (asks yes first).
- `phone_battery {}` -> info only (reads, never acts).

Config (all optional), in config.yaml:
    phone:
      kdeconnect_path: ""   # full path to kdeconnect-cli.exe; empty = PATH or Program Files
      device: ""            # phone name or id; empty = first connected phone
Numbers for "text mom" come from `contacts:` (`mom: {phone: "+91..."}`).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULTS: dict = {"kdeconnect_path": "", "device": ""}
TIMEOUT = 15  # seconds per kdeconnect-cli call

INSTALL_MSG = ("KDE Connect is not installed. Install it with 'winget install KDE.KDEConnect', "
               "put the KDE Connect app on your phone, and pair them once.")
NO_PHONE_MSG = ("I can't find your phone. Open KDE Connect on the phone, "
                "and keep it on the same Wi-Fi as this PC.")

_URL = re.compile(r"^(https?://|www\.)\S+$", re.I)
_NUMBER = re.compile(r"^\+?[\d\s\-().]{7,}$")
_CLIP_WORDS = {"", "this", "it", "that", "link", "this link", "the link", "url", "clipboard",
               "my clipboard", "the clipboard", "copied", "what i copied", "text", "this text"}
_DOWNLOAD_WORDS = {"last download", "my last download", "latest download", "download",
                   "the last download", "newest download", "last downloaded file"}


# ---------- settings ----------
def _config() -> dict:
    try:
        from jarvis.config import load_config

        return load_config() or {}
    except Exception:
        return {}


def settings(cfg: dict | None = None) -> dict:
    cfg = _config() if cfg is None else cfg
    user = cfg.get("phone") or {}
    return {**DEFAULTS, **(user if isinstance(user, dict) else {})}


def find_cli(s: dict) -> str | None:
    """kdeconnect-cli: config path, else PATH, else the usual install folders."""
    p = str(s.get("kdeconnect_path") or "").strip().strip('"')
    if p:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            return p
    found = shutil.which("kdeconnect-cli")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for sub in ("KDE Connect", "kdeconnect", os.path.join("Programs", "KDE Connect")):
            exe = os.path.join(base, sub, "bin", "kdeconnect-cli.exe")
            if os.path.isfile(exe):
                return exe
    return None


# ---------- subprocess wrapper (tests replace this) ----------
def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run without a shell. Returns (exit code, stdout, stderr)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                       creationflags=flags, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout or "", p.stderr or ""


def _call(cmd: list[str]) -> tuple[int, str, str] | str:
    """_run, but errors become a reply string."""
    try:
        return _run(cmd)
    except FileNotFoundError:
        return INSTALL_MSG
    except subprocess.TimeoutExpired:
        return "Your phone did not answer in time."
    except OSError as e:
        return f"KDE Connect failed: {e}"


# ---------- device ----------
def devices(cli: str) -> list[tuple[str, str]] | str:
    """Connected phones as (id, name). A string means an error reply."""
    r = _call([cli, "-a", "--id-name-only"])
    if isinstance(r, str):
        return r
    out = []
    for line in r[1].splitlines():
        line = line.strip()
        if not line:
            continue
        dev_id, _, name = line.partition(" ")
        out.append((dev_id, name.strip() or dev_id))
    return out


def pick_device(devs: list[tuple[str, str]], wanted: str) -> str | None:
    """Device id: the configured one (id or name) if connected, else the first."""
    if not devs:
        return None
    w = (wanted or "").strip().lower()
    if w:
        for dev_id, name in devs:
            if w in (dev_id.lower(), name.lower()):
                return dev_id
        return None  # configured phone is not connected
    return devs[0][0]


def _setup() -> tuple[str, str] | str:
    """(cli, device id) or an error reply."""
    s = settings()
    cli = find_cli(s)
    if not cli:
        return INSTALL_MSG
    devs = devices(cli)
    if isinstance(devs, str):
        return devs
    dev = pick_device(devs, str(s.get("device") or ""))
    if not dev:
        if s.get("device") and devs:
            return f"Your phone {s['device']} is not connected. " + NO_PHONE_MSG
        return NO_PHONE_MSG
    return cli, dev


def _do(extra: list[str], ok: str) -> str:
    setup = _setup()
    if isinstance(setup, str):
        return setup
    cli, dev = setup
    r = _call([cli, "-d", dev, *extra])
    if isinstance(r, str):
        return r
    code, _out, err = r
    if code != 0:
        msg = (err.strip().splitlines() or ["unknown error"])[-1]
        return f"KDE Connect could not do that: {msg}"
    return ok


# ---------- contacts ----------
def _contacts() -> dict:
    c = _config().get("contacts") or {}
    return c if isinstance(c, dict) else {}


def resolve_number(to: str, contacts: dict | None = None) -> str:
    """'mom' -> her phone from contacts; a spoken number -> digits (keeps a leading +)."""
    to = (to or "").strip()
    if not to:
        return ""
    if contacts is None and not _NUMBER.match(to):  # real use: voice-saved + config contacts (contacts.py)
        try:
            from . import contacts as _ct

            saved = _ct.lookup(to)
            if saved and saved.get("phone"):
                return _clean_number(str(saved["phone"]))
        except Exception:
            pass
    contacts = _contacts() if contacts is None else contacts
    key = to.lower().removeprefix("my ").strip()
    for k, v in contacts.items():
        if str(k).lower() == key:
            num = v.get("phone", "") if isinstance(v, dict) else ""
            return _clean_number(str(num or ""))
    if _NUMBER.match(to):  # digits are never fuzzy-matched
        return _clean_number(to)
    from . import fuzzy  # "rohith" -> rohit; two close names = no guess

    fk = fuzzy.contact(key, contacts)
    if fk is not None:
        v = contacts[fk]
        return _clean_number(str((v.get("phone", "") if isinstance(v, dict) else "") or ""))
    return ""


def _clean_number(s: str) -> str:
    s = s.strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return ""
    return ("+" if s.startswith("+") else "") + digits


# ---------- risky (sms) ----------
def needs_confirm(args: dict) -> bool:
    return risky_text(args) is not None


def risky_text(args: dict) -> str | None:
    """Words for 'Are you sure you want to ...?' (only sms with a number and text)."""
    if (args.get("action") or "").lower() != "sms":
        return None
    to = (args.get("to") or "").strip()
    text = (args.get("text") or "").strip()
    num = resolve_number(to)
    if not num or not text:
        return None  # handler asks for the missing part; nothing is sent
    who = to if to.lstrip("+").replace(" ", "").isdigit() else f"{to} ({num})"
    return f"send a text to {who} saying: {text}"


# ---------- actions ----------
def ring(args: dict) -> str:
    return _do(["--ring"], "Ringing your phone.")


def sms(args: dict) -> str:
    to = (args.get("to") or "").strip()
    text = (args.get("text") or "").strip()
    if not to:
        return "Who should I text?"
    num = resolve_number(to)
    if not num:
        return f"I don't have a phone number for {to}. Say: add contact {to} phone, then the number."
    if not text:
        return f"What should the text to {to} say?"
    if not args.get("confirm"):
        return f"Are you sure you want to {risky_text(args)}? Say yes to confirm."
    return _do(["--send-sms", text, "--destination", num], f"Sent your text to {to}.")


def _clipboard() -> str:
    try:
        import pyperclip

        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def _last_download() -> Path | None:
    try:
        from . import recent

        items = recent.scan("downloads")
    except Exception:
        return None
    return Path(items[0].path) if items else None


def _home_file(s: str) -> Path | None:
    """An existing file inside the user's home folder, else None."""
    try:
        p = Path(os.path.expanduser(s.strip().strip('"'))).resolve()
        home = Path(os.path.expanduser("~")).resolve()
        if p.is_file() and (p == home or home in p.parents):
            return p
    except (OSError, ValueError):
        pass
    return None


def share(args: dict) -> str:
    """Send a link, text, file, the clipboard, or the last download to the phone."""
    what = str(args.get("what") or args.get("text") or "").strip()
    low = what.lower().rstrip(".")
    if low in _DOWNLOAD_WORDS:
        f = _last_download()
        if not f:
            return "Your Downloads folder is empty."
        return _do(["--share", str(f)], f"Sent {f.name} to your phone.")
    if low in _CLIP_WORDS:
        what = _clipboard()
        if not what:
            return "Your clipboard is empty. Copy the link or text first."
    if _URL.match(what):
        url = what if what.lower().startswith("http") else "https://" + what
        return _do(["--share", url], "Sent the link to your phone.")
    f = _home_file(what) if len(what) < 400 else None
    if f:
        return _do(["--share", str(f)], f"Sent {f.name} to your phone.")
    return _do(["--share-text", what], "Sent the text to your phone.")


def phone(args: dict) -> str:
    action = (args.get("action") or "").lower().strip()
    if action in ("ring", "find", "ping"):
        return ring(args)
    if action in ("sms", "text", "message"):
        return sms({**args, "action": "sms"})
    if action in ("share", "send"):
        return share(args)
    if action == "battery":
        return phone_battery(args)
    return "I can ring your phone, text someone, send something to it, or check its battery."


# ---------- battery (read only) ----------
def _find_qdbus(cli: str) -> str | None:
    """qdbus ships next to kdeconnect-cli in some builds (verify on Windows)."""
    folder = os.path.dirname(cli)
    for name in ("qdbus.exe", "qdbus6.exe", "qdbus-qt6.exe", "qdbus"):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            return p
    return shutil.which("qdbus") or shutil.which("qdbus6")


def _battery_value(qdbus: str, dev: str, prop: str) -> str | None:
    r = _call([qdbus, "org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev}/battery",
               f"org.kde.kdeconnect.device.battery.{prop}"])
    if isinstance(r, str) or r[0] != 0:
        return None
    return r[1].strip() or None


def phone_battery(args: dict) -> str:
    setup = _setup()
    if isinstance(setup, str):
        return setup
    cli, dev = setup
    qdbus = _find_qdbus(cli)
    if not qdbus:
        return "I can't read the phone battery on this PC. The KDE Connect app shows it."
    charge = _battery_value(qdbus, dev, "charge")
    if not charge or not charge.lstrip("-").isdigit() or int(charge) < 0:
        return "I couldn't read your phone battery. Make sure the battery plugin is on in KDE Connect."
    charging = (_battery_value(qdbus, dev, "isCharging") or "").lower() == "true"
    return f"Your phone is at {int(charge)} percent{' and charging' if charging else ''}."


# ---------- wiring ----------
CATALOG: dict[str, dict] = {
    "phone": {
        "description": ("Control the user's phone through KDE Connect: ring it to find it, send an SMS "
                        "(Jarvis asks the user to confirm), or send a link/text/file/clipboard/last download to it."),
        "properties": {
            "action": {"type": "string", "enum": ["ring", "sms", "share"]},
            "to": {"type": "string", "description": "sms: contact name from config or a phone number."},
            "text": {"type": "string", "description": "sms: the message text."},
            "what": {"type": "string", "description": ("share: a URL, text, a file path, 'clipboard', "
                                                       "or 'last download'. Default clipboard.")},
        },
        "required": ["action"],
    },
    "phone_battery": {"description": "Say the phone's battery level (read only).",
                      "properties": {}, "required": [], "info": True},
}

HANDLERS = {"phone": phone, "phone_battery": phone_battery}
