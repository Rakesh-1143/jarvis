"""Recent files (piece O): newest downloads and recently used files.

Says: "open my last download", "what did I download today", "open the last PDF",
"show recent files", "open my latest picture on the desktop".

Folders: downloads, desktop, documents (newest by modified time, top level only)
and recent (Windows Recent folder, %APPDATA%\\Microsoft\\Windows\\Recent, .lnk files).
Read and open only: never moves or deletes anything.
Config (optional): `downloads_folder` to override ~/Downloads.
Wiring: merge CATALOG and HANDLERS. Not risky. `recent_files` with action list is info.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

KINDS: dict[str, set[str]] = {
    "pdf": {".pdf"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".svg"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma"},
    "doc": {".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".md", ".pdf"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "app": {".exe", ".msi"},
}
# Spoken words -> kind key.
_KIND_WORDS = {
    "pdf": "pdf", "pdfs": "pdf",
    "image": "image", "images": "image", "picture": "image", "pictures": "image", "photo": "image",
    "photos": "image", "screenshot": "image", "screenshots": "image", "pic": "image", "pics": "image",
    "video": "video", "videos": "video", "movie": "video", "movies": "video", "clip": "video",
    "audio": "audio", "song": "audio", "songs": "audio", "music": "audio",
    "doc": "doc", "docs": "doc", "document": "doc", "documents": "doc", "word": "doc",
    "excel": "doc", "sheet": "doc", "spreadsheet": "doc", "file": "", "files": "",
    "zip": "archive", "zips": "archive", "archive": "archive", "archives": "archive",
    "app": "app", "installer": "app", "setup": "app", "exe": "app",
}
_FOLDER_WORDS = {
    "downloads": "downloads", "download": "downloads", "downloaded": "downloads",
    "desktop": "desktop", "documents": "documents", "document": "documents", "my documents": "documents",
    "recent": "recent", "recents": "recent", "recently used": "recent", "recent files": "recent",
}
_FOLDER_NAMES = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents"}
_SKIP_EXT = {".crdownload", ".part", ".partial", ".tmp", ".download", ".ini", ".lnk"}
_ORDINALS = {"first": 1, "last": 1, "latest": 1, "newest": 1, "second": 2, "third": 3,
             "fourth": 4, "fifth": 5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

LIST_COUNT = 5

# Files that run code when opened. Never opened by voice: a bad download would run with one command.
RUNNABLE = {".exe", ".msi", ".msix", ".appx", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
            ".wsf", ".wsh", ".hta", ".scr", ".pif", ".cpl", ".msc", ".jar", ".lnk", ".url", ".reg", ".inf", ".application",
            ".appref-ms", ".py", ".pyw", ".iso", ".img", ".vhd", ".vhdx",
            # N4: more types Windows runs or treats as risky
            ".chm", ".msp", ".mst", ".diagcab", ".search-ms", ".searchconnector-ms", ".library-ms",
            ".settingcontent-ms", ".scf", ".website", ".jnlp", ".xll", ".gadget", ".ps1xml", ".psc1", ".mht",
            ".mhtml", ".svg", ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppsm", ".ppam"}


@dataclass
class Item:
    name: str   # name to say ("report.pdf")
    path: str   # path to open (file, or .lnk for the Recent folder)
    time: float  # modified time (epoch seconds)


# ---------- helpers ----------
def _startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


def _config() -> dict:
    try:
        from ..config import load_config

        return load_config() or {}
    except Exception:
        return {}


def folder_path(folder: str) -> str:
    """Real path of a folder key."""
    if folder == "recent":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return os.path.join(appdata, "Microsoft", "Windows", "Recent")
    if folder == "downloads":
        custom = _config().get("downloads_folder")
        if custom:
            return os.path.expanduser(str(custom))
    if folder in ("desktop", "documents"):  # these are often moved to OneDrive
        try:
            from .fileops import known_folder

            p = known_folder(folder)
            if p is not None:
                return str(p)
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), _FOLDER_NAMES.get(folder, "Downloads"))


def norm_folder(spoken: str | None) -> str:
    s = (spoken or "").lower().strip()
    s = s.removeprefix("my ").removeprefix("the ").strip()
    return _FOLDER_WORDS.get(s, s if s in ("downloads", "desktop", "documents", "recent") else "downloads")


def norm_kind(spoken: str | None) -> str:
    s = (spoken or "").lower().strip().strip(".")
    if s in KINDS:
        return s
    return _KIND_WORDS.get(s, "")


def _which(value) -> int:
    """1 = newest. Accepts 2, "2", "second"."""
    if value is None or value == "":
        return 1
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = _ORDINALS.get(str(value).lower().strip(), 1)
    return max(1, n)


def _since(when: str | None, now: float | None = None) -> float | None:
    """Start time for 'today' / 'yesterday' / 'week'. None = no limit."""
    w = (when or "").lower().strip()
    if not w or w in ("any", "all", "ever"):
        return None
    now_dt = datetime.fromtimestamp(now if now is not None else time.time())
    midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if w == "today":
        return midnight.timestamp()
    if w == "yesterday":
        return (midnight - timedelta(days=1)).timestamp()
    if w in ("week", "this week", "last week", "7 days"):
        return (now_dt - timedelta(days=7)).timestamp()
    if w in ("hour", "last hour"):
        return (now_dt - timedelta(hours=1)).timestamp()
    return None


def _until(when: str | None, now: float | None = None) -> float | None:
    """End time: only 'yesterday' has one (today's midnight)."""
    if (when or "").lower().strip() != "yesterday":
        return None
    now_dt = datetime.fromtimestamp(now if now is not None else time.time())
    return now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _kind_of(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def scan(folder: str, kind: str = "", since: float | None = None,
         until: float | None = None) -> list[Item]:
    """Files in a folder, newest first. Recent folder: .lnk shortcuts to files."""
    path = folder_path(folder)
    items: list[Item] = []
    try:
        entries = list(os.scandir(path))
    except OSError:
        return []
    exts = KINDS.get(kind)
    for e in entries:
        try:
            if not e.is_file() or e.name.startswith((".", "~$")):
                continue
            name = e.name
            if folder == "recent":
                if not name.lower().endswith(".lnk"):
                    continue
                name = name[:-4]
                if not os.path.splitext(name)[1]:
                    continue  # shortcut to a folder, not a file
            elif _kind_of(name) in _SKIP_EXT or name.lower() == "desktop.ini":
                continue
            if exts and _kind_of(name) not in exts:
                continue
            st = e.stat()
            # On Windows st_ctime is the creation time (= download time).
            t = max(st.st_mtime, st.st_ctime) if os.name == "nt" else st.st_mtime
            if since is not None and t < since:
                continue
            if until is not None and t >= until:
                continue
            items.append(Item(name, e.path, t))
        except OSError:
            continue
    items.sort(key=lambda i: i.time, reverse=True)
    return items


def _ago(t: float, now: float | None = None) -> str:
    now = now if now is not None else time.time()
    then, today = datetime.fromtimestamp(t), datetime.fromtimestamp(now)
    days = (today.date() - then.date()).days
    clock = then.strftime("%I:%M %p").lstrip("0")
    if days <= 0:
        mins = int((now - t) // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        return f"today at {clock}"
    if days == 1:
        return f"yesterday at {clock}"
    if days < 7:
        return f"{days} days ago"
    return then.strftime("%d %B").lstrip("0")


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _what(folder: str, kind: str, when: str) -> str:
    noun = {"pdf": "PDFs", "image": "pictures", "video": "videos", "audio": "audio files",
            "doc": "documents", "archive": "zip files", "app": "installers"}.get(kind, "files")
    place = {"downloads": "in Downloads", "desktop": "on the Desktop",
             "documents": "in Documents", "recent": "recently used"}.get(folder, "")
    w = (when or "").lower().strip()
    tail = {"today": " from today", "yesterday": " from yesterday", "week": " from this week",
            "this week": " from this week", "hour": " from the last hour"}.get(w, "")
    return f"{noun} {place}{tail}".strip()


# ---------- handler ----------
def recent_files(args: dict) -> str:
    """args: folder? (downloads|desktop|documents|recent), kind? (pdf|image|video|audio|doc|archive|app),
    action? (list|open, default list), when? (today|yesterday|week), which? (1 = newest), count?"""
    folder = norm_folder(args.get("folder"))
    kind = norm_kind(args.get("kind"))
    when = str(args.get("when") or "")
    action = str(args.get("action") or "list").lower().strip()
    items = scan(folder, kind, _since(when), _until(when))

    if not items:
        if not os.path.isdir(folder_path(folder)):
            return f"I can't find your {folder} folder."
        return f"I found no {_what(folder, kind, when)}."

    if action == "open":
        n = _which(args.get("which"))
        if n > len(items):
            return f"There are only {len(items)} {_what(folder, kind, when)}."
        item = items[n - 1]
        if _kind_of(item.name) in RUNNABLE or _kind_of(item.path) in RUNNABLE and folder != "recent":
            return (f"{item.name} is a program or script. For safety I won't run it by voice. "
                    "Open it yourself if you trust it.")
        try:
            _startfile(item.path)
        except OSError as e:
            return f"I couldn't open {item.name}: {e.strerror or e}."
        return f"Opening {item.name}."

    try:
        count = max(1, min(10, int(args.get("count") or LIST_COUNT)))
    except (TypeError, ValueError):
        count = LIST_COUNT
    shown = items[:count]
    parts = [f"{i.name}, {_ago(i.time)}" for i in shown]
    head = f"Your newest {_what(folder, kind, when)}"
    if len(items) > count:
        head += f" ({len(items)} in total)"
    if when and len(items) <= count:
        w = _what(folder, kind, when)
        head = w[0].upper() + w[1:]
    return f"{head}: {_join(parts)}."


_FOLDER = {"type": "string", "enum": ["downloads", "desktop", "documents", "recent"],
           "description": "Where to look. downloads (default), desktop, documents, or recent = recently used files."}
CATALOG: dict[str, dict] = {
    "recent_files": {
        "description": ("List or open the newest files in Downloads/Desktop/Documents, or recently used files. "
                        "E.g. 'open my last download', 'what did I download today', 'open the last PDF'. "
                        "Read and open only."),
        "properties": {
            "folder": _FOLDER,
            "kind": {"type": "string", "enum": ["pdf", "image", "video", "audio", "doc", "archive", "app"],
                     "description": "Only this type of file."},
            "action": {"type": "string", "enum": ["list", "open"], "description": "list (default) or open."},
            "when": {"type": "string", "enum": ["today", "yesterday", "week", "hour"],
                     "description": "Only files from this time."},
            "which": {"type": "integer", "description": "For open: 1 = newest (default), 2 = second newest."},
            "count": {"type": "integer", "description": "For list: how many to say (default 5, max 10)."},
        },
        "required": [],
        "info": False,  # not info-only: it can open files, so the AI must not run it during a lookup
    },
}

HANDLERS = {"recent_files": recent_files}
