# Wiring notes: piece AX (contacts.py)

Merge: `from .contacts import CATALOG as CAX, HANDLERS as HAX`, then update catalog CATALOG and _HANDLERS.
Also `from . import contacts` in actions/__init__.py. No new packages (json + re only; fuzzy.py for names).

## Intents
- `contact_add {name, phone?, email?, birthday?, notes?}` - save or add details. Not risky.
- `contact_get {name, field?: phone|email|birthday|notes|all}` - **info**.
- `contact_delete {name}` - **risky**.
- `contacts_list {}` - **info**.

## Risky (actions/__init__.py)
- `_risky_text`: `if intent == "contact_delete": return contacts.risky_text(args)`
  (None when the name is not a saved contact: the handler then just says so).
- `_do_risky`: `if intent == "contact_delete": return contacts.contact_delete(args)` (args has confirm=True).
- The handler itself also refuses to delete without `confirm: True`.

## NLU (nlu_features.py) - one helper does all phrases
```python
from jarvis.actions import contacts
r = contacts.parse(text)   # -> (intent, args) or None
if r: return Command(*r)
```
Order does not matter much: "whatsapp Ravi ...", "email mom", "remove milk from my shopping list" all return None here.

| Say | Command |
|---|---|
| "add contact Ravi phone 98765 43210" | contact_add {name: Ravi, phone: "98765 43210"} |
| "add a new contact called Priya with phone plus 91 ... and email priya at gmail dot com" | contact_add {name, phone, email} |
| "Ravi's email is ravi at gmail dot com", "save Ravi's number as 98..." | contact_add {name, email/phone} |
| "Ravi's birthday is 5 May" | contact_add {name, birthday} **only if Ravi is already a contact**, else None |
| "what's Ravi's number", "what is my mom's email" | contact_get {name, field} |
| "show Ravi's details", "show contact Ravi", "find Ravi in my contacts" | contact_get {name, field: all} |
| "delete contact Ravi", "remove Ravi from my contacts" | contact_delete {name} |
| "list my contacts", "how many contacts do I have" | contacts_list {} |

**Birthdays (BA) overlap:** "mom's birthday is 12 March" goes to contacts only when mom is a contact.
If BA is wired, put `birthdays` parse BEFORE `contacts.parse`, and in BA store birthdays of known contacts with
`contacts.contact_add({"name": n, "birthday": d})` (or let BA read `contacts.all_contacts()` - birthday is
"MM-DD" or "YYYY-MM-DD"; `contacts.say_birthday(v)` speaks it). "when is X's birthday" is not parsed here.

## Use contacts.lookup in whatsapp / email / phone / inbox (the main ask)
`contacts.lookup(name) -> {"name","phone","email","birthday","notes"} | None`. It already reads config.yaml
`contacts:` AND the saved file, strips "my"/"'s", and fuzzy-matches (never guesses between two close names,
never fuzzy-matches names under 4 letters). Values: phone is "+919876543210" style, email lower case.

1. `files._contact(name, field)` (email + whatsapp): at the top
   ```python
   from . import contacts
   c = contacts.lookup(name)
   if c and c.get(field): return c[field]
   ```
   keep the old CONTACTS code after it as a fallback. Change the whatsapp message
   "Add it under contacts in config.yaml." -> "Say: add contact {to} phone, then the number."
2. `files.contact_name(name)`: `c = contacts.lookup(name); if c: return c["name"]` first.
3. `phone.resolve_number(to, contacts=None)`: when the `contacts` arg is None (real use, not tests), try
   `contacts.lookup(to)` first (rename the local `contacts` param use or import as `from . import contacts as _ct`
   to avoid the name clash). Digits path stays first.
4. `inbox._resolve_sender(name, contacts)`: try `contacts.lookup(name)` email first.

## brain.py
- Add `contact_add` and `contact_delete` to GUARDED_ACTIONS: text from a web page or email must not be able
  to add or change a contact's number (whatsapp/phone would then use it).
- `contact_get` / `contacts_list` are info and hold the user's own data; no need for UNTRUSTED_INFO.

## Config (optional)
`contacts_file: "~/Documents/Jarvis contacts.json"` (default if missing). config.py DEFAULTS / config.yaml may add it.
Also update the config.yaml comment above `contacts:` to say you can add contacts by voice too.
config.yaml contacts stay read-only: "delete contact mom" for a config-only contact says "remove it in config.yaml".
Adding a detail to a config contact saves only the new field in the JSON file (merged on read).

## Tests
tests/test_contacts.py (74 tests). Uses tmp file + fake config contacts (monkeypatches `_path`, `_config_contacts`).
