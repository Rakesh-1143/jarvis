# Wiring notes: piece BL (sleeptimer.py)

Files: `jarvis/actions/sleeptimer.py`, `tests/test_sleeptimer.py` (17 tests, Linux fakes).
Merge: `from .sleeptimer import CATALOG as CBL, HANDLERS as HBL` (or `from . import sleeptimer`), then update catalog CATALOG and _HANDLERS.
No new packages (uses `system.get_volume/set_volume` (pycaw), WinRT media control already in requirements, `system.sleep/shutdown`).

## Intents
| Intent | Args | Kind |
|---|---|---|
| `sleep_timer` | `{minutes, action: stop_media\|sleep\|shutdown}` (action defaults to stop_media) | sleep/shutdown risky |
| `sleep_timer_cancel` | `{}` | normal |
| `sleep_timer_status` | `{}` | info (add to brain UNTRUSTED_INFO not needed: own text only) |

## Risky (actions/__init__.py `_risky_text`)
```python
if intent == "sleep_timer" and sleeptimer.needs_confirm(args):  # sleep / shutdown only
    return sleeptimer.risky_text(args)  # "shut down the laptop in 2 hours"
```
stop_media never asks. If minutes is missing, needs_confirm is False so the handler asks "In how many minutes?".
brain.py: add `sleep_timer` to GUARDED_ACTIONS (AI-started sleep/shutdown must still ask yes).

## main.py hooks
- At start (in `_wire_features`): `sleeptimer.set_notifier(io.say)`.
- Optional: in the last minute of a sleep/shutdown timer, `sleeptimer.warning_active()` is True. The warning says "Say cancel sleep timer to stop". If you like, route a bare "cancel" / "stop" to `sleep_timer_cancel` while `warning_active()` and no confirm question is pending.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "stop the music in 30 minutes", "turn off the music in 20 min", "sleep timer 45 minutes", "pause music after 1 hour" | sleep_timer | {minutes: 30, action: stop_media} |
| "sleep the laptop in 1 hour", "put the computer to sleep in 40 minutes" | sleep_timer | {minutes: 60, action: sleep} |
| "shut down in 2 hours", "turn off the laptop in 90 minutes", "shutdown after an hour and a half" | sleep_timer | {minutes: 120, action: shutdown} |
| "cancel sleep timer", "stop the sleep timer", "cancel the shutdown timer" | sleep_timer_cancel | {} |
| "how long is left on the sleep timer", "sleep timer status", "when will the music stop" | sleep_timer_status | {} |

Notes:
- Match these BEFORE the plain `shutdown`/`sleep` rules (nlu_control) and before generic `timer`: "shut down in 2 hours" must not become an instant shutdown. Only use sleep_timer when a duration ("in/after N min/hour") is present.
- Convert hours to minutes (`1 hour` -> 60, `an hour and a half` -> 90).
- One timer at a time; a new one replaces the old (reply says so).
- If the laptop was asleep more than 10 minutes past the end time, the timer is dropped (no surprise shutdown on wake).
- Music: volume fades down over the last 30 s, then every playing app is paused (WinRT; fallback media Stop key, never Play/Pause toggle), then the old volume comes back.
- Not tested on real Windows (sandbox). Hand test: "stop the music in 1 minute" while Spotify plays; "sleep the laptop in 2 minutes" -> yes -> warning -> "cancel sleep timer".
