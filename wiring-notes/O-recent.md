# Piece O: recent.py (done 2026-11-07)

Files: `jarvis/actions/recent.py`, `tests/test_recent.py` (13 tests pass).

## Wiring
- `actions/__init__.py`: `from . import recent`; `_HANDLERS.update(recent.HANDLERS)`; `CATALOG.update(recent.CATALOG)`.
- Not risky (read and open only). No main.py hook. No new dependency.
- Catalog marks `recent_files` as `info: True` (list result goes back to the AI; open just returns "Opening X.").
- Optional config: `downloads_folder` (overrides ~/Downloads).

## Intent
`recent_files {folder?, kind?, action?, when?, which?, count?}`
- folder: downloads (default) | desktop | documents | recent (Windows Recent folder)
- kind: pdf | image | video | audio | doc | archive | app (spoken words like "photos", "zip" are normalized by `recent.norm_kind`; folders by `recent.norm_folder`)
- action: list (default) | open
- when: today | yesterday | week | hour
- which: 1 = newest (accepts "second", "2")

## NLU phrases -> args
- "open my last download" / "open the latest download" -> {action: open}
- "open the last pdf" / "open my last downloaded pdf" -> {action: open, kind: pdf}
- "open the second last download" -> {action: open, which: 2}
- "what did I download today" -> {when: today}
- "what did I download yesterday" -> {when: yesterday}
- "show my recent downloads" / "list recent downloads" -> {}
- "show recent files" / "what files did I use recently" -> {folder: recent}
- "open my last recent file" -> {folder: recent, action: open}
- "open the latest picture on my desktop" -> {folder: desktop, kind: image, action: open}
- "show my newest documents" -> {folder: documents}
Suggested regex: `\b(open|show|list|what)\b.*\b(last|latest|newest|recent)\b.*\b(download|pdf|picture|photo|video|file|document|zip)s?\b` and `what did i download( today| yesterday| this week)?`.
Careful: must not catch existing `open_file {name}` ("open file report") or `open_folder` ("open downloads folder").
