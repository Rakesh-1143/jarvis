# Wiring notes: piece BJ (printer.py)

Merge: `from .printer import CATALOG as CBJ, HANDLERS as HBJ`, then update catalog CATALOG and _HANDLERS.
Add `printer` to the module import line in actions/__init__.py.

Intents:
- `print_file {name?}` - risky, ALWAYS asks. `name` empty/"this" = Explorer selection (else newest download),
  "last download", a file name, or a full path (same rules as fileconvert.resolve).
- `print_queue {action?: list|cancel}` - list (default) is safe; cancel is risky. `"info": False` in CATALOG.
- `printer_info {}` - `info: True`, read only.

## Confirm step (actions/__init__.py `_risky_text`)
```python
if intent in ("print_file", "print_queue") and printer.needs_confirm(intent, args):
    return printer.risky_text(intent, args)
```
- Note: `needs_confirm(intent, args)` and `risky_text(intent, args)` take the intent (two intents in one module).
- `risky_text` stores the found file(s) in `args["paths"]` and the printer in `args["printer"]`, so "yes" prints
  the same file even if the selection changes. It returns None when there is nothing to confirm (file not found,
  program file, no default printer, empty queue); the handler then says why.
- Questions: "print report.pdf on HP LaserJet", "cancel all 2 print jobs on HP LaserJet".
- Stored `paths` are re-checked in the handler (no programs/scripts/folders, max 10), so AI-supplied paths are safe.

## brain.py
- UNTRUSTED_INFO += `printer_info`, `print_queue` (document names in the queue and printer names come from other
  apps, other users and the network).
- GUARDED_ACTIONS += `print_file`, `print_queue`.

## NLU phrases -> args
| Say | Intent / args |
|---|---|
| "print this", "print this document", "print the selected file" | print_file {name: "this"} |
| "print my last download", "print the latest download" | print_file {name: "last download"} |
| "print report.pdf", "print my resume" | print_file {name: "report.pdf"} / {name: "resume"} |
| "what's in the print queue", "what's printing", "show print jobs" | print_queue {action: list} |
| "cancel printing", "stop printing", "cancel all print jobs", "clear the print queue" | print_queue {action: cancel} |
| "what's my default printer", "which printer", "is the printer online", "printer status", "is the printer out of paper" | printer_info {} |

Notes:
- Don't clash with inputs.py: "press print" / "print screen" = the PrintScreen key. Only match "print <something>"
  when it is NOT "print screen" / "press print". Match "print screen" first.
- Don't clash with winsettings: "open printer settings" stays winsettings.
- "print" needs an object: bare "print" should not go to print_file.
- No main.py hooks. No config. No new packages (pywin32 already in requirements).

## Test on real Windows
- `win32api.ShellExecute(0, "print", path, None, dir, 0)` on: .pdf (with Adobe Reader / Edge default), .docx, .txt, .jpg.
  If no app supports the print verb we say "no app can print .pdf files" (error 31/1155) - check the real error code.
- Some apps open a window to print (Photos shows a print dialog). That's expected.
- `EnumJobs` / `SetJob(JOB_CONTROL_DELETE)` without admin: own jobs should cancel; other users' jobs report "another user".
- Status flags: turn the printer off and check "is the printer online" says offline (WORK_OFFLINE attribute or
  PRINTER_STATUS_OFFLINE; many network printers only report this through the attribute).
- Tests: tests/test_printer.py (22, all faked, Linux).
