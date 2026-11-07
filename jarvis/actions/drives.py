"""Piece BP: drives (USB pen drives, other disks).

"what drives are connected", "is my pen drive connected", "how much space on D drive",
"open my pen drive", "eject my pen drive".

Intent: drives {action: list|space|open|eject, drive?}
  list   - (info) all drives, or only the asked ones ("is my pen drive connected")
  space  - (info) free / total space on one drive, or on every drive when none is named
  open   - open the drive in File Explorer
  eject  - safely remove a drive (Shell "Eject" verb, like the Explorer right-click menu)

`drive` can be a letter ("D", "d:", "d drive", "dee"), a kind ("pen drive", "usb", "sd card",
"external", "cd", "network") or a volume label ("Kingston").
Read only, except eject. The Windows system drive (C:) is never ejected.
Needs psutil (already a core package). Drive type and label come from kernel32 through ctypes,
so pywin32 is not needed. Tests swap `_drives()`, `_eject()` and `_open()` for fakes.
"""
from __future__ import annotations

import os
import re
import string
import subprocess
import sys
import time

ACTIONS = ("list", "space", "open", "eject")
_SYNONYMS = {
    "show": "list", "connected": "list", "check": "list", "which": "list", "status": "list",
    "free": "space", "storage": "space", "size": "space", "usage": "space",
    "explore": "open", "browse": "open",
    "remove": "eject", "safely_remove": "eject", "unmount": "eject", "disconnect": "eject",
}

# GetDriveTypeW numbers -> our kinds
_TYPES = {2: "removable", 3: "fixed", 4: "network", 5: "cd", 6: "ram"}
_KIND_WORDS = {"removable": "pen drive", "fixed": "local disk", "network": "network drive",
               "cd": "CD/DVD drive", "ram": "RAM disk", "unknown": "drive"}
# what people say -> kind (checked in this order; longer phrases first)
_KIND_ALIASES = [
    (r"\b(?:pen ?drive|pendrive|usb|flash ?drive|thumb ?drive|memory stick|stick|sd ?card|memory card|removable)\b",
     "removable"),
    (r"\b(?:cd|dvd|disc|disk tray|optical)\b", "cd"),
    (r"\b(?:network|shared|nas|mapped)\b", "network"),
    (r"\bexternal\b", "external"),  # removable, or a fixed USB hard disk that is not the system drive
]
_SPOKEN_LETTERS = {
    "ay": "a", "bee": "b", "be": "b", "see": "c", "sea": "c", "cee": "c", "dee": "d", "ee": "e",
    "ef": "f", "eff": "f", "gee": "g", "aitch": "h", "jay": "j", "kay": "k", "el": "l", "em": "m",
    "en": "n", "pee": "p", "queue": "q", "cue": "q", "ar": "r", "es": "s", "tee": "t", "tea": "t",
    "you": "u", "vee": "v", "ex": "x", "why": "y", "zed": "z", "zee": "z",
}
EJECT_WAIT = 5.0  # seconds to wait for the drive to disappear after "Eject"


# ---------- reading drives ----------

def _on_windows() -> bool:
    return sys.platform == "win32"


def _system_letter() -> str:
    return (os.environ.get("SystemDrive") or "C:")[:1].upper()


def _drive_type(mount: str) -> str:
    try:
        import ctypes

        return _TYPES.get(int(ctypes.windll.kernel32.GetDriveTypeW(mount)), "unknown")  # type: ignore[attr-defined]
    except Exception:
        return "unknown"


def _volume_label(mount: str) -> str:
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
            ctypes.c_wchar_p(mount), buf, 261, None, None, None, None, 0)
        return buf.value.strip() if ok else ""
    except Exception:
        return ""


def _drives() -> list[dict]:
    """[{letter: "E", mount: "E:\\", label, kind, total, free}] sorted by letter. Empty CD trays are left out."""
    import psutil

    out: list[dict] = []
    seen: set[str] = set()
    for p in psutil.disk_partitions(all=False):
        mount = p.mountpoint or p.device
        letter = (mount[:1] or "").upper()
        if letter not in string.ascii_uppercase or letter in seen:
            continue
        seen.add(letter)
        kind = _drive_type(mount)
        if kind == "unknown":  # psutil puts "removable" / "cdrom" in opts on Windows
            opts = (p.opts or "").lower()
            kind = "removable" if "removable" in opts else "cd" if "cdrom" in opts else "fixed"
        try:
            u = psutil.disk_usage(mount)
            total, free = int(u.total), int(u.free)
        except Exception:  # empty card reader / CD tray, or a disconnected network drive
            if kind == "cd":
                continue
            total = free = None
        out.append({"letter": letter, "mount": mount, "label": _volume_label(mount),
                    "kind": kind, "total": total, "free": free})
    return sorted(out, key=lambda d: d["letter"])


# ---------- words ----------

def _size(n) -> str:
    if n is None:
        return "unknown"
    gb = n / 1024 ** 3
    if gb >= 1024:
        return f"{gb / 1024:.1f} TB"
    if gb >= 10:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{n / 1024 ** 2:.0f} MB"


def _name(d: dict) -> str:
    """'pen drive E (KINGSTON)'"""
    label = f" ({d['label']})" if d.get("label") else ""
    return f"{_KIND_WORDS.get(d['kind'], 'drive')} {d['letter']}{label}"


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _space_words(d: dict) -> str:
    if d.get("total") is None:
        return f"I can't read the space on {_name(d)}."
    pct = round(100 * d["free"] / d["total"]) if d["total"] else 0
    return f"{_name(d)} has {_size(d['free'])} free of {_size(d['total'])} ({pct}% free)."


# ---------- which drive did they mean ----------

def _letter_of(text: str) -> str | None:
    t = text.strip().lower()
    m = re.fullmatch(r"(?:drive\s+)?([a-z])(?::\\?|:)?(?:\s+drive)?", t)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r"(?:drive\s+)?([a-z]+)(?:\s+drive)?", t)
    if m and m.group(1) in _SPOKEN_LETTERS:
        return _SPOKEN_LETTERS[m.group(1)].upper()
    return None


def _kind_of(text: str) -> str | None:
    t = text.lower()
    for pattern, kind in _KIND_ALIASES:
        if re.search(pattern, t):
            return kind
    return None


def _clean(text) -> str:
    t = re.sub(r"[^\w\s:\\-]", " ", str(text or "").lower())
    t = re.sub(r"\b(?:my|the|a|an|all|every|each|of|on|in)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _match(drive, drives: list[dict]) -> tuple[list[dict], str]:
    """(matching drives, words for what was asked). No drive asked -> all drives."""
    text = _clean(drive)
    if not text or text in ("drives", "drive", "disks", "disk"):
        return drives, "drive"
    letter = _letter_of(text)
    if letter:
        return [d for d in drives if d["letter"] == letter], f"{letter} drive"
    kind = _kind_of(text)
    if kind == "external":
        sysl = _system_letter()
        return ([d for d in drives if d["kind"] == "removable"
                 or (d["kind"] == "fixed" and d["letter"] != sysl and _is_usb_disk(d))], "external drive")
    if kind:
        return [d for d in drives if d["kind"] == kind], _KIND_WORDS[kind]
    label = re.sub(r"\b(?:drive|disk|disc)\b", " ", text).strip()
    if label:
        hits = [d for d in drives if d.get("label") and label in d["label"].lower()]
        if hits:
            return hits, f"{label} drive"
    return [], f"{text} drive" if "drive" not in text else text


def _is_usb_disk(d: dict) -> bool:
    """A fixed drive that is not C: and has a label counts as an external disk. We can't tell a second
    internal partition from a USB hard disk without WMI, so this is a best guess, only used for "external"."""
    return bool(d.get("label"))


# ---------- doing things ----------

def _open(mount: str) -> None:
    os.startfile(mount)  # type: ignore[attr-defined]


def _eject(letter: str) -> None:
    """Explorer's 'Eject' on This PC (Namespace 17). The letter is checked to be A-Z first."""
    if letter not in string.ascii_uppercase or len(letter) != 1:
        raise ValueError("bad drive letter")
    from jarvis.winutil import NO_WINDOW

    script = (f"$d=(New-Object -ComObject Shell.Application).Namespace(17).ParseName('{letter}:');"
              "if($d){$d.InvokeVerb('Eject')}")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                   capture_output=True, text=True, errors="replace", timeout=20, creationflags=NO_WINDOW)


def _still_there(letter: str) -> bool:
    return any(d["letter"] == letter for d in _drives())


def _pick_one(hits: list[dict], asked: str, action: str) -> tuple[dict | None, str | None]:
    if not hits:
        return None, f"I can't find a {asked}. Is it plugged in?"
    if len(hits) > 1:
        names = _join([_name(d) for d in hits])
        return None, f"You have more than one: {names}. Which drive letter should I {action}?"
    return hits[0], None


def drives(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "list").strip().lower().replace(" ", "_")
    action = _SYNONYMS.get(action, action)
    if action not in ACTIONS:
        return "I can list your drives, tell you the free space, open a drive, or eject a pen drive."
    if not _on_windows():
        return "Drive commands only work on Windows."
    try:
        all_drives = _drives()
    except Exception as e:
        return f"I couldn't read your drives: {e}"
    drive = args.get("drive")
    hits, asked = _match(drive, all_drives)

    if action == "list":
        if not _clean(drive) or asked == "drive":
            if not all_drives:
                return "I can't see any drives."
            return f"You have {len(all_drives)} drive{'s' if len(all_drives) != 1 else ''}: " \
                   f"{_join([_name(d) for d in all_drives])}."
        if not hits:
            return f"No, I can't see a {asked}."
        return f"Yes, {_join([_name(d) for d in hits])} {'is' if len(hits) == 1 else 'are'} connected."

    if action == "space":
        if not _clean(drive) or asked == "drive":
            return " ".join(_space_words(d) for d in all_drives) or "I can't see any drives."
        if not hits:
            return f"I can't find a {asked}."
        return " ".join(_space_words(d) for d in hits)

    if action == "open":
        if not _clean(drive) or asked == "drive":
            hits = [d for d in all_drives if d["kind"] == "removable"]
            asked = "pen drive"
        d, problem = _pick_one(hits, asked, "open")
        if problem:
            return problem
        try:
            _open(d["mount"])
        except Exception as e:
            return f"I couldn't open {_name(d)}: {e}"
        return f"Opening {_name(d)}."

    # eject
    if not _clean(drive) or asked == "drive":
        hits = [d for d in all_drives if d["kind"] in ("removable", "cd")]
        asked = "pen drive"
    d, problem = _pick_one(hits, asked, "eject")
    if problem:
        return problem
    if d["letter"] == _system_letter():
        return "That is the Windows drive, so I can't eject it."
    if d["kind"] in ("network", "ram"):
        return f"{_name(d)} can't be ejected. It is not a USB or disc drive."
    try:
        _eject(d["letter"])
    except Exception as e:
        return f"I couldn't eject {_name(d)}: {e}"
    end = time.monotonic() + EJECT_WAIT
    while True:
        try:
            gone = not _still_there(d["letter"])
        except Exception:
            gone = False
        if gone:
            return f"{_name(d)} is ejected. You can unplug it now."
        if time.monotonic() >= end:
            break
        time.sleep(0.5)
    if d["kind"] == "cd":
        return f"I asked Windows to eject {_name(d)}."
    return (f"I couldn't eject {_name(d)}. A file or app is probably still open on it. "
            "Close it and try again.")


# ---------- phrases (for nlu_features) ----------

_DRIVE_REF = (r"(?:(?:my |the |a |an )?(?:pen ?drive|pendrive|usb(?: drive| stick)?|flash ?drive|thumb ?drive|memory stick|"
              r"sd ?card|memory card|external (?:drive|hard ?drive|disk)|cd|dvd|cd drive|dvd drive|network drive|"
              r"removable (?:drive|disk))"
              r"|(?:my |the )?(?:[a-z]|dee|see|sea|ee|ef|gee)(?::)? drive|drive [a-z]\b|[a-z]:)")


def parse(text: str):
    """(intent, args) or None. Call before the old 'disk space' system_info rule and before open_app."""
    t = re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip("?.! ")
    if not t:
        return None

    def ref(m):
        return re.sub(r"^(?:my|the|a|an) ", "", m.strip())

    if re.fullmatch(r"(?:what|which) (?:drives|disks)(?: do i have| are (?:connected|plugged in|there)| are on (?:my|this) (?:pc|laptop|computer))?"
                    r"|(?:list|show)(?: me)?(?: all)?(?: my| the)? (?:drives|disks)|my drives", t):
        return "drives", {"action": "list"}
    m = re.fullmatch(rf"(?:is|are) ({_DRIVE_REF}) (?:connected|plugged in|there|detected|attached)", t)
    if m:
        return "drives", {"action": "list", "drive": ref(m.group(1))}
    m = re.fullmatch(rf"(?:how much|what is the|what's the)? ?(?:free )?(?:space|storage)(?: is)?(?: left| free| available)?"
                     rf"(?: is there)? (?:on|in) ({_DRIVE_REF})(?: left)?", t) \
        or re.fullmatch(rf"how (?:full|empty) is ({_DRIVE_REF})", t) \
        or re.fullmatch(rf"(?:free space|space left|storage) (?:on|in) ({_DRIVE_REF})", t)
    if m:
        return "drives", {"action": "space", "drive": ref(m.group(1))}
    if re.fullmatch(r"(?:how much )?(?:free )?(?:space|storage)(?: is left| left| free)? (?:on|in) (?:all|each|every) "
                    r"(?:my )?(?:drives?|disks?)", t):
        return "drives", {"action": "space"}
    m = re.fullmatch(rf"(?:open|show|explore|browse)(?: me)? ({_DRIVE_REF})", t)
    if m:
        return "drives", {"action": "open", "drive": ref(m.group(1))}
    m = re.fullmatch(rf"(?:eject|safely remove|unmount|remove)(?: the)? ({_DRIVE_REF})(?: safely)?", t)
    if m:
        return "drives", {"action": "eject", "drive": ref(m.group(1))}
    return None


CATALOG: dict[str, dict] = {
    "drives": {
        "description": ("Drives on this PC (USB pen drives, SD cards, other disks, CD, network drives): list them or "
                        "check one is connected, say free/total space on a drive (or all drives), open a drive in "
                        "File Explorer, or safely eject a pen drive / external disk. Never ejects the Windows drive."),
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "drive": {"type": "string",
                      "description": "Drive letter ('D'), kind ('pen drive', 'sd card', 'external', 'cd', 'network') "
                                     "or volume label. Leave out for all drives (list/space) or the only pen drive."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"drives": drives}
