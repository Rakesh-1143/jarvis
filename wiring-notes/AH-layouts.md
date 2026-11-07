# Wiring notes: piece AH (layouts.py)

Tests: `tests/test_layouts.py` (29 pass on Linux with a fake window backend).

## Wire it
- `actions/__init__.py`: import `layouts`, then `_HANDLERS.update(layouts.HANDLERS)`, `CATALOG.update(layouts.CATALOG)`.
- **Risky: action `delete` only** (and only when that layout exists).
  - In `_risky_text`: `if intent == "layout": return layouts.risky_text(args)` (returns None for save/restore/list).
  - In `_do_risky`: add `"layout"` to the tuple `("repeat_reminders", "memo", ...)`. The handler deletes only with `confirm=True`.
- `brain.py`: add `layout` to `GUARDED_ACTIONS` (restore starts programs and moves windows). Not info.
- No main.py hooks. No new packages (plain ctypes + psutil, already in requirements).
- Restore is synchronous and can take up to `wait_seconds` (10 s) while started programs open. Fine to run in the handler; reply comes after.

## Intent
`layout {action: save|restore|list|delete, name?}`
- `name` is cleaned by the module: "the Coding layout" -> "coding". Rules can pass raw words.
- No name: save -> "default"; restore -> the only layout, else "default", else asks which; delete -> asks which.
- Handler also accepts action synonyms: store/remember (save), load/open/apply (restore), show (list), remove/forget (delete).

## NLU phrases (suggested, put in `nlu_features.py`)
| Say | Args |
|---|---|
| "save this layout as coding", "save (my) window layout (as\|called) study", "remember this setup as work", "save layout" | {action: save, name} |
| "restore (my) coding layout", "restore layout coding", "load the study layout", "set up my coding layout", "apply coding layout" | {action: restore, name} |
| "list (my) layouts", "what layouts do I have", "show window layouts" | {action: list} |
| "delete (the) coding layout", "delete layout coding", "forget the study layout" | {action: delete, name} |

Careful:
- Only match when the phrase says "layout" (or "window setup"). "open coding" must stay `open_app`; "save this" must not become layout.
- "remember this setup" may clash with assistant memory ("remember that ..."). Keep "remember" only with "setup"/"layout".

## Config (optional, config.yaml)
```yaml
layouts:
  file: ~/.jarvis-layouts.json
  wait_seconds: 10      # wait for started programs before moving windows
  start_missing: true   # false = only move windows already open
```

## How it works (for the reviewer)
- Save: EnumWindows, keeps visible, titled, non-owned, non-tool, non-cloaked windows. Skips Windows shell parts (Program Manager, TextInputHost, search, start menu) and Jarvis itself. Stores exe path, title, rect, state (normal/maximized/minimized).
- Restore: pairs saved windows with open ones by exe, best title match first. Starts missing programs once each, only if the saved path is absolute, exists and ends in `.exe`, no arguments. Never starts explorer.exe or ApplicationFrameHost.exe (Store apps host).
- Maximized: shrinks onto the saved monitor, then maximizes there. Minimized: SetWindowPlacement with SW_SHOWMINNOACTIVE.
- If the saved monitor is gone, the window keeps its size and goes to the main screen.
- Admin (elevated) windows can't be moved from a normal process; the reply says how many failed.
- Not run on real Windows yet. Small risk: minimized windows use workspace coordinates (a few pixels off if the taskbar is on the top or left).
