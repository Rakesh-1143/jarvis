# Wiring notes: piece BU (voiceid.py)

Merge: `from .voiceid import CATALOG as CBU, HANDLERS as HBU`, then update catalog CATALOG and _HANDLERS.
Add `voiceid` to the module import line in actions/__init__.py.

Intent: `voice_id {action: enrol|check|on|off|status|forget}`. `"info": False` in CATALOG.

## security.py (shared file: wiring thread edits it)
1. Add the voice intents to `DEFAULT_PROTECT` (enrolling, turning the lock off and forgetting need the PIN):
   ```python
   "voice_id:enrol", "voice_id:off", "voice_id:forget",   # = voiceid.PROTECT
   ```
   Without this, `voice_id enrol` refuses on its own ("needs your PIN"), so enrolling would never work.
   Users with their own `security.protect` list in config.yaml must add these too (mention in README).
2. Add one small public helper (used as the PIN backup when the voice does not match on a risky,
   non-protected command such as `phone sms`):
   ```python
   def ask_pin() -> str | None:
       """Ask for the PIN now (voice ID backup). None = no PIN, or PIN blocked after wrong tries."""
       with _lock:
           if not has_pin() or _locked_out():
               return None
           return _ask()
   ```
   Without it, `voiceid.guard` refuses those commands with "That needs the owner's voice." (fails closed).

## Confirm step (actions/__init__.py `_risky_text`)
```python
if intent == "voice_id" and voiceid.needs_confirm(args):  # forget (only when a voice print exists)
    return voiceid.risky_text(args)
```
Question: "forget your voice print (voice lock turns off)". The handler also refuses to delete without `confirm`.

## main.py hooks
1. At start, next to `onboarding.set_io(...)`:
   ```python
   actions.voiceid.set_io(io.say, voice=not args.text)   # "learn my voice" talks and records 5 sentences
   ```
2. Keep the last command's audio. `stt.listen()` returns only text today, so stt.py needs a tiny change:
   collect the chunks it already reads into a buffer and keep them, e.g.
   ```python
   # stt.py
   last_audio: bytes = b""
   def listen(...):
       buf = bytearray()
       for chunk in chunks:
           buf += chunk          # 16 kHz 16-bit mono (already resampled)
           ...
       # on every return path: global last_audio; last_audio = bytes(buf[-15*32000*2:])  (cap ~15-30 s)
   ```
   Then in VoiceIO.listen (main.py): after `self.stt.listen(...)`, call
   `actions.voiceid.remember_audio(self.stt.last_audio)`. TextIO: `voiceid.clear_audio()` (typed commands
   have no voice, so voice lock falls back to the PIN).
   Do NOT call `remember_audio` for the listen that hears a PIN or a "yes" (`_security_ok` / confirm):
   only the command phrase. Simplest: call it in the main loop right after the command text is heard
   (where the follow-up / wake listen happens, ~main.py:575-600), not inside VoiceIO.listen.
3. Replace the body of `_security_ok(cmd, io, actions)`:
   ```python
   voiceid = getattr(actions, "voiceid", None)
   if voiceid is not None:
       return voiceid.guard(cmd, io, getattr(actions, "security", None),
                            risky=_needs_confirm(cmd, cfg, actions))
   ... old code as fallback ...
   ```
   (`_security_ok` needs `cfg` passed in for `_needs_confirm`; or pass `actions.needs_confirm(cmd)`.)
   `guard` keeps every old rule: lock / guest mode / lockout from `security.check` always win; the voice
   only replaces the "Say your PIN." prompt; it never unlocks a locked Jarvis, never turns guest mode off,
   never runs `setup` and never enrols. `no_ask` (background triggers) never uses the voice and never asks.
4. Places that call `security.check("dictation")` / `("interpreter")` directly can stay as they are.

## brain.py
- GUARDED_ACTIONS += `voice_id` (enrol/on/off/forget change security). Not in UNTRUSTED_INFO.

## NLU phrases -> args
| Say | Intent / args |
|---|---|
| "learn my voice", "remember my voice", "train my voice", "enrol my voice" | voice_id {action: enrol} |
| "who am I", "do you know my voice", "is this my voice", "do you recognise me" | voice_id {action: check} |
| "voice lock on", "turn on voice lock", "only listen to my voice" | voice_id {action: on} |
| "voice lock off", "turn off voice lock" | voice_id {action: off} |
| "is voice lock on", "voice lock status" | voice_id {action: status} |
| "forget my voice", "delete my voice print" | voice_id {action: forget} |

Notes:
- Don't clash with jarvis_lock ("lock Jarvis") or tts voice settings ("change your voice"): match
  "voice lock" / "my voice" only. "who am I" must not go to the AI or to onboarding's name lookup.
- "forget my voice" must not go to `forget_memory`.

## config.yaml (optional block, all have defaults)
```yaml
voiceid:
  threshold: 0.75          # 0.5-0.99; out of range = 0.75
  file: "~/.jarvis/voiceid.json"
  samples: 5               # 3-7 sentences when enrolling
```
Note: the voice print is saved as JSON (256 numbers, file mode 600), not `voiceid.npy` as the spec said:
no pickle risk and no numpy needed to read it.

## requirements.txt
`resemblyzer` (optional; pulls numpy + torch, ~800 MB). Put it in the optional section; without it the intent
says "Voice ID needs the resemblyzer package" and voice lock checks fail closed (PIN still works).

## Test on real Windows
- `pip install resemblyzer`; "learn my voice" -> PIN -> read 5 sentences. Check `~/.jarvis/voiceid.json` exists.
- "who am I" from you (expect owner) and from another person / a YouTube voice (expect not). Note the scores
  in the log (`voice check: ... score`) and tune `threshold` if needed (owner usually 0.80+, others < 0.70).
- With voice lock on: "shut down" by you runs without the PIN prompt (then "are you sure?"); by someone else
  asks the PIN. "lock Jarvis" then "unlock Jarvis" must still need the PIN.
- First resemblyzer load takes a few seconds (torch); check it doesn't block the wake word for long.
- Tests: tests/test_voiceid.py (26, all faked, Linux).
- Known limit: a recording of the owner's voice can pass the check. Voice lock is a convenience, not as
  strong as the PIN; say so in the README.
