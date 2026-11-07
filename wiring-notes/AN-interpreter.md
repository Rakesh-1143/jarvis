# Wiring notes: piece AN (interpreter.py)

Merge: `from .interpreter import CATALOG as CAN, HANDLERS as HAN`, then update catalog CATALOG and _HANDLERS.
Intent:
- `interpreter {state: on|off, language?}` - not info, not risky.
No required new packages. Optional: `deep-translator` (used if installed; else plain urllib to Google's free endpoint).
Translation order: Claude (config `ai.api_key` or ANTHROPIC_API_KEY, model `ai.model`) -> Google free.
No config needed.

## Module API
- `interpreter.is_active() -> bool`
- `interpreter.process(text) -> str` - handles one phrase while on. Returns what main should say:
  `""` means it was already spoken with a voice for that language. Otherwise main says the text with the
  default voice. Never raises. Handles "stop translating", "switch to X" / "translate to X", "say that again".
- `start(language)`, `stop()`, `language()`, `find_language(word)`.

## main.py hook (shared file, wiring thread only)
In `handle()`, right after the dictation check (before quiz / routines / nlu):
```python
interpreter = getattr(actions, "interpreter", None)
if interpreter is not None and interpreter.is_active():
    return interpreter.process(text)  # "" = already spoken
```
Also on exit nothing is needed (no threads).
Note: the AI brain must NOT see translated phrases; this hook skips nlu and brain, like dictation.

## brain.py
- No GUARDED/UNTRUSTED changes needed. The `interpreter` tool only turns a mode on/off.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "translate mode Hindi", "translate mode in Hindi", "interpreter mode Spanish", "be my Telugu interpreter", "start translating to Hindi", "translate everything into French" | interpreter | {state: "on", language: "<word>"} |
| "translate mode", "interpreter mode" (no language) | interpreter | {state: "on"} -> asks "Which language?" |
| "stop translating", "stop translation", "exit translate mode", "stop interpreter" | interpreter | {state: "off"} |

Notes:
- Do NOT catch one-off "translate hello to Hindi" here: that is a single question for the AI brain.
  Only "translate mode ..." / "interpreter ..." / "start translating ..." / "translate everything ..." turn the mode on.
- Language word is passed raw; the handler accepts names (Hindi), codes (hi) and aliases (Mandarin).
- STT is the English Vosk model, so the user speaks English and Jarvis speaks the other language.
- Windows voices: Hindi/Telugu etc. need a language pack voice (Settings > Time & language > Speech > Add voices).
  Without one, the default English voice reads the text (poor for non-Latin scripts), and the text is printed in the log.
