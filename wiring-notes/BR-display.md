# Wiring notes: piece BR (display.py)

Files: `jarvis/actions/display.py`, `tests/test_display.py` (45 tests).
Merge: `from .display import CATALOG as CBR, HANDLERS as HBR`, then update catalog CATALOG and _HANDLERS.
No new packages: `DisplaySwitch.exe` (Windows 10/11, Sysnative first for 32-bit Python), pywin32 (core) for
screen info, pyautogui (already used) for Win+P.
Duplicate check: winsettings.py only opens `ms-settings:display`; `screen_off` (nlu_control) turns the screen off.
No projection modes or resolution readout anywhere.

## Intents
| Intent | Args | Kind |
|---|---|---|
| display | {action: extend\|duplicate\|external_only\|internal_only\|info\|menu} | info = info; rest = action |

- Not risky. "second screen only" turns the laptop screen dark; "laptop screen only" or Win+P brings it back,
  and Windows also falls back to the laptop screen when the cable is pulled.

## Brain
No change (fine for the AI).

## main.py hook
None.

## NLU
Use `display.parse(text) -> (intent, args) | None` in nlu_features (before web_search: "what's my resolution"
goes to web_search today).
Kept out on purpose: "turn off the screen" (screen_off), "turn off the tv" (smart home), "turn off my pc".

| Say | Args |
|---|---|
| "extend my screen", "extend my screen to the projector" | {action: extend} |
| "duplicate screen", "mirror my screen", "show my screen on the tv", "same picture on both screens" | {action: duplicate} |
| "second screen only", "projector only", "only use the external monitor" | {action: external_only} |
| "laptop screen only", "pc screen only", "disconnect the projector", "stop projecting" | {action: internal_only} |
| "what's my resolution", "how many monitors do I have", "how many screens" | {action: info} |
| "open projection menu", "show the project menu" | {action: menu} |

## Hand test on Windows
Plug in a second screen or projector: "extend my screen", "duplicate screen", "second screen only",
"laptop screen only", "how many monitors", "what's my resolution", "open projection menu".
