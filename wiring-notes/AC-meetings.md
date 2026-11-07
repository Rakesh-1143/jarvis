# Wiring notes: piece AC (meetings.py)

Files: `jarvis/actions/meetings.py`, `tests/test_meetings.py` (26 tests).
Merge: `from .meetings import CATALOG as CAC, HANDLERS as HAC`, then update catalog CATALOG and _HANDLERS.
No main.py hooks. No new packages (uses agenda module, pyautogui, psutil if present; icalendar for descriptions).
Needs `calendars:` in config (same as agenda). Without it, join says the agenda "No calendar is set up" text.

## Intent
`meeting {action: join|leave|mute|status, when?}` (one intent; `when` only for join).
- `status` is read-only. The intent is NOT marked `info` in CATALOG because join/leave/mute act.
  If you want the AI to read status results, add a small `meeting_status` info alias in catalog
  that calls `meetings.meeting({"action": "status"})`.

## Risky
- `leave` (Meet = ctrl+w closes the tab; Teams hangs up). Not destructive (you can rejoin),
  but please add `meeting` to brain.py GUARDED_ACTIONS so the AI can't start join/leave on its own
  without the user asking. No yes/no confirm needed for direct voice commands.
- Safety built in: hotkeys are only sent after the meeting window is focused AND its title still
  looks like a live meeting. Zoom alt+q only opens Zoom's own Leave dialog; we never press Enter
  (for a host the default button can be "End meeting for all").

## NLU phrases -> intent + args
| Say | Args |
|---|---|
| "join my next meeting", "join my meeting", "join the meeting", "join my class" | {action: join} |
| "join the 3 pm meeting", "join my meeting at 3", "join tomorrow's 10 am call" | {action: join, when: "3 pm" / "tomorrow at 10 am"} |
| "leave meeting", "leave the call", "hang up", "end the call" | {action: leave} |
| "mute me", "mute in meeting", "unmute me", "mute my mic in the meeting" | {action: mute} |
| "am I in a meeting", "am I on a call" | {action: status} |

Notes:
- "mute" alone already goes to volume mute; only route to meeting when the phrase has "me", "meeting",
  "call", or "mic in". "unmute me" = mute toggle (the apps use one key for both).
- Audio piece G has a `mic` intent (mute the Windows mic). "mute my mic" can stay with audio;
  "mute me in the meeting" goes here.
- "when is my next meeting" stays `next_event` (agenda). Match "join" first.
- Teams/Zoom window title rules are best effort. Not tested on real Windows. Check: Zoom call
  window title "Zoom Meeting"; Teams call window title has "Meeting"/"Call" + "Microsoft Teams";
  Meet tab title "Meet - abc-defg-hij".
