# Wiring notes: piece AD (screentime.py)

Files: `jarvis/actions/screentime.py`, `tests/test_screentime.py` (16 tests).
Merge: `from .screentime import CATALOG as CAD, HANDLERS as HAD`, then update catalog CATALOG and _HANDLERS.
No new packages (ctypes + psutil, already used). Windows only; on other OS `start()` returns None and the intents still answer.

## Intents
| Intent | Args | Kind |
|---|---|---|
| `screen_time` | `{app?, period?: today\|week}` | **info** (local data only; window titles are matched, never read back, so no need for UNTRUSTED_INFO) |
| `app_limit` | `{app?, minutes?}` (minutes 0 = remove; no app = list limits; no minutes = say current limit) | normal |

Risky: **nothing risky.** `app_limit` only writes the Jarvis data file; it never closes or blocks apps. Not needed in GUARDED_ACTIONS.

## main.py hooks
- At start: `screentime.start(io.say)`.
- On exit (next to `recorder.stop_all`): `screentime.stop()` (saves the file). Without it, up to 60 s of usage is lost.

## Config (optional; add to config.py DEFAULTS if you like)
```yaml
screentime_file: "~/Documents/Jarvis screen time.json"
screentime: {enabled: true, interval: 5, idle_minutes: 2, keep_days: 60}
app_limits: {youtube: 60}   # minutes per day; matched on process name OR window title
```
Voice-set limits are saved in the data file and override config ones.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "how long did I use chrome today", "how much time on youtube today" | screen_time | {app: "chrome"} |
| "how long did I use chrome this week" | screen_time | {app: "chrome", period: "week"} |
| "my screen time today", "screen time", "top apps today", "what apps did I use most" | screen_time | {} |
| "screen time this week", "my screen time this week" | screen_time | {period: "week"} |
| "warn me after 1 hour of youtube", "limit youtube to 30 minutes", "set a 2 hour limit for chrome" | app_limit | {app: "youtube", minutes: 60} |
| "remove the youtube limit", "no limit for chrome" | app_limit | {app: "youtube", minutes: 0} |
| "what are my app limits", "list app limits" | app_limit | {} |

Notes:
- Convert hours to minutes in NLU ("1 hour" = 60, "an hour and a half" = 90).
- "screen time" must not clash with `screenshot` / screen recorder rules ("take a screenshot", "record screen"). Match `screen time` first.
- "set a timer for 1 hour" belongs to timers; app_limit needs the words limit/warn me after + an app.
- The warning is spoken from a background thread (like monitor alerts), once per app per day.
- App names: spoken "edge", "vs code", "word", "powerpoint", "file explorer" map to the real process names (`norm()`).
- Not tested on real Windows (ctypes GetForegroundWindow / GetLastInputInfo). Test on the PC.
