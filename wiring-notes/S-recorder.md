# Piece S: screen recorder (`actions/recorder.py`)

Tests: `tests/test_recorder.py` (12 pass).

## Wire it
- `actions/__init__.py`: add `recorder` to the module loop (`_HANDLERS.update(recorder.HANDLERS)`, `CATALOG.update(recorder.CATALOG)`).
- Intent: `screen_record {action: start|stop|open}`. Not risky.
- `main.py` (optional): call `actions.recorder.stop_all()` on exit so a running recording is saved.
- No new requirements (uses `pyautogui`, already present). ffmpeg is an optional external program.

## NLU phrases
- start: "start (screen) recording", "record (my) screen", "start recording the screen"
- stop: "stop (screen) recording", "stop recording", "end recording"
- open: "where are my recordings", "open (my) recordings", "show screen recordings"
- Careful: "stop recording" may clash with memos (piece Q) if it uses the same words. Suggest: "stop recording" -> screen_record when a screen recording is running (`recorder._running() or recorder._gamebar`), else memo.

## Config (optional, config.yaml)
```yaml
recorder:
  ffmpeg_path: ""          # empty = find ffmpeg in PATH
  folder: "~/Videos/Jarvis"
  fps: 30
  max_minutes: 60          # 0 = no limit
```
Without ffmpeg it presses Win+Alt+R (Xbox Game Bar, active window only, saves to Videos/Captures).
