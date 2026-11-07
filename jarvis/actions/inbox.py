"""Check email (read only). Never sends, deletes, moves or marks mail as read.

Two ways to read mail (config.yaml, section `email_account:`):
- IMAP (Gmail, Yahoo, iCloud, most others): needs an app password.
    email_account:
      provider: imap            # imap | outlook | auto (default auto)
      user: you@gmail.com
      password: ""              # better: setx JARVIS_IMAP_PASSWORD "your-app-password"
      host: ""                  # empty = guessed from the address
      port: 993
      folder: INBOX
- Outlook desktop app (Windows, needs pywin32 and Outlook set up). Works for
  Outlook.com / Microsoft 365 accounts, which no longer allow IMAP app passwords.

auto = IMAP when user + password are set, else Outlook desktop if it is installed.
Mail is opened read-only and only headers are fetched with BODY.PEEK, so nothing
is marked as read.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import re

PASSWORD_ENV = "JARVIS_IMAP_PASSWORD"
TIMEOUT = 15
DEFAULT_COUNT = 3
MAX_COUNT = 10
_SUBJECT_MAX = 90

_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com", "ymail.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
    "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com", "zoho.com": "imap.zoho.com",
    "aol.com": "imap.aol.com", "gmx.com": "imap.gmx.com",
}

SETUP_HELP = ("Email is not set up. Add your address under email_account in config.yaml, "
              "and set an app password with setx JARVIS_IMAP_PASSWORD.")

# --------------------------------------------------------------------------- settings


def _settings() -> dict:
    try:
        from jarvis.config import load_config

        cfg = load_config() or {}
    except Exception:
        cfg = {}
    acc = dict(cfg.get("email_account") or {})
    acc["_contacts"] = cfg.get("contacts") or {}
    return acc


def _password(acc: dict) -> str:
    return os.environ.get(PASSWORD_ENV) or str(acc.get("password") or "")


def _host(acc: dict) -> str:
    if acc.get("host"):
        return str(acc["host"])
    domain = str(acc.get("user") or "").rpartition("@")[2].lower()
    return _HOSTS.get(domain, f"imap.{domain}" if domain else "")


def _resolve_sender(name: str, contacts: dict) -> str:
    """'mom' -> mom's email from contacts, else the spoken text itself."""
    key = name.strip().lower()
    try:  # voice-saved + config contacts (contacts.py)
        from . import contacts as _ct

        saved = _ct.lookup(name)
        if saved and saved.get("email") and "@" in str(saved["email"]):
            return str(saved["email"])
    except Exception:
        pass
    c = contacts.get(key) if isinstance(contacts, dict) else None
    if c is None and isinstance(contacts, dict) and contacts:
        from . import fuzzy

        fk = fuzzy.contact(key, contacts)
        c = contacts.get(fk) if fk else None
    if isinstance(c, dict):
        c = c.get("email")
    return str(c) if c and "@" in str(c) else name.strip()


def _count(args: dict) -> int:
    try:
        n = int(args.get("count") or DEFAULT_COUNT)
    except (TypeError, ValueError):
        n = DEFAULT_COUNT
    return max(1, min(MAX_COUNT, n))


# --------------------------------------------------------------------------- helpers


def _decode(value) -> str:
    if not value:
        return ""
    try:
        text = str(email.header.make_header(email.header.decode_header(str(value))))
    except Exception:
        text = str(value)
    return re.sub(r"\s+", " ", text).strip()


def _sender_name(from_header: str) -> str:
    name, addr = email.utils.parseaddr(_decode(from_header))
    return name.strip(' "') or addr or "unknown sender"


def _short(subject: str) -> str:
    subject = subject or "no subject"
    return subject if len(subject) <= _SUBJECT_MAX else subject[: _SUBJECT_MAX - 3].rstrip() + "..."


def _imap_quote(text: str) -> str:
    return '"' + re.sub(r'["\\\r\n]', "", text) + '"'


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# --------------------------------------------------------------------------- IMAP


def _imap_fetch(acc: dict, sender: str, unread_only: bool, count: int) -> tuple[int, int, list[tuple[str, str]]]:
    """Return (matching total, unread among them, [(from, subject)] newest first)."""
    conn = imaplib.IMAP4_SSL(_host(acc), int(acc.get("port") or 993), timeout=TIMEOUT)
    try:
        conn.login(str(acc["user"]), _password(acc))
        status, _ = conn.select(_imap_quote(str(acc.get("folder") or "INBOX")), readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error("cannot open folder")

        def search(*criteria: str) -> list[bytes]:
            status, data = conn.uid("SEARCH", *criteria)
            if status != "OK":
                raise imaplib.IMAP4.error("search failed")
            return (data[0] or b"").split() if data else []

        base = ("FROM", _imap_quote(sender)) if sender else ()
        unread = search(*base, "UNSEEN") if base else search("UNSEEN")
        if sender:
            ids = unread if unread_only else search(*base)
        else:
            ids = unread if unread_only else search("ALL")
        items = []
        for uid in reversed(ids[-count:]):
            status, data = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            raw = next((part[1] for part in data or [] if isinstance(part, tuple)), b"")
            if status != "OK" or not raw:
                continue
            msg = email.message_from_bytes(raw)
            items.append((_sender_name(msg.get("From", "")), _short(_decode(msg.get("Subject", "")))))
        return len(ids), len(unread), items
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# --------------------------------------------------------------------------- Outlook desktop


def _outlook_available() -> bool:
    try:
        import win32com.client  # noqa: F401
    except Exception:
        return False
    return True


def _outlook_fetch(sender: str, unread_only: bool, count: int, scan: int = 300) -> tuple[int, int, list[tuple[str, str]]]:
    import win32com.client

    from jarvis.winutil import com_init

    com_init()
    inbox = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI").GetDefaultFolder(6)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)  # newest first
    want = sender.lower()
    total = unread = 0
    found: list[tuple[str, str]] = []
    item = items.GetFirst()
    seen = 0
    while item is not None and seen < scan:
        seen += 1
        if getattr(item, "Class", 43) == 43:  # 43 = mail item
            name = str(getattr(item, "SenderName", "") or "")
            addr = ""
            if want and want not in name.lower():  # the address can show an Outlook security pop-up: read it only if needed
                try:
                    addr = str(item.SenderEmailAddress or "")
                except Exception:
                    addr = ""
            is_unread = bool(getattr(item, "UnRead", False))
            if not want or want in name.lower() or want in addr.lower():
                if is_unread:
                    unread += 1
                if is_unread or not unread_only:
                    total += 1
                    if len(found) < count:
                        found.append((name or addr or "unknown sender", _short(str(item.Subject or ""))))
        item = items.GetNext()
    return total, unread, found


# --------------------------------------------------------------------------- handler


def _reply(sender: str, unread_only: bool, total: int, unread: int, items: list[tuple[str, str]]) -> str:
    who = f" from {sender}" if sender else ""
    if total == 0:
        return f"No new emails{who}." if unread_only else f"I found no emails{who}."
    listing = " ".join(f"{i}. From {f}: {s}." for i, (f, s) in enumerate(items, 1))
    if unread_only:
        head = f"You have {_plural(total, 'new email')}{who}."
    elif sender:
        head = f"You have {_plural(total, 'email')}{who}, {unread} new."
    else:
        head = f"Your latest emails. You have {unread} new."
    if len(items) < total and unread_only:
        head += f" Here are the latest {len(items)}." if len(items) > 1 else " Here is the latest."
    return f"{head} {listing}".strip()


def check_email(args: dict) -> str:
    acc = _settings()
    count = _count(args)
    spoken = str(args.get("from") or "").strip()
    sender = _resolve_sender(spoken, acc["_contacts"]) if spoken else ""
    unread_only = args.get("unread_only")
    if unread_only is None:  # default: new mail only, unless asking about one sender
        unread_only = not sender
    unread_only = bool(unread_only)

    provider = str(acc.get("provider") or "auto").lower()
    use_imap = provider == "imap" or (provider == "auto" and acc.get("user") and _password(acc))
    try:
        if use_imap:
            if not acc.get("user") or not _password(acc):
                return SETUP_HELP
            if not _host(acc):
                return "I don't know your mail server. Add host under email_account in config.yaml."
            total, unread, items = _imap_fetch(acc, sender, unread_only, count)
        elif provider in ("outlook", "auto") and _outlook_available():
            total, unread, items = _outlook_fetch(sender, unread_only, count)
        elif provider == "outlook":
            return "I can't reach the Outlook app. Check that Outlook is installed and pywin32 is installed."
        else:
            return SETUP_HELP
    except imaplib.IMAP4.error as e:
        if "auth" in str(e).lower() or "login" in str(e).lower() or "credential" in str(e).lower():
            return "Email login failed. Check your address and app password."
        return "I couldn't read your email. The mail server said no."
    except OSError:
        return "I couldn't reach the mail server. Check the internet connection."
    except Exception:
        return "I couldn't read your email."
    return _reply(spoken or sender, unread_only, total, unread, items)


# --------------------------------------------------------------------------- wiring

CATALOG: dict[str, dict] = {
    "check_email": {
        "description": ("Check the user's email inbox (read only: never sends or deletes). "
                        "Says how many new emails and the sender and subject of the latest ones. "
                        "Use for 'do I have new emails', 'read my latest emails', 'any email from mom'."),
        "properties": {
            "from": {"type": "string", "description": "Only emails from this person (contact name or email address)."},
            "count": {"type": "integer", "description": f"How many emails to read out, 1-{MAX_COUNT}. Default {DEFAULT_COUNT}."},
            "unread_only": {"type": "boolean",
                            "description": "true = only new (unread) emails. false = latest emails, read or not. "
                                           "Default: true, or false when 'from' is given."},
        },
        "required": [],
        "info": True,
    },
}

HANDLERS = {"check_email": check_email}
