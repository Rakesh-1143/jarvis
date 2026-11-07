# Wiring notes: piece AE (security.py)

Merge: `from .security import CATALOG as CAE, HANDLERS as HAE`, then update catalog CATALOG and _HANDLERS.
Also expose the module as `actions.security` (main uses `getattr(actions, "security", None)`).
Intents: `jarvis_lock {state: on|off|status, pin?}`, `guest_mode {state: on|off|status}`. Not info. No new packages.

## Risky intents
- No "Are you sure?" confirm needed. Instead the PIN guards them:
  - `jarvis_lock off` and `guest_mode off` need a right PIN (the handlers refuse without one, so an AI tool call can't unlock).
  - Default protected (PIN asked first): shutdown, restart, software, phone, device, scene, delete_file, move_file,
    rename_file, copy_file, empty_recycle_bin, kill_process, computer_use, whatsapp, email, forget_memory, list_clear, history:clear.
- brain.py: add `jarvis_lock`, `guest_mode` to GUARDED_ACTIONS. The AI must never fill `pin` (catalog says so).

## main.py hook (one place: top of `_run_one`, so routines and AI tool calls are covered too)
```python
security = getattr(actions, "security", None)
if security is not None and cmd.intent != "routine":
    msg = security.check(cmd)            # None = go ahead
    if msg:
        if not security.pending():
            return msg                   # blocked: guest mode / locked out
        io.say(msg)                      # "Say your PIN." / "Jarvis is locked. Say your PIN."
        ok, reply = security.verify(io.listen())
        if not ok:
            return reply
        # right PIN: carry on and run cmd (it then goes through the normal confirm step)
```
- Run the check BEFORE the "Are you sure?" confirm, so a guest can't even hear the question.
- `routine` itself is not checked; each step goes through `_run_one`, so each step is checked.
- Call `security.configure()` once at start (it also loads lazily on first use).
- `dictation` and quiz answers bypass `_run_one`: if Jarvis is locked or in guest mode, add the same check
  (`security.check("dictation")`) before `dictation.process`, or dictation can type while locked.
- Shortcuts / snippets also end in `_run_one`, so they are covered.

## Never log the PIN
- main logs `heard=%r` and args. Wrap with `security.redact(text)` (hides 4+ digit numbers, runs of digit words,
  and everything while a PIN is pending). For `jarvis_lock` log args without `pin`.
- The text heard by `io.listen()` for the PIN must not go to the log, "repeat that" (`_record`), or history (piece AF).
- `verify` replies never contain the PIN.

## Setup (user)
`python -m jarvis.actions.security set-pin` (asks twice, hidden). Saves only a salted PBKDF2 hash to `~/.jarvis-pin`
and prints a `pin_hash:` line that can go in config.yaml instead. A plain `pin:` in config is ignored with a warning.
No PIN set = everything runs as before; "lock Jarvis" / "guest mode on" say how to set one.

Optional config (config.py DEFAULTS: `"security": {}`):
```yaml
security:
  pin_hash: ""              # from set-pin; empty = read pin_file
  pin_file: "~/.jarvis-pin"
  protect: [shutdown, restart, software, phone, device, scene, delete_file, move_file, rename_file,
            copy_file, empty_recycle_bin, kill_process, computer_use, whatsapp, email, forget_memory,
            list_clear, "history:clear"]   # "intent" or "intent:action"
  guest_mode_intents: [time, weather, world_time, date_calc, calculate, convert, define, synonyms, spell,
                       wikipedia, news, help, random_pick, quiz, timer, timers, volume, media, play, now_playing, repeat]
  max_tries: 3
  lockout_minutes: 5
  grace_seconds: 0          # after a right PIN, don't ask again for this long
```
Unknown text sent to the AI (`unknown`) is not in the guest list, so guests get "Guest mode is on" for chat.
Add `unknown` to guest_mode_intents to allow AI chat (its tool calls are still checked in `_run_one`).

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "lock Jarvis", "lock yourself", "Jarvis lock" | jarvis_lock | {state: "on"} |
| "unlock Jarvis", "unlock yourself" | jarvis_lock | {state: "off"} (main asks for the PIN) |
| "unlock Jarvis 4 8 2 1", "unlock Jarvis one two three four" | jarvis_lock | {state: "off", pin: "<raw words after unlock>"} |
| "are you locked", "is Jarvis locked" | jarvis_lock | {state: "status"} |
| "guest mode on", "turn on guest mode", "enable guest mode", "start guest mode" | guest_mode | {state: "on"} |
| "guest mode off", "turn off guest mode", "exit guest mode", "stop guest mode" | guest_mode | {state: "off"} |
| "is guest mode on" | guest_mode | {state: "status"} |

Notes:
- "lock Jarvis" must come BEFORE the existing `lock` (lock the computer) rule; plain "lock" / "lock the computer" stays `lock`.
- `pin` may be digits or words; the module parses it (`spoken_digits`). Pass the raw text after "unlock jarvis".
- While locked, every intent gets "Jarvis is locked. Say your PIN."; a right PIN unlocks and then runs that command.
- 3 wrong PINs -> PIN refused for 5 minutes; meanwhile only guest intents run (and nothing while locked).
- State (locked / guest) is in memory only; restarting Jarvis clears it.
