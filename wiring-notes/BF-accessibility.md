# Wiring notes: piece BF (accessibility.py)

Files: `jarvis/actions/accessibility.py`, `tests/test_accessibility.py` (64 tests).
Merge: `from .accessibility import CATALOG as CBF, HANDLERS as HBF`, then update catalog CATALOG and _HANDLERS.
No new packages (pyautogui, psutil already in requirements; winreg is built in).
Duplicate check: nothing in jarvis/ for magnifier/narrator/captions/colour filter. winsettings.py only opens the
general `ms-settings:easeofaccess` page ("open accessibility settings") - keep that, no overlap.

## Intent
| Intent | Args | Kind |
|---|---|---|
| accessibility | {feature: magnifier\|narrator\|captions\|color_filter\|text_size\|cursor, action?: on\|off\|toggle\|zoom_in\|zoom_out} | action |

Not risky, not info. Brain: fine for the AI to call (no GUARDED/UNTRUSTED change needed).

## How it works
- Magnifier: Win+= (Win+Plus) starts it / zooms in, Win+- zooms out, Win+Esc closes.
- Narrator Ctrl+Win+Enter, Live captions Win+Ctrl+L (Windows 11 22H2+), colour filter Win+Ctrl+C.
- These are toggles, so "on"/"off" first check state: Magnify.exe / Narrator.exe / LiveCaptions.exe via psutil,
  colour filter via `HKCU\Software\Microsoft\ColorFiltering` `Active`. Already in that state -> says so, no key press.
- Colour filter shortcut is off by default in Windows (`HotkeyEnabled` = 0): then it opens
  `ms-settings:easeofaccess-colorfilter` and tells the user to turn on the shortcut once.
- text_size / cursor only open `ms-settings:easeofaccess-display` / `ms-settings:easeofaccess-mousepointer`.
- If a hotkey fails, it opens that feature's Settings page instead.

## NLU
Use `accessibility.parse(text) -> ("accessibility", {feature, action}) | None` in nlu_features.
**Place it before nlu_control's generic key rules.** Bare "zoom in"/"zoom out" return None on purpose
(nlu_control maps them to Ctrl+Plus/Minus for the browser); magnifier zoom needs "magnify"/"magnifier".
| Say | feature | action |
|---|---|---|
| "turn on the magnifier", "magnifier on", "open magnifier" | magnifier | on |
| "magnify", "magnify more", "magnifier zoom in", "zoom in with magnifier" | magnifier | zoom_in |
| "magnifier zoom out" | magnifier | zoom_out |
| "close the magnifier", "magnifier off" | magnifier | off |
| "turn on narrator", "start the screen reader", "stop narrator", "toggle narrator" | narrator | on/off/toggle |
| "turn on live captions", "show captions", "live captions off" | captions | on/off |
| "turn on colour filter", "turn on grayscale", "grayscale off" | color_filter | on/off |
| "make the text bigger", "bigger text", "change text size" | text_size | toggle |
| "make the cursor bigger", "bigger mouse pointer" | cursor | toggle |

Bare "subtitles" is not caught (could mean YouTube subtitles); "captions" is.

## main.py / config
Nothing.

## Hand test on Windows
1. "turn on the magnifier", "magnifier zoom in", "magnifier zoom out", "close the magnifier" (check Win+= works on your keyboard layout).
2. "turn on narrator" then "stop narrator".
3. "turn on live captions" (Windows 11 22H2+ only).
4. "turn on grayscale": first time it should open Settings; enable the shortcut, then ask again.
5. "make the text bigger" and "bigger mouse pointer" open the right Settings pages.
