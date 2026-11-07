# Wiring notes: piece AU (onboarding.py, first-run voice setup)

Merge: `from .onboarding import CATALOG as CAU, HANDLERS as HAU`, then update catalog CATALOG and _HANDLERS.
Intent: `setup {part?: all|name|city|units|greeting|mic|wake|pin|check}`. Not info, not risky.
No new packages. Uses `security.py` (PIN: has_pin, spoken_digits, save_pin) and `doctor.py` (run_checks, summary, write_report). Nothing rebuilt.

## Data
- `~/.jarvis/user.json` (env `JARVIS_USER_FILE` changes it). Keys: name, city, units (metric|imperial), greeting ("beep"|"Yes?"),
  mic_ok, wake_ok, pin_set, check_problems, done, version, created, updated. Never holds a PIN.
- `done: true` = setup finished or stopped by the user (no nagging). Ctrl+C mid-setup saves `done: false` so it runs again next start.

## config.py (reads user.json)
After `cfg = _merge(DEFAULTS, data)` in `load_config`:
```python
try:
    from jarvis.actions import onboarding
    cfg = _merge(cfg, onboarding.config_overrides())
except Exception:
    pass
```
`config_overrides()` returns only keys the user set by voice, in config shape:
`{"user_name": "Rakesh", "weather": {"city": "Hyderabad", "units": "metric"}, "greeting": "beep"}`.
user.json wins over config.yaml for these keys (it is the newer, spoken choice). Add `"user_name": ""` to DEFAULTS.
onboarding.py has no top-level `jarvis` imports, so this import cannot loop (a test checks it).
Note: `load_config` caches; after a `setup` intent, call `load_config(reload=True)` if main keeps a cfg dict
(or simply: main does `cfg.update(load_config(reload=True))` after the setup reply).

## main.py
- New flag: `parser.add_argument("--setup", action="store_true", help="run the voice setup again")`.
- After `io = ...` and `_wire_features(...)`, before `brain` / `run(...)`:
  ```python
  from jarvis.actions import onboarding
  onboarding.set_io(io.say, io.listen, voice=not args.text)
  if args.setup or onboarding.needs_setup():
      reply = onboarding.run(io.say, io.listen, cfg, voice=not args.text)
      io.say(reply)
      cfg = load_config(args.config, reload=True)   # pick up name, city, greeting
  ```
  (`first_run(say, listen, cfg, voice)` does the same but only when needed; returns None if already done.)
- `--doctor` must still run before this (it exits early), so a broken mic cannot block setup checks.
- Security: the PIN step calls `io.listen()` directly, so main's own logging does not see it. onboarding never logs or
  speaks the PIN. Keep it that way (do not route setup answers through `handle()`).
- After the `setup` intent reply, reload config as above so the new name/city/greeting apply now.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "run setup", "run setup again", "set yourself up", "start setup", "redo setup" | setup | {} |
| "change my name", "call me something else" | setup | {part: name} |
| "change my city", "change my location" | setup | {part: city} |
| "change temperature units", "use fahrenheit/celsius" (only if no weather rule takes it) | setup | {part: units} |
| "change the greeting", "beep instead", "stop beeping" | setup | {part: greeting} |
| "test my mic", "test the microphone" | setup | {part: mic} |
| "test the wake word" | setup | {part: wake} |
| "set up a PIN", "create a PIN" | setup | {part: pin} |

Do not map a bare "call me X" to setup (too close to "call my phone" in nlu_features). "check yourself" stays `self_check` (doctor).

## Other modules that can use the name
- `onboarding.user_name(default)` or `cfg["user_name"]` after the config change, e.g. daily briefing "Good morning, Rakesh".
  Optional; wiring thread decides.

## Notes
- Steps: name, city, units, greeting, mic test, wake test (voice mode only), PIN (optional; skipped if a PIN exists;
  says digits twice; changing an existing PIN stays on the keyboard `set-pin` command), self-check (`doctor.run_checks(mic=False)`,
  since the mic was just tested by voice; API key check is inside doctor).
- Each question: "skip" skips, silence twice skips, "stop setup"/"cancel" ends early.
- The wake test uses `io.listen()` (normal speech recognition), not the wake engine, so it is a rough check only. Test on real Windows.
- Tests: tests/test_onboarding.py (68 tests, fakes, temp user.json and PIN file). Full suite on a private copy: 1721 passed, 3 skipped (Linux).
