# BM filesearch.py — wiring notes

Module: `jarvis/actions/filesearch.py`. Tests: `tests/test_filesearch.py` (18 tests, Windows Search faked).
Searches words INSIDE files with the Windows Search index (OLE DB, `Search.CollatorDSO`) via pywin32
(`win32com.client.Dispatch("ADODB.Connection")`). No new package: pywin32 is already required.
Reuses `recent.norm_kind`, `recent.KINDS`, `recent._since/_until`, `recent.RUNNABLE`.
Not a duplicate: `files.find_file` / `recent.py` match names or newest files only.

## 1. actions/__init__.py + catalog
Merge `filesearch.CATALOG` and `filesearch.HANDLERS`. Two intents, neither risky:
- `find_files {text?, kind?, modified?}` — `info: True`. kind: pdf|doc|image|video|audio|archive (spoken words
  like "pdfs", "word", "pictures" also work). modified: hour|today|yesterday|week ("this week" also works).
  Speaks the top 3 of up to 10 results and remembers them.
- `open_result {number}` — opens result N of the last search (number can be 2, "2", "second", "the second one").
  Never opens programs/scripts (`recent.RUNNABLE`); says so if the file was moved or deleted.

## 2. brain.py
Add `"find_files"` to `UNTRUSTED_INFO` (file names are written by others).
Add `"open_result"` to GUARDED_ACTIONS if the AI may call it (opens a file, like recent_files open).

## 3. nlu_features.py phrases (suggested)
- "find (the )?(file|document|pdf)s? (that )?(mentions?|about|containing|with) <text>" -> find_files {text, kind}
- "find (pdfs|documents|word files|pictures) about <text>" -> find_files {kind, text}
- "(show )?files I (edited|changed|worked on) (today|yesterday|this week)" -> find_files {modified}
- "search inside files for <text>" / "which file mentions <text>" -> find_files {text}
- "open (the )?(first|second|third|1st|2nd|...|number N)( one| result)?" -> open_result {number}
  ONLY when `filesearch.has_results()` is True — check that recent.py's "open the second one" rule
  (if any) does not take it first; the newest action wins in practice, so prefer whichever the user used last.
- Careful: plain "find <name>" (no mentions/about/containing) stays with the existing name search.

## 4. main.py / config / requirements
Nothing. Scope is the user folder (`~`), AppData and folders are skipped.

## Hand-test on Windows (not run on real Windows yet)
- "find the file that mentions <a word in one of your Word docs>" -> lists it.
- "files I edited today" -> newest first. "open the first one" -> opens it.
- If the index is off -> Jarvis says to turn on Settings > Privacy and security > Searching Windows.
- Query uses `System.ItemPathDisplay NOT LIKE '%\AppData\%'`; if Windows rejects that clause the user hears
  the "Windows Search seems to be off" message on every search — then remove that one line in `build_query`.
