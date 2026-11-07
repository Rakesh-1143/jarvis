# Piece V: software installer (`actions/software.py`)

Tests: `tests/test_software.py` (19 pass; winget is faked). Full suite: 843 pass.
No new requirements. Needs `winget` (Windows "App Installer", built into Windows 10/11).

## Wire it
- `actions/__init__.py`:
  - `from . import software`; `_HANDLERS.update(software.HANDLERS)`; `CATALOG.update(software.CATALOG)`.
  - `_risky_text`: `if intent == "software": return software.risky_text(args)`
    (returns None for `check_updates`, and None when the app is not found, so the handler explains).
    `risky_text` writes the found package into `args["id"]` / `args["pkg"]`, so the stored pending args
    install exactly the app named in the question. Call it on the same dict that `_risky` stores (it already does).
  - `_do_risky`: add `"software"` to the tuple that calls `_HANDLERS[intent](args)`.
- Catalog: intent `software` is NOT marked `info` (only `check_updates` is info-like, same as `memo`).
- `main.py`: `actions.software.set_notifier(io.say)` at start (speaks "VLC is installed." when the background job ends).
- Brain/H3 note: install/uninstall/update_all always ask yes (handler never acts without `confirm=True`).

## Intent
`software {action: install|uninstall|update_all|check_updates, name?}`

| Say | Args |
|---|---|
| "install VLC", "download and install 7-Zip", "get Zoom installed" | {action: install, name: "VLC"} |
| "uninstall Zoom", "remove Spotify app", "delete the app Discord" | {action: uninstall, name: "Zoom"} |
| "update all my apps", "update all apps", "upgrade everything" | {action: update_all} |
| "what apps need updates", "check for app updates", "any app updates" | {action: check_updates} |

Careful with clashes:
- "remove X" / "delete X" also match files (fileops) and lists. Only route to `software` when the words say "app"/"program"/"software", or use the "uninstall" verb.
- "update all" must not hit Windows Update settings (winsettings).
- "install" alone with no name -> handler asks "Which app should I install?".

## Behaviour
- Search: `winget search NAME --source winget`; picks exact name, then id, then name prefix, then first row. Cached 2 min (question and "yes" share one search).
- Uninstall searches installed apps: `winget list --name NAME`.
- Jobs run in one background thread at a time (15 min timeout); a second request says "still busy".
- Names are checked (letters, digits, space, `. + _ # & ' -`, max 60, no leading `-`); ids are checked too. All commands are arg lists, no shell.
