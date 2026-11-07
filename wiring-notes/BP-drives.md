# Wiring notes: piece BP (drives.py)

Files: `jarvis/actions/drives.py`, `tests/test_drives.py` (44 tests).
Merge: `from .drives import CATALOG as CBP, HANDLERS as HBP`, then update catalog CATALOG and _HANDLERS.
No new packages: psutil (core) + ctypes kernel32 (drive type, volume label). Eject runs PowerShell
`Shell.Application.Namespace(17).ParseName('E:').InvokeVerb('Eject')` (letter checked A-Z first).
Duplicate check: info.py / monitor.py only read C: (system_info disk). No drive list, open or eject anywhere.

## Intents
| Intent | Args | Kind |
|---|---|---|
| drives | {action: list\|space\|open\|eject, drive?} | list/space = info; open/eject = action |

- `drive`: letter ("D", "d:", "d drive", "dee drive"), kind ("pen drive", "usb", "sd card", "external", "cd", "network") or volume label.
- No drive: list/space = all drives; open/eject = the only pen drive (asks "which letter" if two).
- Eject waits up to 5 s for the drive to go; if it is still there: "A file or app is probably still open on it."
- Never ejects the Windows drive (SystemDrive), never network / RAM drives.

## Info / Risky
- Add `drives` to info intents only for `action in (list, space)` (if info is per intent, leave it out: it is cheap).
- Not risky (eject is safe: Windows refuses when files are open).

## Brain
- `UNTRUSTED_INFO += drives` (volume labels are user/vendor text).
- Fine for the AI to call.

## main.py hook
None.

## NLU
Use `drives.parse(text) -> (intent, args) | None` in nlu_features.
**Order matters:** call it BEFORE the old `system_info` disk rule in nlu.py (~line 319, "free space" would steal
"how much free space on D drive") and BEFORE open_app ("open my pen drive" is parsed as open_app today).
It only claims phrases that name a drive, so "how much disk space" still goes to system_info.

| Say | Args |
|---|---|
| "what drives are connected", "which drives do I have", "list my drives" | {action: list} |
| "is my pen drive connected", "is the usb plugged in" | {action: list, drive} |
| "how much space on D drive", "how much space is left on my pen drive", "how full is my d drive" | {action: space, drive} |
| "free space on all drives" | {action: space} |
| "open my pen drive", "open d drive" | {action: open, drive} |
| "eject my pen drive", "safely remove the usb drive", "eject the sd card" | {action: eject, drive} |

## Hand test on Windows
Plug a pen drive: "what drives are connected", "how much space on my pen drive", "open my pen drive",
then "eject my pen drive" with a file open on it (should say busy), close it, eject again.
