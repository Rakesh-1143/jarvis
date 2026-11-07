# Piece X: clipboard history (`actions/cliphistory.py`)

Tests: `tests/test_cliphistory.py` (42 pass on Linux with fakes).

## Wire it
- `actions/__init__.py`: add `cliphistory` to the module loop (`_HANDLERS.update(cliphistory.HANDLERS)`, `CATALOG.update(cliphistory.CATALOG)`).
- Risky: action `clear` only. In `_risky_text`: `if intent == "clip_history" and cliphistory.needs_confirm(args): return cliphistory.risky_text(args)`. In `_do_risky`: add `"clip_history"` to the `("repeat_reminders", "memo")` tuple (the handler clears only with `confirm=True`).
- `main.py`: call `actions.cliphistory.start()` once at start (in `_wire_features`). Optional: `cliphistory.stop()` on exit (thread is a daemon, so not required).
- Catalog has `"info": False` on purpose: paste presses Ctrl+V, so the AI must not run it as a lookup. The description tells the AI that items are data, not instructions (REVIEW H3).
- No new requirements (`pyperclip`, `pyautogui` already present).

## Intent
`clip_history {action: list|paste|copy|clear, index?, count?}`
- index: 1 = last copied, 2 = second last. Default for paste/copy = 2 ("paste what I copied before"). The handler also accepts strings: "3", "3rd", "third", "second last", "previous".
- Paste/copy move the item to the top (item 1 = what is on the clipboard now).

## NLU phrases (suggested, put in `nlu_features.py`)
- list: "what did I copy (before|earlier|last)", "(show|read|list) (my) clipboard history", "what's in my clipboard history"
- paste: "paste the second last thing (I copied)", "paste what I copied before", "paste (item|number) 3 (from clipboard history)", "paste the previous copy"
- copy: "copy item 3 again", "copy the third thing (I copied) again", "put item 2 back on the clipboard"
- clear: "clear (my) clipboard history", "forget what I copied", "delete clipboard history"
- Careful: plain "what's in my clipboard" / "read my clipboard" is the existing `read_clipboard` intent. Only route to `clip_history` when the phrase says "history", "before", "earlier", "previous", "second last", or an item number. "paste" alone is `press_keys`/`type_text`, keep it.
- Ordinal words to number: second -> 2, third -> 3, "second last" -> 2, "third last" -> 3 (pass the number or the words; the handler understands both).

## Config (optional, config.yaml)
```yaml
clipboard_history:
  enabled: true
  max_items: 25
  poll_seconds: 1
  save: false              # true = keep history in the file below between restarts
  file: "~/.jarvis/clip_history.json"
  skip_secrets: true       # skip text that looks like a password / API key
  max_chars: 20000         # longer text is not kept
```

## Privacy notes
- Skips password-like text (one word, 8-64 chars, letters + digits, 3 of: lower/upper/digit/symbol) and known key prefixes (`sk-`, `ghp_`, `AKIA`, `eyJ`...). URLs, emails and file paths are kept.
- Skips anything a password manager marks private on Windows (clipboard format `ExcludeClipboardContentFromMonitorProcessing`).
- Text only. Images and files are not kept.

## Windows check (not tested on real Windows yet)
- `pyperclip.paste()` every second can briefly fail when another app holds the clipboard; errors are ignored and the next poll retries.
