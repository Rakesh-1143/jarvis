# Wiring notes: piece AJ (notifications.py)

Merge: `from .notifications import CATALOG as CAJ, HANDLERS as HAJ`, then update catalog CATALOG and _HANDLERS.
One intent: `notifications {action: read|clear|announce_on|announce_off}`.
- Risky: action `clear` only. Use `notifications.needs_confirm(args)` / `risky_text(args)` (same shape as cliphistory).
  The handler never clears unless `args["confirm"] is True`.
- CATALOG `info` is False (like clip_history), because clear changes things. If the brain can mark
  info per action, `read` is info.

main.py hook (in `_wire_features`, like monitor):
```python
("notifications", lambda m: m.start(io.say)),   # only polls if announce mode is on
```
Optional on exit: `notifications.stop()` (thread is a daemon).

brain.py:
- add `notifications` to UNTRUSTED_INFO (text is written by other people: WhatsApp, email).
- add `notifications` to GUARDED_ACTIONS (clear, and announce changes saved state).

requirements.txt (Windows only, optional; module works without them using the fallback):
```
winrt-runtime; sys_platform == "win32"
winrt-Windows.Foundation; sys_platform == "win32"
winrt-Windows.Foundation.Collections; sys_platform == "win32"
winrt-Windows.UI.Notifications; sys_platform == "win32"
winrt-Windows.UI.Notifications.Management; sys_platform == "win32"
```

Optional config:
```yaml
notifications:
  announce: false                   # voice choice is saved in state_file and wins
  announce_apps: [WhatsApp, Gmail]  # matches app name OR title; [] = all apps
  poll_seconds: 5
  max_read: 5
  state_file: ~/.jarvis/notifications.json
```

## NLU phrases -> args
| Say | Args |
|---|---|
| "read my notifications", "any notifications", "what are my notifications" | {action: read} |
| "clear my notifications", "dismiss all notifications" | {action: clear} (asks yes) |
| "announce my notifications", "tell me when I get notifications" | {action: announce_on} |
| "stop announcing notifications", "don't announce notifications" | {action: announce_off} |

Notes:
- Must not steal "clear clipboard history" / "clear the list" etc.: only match the word "notification(s)".
- "turn off notifications" is ambiguous with Windows Focus/Do Not Disturb (focus.py). Map it to
  announce_off only if it says "announce"/"read out"; else leave it to focus.

## Does it work for an unpackaged Python app? (NOT tested on real Windows)
- Backend 1, WinRT `UserNotificationListener`: we only poll `get_notifications_async`. We do not use the
  `NotificationChanged` event, which needs package identity. Whether `request_access_async` returns Allowed
  for plain python.exe is not confirmed by Microsoft docs; reports vary. Needs a real test.
- Backend 2 (fallback, read only): copies `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db`
  to a temp folder and reads it with sqlite3. No permission needed. Cannot clear (says so).
  Schema (Notification / NotificationHandler tables) is undocumented and could change.
- If both fail: "Reading notifications is not available on this PC..." + Settings hint.
- Test on Windows: say "read my notifications", then check which backend: `notifications._backend.name`.
