# Wiring notes: piece AR (tray.py, system tray icon)

No intents (CATALOG and HANDLERS are empty dicts), so nothing to add to catalog / nlu / brain.
Do NOT add it to the `_HANDLERS` merge. Only main.py hooks and one requirement.

## requirements.txt
Add: `pystray>=0.19  # tray.py: system tray icon (uses Pillow)`. Pillow is already there.
If pystray is missing or there is no desktop, `tray.start()` logs a warning and returns False; every other
tray call then does nothing. So Jarvis never crashes because of the tray.

## main.py
1. In `main()`, after `_wire_features(io, actions)`, only in voice mode (`not args.text`):
   ```python
   if not args.text:
       from jarvis.actions import tray

       def _quit_from_tray():
           _stop_recordings(actions)
           os._exit(0)  # the main loop is blocked in the mic; a normal return can't reach it

       tray.start(on_quit=_quit_from_tray, say=io.say,
                  config_file=args.config or None, log_file=cfg["log_file"])
   ```
   (`import os` at the top of main.py.) Leave `on_restart` out: the default starts `sys.executable + sys.argv`
   again (works for `python main.py` and for `pythonw start_jarvis.pyw`) and then calls on_quit.
2. `set_state` in `run()` (any thread, cheap, safe with no tray):
   - before `io.wait_for_wake_word()` -> `tray.set_state("idle")`
   - before `text = io.listen()` and in `_next_phrase` before follow-up listening -> `"listening"`
   - before `reply = handle(...)` -> `"thinking"`
   - around `io.say(reply)` -> `"speaking"`, then back to `"idle"` / `"listening"`.
   Simplest: wrap in VoiceIO (`say` sets speaking, `listen` sets listening, `wait_for_wake_word` sets idle) plus one
   `set_state("thinking")` before `handle`. Pick one place, not both.
3. On "goodbye" exit and in `KeyboardInterrupt`: `tray.stop()` (also fine to `atexit.register(tray.stop)`).
4. Tests can pass a fake actions module, so get tray with `getattr(actions, "tray", None)` if you import it in
   actions/__init__.py, or import it directly as above.

## Menu
| Item | Does |
|---|---|
| Pause listening / Resume listening (double-click icon) | `assistant.pause_listening({})` / `resume_listening({})`, same pause as the voice command. Optional `on_pause(paused)` callback. |
| Open config | opens config.yaml (or `--config` file) with `os.startfile` |
| Open log | opens the log file (relative path = working folder, same as setup_logging) |
| Run self-check | `doctor.self_check({})` in a background thread; result is spoken (`say`) and shown as a balloon |
| Restart Jarvis | starts a new Jarvis, then quits this one |
| Quit | removes icon, then `on_quit()` |

## Icon colours
idle grey, listening green, thinking amber, speaking blue, paused red. While paused (voice or tray), idle/listening
show red; thinking/speaking still show (a timer can speak while paused).

## Notes
- pystray runs its own thread (`jarvis-tray`, daemon). pystray on Windows is fine off the main thread.
- Restart briefly has two Jarvis processes on the mic (new one starts, old one exits right after). Test on real Windows.
- Tests: tests/test_tray.py (18 tests, fake pystray). Full suite on a private copy: 1497 passed, 3 skipped (Linux).
