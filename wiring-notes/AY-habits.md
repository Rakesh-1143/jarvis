# Wiring notes: piece AY (habits.py)

Files: `jarvis/actions/habits.py`, `tests/test_habits.py` (44 tests).
Merge: `from .habits import CATALOG as CAY, HANDLERS as HAY`, then update catalog CATALOG and _HANDLERS.
No new packages (json, re, difflib, threading only). Nothing Windows-specific.
Duplicate check: no habit/streak code anywhere in jarvis/ (only quotes in daily_data.py). lists.py has no "done" marking.

## Intents
| Intent | Args | Kind |
|---|---|---|
| habit_done | {name, day?: today\|yesterday} | action |
| habit_status | {name?, period?: today\|week} | info |
| habit_remove | {name} | **risky** |

A habit is created the first time it is marked done. No separate "add habit" intent.

## Risky (actions/__init__.py `_risky_text`)
```python
if intent == "habit_remove":
    return habits.risky_text(args)   # "delete the habit workout and all its history"
```

## Brain
- `UNTRUSTED_INFO += habit_status` (reads back habit names the user said).
- `GUARDED_ACTIONS += habit_remove` (AI must not delete history on its own). `habit_done` is fine for the AI.

## main.py hook
```python
habits.start(io.say)   # in _wire_features, next to recurring.start
```
Starts the evening nudge thread only when `habits.remind_at` is set; otherwise does nothing.
If Jarvis starts after the nudge time, it skips that day's nudge (no nagging at startup).
`habits.stop()` exists for exit (optional; thread is a daemon).

## Config (optional, defaults work)
```yaml
habits:
  file: "~/.jarvis/habits.json"   # {"workout": ["2026-11-07", ...]}
  remind_at: "21:00"              # empty = no evening nudge
```
Add `"habits": {"file": "~/.jarvis/habits.json", "remind_at": ""}` to `config.DEFAULTS`.

## NLU
Use `habits.parse(text) -> (intent, args) | None` in nlu_features (tested, 18 phrases + 9 non-matches).
| Say | Intent | Args |
|---|---|---|
| "I did my workout", "mark reading done", "I meditated yesterday" | habit_done | {name, day?} |
| "did I meditate today" | habit_status | {name, period: today} |
| "my workout streak", "what's my reading streak" | habit_status | {name} |
| "habits this week", "how are my habits", "habit report" | habit_status | {period: week} |
| "habits today", "which habits are left" | habit_status | {period: today} |
| "remove habit reading", "delete my workout habit", "stop tracking meditation" | habit_remove | {name} |

Notes:
- Remove/delete rules need the word "habit" (or "stop tracking") so "delete the file report" is not caught.
- "I did my X" needs "my"/"the", so "I did it" is not caught. "mark this done" returns None.
- Names are cleaned: "meditated"/"meditate" -> meditation, "worked out" -> workout, "read" -> reading.
  Matching to saved habits also allows plural and close spelling (difflib 0.8).
- Place `habits.parse` after dictation/teach/corrections checks; it has no overlap with existing rules
  (searched nlu.py, nlu_control.py, nlu_features.py for mark/done/streak/"i did").
