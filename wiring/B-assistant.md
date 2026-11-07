# Piece B (assistant controls): wiring notes

Module: `jarvis/actions/assistant.py` (`CATALOG`, `HANDLERS`). Tests: `tests/test_assistant.py`.

## actions/__init__.py
- Merge `assistant.CATALOG` into `CATALOG` and `assistant.HANDLERS` into `_HANDLERS`.
- Call `assistant.set_catalog(CATALOG)` after all pieces are merged (help then lists only features that exist).
- No risky intents.

## nlu.py phrases
| Phrase | Command |
|---|---|
| what can I say / what can you do / help / show commands | `help {}` |
| help with timers / how do I use music / what can I say about windows | `help {topic: "timers"}` |
| stop listening for 10 minutes / go quiet for 5 minutes / pause for an hour | `pause_listening {minutes: 10}` |
| stop listening / go quiet / be quiet / go to sleep jarvis | `pause_listening {}` (until resumed) |
| start listening / resume listening / wake up / I'm back | `resume_listening {}` |
| repeat that / say that again / what did you say / pardon | `repeat {}` |
| speak slower / talk slower / slow down | `voice {change: slower}` |
| speak faster / talk faster | `voice {change: faster}` |
| speak louder / talk louder | `voice {change: louder}` |
| speak quieter / speak softer / talk quieter | `voice {change: quieter}` |
| normal voice / reset your voice | `voice {change: reset}` |

Careful: "go to sleep" (no "jarvis") is the existing PC `sleep` intent. "stop" alone is media/cancel. "volume up" stays `volume`.

## main.py hooks (in `run()`)
1. Pause check, right after `text = io.listen()` and inside the follow-up loop:
   ```python
   if assistant.is_paused() and not assistant.allowed_while_paused(text) and not is_exit(text, cfg["exit_phrases"]):
       text = None
       continue          # ignore everything except "start listening"
   ```
   Also skip the beep/greeting while paused (or keep it; user choice). The wake word itself still works, so "Jarvis, start listening" can end the pause.
2. Last reply: call `assistant.new_turn()` before `handle(text, ...)`, and `assistant.record(text)` inside `io.say` (VoiceIO and TextIO), but not for the beep, "I did not hear anything", or "Jarvis is ready". This keeps whole streamed AI answers for "repeat that".
   Simpler option: `assistant.set_last_reply(reply)` after `io.say(reply)` (misses streamed AI answers).
