"""Create, copy, move, rename and delete files and folders by voice.

Safety:
- Only works inside your user folder (C:/Users/<you>). System folders are never touched.
- Delete sends to the Recycle Bin (you can restore it) and always asks "are you sure?" first.
- Never overwrites: if the target name exists, it says so.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

MAX_SCAN = 30000
_FOLDERS = {
    "downloads": "Downloads", "download": "Downloads", "documents": "Documents", "document": "Documents",
    "docs": "Documents", "desktop": "Desktop", "pictures": "Pictures", "photos": "Pictures", "images": "Pictures",
    "music": "Music", "videos": "Videos", "video": "Videos", "home": "",
}
_SEARCH_IN = ("desktop", "documents", "downloads", "pictures", "music", "videos")


def home() -> Path:
    return Path.home()


def known_folder(name: str) -> Path | None:
    key = " ".join((name or "").lower().replace("folder", "").split())
    key = key.removeprefix("my ").removeprefix("the ").strip()
    if key not in _FOLDERS:
        from . import fuzzy  # "down loads" -> downloads (folders only, never file names)

        key = fuzzy.folder(key, _FOLDERS)
        if key is None:
            return None
    sub = _FOLDERS[key]
    for base in (home(), home() / "OneDrive"):  # OneDrive often moves Desktop/Documents/Pictures
        p = base / sub
        if p.is_dir():
            return p
    return home() / sub


def is_network_path(p) -> bool:
    """True for paths on another computer (\\\\host\\share, //host/share, \\\\?\\UNC\\..., file://host).
    Opening one makes Windows connect to that host and send the login hash, so callers refuse it
    BEFORE touching the path (no isfile/resolve on it)."""
    s = str(p or "").strip().strip('"').replace("/", "\\").lower()
    return s.startswith("\\\\") or s.startswith("file:")


def inside_home(p: Path) -> bool:
    try:
        p.resolve().relative_to(home().resolve())
        return True
    except ValueError:
        return False


def _protected(p: Path) -> bool:
    """User root folders themselves (Desktop, Documents, ...) and home can't be moved or deleted."""
    # Both the local and the OneDrive copy of each folder, and the OneDrive folder itself.
    roots = {home().resolve(), (home() / "OneDrive").resolve()}
    for sub in _FOLDERS.values():
        roots |= {(home() / sub).resolve(), (home() / "OneDrive" / sub).resolve()}
    return p.resolve() in roots


def _walk_roots():
    seen = []
    for n in _SEARCH_IN:
        p = known_folder(n)
        if p and p.is_dir() and p not in seen:
            seen.append(p)
    return seen


def locate(name: str, want_dir: bool | None = None) -> Path | None:
    """Find a file or folder by (part of) its name in the user's folders. Exact name wins."""
    want = " ".join((name or "").lower().split())
    if not want:
        return None
    direct = Path(os.path.expanduser(name))
    if direct.is_absolute() and direct.exists():
        return direct
    folder = known_folder(want)
    if folder and want_dir is not False:
        return folder
    best, seen = None, 0
    for root in _walk_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d.lower() not in ("node_modules", "appdata")]
            items = []
            if want_dir is not False:
                items += [(d, True) for d in dirnames]
            if want_dir is not True:
                items += [(f, False) for f in filenames]
            for item, _is_dir in items:
                seen += 1
                low = item.lower()
                if low == want or os.path.splitext(low)[0] == want:
                    return Path(dirpath) / item
                if best is None and want in low:
                    best = Path(dirpath) / item
                if seen > MAX_SCAN:
                    return best
    return best


# Small cache so "are you sure?" and the real delete find the same file.
_cache: dict[str, tuple[float, Path | None]] = {}
CACHE_SECONDS = 60


def locate_cached(name: str) -> Path | None:
    key = (name or "").lower().strip()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS and (hit[1] is None or hit[1].exists()):
        return hit[1]
    p = locate(name)
    if p is not None:  # only remember hits: a file made a moment ago must still be found
        _cache[key] = (time.monotonic(), p)
    return p


def _dest_dir(to: str) -> Path | None:
    to = (to or "").strip()
    if not to:
        return None
    p = known_folder(to)
    if p:
        return p
    direct = Path(os.path.expanduser(to))
    if direct.is_absolute():
        return direct if direct.is_dir() else None
    return locate(to, want_dir=True)


def _where(p: Path) -> str:
    return p.parent.name or str(p.parent)


# ---------- actions ----------
def create_item(args: dict) -> str:
    """args: kind file|folder, name, where (folder name, default desktop)."""
    kind = args.get("kind", "folder")
    name = str(args.get("name") or "").strip().strip(".")
    if not name or any(c in name for c in '<>:"/\\|?*'):
        return "What should I call it?"
    base = _dest_dir(args.get("where") or "desktop")
    if base is None or not inside_home(base):
        return "I can only create things inside your user folders."
    if kind == "file" and not os.path.splitext(name)[1]:
        name += ".txt"
    target = base / name
    if target.exists():
        return f"{name} already exists in {base.name}."
    if kind == "file":
        target.touch()
    else:
        target.mkdir(parents=True)
    return f"Created the {'file' if kind == 'file' else 'folder'} {name} in {base.name}."


def _transfer(args: dict, move: bool) -> str:
    verb = "move" if move else "copy"
    src = locate(str(args.get("name") or ""))
    if not src:
        return f"I couldn't find {args.get('name') or 'that'}."
    dest_dir = _dest_dir(str(args.get("to") or ""))
    if dest_dir is None:
        return f"I couldn't find the folder {args.get('to') or ''}. Where should I {verb} it?"
    if not inside_home(src) or not inside_home(dest_dir):
        return "I can only work inside your user folders."
    if move and _protected(src):
        return f"I won't move your {src.name} folder."
    if src.is_dir() and dest_dir.resolve().is_relative_to(src.resolve()):
        return f"I can't put {src.name} inside itself."
    target = dest_dir / src.name
    if target.exists():
        return f"{src.name} is already in {dest_dir.name}."
    if move:
        shutil.move(str(src), str(target))
        return f"Moved {src.name} to {dest_dir.name}."
    if src.is_dir():
        shutil.copytree(src, target)
    else:
        shutil.copy2(src, target)
    return f"Copied {src.name} to {dest_dir.name}."


def copy_file(args: dict) -> str:
    return _transfer(args, move=False)


def move_file(args: dict) -> str:
    return _transfer(args, move=True)


def rename_file(args: dict) -> str:
    src = locate(str(args.get("name") or ""))
    new = str(args.get("new_name") or "").strip().strip(".")
    if not src:
        return f"I couldn't find {args.get('name') or 'that'}."
    if not new or any(c in new for c in '<>:"/\\|?*'):
        return "What should the new name be?"
    if not inside_home(src) or _protected(src):
        return "I can't rename that."
    if src.is_file() and not os.path.splitext(new)[1]:
        new += src.suffix  # keep the file type
    target = src.with_name(new)
    if target.exists():
        return f"There is already a {new} there."
    src.rename(target)
    return f"Renamed {src.name} to {new}."


def _trash(path: Path) -> None:
    from send2trash import send2trash

    send2trash(str(path))


def delete_question(args: dict) -> str | None:
    """Words for 'Are you sure you want to ...?' or None if there is nothing to delete."""
    p = locate_cached(str(args.get("name") or ""))
    if not p or not inside_home(p) or _protected(p):
        return None
    return f"move {p.name} from {_where(p)} to the recycle bin"


def delete_file(args: dict) -> str:
    """Only deletes when args has confirm=True (actions asks first). Sends to the Recycle Bin."""
    name = str(args.get("name") or "")
    p = locate_cached(name)
    if not p:
        return f"I couldn't find {name or 'that'}."
    if not inside_home(p) or _protected(p):
        return f"I won't delete {p.name}."
    if args.get("confirm") is not True:
        return f"Say yes to move {p.name} to the recycle bin."
    _trash(p)
    _cache.pop(name.lower().strip(), None)
    return f"Moved {p.name} to the recycle bin."
