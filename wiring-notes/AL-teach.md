# Wiring notes: piece AL (teach.py)

Merge: `from .teach import CATALOG as CAL, HANDLERS as HAL`, then update catalog CATALOG and _HANDLERS.
Also `from . import teach` in actions/__init__.py so main can use `actions.teach`.
No new packages (json + re only).

## Intents
- `teach {phrase, steps?: [str], answer?: str}` - saves. Not risky (running the steps later is checked).
- `taught {action: list|forget, phrase?}` - list is info; **forget is risky**.

## Risky (actions/__init__.py)
- `_risky_text`: `if intent == "taught": return teach.risky_text(args)` (returns None unless forget of a known phrase).
- `_do_risky`: `if intent == "taught": return teach.taught(args)` (args has confirm=True).

## NLU (nlu_features.py) - helpers already written, just call them
```python
from jarvis.actions import teach
a = teach.parse_teach(text)    # "when I say X, do Y / say Y" -> {phrase, steps} or {phrase, answer}
if a: return Command("teach", a)
a = teach.parse_taught(text)   # "what have you learned" / "forget the command X"
if a: return Command("taught", a)
```
Put `parse_teach` near the top (the sentence holds other commands, e.g. "open notes", that must not win).
`parse_taught` "forget X" only matches words starting with forget/unlearn, or delete/remove + "command".

| Say | Command |
|---|---|
| "when I say study time, open notes and start focus" | teach {phrase: "study time", steps: ["open notes", "start focus"]} |
| "whenever I say movie night, open netflix then set volume to 60" | teach {phrase, steps} |
| "when I say good night, say sleep well" | teach {phrase: "good night", answer: "sleep well"} |
| "what have you learned", "what did I teach you", "list my taught commands" | taught {action: list} |
| "forget the command study time", "forget study time" | taught {action: forget, phrase: "study time"} |

## main.py hook (in handle, after shortcuts.match, before nlu.parse)
```python
teach = getattr(actions, "teach", None)
if teach is not None:
    reply = teach.run(text, lambda s: handle(s, io, cfg, nlu, actions, brain, depth + 1), io.say, depth)
    if reply is not None:
        return reply
```
- Each step goes through `handle` again, so routines, shortcuts, nlu, AI and the normal
  "are you sure?" confirm all still apply (test: `test_taught_risky_step_still_asks_yes`).
- `run` stops when depth > 2 (a command that calls itself).
- Returns "" after steps (each step reply is already spoken), the fixed answer for "say" commands,
  or None when the text is not a taught phrase.

## brain.py
Add `teach` and `taught` to GUARDED_ACTIONS: text from a web page / email must not be able to teach
or forget commands. Only teach when the user clearly asked.

## Config (optional)
`taught_file: ~/.jarvis/taught.json` (default if missing). config.py DEFAULTS may add it; works without.

## Safety
- Will not learn reserved phrases (yes/no/cancel/stop/goodbye/start listening/help...) or phrases < 3 letters,
  so "yes" can never be hijacked to run something.
- Max 10 steps. A command cannot list itself as a step.
