# Wiring notes: piece BI (timetrack.py)

Files: `jarvis/actions/timetrack.py`, `tests/test_timetrack.py` (58 tests).
Merge: `from .timetrack import CATALOG as CBI, HANDLERS as HBI`, then update catalog CATALOG and _HANDLERS.
No new packages (json, csv, re, difflib, threading only). Nothing Windows-specific.
Duplicate check: screentime.py tracks apps (not named projects), focus.py is a pomodoro countdown,
timers.py is countdowns, habits.py is daily yes/no. No project time logging anywhere.

## Intents
| Intent | Args | Kind |
|---|---|---|
| track | {action: start\|stop\|status, project?} | action |
| track_report | {project?, period?: today\|week\|month, export?: bool} | info (export writes a CSV) |
| track_undo | {} | **risky** |

- One session runs at a time; starting another stops the first (reply says both).
- Week starts Monday; month starts on the 1st. Sessions over midnight are split by the period.
- The running session counts in reports up to now.
- Stopping a session over 12 hours adds a hint to say "delete last session".
- Spoken project names reuse saved names (case, plural, word inside, close spelling).

## Risky (actions/__init__.py `_risky_text`)
```python
if intent == "track_undo":
    return timetrack.risky_text(args)  # "delete the last time tracking session (thesis, 5 minutes, started 07 Nov 11:00, still running)"
```

## Brain
- `UNTRUSTED_INFO += track_report` (reads back project names the user said).
- `GUARDED_ACTIONS += track_undo` (AI must not delete history on its own). `track` is fine for the AI.

## main.py hook
None.

## Config (optional, defaults work)
```yaml
timetrack:
  file: "~/.jarvis/timetrack.json"          # {"sessions": [{"project", "start", "end"}]}
  export_file: "~/Documents/Jarvis time tracking.csv"
```
Add `"timetrack": {"file": "~/.jarvis/timetrack.json", "export_file": "~/Documents/Jarvis time tracking.csv"}` to `config.DEFAULTS`.

## NLU
Use `timetrack.parse(text) -> (intent, args) | None` in nlu_features (tested: 21 phrases + 10 non-matches).
**Order matters:** call it BEFORE `habits.parse` and BEFORE the screen-time rule (nlu_features ~line 934).

| Say | Intent | Args |
|---|---|---|
| "start tracking college project", "start tracking time on X", "begin timing X", "track my time on X", "I'm working on X now" | track | {action: start, project} |
| "stop tracking", "stop time tracking" | track | {action: stop} |
| "stop tracking X" (only if X is the running project) | track | {action: stop, project} |
| "what am I tracking", "am I tracking anything", "tracking status" | track | {action: status} |
| "how long did I work on X today/this week/this month" | track_report | {project, period?} |
| "how much time did I spend on X" (only if X is a tracked project) | track_report | {project, period?} |
| "time report this week", "what did I work on today", "how many hours did I work this week" | track_report | {period?} |
| "export my time report" | track_report | {export: true} |
| "delete last session", "undo the last tracking session" | track_undo | {} |

Overlaps handled inside parse:
- habits.py: "stop tracking X" = remove habit X. timetrack claims it only when X matches the running
  project, else returns None so habits gets it. Plain "stop tracking" (no name) never matches habits.
- screentime: "how much time did I spend on chrome" = app time. timetrack claims "spend on X" only when X
  is a saved project. "how long did I work on X" is timetrack only.
- "stop the timer" / "stop" are left to timers/focus. Start rules need the word tracking/timing.
- parse reads the JSON file for these two shared phrases (small file, fine per utterance).
