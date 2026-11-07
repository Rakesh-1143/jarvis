# Wiring notes: piece AS (corrections.py)

Files: `jarvis/actions/corrections.py`, `tests/test_corrections.py` (51 tests).
Merge: `from .corrections import CATALOG as CAS, HANDLERS as HAS`, then update catalog CATALOG and _HANDLERS.
No new packages (json + re only). Nothing Windows-specific.

## Risky
- None. "remove correction" is small and easy to undo (say the fix again). No confirm needed.

## Brain
- `GUARDED_ACTIONS += correction, corrections`. The AI must not add or remove word fixes on its own
  (a bad fix changes every later command). Only the user's own words should make them.
- `UNTRUSTED_INFO += corrections` (list reads back user-saved text).
- `misheard` is safe for the AI (it only appends to misheard.jsonl).

## Config (optional)
```yaml
corrections_file: "~/.jarvis/corrections.json"
misheard_file: "~/.jarvis/misheard.jsonl"
```
Module has its own defaults; adding them to config.py DEFAULTS is optional.

## main.py hooks
1. **Apply fixes right after listen** (voice and `--text` input), before dictation/routines/shortcuts/teach/nlu:
   ```python
   text = corrections.apply(text)
   ```
   `apply()` never raises, is whole-word + case-insensitive, longest phrase first, one pass.
   It leaves correction commands themselves unchanged (so "remove correction note pad" still works).
   It also remembers the last few raw texts in memory, so "you misheard" can save what was really heard.
2. **No `set_last()`**. The spec said `set_last(text, cmd, reply)`, but per the Round 6 duplicate check
   the last command comes from `history.py`. So `history.log(...)` (AF hook) must be wired, or
   "you misheard" answers "I don't know what the last command was".
   Note: history logs the text **after** `apply()`; misheard.jsonl stores both (`heard` and `raw`).

## NLU phrases -> intent + args
Use `corrections.parse(text) -> (intent, args) | None` in nlu_features.
**Check it before `teach.parse_teach`**: "when I say chrome, I mean google chrome" would otherwise become a teach
command with step "I mean google chrome".

| Say | Intent | Args |
|---|---|---|
| "when you hear note pad I mean notepad", "when I say chrome I mean google chrome", "whenever you hear X it means Y", "remember that when you hear X you should hear Y" (quotes and "Jarvis," ok) | correction | {heard, meant} |
| "you misheard (me)", "that was wrong", "that's wrong", "you heard me wrong", "you got it wrong", "wrong command", "(no,) that's not what I said" | misheard | {} |
| "you misheard, I said notepad" | misheard | {said: "notepad"} |
| "list corrections", "show my corrections", "my corrections", "what corrections do you have" | corrections | {action: list} (info) |
| "remove/delete/forget (the) correction (for) note pad" | corrections | {action: remove, heard: "note pad"} |

Notes:
- `corrections list` is info (read back, no action).
- Refused fixes: yes/no/ok/cancel/stop/exit/goodbye/jarvis/help words on either side, same words,
  over 6 words or 60 chars, more than 200 fixes.
- Remove also works with the right word ("remove correction google chrome").
