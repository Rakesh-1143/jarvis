# Wiring: piece AB `triggers.py` ("when X happens, do Y")

Files: `jarvis/actions/triggers.py`, `tests/test_triggers.py` (48 tests). No new packages (psutil already used; Wi-Fi via `network.wifi_info()`).

## actions/__init__.py
- `from . import triggers`; merge `triggers.HANDLERS` into `_HANDLERS`, `triggers.CATALOG` into `CATALOG`.
- Intent `triggers {action: list|pause|resume}`. `list` is info. **No risky intents.**

## nlu (nlu_features.py)
- Call `triggers.parse(text)` -> `("triggers", {"action": ...})` or None.
  Phrases: "list my triggers", "what triggers do I have", "pause triggers", "turn off my automations",
  "triggers off", "resume triggers", "turn triggers on", "start my triggers again".
- Does not claim "pause music", "open zoom", "what is a trigger".

## main.py
- At start: `actions.triggers.start(runner=lambda p: <run phrase like a routine step>, notify=io.say)`.
  Suggested runner: `lambda p: handle(p, io, cfg, nlu, actions, brain, depth=1)` (returns the reply; the module speaks it).
  Returns None and starts no thread when config has no triggers.
- Optional at exit: `triggers.stop()`.
- **Safety (important):** the runner runs on the trigger thread. It must NOT auto-confirm. A risky step
  (shutdown, delete...) should still ask "Are you sure?" or be skipped. Triggers come only from config.yaml
  (user-written), never from AI/voice.
- Thread note: steps run on the background thread while the main loop may be listening. If `handle`/`io`
  is not thread-safe, wrap the runner in a lock shared with the main loop (same issue as recurring/timers notify).
- brain.py: nothing needed (`triggers` only lists/pauses).

## config.yaml (optional, add commented example)
```yaml
triggers:
  - when: {app_opens: zoom}          # or app_closes; name = process name or a key in apps:
    do: ["volume 20", "open notes"]
  - when: {wifi: Home}               # joined this Wi-Fi
    do: ["open spotify"]
  - when: {charger: unplugged}       # or plugged
    do: ["brightness 40"]
  - when: {time: "09:00", days: weekdays}   # quote the time
    do: ["open outlook"]
    say: "Good morning."             # optional; "" = silent; default e.g. "zoom opened."
```
- No `config.py` DEFAULTS change needed (missing key = no triggers).

## Behaviour
- Checks every 3 s; only reads the sensors that some trigger needs.
- Fires on change only. What is already true when Jarvis starts does not fire.
- Time triggers fire once a day, only within 2 min after the time (skipped if the laptop was asleep).
- Paused: state still tracked, so resuming does not fire old changes. Pause is in memory (resets on restart).
- App match: lowercase, no ".exe", no spaces; names of 4+ letters also match inside a process name ("teams" -> "ms-teams").
- Bad config entries are skipped and logged; "list my triggers" says how many were skipped.
