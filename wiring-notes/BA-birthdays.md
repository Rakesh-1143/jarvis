# Wiring notes: piece BA (birthdays.py)

Merge: `from .birthdays import CATALOG as CBA, HANDLERS as HBA`, then update catalog CATALOG and _HANDLERS.
Also `from . import birthdays` in actions/__init__.py. No new packages (json + re; uses contacts.py and fuzzy.py).

## Intents (nothing risky)
- `birthday_add {name, date, kind?: birthday|anniversary}` - not risky.
  A birthday of a saved contact is stored IN the contact (`contacts.contact_add`); anyone else, and all
  anniversaries, go to `~/.jarvis/birthdays.json`. Name "me" = user's own birthday, "our" = user's anniversary.
- `birthday_get {name?, kind?, period?: today|tomorrow|week|month|upcoming|next, month?: 1-12, ask?: age}` - **info**.
  No name and no period = next 30 days.

## NLU (nlu_features.py) - one helper, put it BEFORE `contacts.parse`
```python
from jarvis.actions import birthdays
r = birthdays.parse(text)   # -> (intent, args) or None
if r: return Command(*r)
```
It returns None quickly unless the text has birth/anniv/bday/born/married/dob/"how old".
Add only when the date really parses ("mom's birthday party is at 6" -> None).

| Say | Command |
|---|---|
| "mom's birthday is 12 March", "remember that Ravi's birthday is on 5th May", "add birthday for Priya on 5/5" | birthday_add |
| "Ravi was born on 5 May 1990", "my birthday is 1 January", "I was born on ..." | birthday_add (name "me" for self) |
| "our anniversary is 10 June 2015", "my wedding anniversary is ...", "we got married on ...", "mom and dad's anniversary is 3 Feb" | birthday_add kind anniversary |
| "when is mom's birthday", "what's Ravi's birthday", "when is our anniversary" | birthday_get {name, kind} |
| "how old is Priya turning", "how old will Priya be", "how old am I turning" | birthday_get {name, ask: age} |
| "birthdays this month", "birthdays in December", "birthdays next month" | birthday_get {period: month, month?} |
| "any birthdays this week", "any birthdays today", "whose birthday is today", "is today anyone's birthday" | birthday_get {period} |
| "upcoming birthdays", "whose birthday is next", "any anniversaries this month" | birthday_get |

Not parsed (left to others): "happy birthday" (song/fun), "how old is the taj mahal", "what's Ravi's number".
Note "what's Ravi's birthday" is now taken by birthdays (before contacts' contact_get): fine, it also reads contacts.

## main.py
`birthdays.start(io.say)` next to `habits.start(io.say)`. Also `birthdays.stop()` on exit (optional; thread is daemon).
Reminder speaks once a day after `remind_at` (default 09:00): "Reminder: Today is Ravi's birthday, Ravi turns 30.
Tomorrow is Mom's birthday." If Jarvis starts after 09:00 it still says today's reminder once (on purpose).
The day it last spoke is saved in the file, so a restart does not repeat it.

## brain.py
- `birthday_get` is info and holds the user's own data: no UNTRUSTED_INFO needed.
- Optional: add `birthday_add` to GUARDED_ACTIONS (a web page/email should not change a contact's birthday).
  Low harm, so your call.

## Config (optional; all have defaults)
```yaml
birthdays:
  file: "~/.jarvis/birthdays.json"
  remind_at: "09:00"     # "" turns reminders off
  day_before: true
```

## Tests
tests/test_birthdays.py (75 tests). Monkeypatches `birthdays._path`, `contacts._path`, `contacts._config_contacts`,
`REMIND_AT`, `DAY_BEFORE`, `notify`. Full suite on a private copy: 2492 passed, 3 skipped.
