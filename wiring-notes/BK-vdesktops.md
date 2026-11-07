# Wiring notes: piece BK (vdesktops.py)

Tests: `tests/test_vdesktops.py` (32 pass on Linux with fake backends).

## Wire it
- `actions/__init__.py`: import `vdesktops`, then `_HANDLERS.update(vdesktops.HANDLERS)`, `CATALOG.update(vdesktops.CATALOG)`.
- Not risky (closing a desktop loses nothing: Windows moves its windows to another desktop). Not info.
- `brain.py`: add `vdesktop` to `GUARDED_ACTIONS` (it changes what is on screen). Not info.
- No main.py hooks.
- `requirements.txt` (optional section): `pyvda>=0.6` (pure Python, needs comtypes which is already core). Without it, the hotkey fallback works for new/next/previous/close/go; "which" and "move window" say to install pyvda. pyvda 0.6.0 API checked against the real wheel: `VirtualDesktop(n)`, `.current()`, `.create()`, `.go()`, `.remove(fallback=)`, `.number`, `.name`, `AppView.current().move(desk)`, `get_virtual_desktops()`.
- pyvda uses COM: `actions.run` already calls `winutil.com_init()`, so nothing extra.

## Intent
`vdesktop {action: new|next|previous|go|move_window|close|which, number?}`
- `number` may be int or words: "2", "two", "second", "desktop 3", "last" (also STT "to" -> 2). Handler cleans it.
- Action synonyms accepted: create/add (new), back/left (previous), right/forward (next), switch (go), move/send (move_window), delete/remove (close), current/count (which).

## NLU phrases (suggested, put in `nlu_features.py`)
| Say | Args |
|---|---|
| "new desktop", "create a (new) virtual desktop", "add a desktop" | {action: new} |
| "next desktop", "switch to the next desktop" | {action: next} |
| "previous desktop", "go back a desktop" (not "last desktop", that is go/last) | {action: previous} |
| "go to desktop 2", "switch to desktop two", "desktop 3" | {action: go, number} |
| "go to the last desktop" | {action: go, number: "last"} |
| "move this window to desktop 3", "send this to desktop two" | {action: move_window, number} |
| "which desktop am I on", "how many desktops (do I have)" | {action: which} |
| "close this desktop", "close (the) virtual desktop", "delete this desktop" | {action: close} |

Careful:
- Only match with the word "desktop". "show desktop" / "show the desktop" must stay `window {show_desktop}`. "desktop" alone with no verb/number should not match.
- "close this window" stays `window close`; only "close this desktop" is `vdesktop close`.
- "open desktop folder" / "files on my desktop" are files, not this.
- "next track"/"previous" without "desktop" stay media.

## How it works (for the reviewer)
- pyvda path: exact numbers, edge checks ("already on the first/last desktop", "you have only 3 desktops"), new = create then go to it (like Win+Ctrl+D). Close: fallback = next desktop, or previous if this is the last; refuses when only one desktop. Move window moves the foreground window and stays on the current desktop.
- Hotkey path (no pyvda): Win+Ctrl+D / Left / Right / F4. "go to desktop N" presses Left 20 times (stops at desktop 1) then Right N-1 times; with more than 20 desktops it may land wrong. Desktop switch animations may look busy for a second.
- COM errors are caught and spoken ("I couldn't change desktops: ...").
- Not run on real Windows yet. Small risk: pyvda breaks on some new Windows 11 builds (its COM GUIDs change); then import fails and the hotkey fallback is used automatically.
