"""Contacts by voice (piece AX): phone, email, birthday and notes for people.

Says: "add contact Ravi phone 98765 43210", "Ravi's email is ravi at gmail dot com",
"what's Ravi's number", "show Ravi's details", "delete contact Ravi" (asks yes first),
"list my contacts".

Storage: config `contacts_file` (default "~/.jarvis/contacts.json", not synced by OneDrive).
File format: {"ravi": {"name": "Ravi", "phone": "+919876543210", "email": "...",
                        "birthday": "05-05" or "1990-05-05", "notes": "..."}}
Contacts in config.yaml `contacts:` are also read (they are read-only here). When a name is in
both, the saved file's fields win, and empty fields fall back to config.yaml.

For other modules (wiring thread connects them):
    lookup(name) -> dict | None     {"name", "phone", "email", "birthday", "notes"}; fuzzy, never guesses a tie
    all_contacts() -> dict          {key: that dict} for every contact (birthdays.py can read this)
    parse(text) -> (intent, args) | None    phrase rules for nlu_features.py
    risky_text(args) -> str | None  question words for contact_delete
Wiring: merge CATALOG and HANDLERS; treat `contact_delete` as risky.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading

DEFAULT_FILE = "~/.jarvis/contacts.json"
CONTACTS_FILE = ""  # empty = read config on first use
FIELDS = ("phone", "email", "birthday", "notes")
MAX_SPOKEN = 20  # names read out by "list my contacts"
_lock = threading.Lock()

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_DIGIT_WORDS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_FIELD_WORDS = {
    "number": "phone", "phone": "phone", "phone number": "phone", "mobile": "phone",
    "mobile number": "phone", "cell": "phone", "cell number": "phone", "contact number": "phone",
    "email": "email", "e-mail": "email", "email address": "email", "e-mail address": "email",
    "mail": "email", "mail id": "email", "email id": "email",
    "birthday": "birthday", "date of birth": "birthday", "birth date": "birthday", "dob": "birthday",
    "notes": "notes", "note": "notes",
    "details": "all", "info": "all", "contact": "all", "contact details": "all",
}
_SAY_FIELD = {"phone": "number", "email": "email", "birthday": "birthday", "notes": "notes"}


# ---------- storage ----------
def _path() -> str:
    global CONTACTS_FILE
    if not CONTACTS_FILE:
        try:
            from ..config import load_config

            CONTACTS_FILE = load_config().get("contacts_file") or DEFAULT_FILE
        except Exception:
            CONTACTS_FILE = DEFAULT_FILE
    return os.path.expanduser(str(CONTACTS_FILE))


def _load() -> dict[str, dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[_key(k)] = {"name": str(v.get("name") or k),
                            **{f: str(v[f]) for f in FIELDS if v.get(f)}}
    return out


def _save(data: dict[str, dict]) -> None:
    path = _path()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # never leaves a half-written file


def _config_contacts() -> dict:
    """config.yaml `contacts:` -> {key: {name, phone?, email?, ...}}. A plain string value is an email."""
    try:
        from ..config import load_config

        raw = load_config().get("contacts") or {}
    except Exception:
        raw = {}
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        entry = {"name": str(k)}
        if isinstance(v, dict):
            entry.update({f: str(v[f]) for f in FIELDS if v.get(f)})
        elif isinstance(v, str) and "@" in v:
            entry["email"] = v.strip()
        out[_key(k)] = entry
    return out


def all_contacts() -> dict[str, dict]:
    """Every contact: config.yaml ones plus saved ones (saved fields win). Keys are lower case."""
    merged = {k: dict(v) for k, v in _config_contacts().items()}
    for k, v in _load().items():
        base = merged.get(k, {})
        merged[k] = {**base, **{f: x for f, x in v.items() if x}}
    return merged


# ---------- text helpers ----------
def _key(name) -> str:
    return " ".join(str(name or "").lower().split())


def clean_name(spoken) -> str:
    """"my mom's" -> "mom", "Ravi Kumar" -> "Ravi Kumar"."""
    n = str(spoken or "").strip(" .,!?\"")
    n = re.sub(r"^(?:my|the)\s+", "", n, flags=re.I)
    n = re.sub(r"(?:'s|’s|')$", "", n, flags=re.I)
    n = re.sub(r"\s+(?:contact|from (?:my )?contacts)$", "", n, flags=re.I)
    return " ".join(n.split())


def _find_key(name: str, contacts: dict) -> str | None:
    k = _key(clean_name(name))
    if not k:
        return None
    if k in contacts:
        return k
    from . import fuzzy  # "rohith" -> rohit; two close names = no guess

    return fuzzy.contact(k, contacts)


def lookup(name: str) -> dict | None:
    """The contact a spoken name means, or None. For whatsapp/email/phone/birthdays."""
    contacts = all_contacts()
    k = _find_key(name, contacts)
    if k is None:
        return None
    c = contacts[k]
    return {"name": c.get("name", k), **{f: c.get(f, "") for f in FIELDS}}


def clean_phone(text) -> str:
    """"plus 91 98765 43210" -> "+919876543210". "" when fewer than 7 digits."""
    t = str(text or "").lower().replace("plus", "+")
    t = re.sub(r"\b(double|triple)\s+(\w+)", lambda m: " ".join([m.group(2)] * (2 if m.group(1) == "double" else 3)), t)
    t = re.sub(r"\b(zero|oh|o|one|two|three|four|five|six|seven|eight|nine)\b", lambda m: _DIGIT_WORDS[m.group(1)], t)
    digits = re.sub(r"\D", "", t)
    if not 7 <= len(digits) <= 15:
        return ""
    return ("+" if t.strip().startswith("+") else "") + digits


def clean_email(text) -> str:
    """"Ravi at gmail dot com" -> "ravi@gmail.com". "" when it does not look like an email."""
    t = str(text or "").strip().lower()
    t = re.sub(r"\s*\bat the rate(?: of)?\s+|\s+at\s+", "@", t)
    t = re.sub(r"\s+dot\s+", ".", t)
    t = re.sub(r"\s+(underscore)\s+", "_", t)
    t = re.sub(r"\s+(dash|hyphen)\s+", "-", t)
    t = t.replace(" ", "").strip(".,!?")
    return t if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", t) else ""


def clean_birthday(text, today: _dt.date | None = None) -> str:
    """"5 May", "May 5th", "5/5/1990", "1990-05-05" -> "05-05" or "1990-05-05". "" if not a date."""
    t = str(text or "").lower().strip(" .,!?")
    t = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", t).replace(" of ", " ").replace(",", " ")
    year = day = month = None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    m = m or re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}))?", t)  # day/month (India, UK)
    if m and day is None:
        day, month, year = int(m[1]), int(m[2]), int(m[3]) if m[3] else None
    if day is None:
        m = (re.fullmatch(r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?", t)
             or re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:\s+(\d{4}))?", t))
        if m:
            a, b = m[1], m[2]
            day, mon = (int(a), b) if a.isdigit() else (int(b), a)
            month = _MONTHS.get(mon)
            year = int(m[3]) if m[3] else None
    if not month or not day:
        return ""
    try:
        _dt.date(year or 2000, month, day)  # 2000 is a leap year: 29 Feb is fine without a year
    except ValueError:
        return ""
    if year and not 1900 <= year <= (today or _dt.date.today()).year:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}" if year else f"{month:02d}-{day:02d}"


def say_birthday(value: str) -> str:
    """"05-05" -> "5 May", "1990-05-05" -> "5 May 1990"."""
    parts = [int(p) for p in str(value).split("-") if p.isdigit()]
    if len(parts) == 3:
        y, mo, d = parts
    elif len(parts) == 2:
        y, (mo, d) = None, parts
    else:
        return str(value)
    if not 1 <= mo <= 12:
        return str(value)
    name = list(_MONTHS)[mo - 1].capitalize()
    return f"{d} {name}" + (f" {y}" if y else "")


def _say_phone(p: str) -> str:
    return " ".join(p)  # TTS reads digit by digit, not "nine billion..."


def _say_field(field: str, value: str) -> str:
    if field == "phone":
        return _say_phone(value)
    if field == "birthday":
        return say_birthday(value)
    return value


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# ---------- phrase rules (for nlu_features.py) ----------
_NAME = r"(?P<name>[a-z][\w .'-]{0,40}?)"
_FIELD = r"(?P<field>phone number|mobile number|cell number|contact number|email address|e-mail address|" \
         r"email id|mail id|date of birth|birth date|number|phone|mobile|cell|e-mail|email|birthday|dob|notes?)"
_ADD_FIELD = re.compile(
    r"(?:(?:add|save|store|set|put)\s+)?(?:my\s+)?" + _NAME + r"(?:'s|’s|s')\s+" + _FIELD +
    r"\s+(?:is|as|to|=|:)?\s*(?P<value>.+)$", re.I)
_ADD_SAVE = re.compile(
    r"(?:add|save|store)\s+(?:my\s+)?" + _NAME + r"(?:'s|’s|s')\s+" + _FIELD + r"(?:\s+(?:is|as)?\s*(?P<value>.+))?$", re.I)
_ADD_CONTACT = re.compile(
    r"(?:add|save|create|make)\s+(?:a\s+)?(?:new\s+)?contact\s+(?:for\s+|called\s+|named\s+)?" + _NAME +
    r"(?:\s*,?\s+(?:with\s+)?(?:(?:the|his|her|their)\s+)?(?P<rest>(?:phone|number|mobile|cell|email|e-mail|mail|birthday|dob)\b.*))?$", re.I)
_GET = re.compile(
    r"(?:what(?:'s| is| was)|tell me|give me|say|read(?: me)?|do (?:i|you) (?:have|know))\s+(?:the\s+)?(?:my\s+)?" +
    _NAME + r"(?:'s|’s|s')\s+(?P<field>[a-z -]+?)$", re.I)
# Vosk often drops the apostrophe: "what is ravis number". Only used when "ravi" is a saved contact.
_GET_NOAPOS = re.compile(
    r"(?:what(?:'s| is| was)|tell me|give me|say|read(?: me)?)\s+(?:the\s+)?(?:my\s+)?"
    r"(?P<name>[a-z]+(?: [a-z]+)?)s\s+(?P<field>(?:phone )?number|phone|e ?mail(?: address)?|birthday)$", re.I)
_GET_SHOW = re.compile(
    r"(?:show|open|find|look up|lookup|search)\s+(?:me\s+)?(?:the\s+)?(?:contact\s+(?:for\s+)?|my\s+)?" + _NAME +
    r"(?:(?:'s|’s|s')\s+(?P<field>[a-z -]+?)|\s+(?:in|from)\s+(?:my\s+)?contacts)$", re.I)
_GET_SHOW_CONTACT = re.compile(r"(?:show|open|find|look up|lookup)\s+(?:the\s+)?contact\s+(?:for\s+)?" + _NAME + r"$", re.I)
_DELETE = re.compile(
    r"(?:delete|remove|erase|forget)\s+(?:the\s+)?(?:contact\s+(?:for\s+)?" + _NAME + r"|" +
    r"(?P<name2>[a-z][\w .'-]{0,40}?)\s+from\s+(?:my\s+)?contacts)$", re.I)
_LIST = re.compile(
    r"(?:list|show|read|tell me|what are)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?my\s+contacts|"
    r"(?:list|show)\s+(?:all\s+)?contacts|who(?:'s| is| are)\s+in\s+my\s+contacts|"
    r"how many contacts(?: do i have)?|who are my contacts", re.I)
_REST_PART = re.compile(r"\b(phone(?: number)?|number|mobile|cell|e-?mail(?: address)?|mail|birthday|dob)\s+(?:is\s+|as\s+)?", re.I)


def _field_of(word: str) -> str | None:
    return _FIELD_WORDS.get(" ".join(str(word or "").lower().split()))


def _split_rest(rest: str) -> dict:
    """"phone 98765 and email ravi at gmail dot com" -> {phone: "98765", email: "ravi at gmail dot com"}."""
    out: dict[str, str] = {}
    hits = list(_REST_PART.finditer(rest))
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(rest)
        value = re.sub(r"\s*(?:,|\band\b)\s*$", "", rest[h.end():end].strip()).strip()
        field = _field_of(h.group(1).replace("e mail", "email")) or ("email" if "mail" in h.group(1).lower() else None)
        if field and value:
            out[field] = value
    return out


def parse(text: str) -> tuple[str, dict] | None:
    """Spoken text -> (intent, args), or None when it is not about contacts."""
    t = " ".join(str(text or "").split()).strip(" .!?")
    t = re.sub(r"^(?:jarvis|hey jarvis)[, ]+", "", t, flags=re.I)
    if not t:
        return None
    if _LIST.fullmatch(t):
        return "contacts_list", {}
    m = _DELETE.fullmatch(t)
    if m:
        name = clean_name(m.group("name") or m.group("name2"))
        return ("contact_delete", {"name": name}) if name else None
    m = _ADD_CONTACT.fullmatch(t)
    if m:
        args = {"name": clean_name(m.group("name"))}
        args.update(_split_rest(m.group("rest") or ""))
        return "contact_add", args
    m = _GET_NOAPOS.fullmatch(t)
    if m and lookup(m.group("name")) is not None:
        field = _field_of(m.group("field").replace("e mail", "email"))
        if field:
            return "contact_get", {"name": clean_name(m.group("name")), "field": field}
    m = _GET.fullmatch(t)
    if m:
        field = _field_of(m.group("field"))
        if field:
            return "contact_get", {"name": clean_name(m.group("name")), "field": field}
        return None
    for rx in (_GET_SHOW_CONTACT, _GET_SHOW):
        m = rx.fullmatch(t)
        if m:
            field = _field_of(m.groupdict().get("field") or "details")
            if field:
                return "contact_get", {"name": clean_name(m.group("name")), "field": field}
    m = _ADD_FIELD.fullmatch(t) or _ADD_SAVE.fullmatch(t)
    if m and m.group("value"):
        field = _field_of(m.group("field")) or "notes"
        name = clean_name(m.group("name"))
        if field == "birthday" and lookup(name) is None:
            return None  # not a contact: leave "mom's birthday is ..." to birthdays.py
        return "contact_add", {"name": name, field: m.group("value").strip()}
    return None


# ---------- confirm ----------
def risky_text(args: dict) -> str | None:
    """Deleting a saved contact asks yes first. None when there is nothing to delete."""
    name = clean_name(args.get("name"))
    k = _find_key(name, _load()) if name else None
    if k is None:
        return None
    return f"delete the contact {_load()[k]['name']}"


def _tail(v: str) -> str:
    return "..." + v[-4:] if len(v) > 4 else v


def change_text(args: dict) -> str | None:
    """'change Mom's number from ...4321 to ...1234' when add would CHANGE a saved phone or email, else None.
    Texts, WhatsApp and emails go to these, so a change asks yes first."""
    name = clean_name((args or {}).get("name"))
    if not name:
        return None
    try:
        known = all_contacts()
        k = _find_key(name, known)
        old = known.get(k) if k else None
    except Exception:
        return None
    if not old:
        return None
    parts = []
    for field, cleaner, word in (("phone", clean_phone, "number"), ("email", clean_email, "email")):
        value = cleaner(args[field]) if args.get(field) else ""
        if value and old.get(field) and value != old[field]:
            parts.append(f"{word} from {_tail(str(old[field]))} to {_tail(value)}")
    if not parts:
        return None
    return f"change {old.get('name') or name}'s {' and '.join(parts)}"


# ---------- handlers ----------
def contact_add(args: dict) -> str:
    name = clean_name(args.get("name"))
    if not name:
        return "Whose contact should I save? Say: add contact Ravi phone 98765 43210."
    new: dict[str, str] = {}
    bad: list[str] = []
    for field, cleaner, word in (("phone", clean_phone, "number"), ("email", clean_email, "email"),
                                 ("birthday", clean_birthday, "birthday")):
        if args.get(field):
            value = cleaner(args[field])
            if value:
                new[field] = value
            else:
                bad.append(word)
    if args.get("notes"):
        new["notes"] = " ".join(str(args["notes"]).split())[:300]
    if bad and not new:
        return f"Sorry, I didn't catch a valid {_join(bad)} for {name}. Please say it again."
    question = change_text(args)
    if question and args.get("confirm") is not True:
        return f"Are you sure you want to {question}? Say yes to confirm."
    with _lock:
        data = _load()
        known = all_contacts()
        k = _find_key(name, known) or _key(name)
        existed = k in known
        entry = data.get(k) or {"name": (known.get(k) or {}).get("name") or name}
        entry.update(new)
        data[k] = entry
        try:
            _save(data)
        except OSError as exc:
            return f"Sorry, I couldn't save that: {exc}"
    shown = entry["name"]
    if not new:
        return f"{'I already have' if existed else 'Saved'} {shown} as a contact."
    said = _join([f"{_SAY_FIELD[f]} {_say_field(f, v)}" for f, v in new.items() if f != "notes"]
                 + (["a note"] if "notes" in new else []))
    msg = f"{'Updated' if existed else 'Saved'} {shown}: {said}."
    if bad:
        msg += f" I didn't catch a valid {_join(bad)}."
    return msg


def contact_get(args: dict) -> str:
    name = clean_name(args.get("name"))
    if not name:
        return "Whose contact? Say: what's Ravi's number."
    c = lookup(name)
    if c is None:
        return f"I don't have a contact called {name}. Say: add contact {name} phone, then the number."
    field = _field_of(args.get("field") or "") or str(args.get("field") or "all")
    if field in FIELDS:
        if not c.get(field):
            return f"I don't have {c['name']}'s {_SAY_FIELD[field]}."
        return f"{c['name']}'s {_SAY_FIELD[field]} is {_say_field(field, c[field])}."
    parts = [f"{_SAY_FIELD[f]} {_say_field(f, c[f])}" for f in FIELDS if c.get(f)]
    if not parts:
        return f"I have {c['name']} saved, but no details yet."
    return f"{c['name']}: " + ", ".join(parts) + "."


def contact_delete(args: dict) -> str:
    name = clean_name(args.get("name"))
    if not name:
        return "Which contact should I delete?"
    with _lock:
        data = _load()
        k = _find_key(name, data)
        if k is None:
            if _find_key(name, _config_contacts()):
                return f"{name} is in config.yaml under contacts. Remove it there."
            return f"I don't have a contact called {name}."
        if args.get("confirm") is not True:  # never delete without a yes
            return f"Are you sure you want to delete the contact {data[k]['name']}? Say yes to confirm."
        shown = data.pop(k)["name"]
        try:
            _save(data)
        except OSError as exc:
            return f"Sorry, I couldn't delete that: {exc}"
    if k in _config_contacts():
        return f"Deleted {shown}. The copy in config.yaml is still there."
    return f"Deleted the contact {shown}."


def contacts_list(args: dict | None = None) -> str:
    contacts = all_contacts()
    if not contacts:
        return "You have no contacts yet. Say: add contact Ravi phone 98765 43210."
    names = sorted((c.get("name") or k for k, c in contacts.items()), key=str.lower)
    n = len(names)
    head = f"You have {n} contact{'s' if n != 1 else ''}"
    if n > MAX_SPOKEN:
        return f"{head}. The first {MAX_SPOKEN} are: {_join(names[:MAX_SPOKEN])}."
    return f"{head}: {_join(names)}."


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {
    "contact_add": {
        "description": "Save a contact or add details to one (phone, email, birthday, notes). Only when the user "
                       "clearly asks to save a person's details.",
        "properties": {
            "name": {"type": "string", "description": "Person's name as spoken, e.g. 'Ravi' or 'mom'."},
            "phone": {"type": "string", "description": "Phone number with country code if given."},
            "email": {"type": "string"},
            "birthday": {"type": "string", "description": "Date like '5 May' or '5 May 1990'."},
            "notes": {"type": "string"},
        },
        "required": ["name"],
    },
    "contact_get": {
        "description": "Look up a saved contact's phone number, email, birthday, notes, or all details.",
        "properties": {
            "name": {"type": "string"},
            "field": {"type": "string", "enum": ["phone", "email", "birthday", "notes", "all"]},
        },
        "required": ["name"],
        "info": True,
    },
    "contact_delete": {
        "description": "Delete a saved contact (asks the user to confirm).",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    "contacts_list": {
        "description": "List the names of the user's saved contacts.",
        "properties": {},
        "required": [],
        "info": True,
    },
}

HANDLERS = {
    "contact_add": contact_add,
    "contact_get": contact_get,
    "contact_delete": contact_delete,
    "contacts_list": contacts_list,
}
