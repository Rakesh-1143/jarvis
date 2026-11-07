"""Printer control by voice (piece BJ).

Says: "print this document", "print my last download", "print report.pdf",
"what's in the print queue", "cancel printing", "what's my default printer",
"is the printer online".

Which file (same rules as fileconvert.resolve):
- empty / "this" -> file(s) selected in the front Explorer window, else newest download.
- "last download" -> newest file in Downloads.
- a name -> newest matching file in Downloads, Desktop, Documents; or a full path.

Printing uses the file's own Windows "print" verb (ShellExecute) on the DEFAULT printer.
PDFs need a default PDF app that can print (Edge can't always); if no app can print the
file type we say so.

Safety:
- print_file is risky: asks "Print report.pdf on HP LaserJet?". risky_text() stores the
  found file path(s) in args, so "yes" prints the same file even if the selection changes.
- print_queue cancel is risky (deletes all jobs on the default printer). Only asks when
  there is something to cancel.
- Program/script files and folders are never printed. Max 10 files at once.

Intents:
  print_file {name?}                      risky
  print_queue {action: list|cancel}       list = info, cancel = risky
  printer_info {}                         info
Needs: pywin32 (already in requirements). Windows only.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
MAX_FILES = 10
MAX_JOBS_SPOKEN = 5

NOT_WINDOWS = "Printing works only on Windows."
NO_PYWIN32 = "Printing needs the pywin32 package. Run install.bat again."
NO_DEFAULT = "You have no default printer. Set one in Settings, Printers and scanners."

# Printer status flags (winspool.h PRINTER_STATUS_*), worst first.
PRINTER_STATUS = [
    (0x00000080, "offline"),
    (0x00001000, "not available"),
    (0x00000008, "has a paper jam"),
    (0x00000010, "is out of paper"),
    (0x00000040, "has a paper problem"),
    (0x00400000, "has a door open"),
    (0x00040000, "is out of toner or ink"),
    (0x00000002, "has an error"),
    (0x00100000, "needs your attention"),
    (0x00000001, "is paused"),
    (0x00020000, "is low on toner or ink"),
    (0x00000400, "is printing"),
    (0x00000200, "is busy"),
]
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400

# Job status flags (JOB_STATUS_*).
JOB_STATUS = [
    (0x00000002, "error"),
    (0x00000040, "out of paper"),
    (0x00000020, "printer offline"),
    (0x00000400, "needs attention"),
    (0x00000200, "blocked"),
    (0x00000001, "paused"),
    (0x00000004, "cancelling"),
    (0x00000010, "printing"),
    (0x00000008, "spooling"),
    (0x00000080, "printed"),
]
JOB_CONTROL_DELETE = 5
# ShellExecute errors meaning "no app can print this type".
NO_PRINT_APP_ERRORS = {31, 1155, 1156, 2, 1785}


class PrinterError(Exception):
    """A problem with a message that can be spoken to the user."""


# ---------- pywin32 access (faked in tests) ----------

def _win32print():
    if not IS_WINDOWS:
        raise PrinterError(NOT_WINDOWS)
    try:
        import win32print  # type: ignore
    except ImportError:
        raise PrinterError(NO_PYWIN32)
    return win32print


def _shell_print(path: str) -> None:
    """Send a file to the default printer with its app's print verb."""
    if not IS_WINDOWS:
        raise PrinterError(NOT_WINDOWS)
    try:
        import win32api  # type: ignore
    except ImportError:
        raise PrinterError(NO_PYWIN32)
    win32api.ShellExecute(0, "print", path, None, os.path.dirname(path) or ".", 0)


# ---------- printer facts ----------

def default_printer() -> str:
    wp = _win32print()
    try:
        name = wp.GetDefaultPrinter()
    except Exception:
        name = ""
    if not name:
        raise PrinterError(NO_DEFAULT)
    return name


def _info2(name: str) -> dict:
    wp = _win32print()
    h = wp.OpenPrinter(name)
    try:
        return wp.GetPrinter(h, 2) or {}
    finally:
        wp.ClosePrinter(h)


def status_words(info: dict) -> list[str]:
    """Problems/state of a printer from GetPrinter level 2. Empty list = ready."""
    status = int(info.get("Status") or 0)
    words = [w for flag, w in PRINTER_STATUS if status & flag]
    if int(info.get("Attributes") or 0) & PRINTER_ATTRIBUTE_WORK_OFFLINE and "offline" not in words:
        words.insert(0, "offline")
    return words


def jobs(name: str) -> list[dict]:
    wp = _win32print()
    h = wp.OpenPrinter(name)
    try:
        return list(wp.EnumJobs(h, 0, 999, 1) or [])
    finally:
        wp.ClosePrinter(h)


def all_printers() -> list[str]:
    wp = _win32print()
    flags = getattr(wp, "PRINTER_ENUM_LOCAL", 2) | getattr(wp, "PRINTER_ENUM_CONNECTIONS", 4)
    try:
        rows = wp.EnumPrinters(flags, None, 1) or []
    except Exception:
        return []
    names = []
    for r in rows:
        n = r[2] if isinstance(r, (tuple, list)) and len(r) > 2 else (r.get("pName") if isinstance(r, dict) else None)
        if n and n not in names:
            names.append(str(n))
    return names


def _job_words(job: dict) -> str:
    doc = str(job.get("pDocument") or "a document").strip()[:60]
    status = int(job.get("Status") or 0)
    state = next((w for flag, w in JOB_STATUS if status & flag), "waiting")
    total, done = int(job.get("TotalPages") or 0), int(job.get("PagesPrinted") or 0)
    if state == "printing" and total:
        state = f"printing, page {min(done + 1, total)} of {total}"
    return f"{doc} ({state})"


def _join(parts: list[str]) -> str:
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ---------- files ----------

def _resolve_files(name: str | None) -> list[str]:
    from . import fileconvert

    try:
        paths = fileconvert.resolve(name)
    except fileconvert.ConvertError as e:
        raise PrinterError(str(e))
    return _check(paths)


def _check(paths: list[str]) -> list[str]:
    from .fileops import is_network_path
    from .recent import RUNNABLE

    for p in paths:
        if is_network_path(p):
            raise PrinterError("I only print files on this computer, not network paths.")
        if os.path.isdir(p):
            raise PrinterError(f"{os.path.basename(p)} is a folder. I can print files only.")
        if os.path.splitext(p)[1].lower() in RUNNABLE:
            raise PrinterError(f"I don't print program or script files like {os.path.basename(p)}.")
    if len(paths) > MAX_FILES:
        raise PrinterError(f"That's too many files. I can print up to {MAX_FILES} at once.")
    return paths


def _stored_paths(args: dict) -> list[str]:
    p = args.get("paths")
    if isinstance(p, list) and p and all(isinstance(x, str) for x in p):
        return _check(p)
    return []


def _files_words(paths: list[str]) -> str:
    names = [os.path.basename(p) for p in paths]
    if len(names) <= 3:
        return _join(names)
    return f"{len(names)} files"


# ---------- risky step ----------

def needs_confirm(intent: str, args: dict) -> bool:
    args = args or {}
    if intent == "print_file":
        return True
    if intent == "print_queue":
        return str(args.get("action") or "list").lower().strip() == "cancel"
    return False


def risky_text(intent: str, args: dict) -> str | None:
    """Words for 'are you sure you want to ...?'. None = nothing to confirm (the handler
    then explains why, e.g. file not found or empty queue). Stores what it found in args."""
    if not needs_confirm(intent, args):
        return None
    try:
        printer = default_printer()
        if intent == "print_file":
            paths = _stored_paths(args) or _resolve_files(args.get("name") or args.get("path"))
            args["paths"] = paths
            args["printer"] = printer
            return f"print {_files_words(paths)} on {printer}"
        found = jobs(printer)
    except PrinterError:
        return None
    except Exception:
        return None
    if not found:
        return None
    args["printer"] = printer
    n = len(found)
    return f"cancel {'the print job' if n == 1 else f'all {n} print jobs'} on {printer}"


# ---------- handlers ----------

def print_file(args: dict) -> str:
    try:
        printer = default_printer()
        paths = _stored_paths(args) or _resolve_files(args.get("name") or args.get("path"))
        sent, failed = [], []
        for p in paths:
            if not os.path.isfile(p):
                failed.append(f"{os.path.basename(p)} is gone")
                continue
            try:
                _shell_print(p)
                sent.append(p)
            except PrinterError:
                raise
            except Exception as e:
                code = getattr(e, "winerror", None)
                if code is None and getattr(e, "args", None) and isinstance(e.args[0], int):
                    code = e.args[0]
                ext = os.path.splitext(p)[1].lower() or "this"
                if code in NO_PRINT_APP_ERRORS:
                    failed.append(f"no app can print {ext} files. Open {os.path.basename(p)} and press Control P, "
                                  "or set a default app that can print them")
                else:
                    failed.append(f"{os.path.basename(p)} failed: {e}")
        if not sent:
            return "I couldn't print: " + "; ".join(failed) + "."
        msg = f"Sent {_files_words(sent)} to {printer}."
        try:
            problems = [w for w in status_words(_info2(printer)) if w not in ("is printing", "is busy")]
        except Exception:
            problems = []
        if problems:
            first = problems[0]
            msg += f" But the printer {'is ' + first if first in ('offline', 'not available') else first}."
        if failed:
            msg += " Not printed: " + "; ".join(failed) + "."
        return msg
    except PrinterError as e:
        return str(e)
    except Exception as e:  # never crash the assistant
        return f"Sorry, printing failed: {e}"


def print_queue(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "list").lower().strip()
    try:
        printer = default_printer()
        found = jobs(printer)
        if action == "cancel":
            if not found:
                return f"There's nothing to cancel. The queue on {printer} is empty."
            wp = _win32print()
            h = wp.OpenPrinter(printer)
            done, failed = 0, 0
            try:
                for j in found:
                    try:
                        wp.SetJob(h, j.get("JobId"), 0, None, getattr(wp, "JOB_CONTROL_DELETE", JOB_CONTROL_DELETE))
                        done += 1
                    except Exception:
                        failed += 1
            finally:
                wp.ClosePrinter(h)
            msg = f"Cancelled {done} print job{'s' if done != 1 else ''} on {printer}."
            if failed:
                msg += (f" {failed} could not be cancelled; they may belong to another user. "
                        "Open the printer queue in Settings to remove them.")
            return msg
        if action != "list":
            return "I can list the print queue or cancel printing."
        if not found:
            return f"The print queue on {printer} is empty."
        n = len(found)
        words = [_job_words(j) for j in found[:MAX_JOBS_SPOKEN]]
        more = f" and {n - MAX_JOBS_SPOKEN} more" if n > MAX_JOBS_SPOKEN else ""
        return f"{n} job{'s' if n != 1 else ''} on {printer}: {', '.join(words)}{more}."
    except PrinterError as e:
        return str(e)
    except Exception as e:
        return f"Sorry, I couldn't read the print queue: {e}"


def printer_info(args: dict) -> str:
    try:
        printer = default_printer()
        try:
            info = _info2(printer)
        except Exception:
            info = None
        if info is None:
            state = "I couldn't read its status"
        else:
            words = status_words(info)
            if not words:
                state = "It is online and ready"
            elif words[0] in ("offline", "not available"):
                state = f"It is {words[0]}"
            else:
                state = "It is online but " + _join(words[:2])
        msg = f"Your default printer is {printer}. {state}."
        if info is not None:
            n = int(info.get("cJobs") or 0)
            if n:
                msg += f" {n} job{'s' if n != 1 else ''} waiting."
        others = [p for p in all_printers() if p != printer]
        if others:
            msg += f" Other printers: {_join(others[:4])}{' and more' if len(others) > 4 else ''}."
        return msg
    except PrinterError as e:
        return str(e)
    except Exception as e:
        return f"Sorry, I couldn't check the printer: {e}"


CATALOG: dict[str, dict] = {
    "print_file": {
        "description": "Print a file on the default printer (Jarvis asks the user to confirm). name: empty or "
                       "'this' = file(s) selected in File Explorer, 'last download', or a file name.",
        "properties": {
            "name": {"type": "string", "description": "File name, 'this', or 'last download'."},
        },
        "required": [],
    },
    "print_queue": {
        "description": "Default printer's queue. list = what is waiting/printing; cancel = delete all jobs "
                       "(Jarvis asks the user to confirm).",
        "properties": {
            "action": {"type": "string", "enum": ["list", "cancel"], "description": "Default list."},
        },
        "required": [],
        "info": False,  # cancel changes things, so the AI must not run it during a lookup
    },
    "printer_info": {
        "description": "Read-only: name of the default printer, whether it is online/ready (paper, toner, "
                       "errors), jobs waiting, and other installed printers.",
        "properties": {},
        "required": [],
        "info": True,
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {
    "print_file": print_file,
    "print_queue": print_queue,
    "printer_info": printer_info,
}
