"""Convert files (piece BC): to PDF, merge PDFs, resize/compress images, change image format.

Says: "convert this to PDF", "make my last download a PDF", "merge these PDFs",
"resize this picture to half", "compress this photo", "convert this image to PNG".

Which file:
- name empty / "this" / "selected" -> the file(s) selected in the front Explorer
  window (Shell.Application COM). If nothing is selected: the newest download.
- "last download" / "latest download" -> the newest file in Downloads (recent.py).
- a name -> newest file whose name matches, searched in Downloads, Desktop, Documents.
- a full path that exists -> that file.

Actions:
- to_pdf     images -> one PDF (Pillow); Word/PowerPoint/Excel -> PDF through Microsoft
             Office (win32com). Without Office: says it needs Microsoft Office.
- merge_pdfs 2+ PDFs -> one PDF (pypdf). Selected PDFs, or names joined by "and".
- resize     image -> smaller copy "<name>-small.<ext>". size: "50%", "half", "800" (width),
             "800x600" (fits inside the box). Default 50%.
- compress   image -> "<name>-small.jpg" (JPEG quality 70, max side 2000).
- to_format  image -> png | jpg | webp | bmp.

Safety: originals are only read, never changed. Output goes next to the source and
NEVER overwrites a file: "name.pdf" -> "name-1.pdf" -> "name-2.pdf". Program and
script files are never touched. Not risky (only creates new files).

Intent: `convert_file {action, name?, format?, size?}` -> HANDLERS["convert_file"].
Needs: Pillow (in requirements), pypdf (merge only; add `pypdf>=4` to requirements),
pywin32 (Explorer selection + Office, Windows only; already in requirements).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

ACTIONS = ("to_pdf", "merge_pdfs", "resize", "compress", "to_format")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
WORD_EXT = {".doc", ".docx", ".rtf", ".odt"}
POWERPOINT_EXT = {".ppt", ".pptx", ".odp"}
EXCEL_EXT = {".xls", ".xlsx", ".csv", ".ods"}
OFFICE_EXT = WORD_EXT | POWERPOINT_EXT | EXCEL_EXT
# Files made to carry macros: never opened in Office by Jarvis.
MACRO_EXT = {".docm", ".dotm", ".xlsm", ".xltm", ".xlsb", ".xlam", ".pptm", ".potm", ".ppsm", ".ppam"}
MSO_FORCE_DISABLE = 3  # msoAutomationSecurityForceDisable: macros never run in files we open
FORMATS = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "bmp": ".bmp"}
_PIL_FORMAT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".bmp": "BMP",
               ".gif": "GIF", ".tif": "TIFF", ".tiff": "TIFF"}
SEARCH_FOLDERS = ("downloads", "desktop", "documents")
COMPRESS_QUALITY = 70
COMPRESS_MAX_SIDE = 2000
MAX_PIXELS = 100_000_000   # refuse huge images (memory)
MAX_FILES = 50             # images to one PDF / PDFs to merge

NO_OFFICE = "Converting {ext} files to PDF needs Microsoft Office installed."
NO_PYPDF = "Merging PDFs needs the pypdf package. Run install.bat again."

_THIS_WORDS = {"", "this", "this file", "these", "these files", "selected", "the selected file",
               "selection", "it", "that", "that file", "this one", "this picture", "this image",
               "this photo", "this document", "these pdfs", "these pictures", "these images"}
_LAST_WORDS = {"last download", "latest download", "newest download", "my last download",
               "my latest download", "the last download", "last downloaded file", "my download"}
_HALF = {"half": 50, "quarter": 25, "third": 33, "smaller": 50, "small": 50}


class ConvertError(Exception):
    """A problem with a message that can be spoken to the user."""


# ---------- finding the input files ----------

def _foreground_hwnd() -> int:
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())  # type: ignore[attr-defined]
    except Exception:
        return 0


def explorer_selection() -> list[str]:
    """Paths selected in the front File Explorer window (or the only one with a selection)."""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception:
        return []
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    front = _foreground_hwnd()
    found: list[list[str]] = []
    try:
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                paths = [str(i.Path) for i in w.Document.SelectedItems()]
            except Exception:
                continue
            paths = [p for p in paths if p and os.path.isfile(p)]
            if not paths:
                continue
            try:
                if front and int(w.HWND) == front:
                    return paths
            except Exception:
                pass
            found.append(paths)
    except Exception:
        return []
    return found[0] if len(found) == 1 else []


def _recent():
    from . import recent

    return recent


def last_download() -> str | None:
    items = _recent().scan("downloads")
    return items[0].path if items else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def find_by_name(name: str) -> str | None:
    """Newest file whose name matches in Downloads, Desktop or Documents."""
    from .fileops import is_network_path

    if is_network_path(name):
        return None  # N1: never touch another computer's share
    p = os.path.expanduser(name.strip().strip('"'))
    if os.path.isabs(p) and os.path.isfile(p):
        return p
    want = _norm(name)
    if not want:
        return None
    exact, partial = [], []
    for folder in SEARCH_FOLDERS:
        for item in _recent().scan(folder):
            stem = _norm(os.path.splitext(item.name)[0])
            full = _norm(item.name)
            if want in (stem, full):
                exact.append(item)
            elif want in full:
                partial.append(item)
    for group in (exact, partial):
        if group:
            return max(group, key=lambda i: i.time).path
    return None


def resolve(name: str | None) -> list[str]:
    """Input paths for a spoken name. Raises ConvertError if nothing is found."""
    from .fileops import is_network_path

    n = (name or "").strip()
    if is_network_path(n):
        raise ConvertError("I only use files on this computer, not network paths.")
    low = n.lower().strip(" .")
    if low in _THIS_WORDS:
        sel = explorer_selection()
        if sel:
            return sel
        last = last_download()
        if last:
            return [last]
        raise ConvertError("Select a file in File Explorer first, or tell me its name.")
    if low in _LAST_WORDS:
        last = last_download()
        if last:
            return [last]
        raise ConvertError("Your Downloads folder is empty.")
    parts = [n]
    if " and " in low or "," in n:
        parts = [x for x in re.split(r",|\band\b", n, flags=re.I) if x.strip()]
    paths: list[str] = []
    for part in parts:
        p = find_by_name(part)
        if not p:
            raise ConvertError(f"I couldn't find a file called {part.strip()}.")
        if p not in paths:
            paths.append(p)
    return paths


# ---------- output names ----------

def unique_path(path: str | Path) -> Path:
    """`path` if free, else name-1.ext, name-2.ext ... Never returns an existing file."""
    p = Path(path)
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem}-{i}{p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _say(out: Path) -> str:
    return f"{out.name} in {out.parent.name or out.parent}"


# ---------- images ----------

def _open_image(path: str):
    from PIL import Image

    img = Image.open(path)
    if img.width * img.height > MAX_PIXELS:
        img.close()
        raise ConvertError(f"{os.path.basename(path)} is too big to convert.")
    return img


def _flatten(img):
    """RGB copy (white background for transparent images): needed for JPEG and PDF."""
    from PIL import Image

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB") if img.mode != "RGB" else img


def _save(img, out: Path) -> None:
    fmt = _PIL_FORMAT.get(out.suffix.lower(), "PNG")
    if fmt in ("JPEG", "BMP"):
        img = _flatten(img)
    kwargs = {"quality": 90} if fmt in ("JPEG", "WEBP") else {}
    img.save(out, fmt, **kwargs)


def images_to_pdf(paths: list[str]) -> Path:
    opened, imgs = [], []
    try:
        for p in paths:
            img = _open_image(p)
            opened.append(img)
            imgs.append(_flatten(img))
        out = unique_path(Path(paths[0]).with_suffix(".pdf"))
        imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:], resolution=150.0)
        return out
    finally:
        for im in imgs + opened:  # close all: Windows locks open files
            try:
                im.close()
            except Exception:
                pass


def parse_size(size, w: int, h: int) -> tuple[int, int]:
    """New (width, height), never bigger than the original. Default 50%."""
    s = str(size if size is not None else "").lower().strip()
    s = s.replace("percent", "%").replace("pixels", "").replace("px", "").replace(" by ", "x").strip()
    pct = None
    if not s:
        pct = 50
    elif s in _HALF:
        pct = _HALF[s]
    elif m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", s):
        pct = float(m.group(1))
    elif m := re.fullmatch(r"(\d+)\s*[x×*]\s*(\d+)", s):
        bw, bh = int(m.group(1)), int(m.group(2))
        scale = min(bw / w, bh / h, 1.0)
        return max(1, round(w * scale)), max(1, round(h * scale))
    elif m := re.fullmatch(r"(\d+)", s):
        nw = min(int(m.group(1)), w)
        return max(1, nw), max(1, round(h * nw / w))
    else:
        raise ConvertError(f"I didn't understand the size {size}. Say a percent like 50 percent, or a width.")
    if not 0 < pct <= 100:
        raise ConvertError("The size must be between 1 and 100 percent.")
    return max(1, round(w * pct / 100)), max(1, round(h * pct / 100))


def resize_image(path: str, size=None) -> Path:
    from PIL import Image

    img = _open_image(path)
    try:
        new = parse_size(size, img.width, img.height)
        small = img.resize(new, Image.LANCZOS) if new != img.size else img.copy()
        ext = _ext(path) if _ext(path) in _PIL_FORMAT else ".png"
        out = unique_path(Path(path).with_name(f"{Path(path).stem}-small{ext}"))
        _save(small, out)
        return out
    finally:
        img.close()


def compress_image(path: str) -> Path:
    img = _open_image(path)
    try:
        small = _flatten(img)
        small.thumbnail((COMPRESS_MAX_SIDE, COMPRESS_MAX_SIDE))
        out = unique_path(Path(path).with_name(f"{Path(path).stem}-small.jpg"))
        small.save(out, "JPEG", quality=COMPRESS_QUALITY, optimize=True)
        return out
    finally:
        img.close()


def change_format(path: str, fmt: str) -> Path:
    ext = FORMATS.get((fmt or "").lower().strip(" ."))
    if not ext:
        raise ConvertError("I can convert pictures to PNG, JPG, WebP or BMP.")
    if _ext(path) == ext or (_ext(path) == ".jpeg" and ext == ".jpg"):
        raise ConvertError(f"{os.path.basename(path)} is already a {ext[1:].upper()}.")
    img = _open_image(path)
    try:
        out = unique_path(Path(path).with_suffix(ext))
        _save(img, out)
        return out
    finally:
        img.close()


# ---------- PDFs ----------

def merge_pdfs(paths: list[str]) -> Path:
    try:
        from pypdf import PdfWriter
    except ImportError:
        raise ConvertError(NO_PYPDF) from None
    writer = PdfWriter()
    try:
        for p in paths:
            writer.append(p)
        out = unique_path(Path(paths[0]).with_name("merged.pdf"))
        with open(out, "xb") as f:   # "x": fail rather than overwrite
            writer.write(f)
        return out
    except ConvertError:
        raise
    except Exception as e:
        raise ConvertError(f"I couldn't merge those PDFs: {e}") from None
    finally:
        writer.close()


# ---------- Office -> PDF ----------

def _dispatch(prog_id: str):
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    app = win32com.client.DispatchEx(prog_id)
    # Office started by automation runs macros with no prompt by default. Turn them off before any Open.
    try:
        app.AutomationSecurity = MSO_FORCE_DISABLE
    except Exception:
        try:
            app.Quit()
        finally:
            raise ConvertError("I couldn't turn off macros in Office, so I won't open the file.")
    return app


def _com_done() -> None:
    try:
        import pythoncom  # type: ignore

        pythoncom.CoUninitialize()
    except Exception:
        pass


def office_to_pdf(path: str) -> Path:
    ext = _ext(path)
    if ext in MACRO_EXT:
        raise ConvertError(f"{os.path.basename(path)} can contain macros, so I won't open it.")
    src = os.path.abspath(path)
    out = unique_path(Path(src).with_suffix(".pdf"))
    try:
        if ext in WORD_EXT:
            app = _dispatch("Word.Application")
        elif ext in POWERPOINT_EXT:
            app = _dispatch("PowerPoint.Application")
        else:
            app = _dispatch("Excel.Application")
    except ConvertError:
        _com_done()
        raise
    except Exception:
        _com_done()
        raise ConvertError(NO_OFFICE.format(ext=ext[1:].upper())) from None
    try:
        if ext in WORD_EXT:
            app.Visible = False
            doc = app.Documents.Open(src, ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
                                     Visible=False)
            try:
                doc.ExportAsFixedFormat(str(out), 17)          # wdExportFormatPDF
            finally:
                doc.Close(False)
        elif ext in POWERPOINT_EXT:
            pres = app.Presentations.Open(src, ReadOnly=True, WithWindow=False)
            try:
                pres.SaveAs(str(out), 32)                      # ppSaveAsPDF
            finally:
                pres.Close()
        else:
            app.Visible = False
            app.DisplayAlerts = False
            book = app.Workbooks.Open(src, ReadOnly=True)
            try:
                book.ExportAsFixedFormat(0, str(out))          # xlTypePDF
            finally:
                book.Close(False)
    except ConvertError:
        raise
    except Exception as e:
        raise ConvertError(f"Office couldn't convert {os.path.basename(path)}: {e}") from None
    finally:
        try:
            app.Quit()
        except Exception:
            pass
        _com_done()
    return out


# ---------- handler ----------

def _check(paths: list[str]) -> None:
    from .recent import RUNNABLE

    for p in paths:
        if _ext(p) in RUNNABLE:
            raise ConvertError(f"I don't convert program files like {os.path.basename(p)}.")


def _images_only(paths: list[str]) -> None:
    bad = [os.path.basename(p) for p in paths if _ext(p) not in IMAGE_EXT]
    if bad:
        raise ConvertError(f"{bad[0]} is not a picture.")


def convert(action: str, name: str | None = None, fmt: str | None = None, size=None) -> str:
    action = (action or "").lower().strip()
    if action not in ACTIONS:
        raise ConvertError("I can convert to PDF, merge PDFs, resize, compress, or change a picture's format.")
    paths = resolve(name)
    _check(paths)
    if len(paths) > MAX_FILES:
        raise ConvertError(f"That's too many files. I can do up to {MAX_FILES} at once.")

    if action == "merge_pdfs":
        if len(paths) < 2:
            raise ConvertError("Select two or more PDFs to merge.")
        bad = [os.path.basename(p) for p in paths if _ext(p) != ".pdf"]
        if bad:
            raise ConvertError(f"{bad[0]} is not a PDF.")
        out = merge_pdfs(paths)
        return f"Merged {len(paths)} PDFs into {_say(out)}."

    if action == "to_pdf":
        if all(_ext(p) in IMAGE_EXT for p in paths):
            out = images_to_pdf(paths)
            n = len(paths)
            return f"Saved {'the picture' if n == 1 else f'{n} pictures'} as {_say(out)}."
        if len(paths) > 1:
            raise ConvertError("I can turn several pictures into one PDF, but documents one at a time.")
        p = paths[0]
        if _ext(p) == ".pdf":
            return f"{os.path.basename(p)} is already a PDF."
        if _ext(p) not in OFFICE_EXT:
            raise ConvertError(f"I can't turn {os.path.basename(p)} into a PDF.")
        out = office_to_pdf(p)
        return f"Saved {_say(out)}."

    _images_only(paths)
    outs: list[Path] = []
    for p in paths:
        if action == "resize":
            outs.append(resize_image(p, size))
        elif action == "compress":
            outs.append(compress_image(p))
        else:
            outs.append(change_format(p, fmt or ""))
    verb = {"resize": "Resized", "compress": "Compressed", "to_format": "Converted"}[action]
    if len(outs) == 1:
        return f"{verb}. Saved {_say(outs[0])}."
    return f"{verb} {len(outs)} pictures. Saved them in {outs[0].parent.name}."


def convert_file(args: dict) -> str:
    try:
        return convert(args.get("action", ""), args.get("name") or args.get("path"),
                       args.get("format"), args.get("size"))
    except ConvertError as e:
        return str(e)
    except Exception as e:  # never crash the assistant
        return f"Sorry, the conversion failed: {e}"


CATALOG: dict[str, dict] = {
    "convert_file": {
        "description": "Convert a file and save the result next to it (the original is never changed or "
                       "overwritten). action: to_pdf (pictures -> one PDF; Word/PowerPoint/Excel -> PDF "
                       "via Microsoft Office), merge_pdfs (2+ PDFs -> merged.pdf), resize (picture -> "
                       "smaller copy, size like '50%', 'half', '800' width or '800x600'), compress "
                       "(picture -> smaller JPG), to_format (picture -> png/jpg/webp/bmp). name: empty or "
                       "'this' = the file(s) selected in File Explorer, 'last download', a file name, or "
                       "several names joined by 'and'.",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "name": {"type": "string", "description": "File name, 'this', or 'last download'."},
            "format": {"type": "string", "enum": ["png", "jpg", "webp", "bmp"],
                       "description": "Only for to_format."},
            "size": {"type": "string", "description": "Only for resize: '50%', 'half', '800', '800x600'."},
        },
        "required": ["action"],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"convert_file": convert_file}
