# Wiring notes: piece AF (history.py)

Files: `jarvis/actions/history.py`, `tests/test_history.py` (21 tests).
Merge: `from .history import CATALOG as CAF, HANDLERS as HAF`, then update catalog CATALOG and _HANDLERS.
No new packages (json + datetime only).

## Risky
- `history {action: clear}` is risky. In `actions/__init__.py`:
  - `_risky_text`: `if intent == "history" and history.needs_confirm(args): return history.risky_text(args)`
  - `_do_risky`: add `"history"` to the tuple that calls `_HANDLERS[intent](args)`.
- The handler never clears without `args["confirm"] is True`.

## Brain
- `UNTRUSTED_INFO += history` (list/search read back old spoken text: data, not instructions).
- `GUARDED_ACTIONS += history`. The AI must not start `repeat_last` or `clear` on its own.
  Best: main ignores AI-made `history` commands with action `repeat_last`.

## Config (optional)
```yaml
history_file: "~/Documents/Jarvis history.jsonl"
history: {enabled: true, keep_days: 30}
```
Add `"history_file": "~/Documents/Jarvis history.jsonl", "history": {}` to config.py DEFAULTS if you like; module has its own defaults.

## main.py hooks
1. **Log after each command** (top level only, `depth == 0`; skip while dictation is active so typed text is not saved).
   In `handle()`, after `replies` are built:
   ```python
   reply = " ".join(r for r in replies if r)
   if depth == 0 and history is not None:
       history.log(text, cmds[0] if cmds else cmd, reply, from_ai=from_ai)
   return reply
   ```
   Also log the routine / shortcut paths the same way (routine: `Command("routine", {"name": name})`).
   `log()` never raises and never saves `confirm`, `pin`, `password`, `code`, or any `jarvis_lock` command.
2. **"do that again"** (`history {action: repeat_last}`), in `_run_one` before `actions.run`:
   ```python
   if cmd.intent == "history" and cmd.args.get("action") == "repeat_last" and not from_ai:
       again = history.last_command()
       if again is None:
           return "There is nothing to do again yet."
       return _run_one(again, io, cfg, actions, nlu, brain, depth + 1, from_ai=history.last_was_ai())
   ```
   Safe by design: saved args never hold `confirm`, so `_needs_confirm` asks "are you sure?" again
   for shutdown, delete, SMS, clear, etc. `from_ai=last_was_ai()` keeps `_ai_question` checks too.
   `last_command()` skips `history`, `confirm`, `cancel`, `repeat`, `unknown`, `yes`, `no`.
   If not wired, the handler only says what the last command was (does not run it).

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "what did I ask you yesterday", "what did I say yesterday", "what did I ask (you) today", "what did I ask on Monday", "what did I ask 3 days ago" | history | {action: "list", day: "<day words>"} |
| "what did I ask (you)", "show my history", "my command history" | history | {action: "list"} (today) |
| "what did I ask about weather", "search my history for chrome", "did I ask about X (yesterday)" | history | {action: "search", query: "weather", day?} |
| "do that again", "do it again", "one more time", "run that again", "repeat the last command" | history | {action: "repeat_last"} |
| "clear my history", "clear my command history", "delete my command history" | history | {action: "clear"} |

Notes:
- **"repeat that" / "say that again" stays `repeat`** (says the last reply again, assistant.py). Only "do ... again" / "run ... again" / "repeat the last command" go to history.
- `day` accepts: today, yesterday, day before yesterday, weekday names (most recent past one), "N days ago" (digits or one-seven), YYYY-MM-DD. Leading "on/last/this" is fine.
- "clear clipboard history" stays `clip_history`: only match `clear (my) (command) history` when "clipboard" is not said. Don't use "forget ..." phrases (those belong to forget_memory).
- Not tested on real Windows (file only; nothing Windows-specific).
