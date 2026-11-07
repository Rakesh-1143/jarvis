# Piece Q: voice memos — wiring notes

Files: `jarvis/actions/memos.py`, `tests/test_memos.py` (14 tests pass). No new packages (uses `sounddevice`, already in requirements; `wave`, `winsound` are built in; `Send2Trash` already there).

## actions/__init__.py + catalog
- Merge `memos.CATALOG` and `memos.HANDLERS` (one intent: `memo {action: record|stop|play|list|delete|open, which?}`).
- Risky only when `action == "delete"`: in `_risky_text` add `if intent == "memo": return memos.risky_text(args)` (returns None for other actions). Handler never deletes without `confirm=True`.

## main.py hooks
1. At start: `memos.set_notifier(io.say)` (says "Memo saved, 12 seconds." when recording ends by silence/max time).
2. After speaking the reply to a `memo` record command: `memos.begin()` (starts recording now, so the reply is not recorded; without it, it starts after 1.5 s).
3. Main loop, before `wait_for_wake_word` / `listen` (and before follow-up listening):
   `while memos.is_recording(): time.sleep(0.2)` — never open the mic while recording.
   Recording stops by itself after 3 s of quiet, 8 s with no speech, or 2 minutes.
   Text mode (`--text`): typing "stop recording" works, since it doesn't use the mic.

## NLU phrases
- record: "record a (voice) memo", "take a voice memo", "start a voice memo", "new voice memo", "record a voice note"
- stop: "stop recording (the memo)", "stop the memo", "cancel the memo" — only when `memos.is_recording()`, else let "stop recording" go to recorder.py (screen recording). Also "stop playing the memo".
- play: "play my (last|latest) memo", "play memo 2", "play the first memo", "play my previous memo" -> which = last / 2 / first / previous
- list: "list my memos", "what voice memos do I have", "how many memos do I have"
- delete: "delete my last memo", "delete memo 3" -> which (risky)
- open: "open my memos folder", "show my voice memos"

## Config (optional, all have defaults)
```yaml
memos:
  folder: "~/Documents/Jarvis memos"
  max_seconds: 120
  silence_seconds: 3
  no_speech_seconds: 8
  silence_level: 500   # raise if a noisy room never counts as quiet
  start_delay: 1.5
```
