# Wiring notes: piece BO (recap.py)

Files: `jarvis/actions/recap.py`, `tests/test_recap.py` (55 tests).
Merge: `from .recap import CATALOG as CBO, HANDLERS as HBO`, then update catalog CATALOG and _HANDLERS.
No new packages (datetime, re, threading only). Nothing Windows-specific.
Duplicate check: `agenda.briefing` is the MORNING summary (time, weather, today's events, reminder count).
No end-of-day recap existed. recap reuses data from screentime, timetrack, habits, expenses, lists,
timers, agenda and birthdays. It is read only (a test checks no file is written).

## Intents
| Intent | Args | Kind |
|---|---|---|
| recap | {day?: today\|tomorrow} | info |

- today: screen time (top 3 apps), project time today, habits done / not done, money spent today,
  open to-dos (the "to-do" list), reminders still set for tonight, tomorrow's first event, birthdays tomorrow.
- tomorrow: tomorrow's events (first 3 + count), reminders set for tomorrow, birthdays tomorrow.
- Each part is skipped when it is empty, its module is missing, or it throws.

## Brain
- `UNTRUSTED_INFO += recap` (it reads back app names, event titles, list items, habit and project names).
- Not risky, nothing to guard.

## main.py hook
```python
recap.start(io.say)   # in _wire_features, next to habits.start
```
Starts the daily thread only when `recap.at` is set; otherwise does nothing.
If Jarvis starts after that time, it skips that day (no recap at startup). `recap.stop()` exists (daemon thread).

## Config (optional)
```yaml
recap:
  at: "21:30"   # empty = no automatic evening recap
```
Add `"recap": {"at": ""}` to `config.DEFAULTS`.

## NLU
Use `recap.parse(text) -> (intent, args) | None` in nlu_features. Place it BEFORE `_agenda`
(no overlap today, but "what's tomorrow look like" must not fall into agenda rules later).
| Say | Args |
|---|---|
| "how was my day", "how did my day go", "evening recap", "day / daily / end of day recap", "recap my day", "wrap up my day" | {day: today} |
| "what does tomorrow look like", "how does tomorrow look", "what's tomorrow like", "prepare me for tomorrow" | {day: tomorrow} |

Not caught (stay with their modules): "summary of my day" (agenda briefing), "what's on tomorrow" (agenda),
"how was the movie", "recap the meeting".

## Known limits
- "Missed reminders" from the spec: timers.py keeps no record of missed reminders (it announces them at
  startup and forgets them), so recap says reminders still set for tonight instead. Adding a missed log
  would need a change in timers.py (shared module; not done here).
- recap reads other modules' private loaders (`_load`, `_lock`, `timetrack._totals`, `agenda._describe`,
  `birthdays._label`) because they have no public data functions. If one of those is renamed, that part is
  just skipped (try/except), and test_recap.py fails so it is noticed.
- Calendar parts can take up to agenda.TIMEOUT seconds when offline.
