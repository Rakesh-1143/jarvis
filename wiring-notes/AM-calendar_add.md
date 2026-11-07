# Wiring notes: piece AM (calendar_add.py)

Files: `jarvis/actions/calendar_add.py`, `tests/test_calendar_add.py` (47 tests).
Merge: `from . import calendar_add`, then add it to the `for _mod in (...)` loop in actions/__init__.py
(CATALOG + HANDLERS). No main.py hooks.

## Intent
`calendar_add {title, start, minutes?, location?}`
- `start`: ISO from the AI ("2026-11-08T16:00", "...Z" ok) OR spoken text from phrase rules
  ("tomorrow at 4 pm", "friday 10am", "4 pm tomorrow", "20 november at 3:30 pm").
  A time with no day that already passed today = tomorrow.
- `minutes`: int or text ("1 hour", "an hour and a half", "90 minutes"). Default 60
  (config `calendar.default_minutes`). Aliases accepted: `when` for start, `duration` for minutes.

## Risky (always) - please add to actions/__init__.py
- `_risky_text`: `if intent == "calendar_add": return calendar_add.risky_text(args)`
  Returns e.g. "add 'Dentist' tomorrow at 4:00 PM for 1 hour to your calendar".
  Returns None when title/time is missing or bad: then the handler runs and asks for the missing
  part ("What time should I add it?") instead of a useless yes/no.
- `_do_risky`: add "calendar_add" to the tuple that calls `_HANDLERS[intent](args)`.
- The handler itself also refuses to save without `confirm: True` (safe if called directly).
- brain.py: add `calendar_add` to GUARDED_ACTIONS (the AI should not add events the user didn't ask for).

## Where it saves (config, all optional)
```yaml
calendar:              # same section agenda.py uses; new keys only
  add_with: auto       # auto | outlook | google | link
  default_minutes: 60
google_calendar:
  credentials_file: "" # OAuth "Desktop app" client JSON; empty = Google API not used
  token_file: "~/.jarvis-google-calendar-token.json"
  calendar_id: primary
```
auto = Outlook desktop (pywin32, already in requirements) -> Google API (only if credentials_file set)
-> open the prefilled Google Calendar page in the browser (user clicks Save). If Outlook/Google fails
with a real error, it is logged and the browser page is opened instead.

Optional packages (only for the Google API way), add to requirements.txt as optional:
`google-api-python-client>=2.100`, `google-auth-oauthlib>=1.2`. First use opens a browser sign-in
(waits up to 120 s; this blocks the voice loop once).

## NLU phrases -> intent + args (suggested)
| Say | Args |
|---|---|
| "add dentist tomorrow at 4 pm for 1 hour" | {title: "dentist", start: "tomorrow at 4 pm", minutes: "1 hour"} |
| "add meeting with Ravi on Friday at 10" | {title: "meeting with Ravi", start: "friday at 10"} |
| "add gym to my calendar at 7 am tomorrow" | {title: "gym", start: "7 am tomorrow"} |
| "schedule lunch with Priya on 20 november at 1 pm at Cafe X" | {..., location: "Cafe X"} |
| "put/create an event called X ..." | same |

Notes:
- Match only with a calendar word ("calendar", "event", "schedule") OR "add <x> <day/time>". Do NOT
  steal "add milk to my shopping list" (lists) or "add a note" (notes). Safe rule: needs a day or
  time word after the title, and not "to my ... list".
- "for N hour(s)/minutes" at the end = minutes; " at <place>" after the time = location.
- "remind me ..." stays reminder/recurring.
- Not tested on real Windows/Outlook. Check: Outlook item.Start as "YYYY-MM-DD HH:MM" string is
  read as local time; the new Outlook app has no COM, so it falls back to the browser page.
