# Wiring notes: piece AA (generate.py)

Merge: `from .generate import CATALOG as CAA, HANDLERS as HAA`, then update catalog CATALOG and _HANDLERS.
One intent: `generate {kind: password|pin|uuid|qr, text?, length?}`. Not info. Not risky. No main.py hooks.
Package: `qrcode>=7.4` (already added to requirements.txt; uses Pillow, already there). Missing -> polite "pip install qrcode" reply.
Optional config (defaults work without it):
```yaml
generate:
  password_length: 16
  pin_length: 4
  symbols: true
  speak_secrets: false   # true = also read password/PIN aloud, letter by letter
  clear_after: 60        # seconds; clipboard emptied if it still holds the secret (0 = never)
```

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "generate a password", "make me a strong password", "new password", "create a random password" | generate | {kind: "password"} |
| "make a 24 character password", "password with 20 characters" | generate | {kind: "password", length: 24} |
| "give me a PIN", "random 6 digit pin", "generate a passcode" | generate | {kind: "pin", length?: 6} |
| "generate a uuid", "new guid" | generate | {kind: "uuid"} |
| "make a QR code of this link", "QR code for this", "QR of my clipboard", "show this as a QR code" | generate | {kind: "qr"} (no text = clipboard) |
| "make a QR code for hello world", "QR code of https://x.com" | generate | {kind: "qr", text: "hello world"} |

Notes:
- `length` may be a number or words ("twenty four characters"); the module parses it. Password 8-128, PIN 4-12.
- Text "this", "this link", "it", "clipboard" -> the module reads the clipboard itself, so rules can pass them raw.
- QR PNG goes to `%TEMP%\jarvis_qr.png` and opens in the default image viewer (`os.startfile`).
- Passwords/PINs are never in the reply unless `speak_secrets: true`. If copy fails, it says so and still does not speak it.
- "repeat that" (main._record) only repeats the reply, so the secret is never repeated.
- Piece X (cliphistory) with `skip_secrets: true` should skip these passwords (no spaces, mixed chars, 8-64 long). PINs are digits only and may be kept; fine.
- Put "password" rules before any generic "type ..." / "copy ..." rules so "generate a password" is not typed.
