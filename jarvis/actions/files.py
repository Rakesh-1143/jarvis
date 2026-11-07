"""Open folders and files, notes, and email drafts."""
from __future__ import annotations

import datetime as _dt
import os
import re
import urllib.parse
from pathlib import Path

NOTES_FILE = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis notes.txt")
CONTACTS: dict[str, object] = {}  # spoken name -> "email" or {email, phone}, from config.yaml "contacts"
MEMORY_FILE = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis memory.txt")
WHATSAPP_AUTO_SEND = False  # True = press Enter for you (Jarvis asks "are you sure?" first)
WHATSAPP_SEND_DELAY = 6  # seconds to wait for WhatsApp to open before pressing Enter
MAX_FILES_TO_SCAN = 30000

_FOLDERS = {
    "downloads": "Downloads", "download": "Downloads",
    "documents": "Documents", "document": "Documents", "docs": "Documents",
    "desktop": "Desktop", "pictures": "Pictures", "photos": "Pictures", "images": "Pictures",
    "music": "Music", "videos": "Videos", "video": "Videos",
    "home": "", "user": "",
}


def _startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


def _known_folder(name: str) -> Path | None:
    key = name.lower().strip()
    if key not in _FOLDERS:
        from . import fuzzy  # "down loads" -> downloads

        key = fuzzy.folder(key, _FOLDERS)
        if key is None:
            return None
    home = Path.home()
    sub = _FOLDERS[key]
    for base in (home, home / "OneDrive"):  # OneDrive often moves Documents/Desktop/Pictures
        p = base / sub
        if p.is_dir():
            return p
    return home / sub


def open_folder(args: dict) -> str:
    name = (args.get("name") or "").strip()
    if not name:
        return "Which folder should I open?"
    path = _known_folder(name) or Path(os.path.expanduser(name))
    if not path.is_dir():
        return f"I couldn't find the {name} folder."
    _startfile(str(path))
    return f"Opening {name}." if name.lower() != "home" else "Opening your home folder."


def find_file(name: str, roots: list[Path] | None = None) -> Path | None:
    """First file whose name contains `name` (ignores case and extension)."""
    want = name.lower().strip()
    if not want:
        return None
    if roots is None:
        roots = [p for p in (_known_folder(f) for f in ("desktop", "documents", "downloads", "pictures", "music", "videos")) if p]
    seen = 0
    best = None
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d.lower() != "node_modules"]
            for f in filenames:
                seen += 1
                stem = os.path.splitext(f)[0].lower()
                if stem == want:
                    return Path(dirpath) / f
                if best is None and want in f.lower():
                    best = Path(dirpath) / f
                if seen > MAX_FILES_TO_SCAN:
                    return best
    return best


def open_file(args: dict) -> str:
    name = (args.get("name") or "").strip()
    if not name:
        return "Which file should I open?"
    path = find_file(name)
    if not path:
        return f"I couldn't find a file called {name}."
    _startfile(str(path))
    return f"Opening {path.name}."


# ---------- notes ----------
def add_note(args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "What should I write in the note?"
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {text}\n")
    return "Noted."


def read_notes(args: dict, count: int = 5) -> str:
    try:
        with open(NOTES_FILE, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        lines = []
    if not lines:
        return "You have no notes."
    last = [ln.split("] ", 1)[-1] for ln in lines[-count:]]
    return f"Your last {len(last)} notes: " + " ... ".join(last) + "."


# ---------- email (opens a draft, never sends) ----------
def email(args: dict) -> str:
    to = (args.get("to") or "").strip()
    to = _contact(to, "email") or to
    if to and "@" not in to:
        to = ""  # unknown name: let the user type the address
    query = urllib.parse.urlencode(
        {k: v for k, v in (("subject", args.get("subject")), ("body", args.get("body"))) if v},
        quote_via=urllib.parse.quote,
    )
    url = f"mailto:{urllib.parse.quote(to, safe='@')}" + (f"?{query}" if query else "")
    import webbrowser

    webbrowser.open(url)
    return "I opened an email draft. Check it and press send."


def _contact(name: str, field: str) -> str:
    try:  # voice-saved contacts + config.yaml contacts (contacts.py, piece AX)
        from . import contacts

        saved = contacts.lookup(name)
        if saved and saved.get(field):
            return str(saved[field])
    except Exception:
        pass
    c = CONTACTS.get(name.lower().strip())
    if c is None:
        from . import fuzzy  # "rohith" -> rohit; two close names = no guess

        key = fuzzy.contact(name, CONTACTS)
        c = CONTACTS.get(key) if key else None
    if isinstance(c, dict):
        return str(c.get(field) or "")
    if isinstance(c, str) and field == "email" and "@" in c:
        return c
    return ""


# ---------- WhatsApp (WhatsApp Desktop app) ----------
def contact_name(name: str) -> str:
    """The saved contact that a spoken name matches (fuzzy), for "are you sure?" questions. Else the name."""
    n = (name or "").strip()
    try:
        from . import contacts

        saved = contacts.lookup(n)
        if saved and saved.get("name"):
            return str(saved["name"])
    except Exception:
        pass
    if n.lower() in CONTACTS:
        return n
    try:
        from . import fuzzy

        return fuzzy.contact(n, CONTACTS) or n
    except Exception:
        return n


def whatsapp_needs_confirm(args: dict) -> bool:
    return WHATSAPP_AUTO_SEND


def whatsapp(args: dict) -> str:
    to = (args.get("to") or "").strip()
    text = (args.get("text") or "").strip()
    if not to:
        return "Who should I message?"
    phone = _contact(to, "phone") or (to if re.fullmatch(r"\+?[\d ]{7,}", to) else "")
    phone = re.sub(r"[^\d]", "", phone)
    if not phone:
        return f"I don't have a phone number for {to}. Say: add contact {to} phone, then the number."
    _startfile(f"whatsapp://send?phone={phone}&text={urllib.parse.quote(text)}")
    if WHATSAPP_AUTO_SEND and args.get("confirm") and text:
        import time

        import pyautogui

        time.sleep(WHATSAPP_SEND_DELAY)
        try:
            title = str(pyautogui.getActiveWindowTitle() or "")
        except Exception:
            title = ""
        if "whatsapp" not in title.lower():  # never press Enter in some other window
            return f"I opened WhatsApp with your message to {to}, but it is not in front. Press Enter to send."
        pyautogui.press("enter")
        return f"Sent your WhatsApp message to {to}."
    return f"I opened WhatsApp with your message to {to}. Press Enter to send."


# ---------- long-term memory (facts the AI should always know) ----------
def remember(args: dict) -> str:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return "What should I remember?"
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(fact.replace("\n", " ") + "\n")
    return "Got it, I will remember that."


def memories() -> list[str]:
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return []


def recall(args: dict) -> str:
    facts = memories()
    if not facts:
        return "I don't remember anything yet. Say: remember that ..."
    return "I remember: " + " ... ".join(facts[-10:]) + "."


def forget_memory(args: dict) -> str:
    try:
        os.remove(MEMORY_FILE)
    except FileNotFoundError:
        pass
    return "Okay, I forgot everything you told me to remember."
