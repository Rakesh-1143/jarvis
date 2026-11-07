"""Recent files (piece O). Uses temp folders; never opens real files."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import recent  # noqa: E402


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    d = {k: tmp_path / k for k in ("downloads", "desktop", "documents", "recent")}
    for p in d.values():
        p.mkdir()
    monkeypatch.setattr(recent, "folder_path", lambda f: str(d[f]))
    opened = []
    monkeypatch.setattr(recent, "_startfile", opened.append)
    d["opened"] = opened
    return d


def make(folder, name, age_s):
    p = folder / name
    p.write_text("x")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_open_last_download(dirs):
    make(dirs["downloads"], "old.zip", 3 * 86400)
    new = make(dirs["downloads"], "new.pdf", 60)
    make(dirs["downloads"], "half.pdf.crdownload", 1)  # unfinished download is skipped
    make(dirs["downloads"], "desktop.ini", 1)
    r = recent.recent_files({"action": "open"})
    assert r == "Opening new.pdf."
    assert dirs["opened"] == [str(new)]


def test_open_by_kind_and_which(dirs):
    make(dirs["downloads"], "a.pdf", 300)
    b = make(dirs["downloads"], "b.pdf", 600)
    make(dirs["downloads"], "c.png", 10)
    assert recent.recent_files({"action": "open", "kind": "pdf", "which": "second"}) == "Opening b.pdf."
    assert dirs["opened"] == [str(b)]
    assert "only 2" in recent.recent_files({"action": "open", "kind": "pdf", "which": 5})


def test_list_newest_first(dirs):
    for i in range(7):
        make(dirs["downloads"], f"f{i}.txt", (i + 1) * 120)
    r = recent.recent_files({})
    assert r.startswith("Your newest files in Downloads (7 in total): f0.txt, 2 minutes ago")
    assert "f4.txt" in r and "f5.txt" not in r
    assert dirs["opened"] == []


def test_today_filter(dirs):
    make(dirs["downloads"], "now.png", 30)
    make(dirs["downloads"], "old.png", 5 * 86400)
    r = recent.recent_files({"when": "today", "kind": "picture"})
    if time.localtime().tm_hour == 0 and time.localtime().tm_min < 1:
        pytest.skip("too close to midnight")
    assert r == "Pictures in Downloads from today: now.png, just now."


def test_nothing_found(dirs):
    make(dirs["downloads"], "a.txt", 5 * 86400)
    assert recent.recent_files({"when": "today"}) == "I found no files in Downloads from today."
    assert recent.recent_files({"kind": "video"}) == "I found no videos in Downloads."


def test_missing_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(recent, "folder_path", lambda f: str(tmp_path / "nope"))
    assert recent.recent_files({}) == "I can't find your downloads folder."


def test_recent_folder_shortcuts(dirs):
    lnk = make(dirs["recent"], "report.docx.lnk", 60)
    make(dirs["recent"], "Projects.lnk", 10)  # folder shortcut: skipped
    make(dirs["recent"], "notes.txt", 5)       # not a shortcut: skipped
    assert recent.recent_files({"folder": "recent"}).startswith("Your newest files recently used: report.docx")
    assert recent.recent_files({"folder": "recent", "action": "open"}) == "Opening report.docx."
    assert dirs["opened"] == [str(lnk)]


def test_desktop_folder(dirs):
    make(dirs["desktop"], "shot.png", 20)
    assert recent.recent_files({"folder": "my desktop", "action": "open", "kind": "image"}) == "Opening shot.png."


def test_open_error(dirs, monkeypatch):
    make(dirs["downloads"], "x.pdf", 5)

    def boom(_):
        raise OSError(2, "No application is associated")
    monkeypatch.setattr(recent, "_startfile", boom)
    assert recent.recent_files({"action": "open"}) == "I couldn't open x.pdf: No application is associated."


def test_normalizers():
    assert recent.norm_folder("Downloaded") == "downloads"
    assert recent.norm_folder(None) == "downloads"
    assert recent.norm_folder("recent files") == "recent"
    assert recent.norm_kind("PDF") == "pdf"
    assert recent.norm_kind("photos") == "image"
    assert recent.norm_kind("files") == ""
    assert recent._which("third") == 3 and recent._which(None) == 1 and recent._which("0") == 1


def test_since_until():
    now = time.mktime((2026, 11, 7, 15, 0, 0, 0, 0, -1))
    midnight = time.mktime((2026, 11, 7, 0, 0, 0, 0, 0, -1))
    assert recent._since("today", now) == midnight
    assert recent._until("yesterday", now) == midnight
    assert recent._since("yesterday", now) < midnight
    assert recent._since("", now) is None


def test_real_folder_paths(monkeypatch):
    monkeypatch.setenv("APPDATA", "/x/Roaming")
    assert recent.folder_path("recent") == os.path.join("/x/Roaming", "Microsoft", "Windows", "Recent")
    monkeypatch.setattr(recent, "_config", lambda: {"downloads_folder": "/d/dl"})
    assert recent.folder_path("downloads") == "/d/dl"
    assert recent.folder_path("desktop").endswith("Desktop")


def test_catalog_matches_handlers():
    assert set(recent.CATALOG) == set(recent.HANDLERS)
    for spec in recent.CATALOG.values():
        assert spec["description"] and "properties" in spec and "required" in spec


def test_never_runs_programs(dirs):
    for name in ("setup.exe", "x.msi", "run.bat", "a.ps1", "b.vbs", "c.js", "d.hta", "e.scr"):
        make(dirs["downloads"], name, 1)
        assert "won't run it" in recent.recent_files({"action": "open"})
        os.remove(dirs["downloads"] / name)
    make(dirs["recent"], "tool.exe.lnk", 1)
    assert "won't run it" in recent.recent_files({"action": "open", "folder": "recent"})
    assert dirs["opened"] == []
