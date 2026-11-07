"""Tests for actions/vdesktops.py with fake backends (no Windows needed)."""
import types

import pytest

from jarvis.actions import vdesktops as vd


class FakeExact:
    exact = True

    def __init__(self, count=3, current=1, names=None, has_window=True):
        self.n, self.cur = count, current
        self.names = names or {}
        self.has_window = has_window
        self.moved, self.closed = [], []

    def count(self):
        return self.n

    def current(self):
        return self.cur

    def name(self, n):
        return self.names.get(n, "")

    def go(self, n):
        self.cur = n

    def new(self):
        self.n += 1
        self.cur = self.n
        return self.n

    def move_window(self, n):
        if not self.has_window:
            return False
        self.moved.append(n)
        return True

    def close(self, n, fallback):
        self.closed.append((n, fallback))
        self.n -= 1


class FakeKeys(vd.HotkeyBackend):
    def __init__(self):
        self.keys = []

    def _keys(self, *keys):
        self.keys.append(keys)


@pytest.fixture
def exact(monkeypatch):
    b = FakeExact()
    monkeypatch.setattr(vd, "_backend", lambda: b)
    return b


@pytest.fixture
def keys(monkeypatch):
    b = FakeKeys()
    monkeypatch.setattr(vd, "_backend", lambda: b)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return b


@pytest.mark.parametrize("value,expected", [
    (2, 2), ("3", 3), ("two", 2), ("second", 2), ("desktop 4", 4), ("to", 2), ("last", -1),
    (0, None), ("", None), (None, None), (True, None), ("banana", None), ("the third one", 3),
])
def test_number(value, expected):
    assert vd._number(value) == expected


def test_unknown_action_and_missing_number(exact):
    assert "I can make" in vd.vdesktop({"action": "dance"})
    assert vd.vdesktop({"action": "go"}) == "Which desktop number?"
    assert vd.vdesktop({"action": "move_window"}) == "Which desktop number?"
    assert "I can make" in vd.vdesktop({})


def test_no_backend(monkeypatch):
    monkeypatch.setattr(vd, "_backend", lambda: None)
    assert "only work on Windows" in vd.vdesktop({"action": "new"})


def test_backend_none_off_windows(monkeypatch):
    monkeypatch.setattr(vd.sys, "platform", "linux")
    assert vd._backend() is None


def test_backend_prefers_pyvda(monkeypatch):
    monkeypatch.setattr(vd.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "pyvda", types.ModuleType("pyvda"))
    assert isinstance(vd._backend(), vd.PyvdaBackend)


def test_backend_falls_back_to_hotkeys(monkeypatch):
    monkeypatch.setattr(vd.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "pyvda", None)  # import raises
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", types.ModuleType("pyautogui"))
    assert isinstance(vd._backend(), vd.HotkeyBackend)


# ---------- exact (pyvda) ----------

def test_which(exact):
    exact.cur = 2
    assert vd.vdesktop({"action": "which"}) == "You are on desktop 2 of 3."
    exact.names[2] = "Work"
    assert vd.vdesktop({"action": "current"}) == "You are on desktop 2 (Work) of 3."
    exact.names[2] = "Desktop 2"  # default-looking name is not repeated
    assert vd.vdesktop({"action": "which"}) == "You are on desktop 2 of 3."


def test_new(exact):
    assert vd.vdesktop({"action": "new"}) == "New desktop made. You are on desktop 4."
    assert exact.n == 4 and exact.cur == 4


def test_next_previous_edges(exact):
    assert "first desktop" in vd.vdesktop({"action": "previous"})
    assert vd.vdesktop({"action": "next"}) == "Desktop 2."
    assert vd.vdesktop({"action": "right"}) == "Desktop 3."
    assert "last desktop" in vd.vdesktop({"action": "next"})
    assert vd.vdesktop({"action": "back"}) == "Desktop 2."


def test_go(exact):
    assert vd.vdesktop({"action": "go", "number": "three"}) == "Desktop 3."
    assert exact.cur == 3
    assert "already on desktop 3" in vd.vdesktop({"action": "go", "number": 3})
    assert vd.vdesktop({"action": "go", "number": 7}) == "You have only 3 desktops."
    exact.cur = 1
    assert vd.vdesktop({"action": "go", "number": "last"}) == "Desktop 3."


def test_move_window(exact):
    assert vd.vdesktop({"action": "move_window", "number": 3}) == "Moved this window to desktop 3."
    assert exact.moved == [3] and exact.cur == 1  # stays on the current desktop
    assert "already on desktop 1" in vd.vdesktop({"action": "move", "number": 1})
    assert "only 3" in vd.vdesktop({"action": "move_window", "number": 9})
    exact.has_window = False
    assert "no active window" in vd.vdesktop({"action": "move_window", "number": 2})


def test_close_moves_to_next_or_previous(exact):
    exact.cur = 2
    assert vd.vdesktop({"action": "close"}) == "Closed desktop 2. Its windows moved to desktop 2, where you are now."
    assert exact.closed == [(2, 3)]
    exact.cur = 2  # now last of 2
    assert vd.vdesktop({"action": "close"}) == "Closed desktop 2. Its windows moved to desktop 1, where you are now."
    assert exact.closed[-1] == (2, 1)


def test_close_only_desktop(exact):
    exact.n = 1
    assert "only desktop" in vd.vdesktop({"action": "close"})
    assert exact.closed == []


def test_errors_are_spoken(exact, monkeypatch):
    def boom(n):
        raise OSError("COM failed")

    monkeypatch.setattr(exact, "go", boom)
    assert vd.vdesktop({"action": "go", "number": 2}) == "I couldn't change desktops: COM failed"


# ---------- hotkey fallback ----------

def test_hotkeys_simple(keys):
    assert vd.vdesktop({"action": "new"}) == "New desktop made."
    assert vd.vdesktop({"action": "next"}) == "Next desktop."
    assert vd.vdesktop({"action": "previous"}) == "Previous desktop."
    assert "Closed this desktop" in vd.vdesktop({"action": "close"})
    assert keys.keys == [("win", "ctrl", "d"), ("win", "ctrl", "right"),
                         ("win", "ctrl", "left"), ("win", "ctrl", "f4")]


def test_hotkeys_go_sweeps_left_then_right(keys):
    assert vd.vdesktop({"action": "go", "number": 3}) == "Going to desktop 3."
    assert keys.keys == [("win", "ctrl", "left")] * vd.MAX_SWEEP + [("win", "ctrl", "right")] * 2


def test_hotkeys_go_last(keys):
    assert vd.vdesktop({"action": "go", "number": "last"}) == "Going to the last desktop."
    assert keys.keys == [("win", "ctrl", "right")] * vd.MAX_SWEEP


def test_hotkeys_need_pyvda(keys):
    assert vd.vdesktop({"action": "which"}) == vd.NEED_PYVDA
    assert vd.vdesktop({"action": "move_window", "number": 2}) == vd.NEED_PYVDA
    assert keys.keys == []


# ---------- PyvdaBackend against a fake pyvda module ----------

def _fake_pyvda():
    state = {"desktops": ["a", "b"], "cur": 1, "moved": None, "removed": None}

    class VirtualDesktop:
        def __init__(self, number=None, current=False):
            self.number = state["cur"] if current else number
            self.name = f"N{self.number}"

        @classmethod
        def current(cls):
            return cls(current=True)

        @classmethod
        def create(cls):
            state["desktops"].append("new")

        def go(self):
            state["cur"] = self.number

        def remove(self, fallback):
            state["removed"] = (self.number, fallback.number)

    class AppView:
        hwnd = 55

        @classmethod
        def current(cls):
            return cls()

        def move(self, desk):
            state["moved"] = desk.number

    mod = types.SimpleNamespace(VirtualDesktop=VirtualDesktop, AppView=AppView,
                                get_virtual_desktops=lambda: list(state["desktops"]))
    return mod, state


def test_pyvda_backend():
    mod, state = _fake_pyvda()
    b = vd.PyvdaBackend(mod)
    assert b.count() == 2 and b.current() == 1 and b.name(2) == "N2"
    assert b.new() == 3 and state["cur"] == 3
    assert b.move_window(1) is True and state["moved"] == 1
    b.close(3, 2)
    assert state["removed"] == (3, 2)


def test_catalog_shape():
    spec = vd.CATALOG["vdesktop"]
    assert spec["properties"]["action"]["enum"] == list(vd.ACTIONS)
    assert vd.HANDLERS["vdesktop"] is vd.vdesktop
