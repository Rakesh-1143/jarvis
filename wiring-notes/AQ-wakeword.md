# Wiring notes: piece AQ (wakeword.py)

Merge: `from .wakeword import CATALOG as CAQ, HANDLERS as HAQ`, then update catalog CATALOG and _HANDLERS.
One intent: `wake_sensitivity {change?: up|down, value?}`. No args = say the current level.
Not risky, not info (it saves a setting). brain.py: nothing needed.

## main.py hook (pick engine at start)
In `VoiceIO.__init__`:
```python
from jarvis.actions import wakeword
self.wake_engine, self._wake_wait = wakeword.choose(cfg)
```
and `VoiceIO.wait_for_wake_word` becomes:
```python
def wait_for_wake_word(self) -> None:
    self._wake_wait()
```
`choose()` never raises: if openwakeword or its model is missing it returns ("vosk", stt wait).
If openwakeword breaks later (mic/model error), the wait function switches to Vosk for the rest of the run.
Sensitivity is read on every wait, so a voice change works on the next wake (no restart).

## config.py DEFAULTS / config.yaml (optional, works without)
```yaml
stt:
  engine: vosk
  model_path: models/vosk-model-small-en-us-0.15
  wake_engine: vosk          # vosk | openwakeword  (openwakeword: say "hey Jarvis")
  wake_sensitivity: 0.5      # 0.1 = few wakes .. 0.9 = wakes easily. Voice changes go to wake.json
  wake_model: ""             # optional own .onnx model; built-in: jarvis -> hey_jarvis, alexa, mycroft
wake_file: ~/.jarvis/wake.json
```
Careful: `_merge` must keep the existing `stt` keys when adding these.

## requirements.txt
Optional line: `openwakeword>=0.6 ; sys_platform == "win32"` (pulls onnxruntime). Leave it optional,
since Vosk still works without it. First use downloads the hey_jarvis model (small, one time).

## NLU phrases -> args
| Say | Args |
|---|---|
| "make the wake word more sensitive", "wake word more sensitive", "increase wake sensitivity" | {change: up} |
| "make the wake word less sensitive", "you wake up too often", "stop waking up by mistake" | {change: down} |
| "set wake word sensitivity to 6 / 60 percent / 0.6" | {value: 6} (0.1-0.9, 1-9, 10-90 all accepted) |
| "how sensitive is the wake word", "wake word sensitivity" | {} |

Notes:
- "more/less sensitive" must say "wake" to match (don't steal mic/volume phrases).
- Mapping: score threshold = 1 - sensitivity (default 0.5 = openWakeWord's own default).
- With engine vosk, the reply adds a note that sensitivity only matters for openWakeWord.
- Doctor (AP) could add a check: `wakeword.engine_name()` vs `import openwakeword` works.
- Not tested with a real mic or the real openwakeword package (not installed here). Test on Windows:
  `python -m jarvis.actions.wakeword` prints the engine and waits for "hey Jarvis".
