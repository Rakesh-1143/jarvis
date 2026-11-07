"""Tests for actions/fileconvert.py (piece BC). Real Pillow/pypdf; Explorer and Office are faked."""
import os
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from jarvis.actions import fileconvert as fc
from jarvis.actions import recent


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Downloads/Desktop/Documents in tmp; no real Explorer selection."""
    paths = {k: tmp_path / k for k in ("downloads", "desktop", "documents")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setattr(recent, "folder_path", lambda f: str(paths.get(f, tmp_path / "none")))
    monkeypatch.setattr(fc, "explorer_selection", lambda: [])
    return paths


def _img(path, size=(400, 200), mode="RGB", color=(200, 10, 10)):
    if mode == "RGBA":
        color = (*color, 128)
    Image.new(mode, size, color).save(path)
    return str(path)


def _pdf(path, pages=1):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(100, 100)
    with open(path, "wb") as f:
        w.write(f)
    return str(path)


def _pages(path):
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def _run(**args):
    return fc.convert_file(args)


# ---------- unique names ----------

def test_unique_path_never_existing(tmp_path):
    p = tmp_path / "a.pdf"
    assert fc.unique_path(p) == p
    p.write_bytes(b"x")
    assert fc.unique_path(p).name == "a-1.pdf"
    (tmp_path / "a-1.pdf").write_bytes(b"x")
    assert fc.unique_path(p).name == "a-2.pdf"


# ---------- to_pdf ----------

def test_image_to_pdf(folders):
    src = _img(folders["downloads"] / "photo.png")
    before = Path(src).read_bytes()
    out = _run(action="to_pdf", name="photo")
    assert "photo.pdf" in out
    assert _pages(folders["downloads"] / "photo.pdf") == 1
    assert Path(src).read_bytes() == before  # original untouched


def test_to_pdf_does_not_overwrite(folders):
    _img(folders["downloads"] / "photo.png")
    old = folders["downloads"] / "photo.pdf"
    old.write_bytes(b"keep me")
    out = _run(action="to_pdf", name="photo.png")
    assert "photo-1.pdf" in out
    assert old.read_bytes() == b"keep me"


def test_selected_images_to_one_pdf(folders, monkeypatch):
    a = _img(folders["desktop"] / "a.jpg")
    b = _img(folders["desktop"] / "b.png", mode="RGBA")
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    out = _run(action="to_pdf", name="these")
    assert "2 pictures" in out
    assert _pages(folders["desktop"] / "a.pdf") == 2


def test_this_falls_back_to_last_download(folders):
    _img(folders["downloads"] / "scan.png")
    assert "scan.pdf" in _run(action="to_pdf")


def test_this_with_nothing(folders):
    assert "Select a file" in _run(action="to_pdf", name="this")


def test_last_download_words(folders):
    old = _img(folders["downloads"] / "old.png")
    os.utime(old, (1, 1))
    _img(folders["downloads"] / "new.png")
    assert "new.pdf" in _run(action="to_pdf", name="my last download")


def test_already_pdf(folders):
    _pdf(folders["documents"] / "report.pdf")
    assert "already a PDF" in _run(action="to_pdf", name="report")


def test_unknown_type_to_pdf(folders):
    (folders["documents"] / "song.mp3").write_bytes(b"x")
    assert "can't turn" in _run(action="to_pdf", name="song")


def test_name_not_found(folders):
    assert "couldn't find a file called nothing" in _run(action="to_pdf", name="nothing")


def test_runnable_refused(folders):
    (folders["downloads"] / "setup.exe").write_bytes(b"MZ")
    out = _run(action="to_pdf", name="setup")
    assert "program files" in out
    assert not (folders["downloads"] / "setup.pdf").exists()


def test_bad_action(folders):
    assert "I can convert" in _run(action="explode")


# ---------- Office ----------

class _FakeDoc:
    def __init__(self, log):
        self.log = log

    def ExportAsFixedFormat(self, *a):
        self.log.append(("export", a))
        out = a[0] if isinstance(a[0], str) else a[1]
        Path(out).write_bytes(b"%PDF")

    def SaveAs(self, out, kind):
        self.log.append(("saveas", out, kind))
        Path(out).write_bytes(b"%PDF")

    def Close(self, *a):
        self.log.append(("close",))


class _FakeApp:
    def __init__(self, log):
        self.log = log
        coll = types.SimpleNamespace(Open=self._open)
        self.Documents = self.Presentations = self.Workbooks = coll

    def _open(self, path, **kw):
        self.log.append(("open", path, kw))
        return _FakeDoc(self.log)

    def Quit(self):
        self.log.append(("quit",))


@pytest.mark.parametrize("ext,prog,kind", [(".docx", "Word.Application", 17),
                                           (".pptx", "PowerPoint.Application", 32),
                                           (".xlsx", "Excel.Application", 0)])
def test_office_to_pdf(folders, monkeypatch, ext, prog, kind):
    (folders["documents"] / f"notes{ext}").write_bytes(b"office")
    log, used = [], []

    def dispatch(pid):
        used.append(pid)
        return _FakeApp(log)

    monkeypatch.setattr(fc, "_dispatch", dispatch)
    out = _run(action="to_pdf", name="notes")
    assert out == "Saved notes.pdf in documents."
    assert used == [prog]
    assert log[0][2].get("ReadOnly") is True
    assert ("quit",) in log
    assert (folders["documents"] / "notes.pdf").exists()
    assert kind in [x for e in log[1:2] for x in (e[1] if isinstance(e[1], tuple) else e[1:])]


def test_no_office(folders, monkeypatch):
    (folders["documents"] / "notes.docx").write_bytes(b"x")

    def boom(pid):
        raise OSError("no class")

    monkeypatch.setattr(fc, "_dispatch", boom)
    assert "needs Microsoft Office" in _run(action="to_pdf", name="notes")


def test_office_error_quits(folders, monkeypatch):
    (folders["documents"] / "notes.docx").write_bytes(b"x")
    log = []
    app = _FakeApp(log)

    def bad_open(path, **kw):
        raise RuntimeError("file is damaged")

    app.Documents = types.SimpleNamespace(Open=bad_open)
    monkeypatch.setattr(fc, "_dispatch", lambda pid: app)
    out = _run(action="to_pdf", name="notes")
    assert "couldn't convert" in out
    assert ("quit",) in log


def test_several_documents_refused(folders, monkeypatch):
    a = str(folders["documents"] / "a.docx")
    b = str(folders["documents"] / "b.docx")
    Path(a).write_bytes(b"x")
    Path(b).write_bytes(b"x")
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    assert "one at a time" in _run(action="to_pdf")


# ---------- merge ----------

def test_merge_selected(folders, monkeypatch):
    a = _pdf(folders["downloads"] / "a.pdf", 2)
    b = _pdf(folders["downloads"] / "b.pdf", 3)
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    out = _run(action="merge_pdfs")
    assert "Merged 2 PDFs into merged.pdf" in out
    assert _pages(folders["downloads"] / "merged.pdf") == 5
    assert _pages(a) == 2 and _pages(b) == 3


def test_merge_by_names_no_overwrite(folders):
    _pdf(folders["downloads"] / "invoice.pdf", 1)
    _pdf(folders["documents"] / "receipt.pdf", 1)
    (folders["downloads"] / "merged.pdf").write_bytes(b"old")
    out = _run(action="merge_pdfs", name="invoice and receipt")
    assert "merged-1.pdf" in out
    assert (folders["downloads"] / "merged.pdf").read_bytes() == b"old"
    assert _pages(folders["downloads"] / "merged-1.pdf") == 2


def test_merge_needs_two(folders):
    _pdf(folders["downloads"] / "a.pdf")
    assert "two or more" in _run(action="merge_pdfs", name="a")


def test_merge_non_pdf(folders, monkeypatch):
    a = _pdf(folders["downloads"] / "a.pdf")
    b = _img(folders["downloads"] / "b.png")
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    assert "b.png is not a PDF" in _run(action="merge_pdfs")


def test_merge_without_pypdf(folders, monkeypatch):
    a = _pdf(folders["downloads"] / "a.pdf")
    b = _pdf(folders["downloads"] / "b.pdf")
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert "pypdf" in _run(action="merge_pdfs")


# ---------- resize / compress / format ----------

@pytest.mark.parametrize("size,expect", [(None, (200, 100)), ("half", (200, 100)), ("25%", (100, 50)),
                                         ("25 percent", (100, 50)), ("100", (100, 50)),
                                         ("100x100", (100, 50)), ("200 by 200", (200, 100)),
                                         ("5000", (400, 200))])
def test_parse_size(size, expect):
    assert fc.parse_size(size, 400, 200) == expect


@pytest.mark.parametrize("size", ["huge", "0%", "150%"])
def test_parse_size_bad(size):
    with pytest.raises(fc.ConvertError):
        fc.parse_size(size, 400, 200)


def test_resize(folders):
    src = _img(folders["downloads"] / "cat.png")
    out = _run(action="resize", name="cat", size="50%")
    assert "cat-small.png" in out
    with Image.open(folders["downloads"] / "cat-small.png") as im:
        assert im.size == (200, 100)
    with Image.open(src) as im:
        assert im.size == (400, 200)


def test_resize_twice_no_overwrite(folders):
    _img(folders["downloads"] / "cat.png")
    _run(action="resize", name="cat.png")
    assert "cat-small-1.png" in _run(action="resize", name="cat.png")


def test_compress_transparent_png(folders):
    _img(folders["downloads"] / "logo.png", size=(3000, 1500), mode="RGBA")
    out = _run(action="compress", name="logo")
    assert "logo-small.jpg" in out
    with Image.open(folders["downloads"] / "logo-small.jpg") as im:
        assert im.format == "JPEG" and max(im.size) == 2000


def test_to_format(folders):
    _img(folders["downloads"] / "pic.png", mode="RGBA")
    assert "pic.jpg" in _run(action="to_format", name="pic", format="JPG")
    with Image.open(folders["downloads"] / "pic.jpg") as im:
        assert im.format == "JPEG"
    assert "pic.webp" in _run(action="to_format", name="pic.png", format="webp")


def test_to_format_same_or_bad(folders):
    _img(folders["downloads"] / "pic.jpg")
    assert "already a JPG" in _run(action="to_format", name="pic", format="jpeg")
    assert "PNG, JPG, WebP or BMP" in _run(action="to_format", name="pic", format="tiff")


def test_resize_non_image(folders):
    _pdf(folders["downloads"] / "doc.pdf")
    assert "not a picture" in _run(action="resize", name="doc")


def test_several_pictures_compressed(folders, monkeypatch):
    a = _img(folders["desktop"] / "a.png")
    b = _img(folders["desktop"] / "b.png")
    monkeypatch.setattr(fc, "explorer_selection", lambda: [a, b])
    assert "Compressed 2 pictures" in _run(action="compress")
    assert (folders["desktop"] / "a-small.jpg").exists() and (folders["desktop"] / "b-small.jpg").exists()


def test_broken_image_does_not_crash(folders):
    (folders["downloads"] / "bad.png").write_bytes(b"not an image")
    out = _run(action="resize", name="bad")
    assert out.startswith("Sorry")


def test_huge_image_refused(folders, monkeypatch):
    _img(folders["downloads"] / "big.png")
    monkeypatch.setattr(fc, "MAX_PIXELS", 100)
    assert "too big" in _run(action="compress", name="big")


# ---------- finding files ----------

def test_find_prefers_exact_then_newest(folders):
    a = _img(folders["documents"] / "report final.png")
    os.utime(a, (1, 1))
    _img(folders["downloads"] / "report.png")
    assert fc.find_by_name("report").endswith(os.path.join("downloads", "report.png"))
    assert fc.find_by_name("report final").endswith("report final.png")


def test_find_absolute_path(tmp_path, folders):
    p = _img(tmp_path / "elsewhere.png")
    assert fc.find_by_name(p) == p


def test_explorer_selection_without_pywin32(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    assert fc.explorer_selection() == []


def test_explorer_selection_prefers_front_window(tmp_path, monkeypatch):
    a, b = _img(tmp_path / "a.png"), _img(tmp_path / "b.png")

    def win(hwnd, paths):
        items = [types.SimpleNamespace(Path=p) for p in paths]
        return types.SimpleNamespace(HWND=hwnd, Document=types.SimpleNamespace(SelectedItems=lambda: items))

    shell = types.SimpleNamespace(Windows=lambda: [win(1, [a]), win(2, [b])])
    client = types.SimpleNamespace(Dispatch=lambda name: shell)
    monkeypatch.setitem(sys.modules, "pythoncom", types.SimpleNamespace(CoInitialize=lambda: None))
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(fc, "_foreground_hwnd", lambda: 2)
    assert fc.explorer_selection() == [b]
    monkeypatch.setattr(fc, "_foreground_hwnd", lambda: 99)
    assert fc.explorer_selection() == []  # two windows, neither in front: don't guess


def test_catalog_matches_handlers():
    assert set(fc.CATALOG) == set(fc.HANDLERS) == {"convert_file"}
    assert fc.CATALOG["convert_file"]["properties"]["action"]["enum"] == list(fc.ACTIONS)


def test_z1_macros_forced_off_before_open(monkeypatch):
    import sys as _sys

    made = []

    class App:
        def __setattr__(self, k, v):
            made.append((k, v))
            object.__setattr__(self, k, v)

        def Quit(self):
            made.append(("quit",))

    monkeypatch.setitem(_sys.modules, "pythoncom", types.SimpleNamespace(CoInitialize=lambda: None,
                                                                         CoUninitialize=lambda: None))
    client = types.SimpleNamespace(DispatchEx=lambda pid: App())
    monkeypatch.setitem(_sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(_sys.modules, "win32com.client", client)
    app = fc._dispatch("Word.Application")
    assert made[0] == ("AutomationSecurity", fc.MSO_FORCE_DISABLE) and app is not None


def test_z1_macro_files_refused(tmp_path):
    p = tmp_path / "invoice.docm"
    p.write_bytes(b"x")
    with pytest.raises(fc.ConvertError, match="macros"):
        fc.office_to_pdf(str(p))
