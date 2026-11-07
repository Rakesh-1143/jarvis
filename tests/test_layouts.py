"""Tests for actions/layouts.py with a fake window backend (no Windows needed)."""
import json
import os

import pytest

from jarvis.actions import layouts


class FakeBackend:
    def __init__(self, windows=None, offscreen=(), fail=(), spawn=None):
        self.windows = list(windows or [])
        self.placed = []          # (hwnd, rect, state)
        self.started = []
        self.offscreen = set(offscreen)
        self.fail = set(fail)
        self.spawn = spawn or {}  # exe -> window dict that appears after start

    def list_windows(self):
        return [dict(w) for w in self.windows]

    def on_screen(self, rect):
        return tuple(rect) not in self.offscreen

    def place(self, hwnd, rect, state):
        if hwnd in self.fail:
            return False
        self.placed.append((hwnd, list(rect), state))
        return True

    def start(self, exe):
        self.started.append(exe)
        if exe in self.spawn:
            self.windows.append(self.spawn[exe])
        return True


def W(hwnd, exe, title, rect=(0, 0, 800, 600), state="normal", pid=100):
    return {"hwnd": hwnd, "pid": pid, "exe": exe, "title": title, "rect": list(rect), "state": state}


@pytest.fixture
def env(tmp_path, monkeypatch):
    f = tmp_path / "layouts.json"
    monkeypatch.setattr(layouts, "settings", lambda cfg=None: {**layouts.DEFAULTS, "file": str(f), "wait_seconds": 1})
    clock = {"t": 0.0}
    monkeypatch.setattr(layouts, "_now", lambda: clock["t"])
    monkeypatch.setattr(layouts, "_sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    be = FakeBackend()
    monkeypatch.setattr(layouts, "_backend", be)
    return be, f


def _exe(tmp_path, name):
    p = tmp_path / name
    p.write_text("x")
    return str(p)


def test_catalog_and_handlers():
    assert set(layouts.CATALOG) == set(layouts.HANDLERS) == {"layout"}
    c = layouts.CATALOG["layout"]
    assert c["required"] == ["action"]
    assert c["properties"]["action"]["enum"] == ["save", "restore", "list", "delete"]


@pytest.mark.parametrize("raw,want", [
    ("coding", "coding"), ("the Coding layout", "coding"), ("my study setup", "study"),
    (None, ""), ("  ", ""), ("work-2!", "work-2"), ("x" * 80, "x" * 40),
])
def test_clean_name(raw, want):
    assert layouts.clean_name(raw) == want


def test_not_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(layouts, "_backend", None)
    monkeypatch.setattr(layouts.sys, "platform", "linux")
    assert "only work on Windows" in layouts.layout({"action": "save", "name": "x"})
    assert "only work on Windows" in layouts.layout({"action": "restore", "name": "x"})


def test_save_and_list(env):
    be, f = env
    be.windows = [W(1, r"C:\Code\code.exe", "main.py - VS Code", (0, 0, 960, 1080)),
                  W(2, r"C:\Chrome\chrome.exe", "Docs - Chrome", (960, 0, 1920, 1080), "maximized")]
    r = layouts.layout({"action": "save", "name": "coding layout"})
    assert r == "Saved the coding layout with 2 windows."
    data = json.loads(f.read_text())
    assert [w["title"] for w in data["coding"]["windows"]] == ["main.py - VS Code", "Docs - Chrome"]
    assert data["coding"]["windows"][1]["state"] == "maximized"
    assert "hwnd" not in data["coding"]["windows"][0]
    assert layouts.layout({"action": "save", "name": "coding"}).startswith("Updated the coding layout")
    assert layouts.layout({"action": "list"}) == "Your layouts: coding (2 windows)."


def test_save_default_name_and_skips(env, monkeypatch):
    be, f = env
    be.windows = [W(1, r"C:\x\notepad.exe", "notes"),
                  W(2, r"C:\Windows\explorer.exe", "Program Manager"),
                  W(3, r"C:\Windows\TextInputHost.exe", "Input"),
                  W(4, r"C:\py\python.exe", "Jarvis", pid=os.getpid()),
                  W(5, r"C:\x\a.exe", "   ")]
    assert layouts.layout({"action": "save"}) == "Saved the default layout with 1 window."


def test_save_nothing_open(env):
    assert layouts.layout({"action": "save", "name": "x"}) == "There are no open windows to save."


def test_list_empty(env):
    assert layouts.layout({"action": "list"}) == "You have no saved layouts."


def test_restore_moves_matching_windows(env):
    be, f = env
    be.windows = [W(1, r"C:\Code\code.exe", "main.py - VS Code", (0, 0, 960, 1080)),
                  W(2, r"C:\Chrome\chrome.exe", "Docs - Chrome", (960, 0, 1920, 1080), "maximized")]
    layouts.save("coding")
    # windows moved around, titles changed a bit
    be.windows = [W(20, r"C:\Chrome\chrome.exe", "Gmail - Chrome", (5, 5, 50, 50)),
                  W(10, r"C:\Code\code.exe", "other.py - VS Code", (5, 5, 50, 50))]
    r = layouts.layout({"action": "restore", "name": "coding"})
    assert r == "Restored the coding layout: moved 2 windows."
    assert (10, [0, 0, 960, 1080], "normal") in be.placed
    assert (20, [960, 0, 1920, 1080], "maximized") in be.placed
    assert be.started == []


def test_restore_prefers_exact_title(env):
    be, f = env
    be.windows = [W(1, r"C:\x\notepad.exe", "todo.txt - Notepad", (0, 0, 100, 100)),
                  W(2, r"C:\x\notepad.exe", "ideas.txt - Notepad", (200, 0, 300, 100))]
    layouts.save("n")
    be.windows = [W(7, r"C:\x\notepad.exe", "ideas.txt - Notepad"), W(8, r"C:\x\notepad.exe", "todo.txt - Notepad")]
    layouts.restore("n")
    assert (8, [0, 0, 100, 100], "normal") in be.placed
    assert (7, [200, 0, 300, 100], "normal") in be.placed


def test_restore_starts_missing_and_waits(env, tmp_path):
    be, f = env
    code = _exe(tmp_path, "code.exe")
    be.windows = [W(1, code, "VS Code", (0, 0, 900, 900))]
    layouts.save("coding")
    be.windows = []
    be.spawn = {code: W(55, code, "Welcome - VS Code")}
    r = layouts.restore("coding")
    assert be.started == [code]
    assert r == "Restored the coding layout: moved 1 window."
    assert be.placed == [(55, [0, 0, 900, 900], "normal")]


def test_restore_start_once_per_program_and_timeout(env, tmp_path):
    be, f = env
    code = _exe(tmp_path, "code.exe")
    be.windows = [W(1, code, "a"), W(2, code, "b")]
    layouts.save("c")
    be.windows = []  # never appears
    r = layouts.restore("c")
    assert be.started == [code]
    assert "moved 0 windows" in r and "Still not open: code." in r


def test_restore_does_not_start_bad_paths(env, tmp_path):
    be, f = env
    be.windows = [W(1, r"C:\gone\missing.exe", "a"), W(2, "relative.exe", "b"),
                  W(3, _exe(tmp_path, "script.bat"), "c"), W(4, r"C:\Windows\explorer.exe", "Downloads")]
    layouts.save("x")
    be.windows = []
    r = layouts.restore("x")
    assert be.started == []
    assert "I couldn't start missing, relative, script." in r
    assert "Still not open: explorer." in r


def test_restore_start_missing_off(env, tmp_path, monkeypatch):
    be, f = env
    code = _exe(tmp_path, "code.exe")
    be.windows = [W(1, code, "a")]
    layouts.save("c")
    be.windows = []
    monkeypatch.setattr(layouts, "settings", lambda cfg=None: {**layouts.DEFAULTS, "file": str(f),
                                                                "start_missing": False})
    layouts.restore("c")
    assert be.started == []


def test_restore_offscreen_goes_to_main_screen(env):
    be, f = env
    be.windows = [W(1, r"C:\x\a.exe", "a", (3000, 100, 3800, 700))]
    layouts.save("two")
    be.offscreen = {(3000, 100, 3800, 700)}
    r = layouts.restore("two")
    assert be.placed == [(1, [50, 50, 850, 650], "normal")]
    assert "main screen" in r


def test_restore_reports_failures(env):
    be, f = env
    be.windows = [W(1, r"C:\x\a.exe", "a")]
    layouts.save("x")
    be.fail = {1}
    assert "couldn't move 1 window" in layouts.restore("x")


def test_restore_names(env):
    be, f = env
    assert "no saved layouts" in layouts.restore("x")
    be.windows = [W(1, r"C:\x\a.exe", "a")]
    layouts.save("study")
    assert layouts.restore("").startswith("Restored the study layout")  # only one layout
    layouts.save("coding")
    assert layouts.restore("") == "Which layout? You have: coding, study."
    assert layouts.restore("gaming") == "I don't have a layout called gaming. You have: coding, study."
    layouts.save("")
    assert layouts.restore("").startswith("Restored the default layout")


def test_restore_keeps_minimized_state(env):
    be, f = env
    be.windows = [W(1, r"C:\x\a.exe", "a", (10, 10, 400, 400), "minimized")]
    layouts.save("m")
    layouts.restore("m")
    assert be.placed == [(1, [10, 10, 400, 400], "minimized")]


def test_delete_needs_confirm(env):
    be, f = env
    be.windows = [W(1, r"C:\x\a.exe", "a")]
    layouts.save("coding")
    args = {"action": "delete", "name": "coding"}
    assert layouts.needs_confirm(args)
    assert layouts.risky_text(args) == "delete the coding window layout"
    assert layouts.layout(args) == "Are you sure you want to delete the coding layout?"
    assert "coding" in json.loads(f.read_text())
    assert layouts.layout({**args, "confirm": True}) == "Deleted the coding layout."
    assert json.loads(f.read_text()) == {}


def test_delete_unknown_or_no_name(env):
    be, f = env
    assert not layouts.needs_confirm({"action": "delete", "name": "x"})
    assert layouts.risky_text({"action": "delete", "name": "x"}) is None
    assert layouts.layout({"action": "delete", "name": "x"}) == "I don't have a layout called x."
    assert layouts.layout({"action": "delete"}) == "You have no saved layouts."
    be.windows = [W(1, r"C:\x\a.exe", "a")]
    layouts.save("a")
    assert not layouts.needs_confirm({"action": "delete"})
    assert layouts.layout({"action": "delete"}) == "Which layout should I delete? You have: a."


def test_other_actions_not_risky(env):
    for a in ("save", "restore", "list", ""):
        assert not layouts.needs_confirm({"action": a, "name": "x"})
        assert layouts.risky_text({"action": a}) is None


def test_action_synonyms_and_unknown(env):
    be, f = env
    be.windows = [W(1, r"C:\x\a.exe", "a")]
    assert layouts.layout({"action": "remember", "name": "x"}).startswith("Saved")
    assert layouts.layout({"action": "load", "name": "x"}).startswith("Restored")
    assert layouts.layout({"action": "SHOW"}).startswith("Your layouts")
    assert "save, restore, list or delete" in layouts.layout({"action": "dance"})
    assert "save, restore, list or delete" in layouts.layout({})


def test_corrupt_file(env):
    be, f = env
    f.write_text("{not json")
    assert layouts.layout({"action": "list"}) == "You have no saved layouts."
    f.write_text("[1, 2]")
    assert layouts.layout({"action": "list"}) == "You have no saved layouts."


def test_backend_errors(env):
    be, f = env

    def boom():
        raise OSError("x")

    be.list_windows = boom
    assert "couldn't read the open windows" in layouts.save("x")
