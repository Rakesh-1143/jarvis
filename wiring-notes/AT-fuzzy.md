# Wiring notes: piece AT (fuzzy.py, name matching)

File: `jarvis/actions/fuzzy.py`. Tests: `tests/test_fuzzy.py` (64 tests with difflib, 128 when rapidfuzz is installed: every test runs on both).
No intents, no CATALOG/HANDLERS, no config keys. Do NOT merge into catalog.py or `_HANDLERS`.
Smart-home is NOT wired: smarthome.py keeps its own difflib matching (Round 6 duplicate check).

## API
- `fuzzy.app(name, apps=None)` -> key or None. Default list = `apps.APP_PATHS` + `apps.WEBSITES`.
- `fuzzy.contact(name, contacts)` -> original contact key or None. Cutoff 85; two close people = None (never guesses between people).
- `fuzzy.folder(name, names=None)` -> folder key or None. Default list = `fileops._FOLDERS` keys. Strips the word "folder".
- `fuzzy.best(name, choices, cutoff=80)`, `fuzzy.matches(name, choices, cutoff, limit=3)` (for "did you mean"), `fuzzy.score(a, b)`, `fuzzy.fix_slips(text)`, `fuzzy.normalize(text)`.
- Always returns the ORIGINAL key, so `choices[key]` works.
- Safe by design: names under 4 letters must match exactly ("tom" never becomes "mom"); a name with extra whole words never matches ("visual studio" is not "visual studio code", "priya" is not "priya sharma").

## Rule for every call site
Call fuzzy ONLY when the exact lookup failed. Never before it. Keep the current exact code path untouched.

## Call sites (small edits, done by the wiring thread)

### 1. `jarvis/actions/apps.py` `open_app`
Where: the `except OSError:` branch after `_launch(target)` (today it returns "I couldn't find {name}.").
```python
    except OSError:
        from . import fuzzy
        key = fuzzy.app(name)
        if not key or key == name:
            return f"I couldn't find {name}."
        url = None if key in APP_PATHS else _website(key)
        if url:
            webbrowser.open(url)
            return f"Opening {key}."
        try:
            _launch(APP_PATHS[key])
        except OSError:
            return f"I couldn't find {key}."
        return f"Opening {key}."
```
Why only after launch fails: "open blender" / "open visual studio" must still launch real installed apps that are not in APP_PATHS.

### 2. `jarvis/actions/apps.py` `close_app`
Where: right after `name = _clean(name)` and the empty/_BAD_CHARS checks:
```python
    if name not in APP_PATHS and name not in PROCESS_NAMES:
        from . import fuzzy
        name = fuzzy.app(name, {**APP_PATHS, **PROCESS_NAMES}) or name
```
(Unknown names keep the old behaviour: taskkill `<name>.exe`.)

### 3. Contacts (3 places, same pattern)
- `jarvis/actions/files.py` `_contact(name, field)`: when `CONTACTS.get(...)` is None:
  `key = fuzzy.contact(name, CONTACTS); c = CONTACTS.get(key) if key else None`.
- `jarvis/actions/phone.py` `resolve_number`: after the `for k, v in contacts.items()` loop finds nothing and before the number check:
  `key = fuzzy.contact(key, contacts)` -> if found use `contacts[key]` the same way.
  Keep the number path first if `to` looks like a phone number (`_NUMBER.match(to)`), so digits are never fuzzy-matched.
- `jarvis/actions/inbox.py` `_resolve_sender`: when `contacts.get(key)` is None:
  `fk = fuzzy.contact(key, contacts); c = contacts.get(fk) if fk else None`.

### 4. Folders (3 places)
- `jarvis/actions/files.py` `_known_folder(name)`: when `key not in _FOLDERS`:
  `key = fuzzy.folder(key, _FOLDERS)`; return None if still None. (files has an extra "user" key, so pass its own `_FOLDERS`.)
- `jarvis/actions/fileops.py` `known_folder(name)`: when `key not in _FOLDERS`: `key = fuzzy.folder(key, _FOLDERS)`; return None if None.
  This also fixes `locate()` and `_dest_dir()` ("move it to down loads"), since both call `known_folder`.
- Do NOT fuzzy-match file names in `locate()` / `find_file()`: they already do part-name search; fuzzy there could pick a wrong file to move or delete.

### 5. requirements.txt (optional)
Add `rapidfuzz>=3.0` (pure speed; works without it via difflib). Doctor (AP) can list it as optional.

## Not wired on purpose
- smarthome.py (own matcher), spotify/podcast search (the services do their own search), teach/shortcuts phrases (exact phrases are safer).
- AS corrections (`corrections.apply`) and `fuzzy.fix_slips` overlap a little. Corrections = user's own fixes for whole sentences; fuzzy slips = built-in name fixes used only inside lookups. If both are wired, run corrections first (in main), fuzzy only inside lookups. Do not call `fix_slips` on the whole heard sentence.

## Tests to add in test_wiring.py after wiring
- `apps.open_app("crome")` with `_launch` faked to raise OSError for "crome" -> opens "chrome.exe".
- `files._contact("my mum", ...)` style with config contacts `{"mum": ...}` -> exact still wins; `"rohith"` -> "rohit".
- `fileops.known_folder("down loads")` -> Downloads path.
- `phone.resolve_number("+91 98765 43210")` unchanged (never fuzzy).
