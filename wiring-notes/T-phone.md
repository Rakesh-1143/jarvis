# Piece T: phone link (`actions/phone.py`)

Tests: `tests/test_phone.py` (23 pass, fake kdeconnect-cli).

## Change from the spec
Battery is its own intent `phone_battery` (info). `phone` (ring/sms/share) is NOT info.
Reason: REVIEW.md says info intents must not act (the brain runs info tools with no question).

## Wire it
- `actions/__init__.py`: import `phone`, then `_HANDLERS.update(phone.HANDLERS)` and `CATALOG.update(phone.CATALOG)`.
- `_risky_text`: add
  ```python
  if intent == "phone":  # only action=sms with a number and text
      return phone.risky_text(args)
  ```
  `_do_risky` needs nothing special: the handler sends only when `args["confirm"]` is True.
- `main.py`: no hooks. No new requirements (uses `pyperclip`, already present).

## Intents
- `phone {action: ring|sms|share, to?, text?, what?}`
  - sms: `to` = contact name or number, `text` = message. Risky (asks yes).
  - share: `what` = URL, text, file path (inside user home), "clipboard"/"this link" (default), or "last download".
- `phone_battery {}` (info, read only).

## NLU phrases
- ring: "ring my phone", "find my phone", "where is my phone", "make my phone ring" -> `phone {action: ring}`
- sms: "text mom saying I'm late", "send a text to mom saying ...", "send an sms to 98765 43210 saying ...",
  "message mom on my phone that ..." -> `phone {action: sms, to, text}`.
  Careful: "message mom ..." without "text/sms/phone" should stay WhatsApp. Suggest: only words "text", "sms", "send a text" go here.
- share: "send this link to my phone", "send this to my phone", "send my clipboard to my phone" -> `{action: share, what: "clipboard"}`;
  "send my last download to my phone" -> `{action: share, what: "last download"}`;
  "send <url> to my phone" -> `{action: share, what: <url>}`.
- battery: "phone battery", "how much battery does my phone have", "is my phone charging" -> `phone_battery {}`.
  Careful: must come before the laptop `system_info` battery rule (any phrase with "phone").

## Config (optional, config.yaml)
```yaml
phone:
  kdeconnect_path: ""   # full path to kdeconnect-cli.exe; empty = PATH or Program Files\KDE Connect\bin
  device: ""            # phone name or id; empty = first connected phone
```
Phone numbers: `contacts: {mom: {email: "...", phone: "+91..."}}` (same as WhatsApp).

## Verify on Windows
- Install: `winget install KDE.KDEConnect`, pair the phone. SMS needs the SMS permission in the phone app.
- Battery reads through `qdbus` next to kdeconnect-cli; if the Windows build has no qdbus, Jarvis says to check the app.
- `--share-text` needs KDE Connect 21.04+.
