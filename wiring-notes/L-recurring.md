# Wiring: piece L `recurring.py` (repeating reminders)

Files: `jarvis/actions/recurring.py`, `tests/test_recurring.py` (32 tests). No new packages.

## actions/__init__.py
- `from . import recurring`; merge `recurring.HANDLERS` into `_HANDLERS`, `recurring.CATALOG` into `CATALOG`.
- Risky: `repeat_reminders` with action=cancel and text "all"/empty. Use `recurring.needs_confirm(args)`
  and `recurring.risky_text(args)` ("stop all your repeating reminders"). Handler itself never clears all
  without `confirm=True` (returns "Are you sure ...?").

## nlu.py
- Call `recurring.parse(text)` BEFORE the one-time reminder/timer rules. Returns `(intent, args)` or None.
  Phrases: "remind me to drink water every hour", "remind me every 30 minutes to stretch",
  "every weekday at 9 take medicine", "remind me every day at 8 pm to call mom",
  "every Monday at 10 remind me about the team call", "remind me every morning to check email" (8 AM),
  "list repeating reminders", "stop all repeating reminders", "stop the water reminder".
- "stop the X reminder" is claimed only if a saved repeating reminder matches X; otherwise None (timers keeps it).
- "remind me ... in 10 minutes" (no "every"/"daily") returns None.

## main.py
- At start: `actions.recurring.start(io.say)` (daemon thread, 1 s tick). Optional at exit: `recurring.stop()`.

## config.yaml
- Optional `recurring_file: "~/Documents/Jarvis repeating.json"` (this is the default).

## Behaviour
- Wall-clock thread; fires after sleep. Missed by > 1 hour = skipped (interval ones restart from now).
- Args: `repeat_reminder {text, every_minutes?, at? ("HH:MM" or "9 am"), days? ("weekdays"|"weekends"|"daily"|"monday and friday"|[0..6])}`;
  `repeat_reminders {action: list|cancel, text?}`.
