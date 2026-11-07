# Wiring notes: piece BS (webcam.py)

Files: `jarvis/actions/webcam.py`, `tests/test_webcam.py` (37 tests).
Merge: `from .webcam import CATALOG as CBS, HANDLERS as HBS`, then update catalog CATALOG and _HANDLERS.
Duplicate check: apps.py only opens the Camera app; winsettings opens `ms-settings:privacy-webcam`.
No hands-free photo or "camera in use" check anywhere.

## New package (requirements.txt, optional)
```
opencv-python>=4.8  # webcam: take a photo (optional)
```
Without it, "take a photo" says how to install it. "Is my camera on" needs nothing (winreg).

## Intents
| Intent | Args | Kind |
|---|---|---|
| webcam | {action: photo\|status, delay?: 0-10} | status = info; photo = action |

- Photo: DirectShow first (fast open), then Media Foundation; 10 warm-up frames; JPEG saved with `write_bytes`
  (cv2.imwrite fails on non-English paths); camera released in `finally`. Countdown beeps each second (winsound).
  Never overwrites (adds " (2)"). Warns if the photo is black (camera cover closed).
- Status: `HKCU` + `HKLM` `...\CapabilityAccessManager\ConsentStore\webcam` (and `NonPackaged`):
  `LastUsedTimeStop == 0` and `LastUsedTimeStart != 0` means in use now.
- Not risky (one photo the user asked for, saved locally, the reply says so).

## Brain
- `GUARDED_ACTIONS += webcam` (privacy: the AI must not take photos on its own). Status is fine.
- `UNTRUSTED_INFO += webcam` (app names come from the registry).

## main.py hook
None. The countdown blocks the handler for up to 10 s (beeps only, nothing spoken mid-way).

## Config (optional, defaults work)
```yaml
webcam:
  folder: "~/Pictures/Jarvis"   # default: Pictures (or OneDrive/Pictures)/Jarvis
  camera: 0
  open_after: true
```
Add `"webcam": {"camera": 0, "open_after": True}` to `config.DEFAULTS` (leave folder out so the default is used).

## NLU
Use `webcam.parse(text) -> (intent, args) | None` in nlu_features, before open_app.
Returns None for anything with "screen" (screenshot stays with its rule) and for "open camera" (apps.py).

| Say | Args |
|---|---|
| "take a photo", "take a picture", "click a selfie", "take a photo with the webcam" | {action: photo} |
| "take a photo in 3 seconds", "take a picture in five seconds" | {action: photo, delay} |
| "take a selfie with a timer" | {action: photo, delay: 3} |
| "is my camera on", "is the webcam in use", "which app is using my camera", "who is using my webcam" | {action: status} |

## Hand test on Windows
`pip install opencv-python`, then "take a photo", "take a photo in 3 seconds" (3 beeps + high beep), check
Pictures\Jarvis. Open Teams/Zoom with video on and ask "is my camera on" (should name the app), then close it and ask again.
