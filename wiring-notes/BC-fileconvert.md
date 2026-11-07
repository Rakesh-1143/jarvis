# Wiring notes: piece BC (fileconvert.py, convert files)

File: `jarvis/actions/fileconvert.py`. Tests: `tests/test_fileconvert.py` (48 tests, real Pillow + pypdf; Explorer and Office are faked).

## Merge
- `CATALOG` + `HANDLERS` -> catalog.py / `_HANDLERS` (one intent: `convert_file`).
- Not risky (only creates new files; originals are opened read-only and never overwritten). Not info.
- Brain: add `convert_file` to `GUARDED_ACTIONS` (it writes files) so a page/OCR lookup can't trigger it.
- requirements.txt: add `pypdf>=4  # fileconvert.py: merge PDFs` (only merge needs it; AW documents also uses pypdf). Pillow and pywin32 are already there.
- No config keys. No main.py hooks.

## Intent
`convert_file {action: to_pdf|merge_pdfs|resize|compress|to_format, name?, format?: png|jpg|webp|bmp, size?}`
- `name` empty / "this" / "these" / "selected" -> files selected in the front File Explorer window; if none, the newest download.
- "last download" / "my latest download" -> newest file in Downloads.
- a name -> newest match in Downloads, Desktop, Documents. Several names: "invoice and receipt".
- `size` (resize): "50%", "50 percent", "half", "quarter", "800" (width), "800x600" / "800 by 600". Default 50%. Never enlarges.

## Phrases for nlu_features.py (suggested)
- `(convert|turn|make|save) (this|these|that|it|<name>|my last download) (to|into|as) (a )?pdf` -> to_pdf
- `(merge|combine|join) (these|the selected)? pdfs?( <a> and <b>)?` -> merge_pdfs (name = "<a> and <b>" if given)
- `(resize|shrink|make smaller) (this|<name>)( picture| image| photo)?( to <size>)?` -> resize
- `(compress|reduce the size of) (this|<name>)( picture| image| photo)?` -> compress
- `convert (this|<name>)( picture| image)? to (png|jpg|jpeg|webp|bmp)` -> to_format, format = group
- Careful: "convert 5 km to miles" / "convert 100 dollars to rupees" belong to `convert` (convert.py, units). Only route here when the target is pdf/png/jpg/jpeg/webp/bmp, or the object is this/these/file/picture/photo/image/document/download.

## Outputs (all next to the source, never overwrite: name-1, name-2 ...)
- pictures -> `<first>.pdf` (several selected pictures = one PDF, one page each)
- Word/PowerPoint/Excel -> `<name>.pdf` via Office COM (`win32com DispatchEx`, ReadOnly). No Office -> "Converting DOCX files to PDF needs Microsoft Office installed."
- merge -> `merged.pdf` in the first PDF's folder
- resize -> `<name>-small.<same ext>`; compress -> `<name>-small.jpg` (quality 70, max side 2000); to_format -> `<name>.<ext>`
- Refuses program/script files (`recent.RUNNABLE`), images over 100 MP, more than 50 files.

## Not tested on Windows yet
Explorer selection (`Shell.Application`) and Office export are only tested with fakes.
