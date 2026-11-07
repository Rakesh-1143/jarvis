"""Piece AA: generate (password, PIN, UUID, QR). Clipboard and file opening are faked."""
import os
import string
import sys
import types
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import generate as g  # noqa: E402


@pytest.fixture
def clip(monkeypatch):
    """Fake pyperclip module; returns a dict holding the clipboard."""
    box = {"text": ""}
    fake = types.ModuleType("pyperclip")
    fake.copy = lambda t: box.__setitem__("text", t)
    fake.paste = lambda: box["text"]
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    return box


@pytest.fixture
def cfg(monkeypatch):
    """Settings with no auto-clear timer (tests stay fast)."""
    s = {"password_length": 16, "pin_length": 4, "symbols": True, "speak_secrets": False, "clear_after": 0}
    monkeypatch.setattr(g, "_settings", lambda: dict(s))
    return s


# ---------- password ----------

def test_password_has_all_groups_and_length():
    for _ in range(50):
        pw = g.make_password(16)
        assert len(pw) == 16
        assert any(c in string.ascii_lowercase for c in pw)
        assert any(c in string.ascii_uppercase for c in pw)
        assert any(c in string.digits for c in pw)
        assert any(c in g.SYMBOLS for c in pw)
        assert not set(pw) & g._LOOKALIKE


def test_password_without_symbols_and_clamped():
    pw = g.make_password(3, symbols=False)
    assert len(pw) == g.PW_MIN
    assert not any(c in g.SYMBOLS for c in pw)
    assert len(g.make_password(999)) == g.PW_MAX


def test_password_is_random():
    assert len({g.make_password(16) for _ in range(20)}) == 20


def test_password_copied_not_spoken(clip, cfg):
    reply = g.generate({"kind": "password"})
    pw = clip["text"]
    assert len(pw) == 16
    assert pw not in reply
    assert "copied a 16-character password" in reply


def test_password_length_from_words(clip, cfg):
    g.generate({"kind": "password", "length": "twenty four characters"})
    assert len(clip["text"]) == 24
    g.generate({"kind": "password", "length": 20})
    assert len(clip["text"]) == 20


def test_password_never_spoken_when_copy_fails(monkeypatch, cfg):
    monkeypatch.setattr(g, "_copy", lambda t: False)
    seen = {}
    real = g.make_password
    monkeypatch.setattr(g, "make_password", lambda *a: seen.setdefault("pw", real(*a)))
    reply = g.generate({"kind": "password"})
    assert "couldn't copy" in reply
    assert seen["pw"] not in reply


def test_speak_secrets_option(clip, cfg):
    cfg["speak_secrets"] = True
    reply = g.generate({"kind": "pin", "length": 6})
    pin = clip["text"]
    assert len(pin) == 6 and pin.isdigit()
    assert ", ".join(pin) in reply


def test_spell_out():
    assert g._spell_out("aB3!") == "a, capital B, 3, exclamation"


# ---------- clipboard auto clear ----------

def test_clear_only_if_still_same(clip, monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, sec, fn):
            self.sec, self.fn, self.daemon = sec, fn, False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(g.threading, "Timer", FakeTimer)
    clip["text"] = "secret"
    g._schedule_clear("secret", 60)
    timers[-1].fn()
    assert clip["text"] == ""

    clip["text"] = "secret2"
    g._schedule_clear("secret2", 60)
    clip["text"] = "user copied something else"
    timers[-1].fn()
    assert clip["text"] == "user copied something else"


def test_reply_mentions_clear(clip, cfg, monkeypatch):
    cfg["clear_after"] = 60
    monkeypatch.setattr(g, "_schedule_clear", lambda s, n: None)
    assert "cleared in 60 seconds" in g.generate({"kind": "password"})


# ---------- pin / uuid ----------

def test_pin_default_and_clamp(clip, cfg):
    assert "4-character PIN" in g.generate({"kind": "pin"})
    assert len(clip["text"]) == 4 and clip["text"].isdigit()
    g.generate({"kind": "pin", "length": 99})
    assert len(clip["text"]) == g.PIN_MAX
    g.generate({"kind": "pin code", "length": 1})
    assert len(clip["text"]) == g.PIN_MIN


def test_uuid(clip):
    reply = g.generate({"kind": "uuid"})
    assert "copied a new UUID" in reply
    assert len(clip["text"]) == 36 and clip["text"].count("-") == 4


def test_unknown_kind_and_default():
    assert "password, a PIN" in g.generate({"kind": "lottery"})


# ---------- QR ----------

@pytest.fixture
def fake_qr(monkeypatch, tmp_path):
    made = {}

    class Img:
        def save(self, path):
            made["path"] = path
            open(path, "wb").close()

    mod = types.ModuleType("qrcode")
    mod.make = lambda text: made.__setitem__("text", text) or Img()
    monkeypatch.setitem(sys.modules, "qrcode", mod)
    monkeypatch.setattr(g.tempfile, "gettempdir", lambda: str(tmp_path))
    opened = []
    monkeypatch.setattr(g, "_open_file", opened.append)
    made["opened"] = opened
    return made


def test_qr_from_text(fake_qr):
    reply = g.generate({"kind": "qr", "text": "https://www.example.com/page/"})
    assert fake_qr["text"] == "https://www.example.com/page/"
    assert fake_qr["opened"] == [fake_qr["path"]]
    assert "example.com/page" in reply and "Scan it" in reply


def test_qr_from_clipboard(fake_qr, clip):
    clip["text"] = "https://secret.example.com/x?token=abc"
    reply = g.generate({"kind": "qr", "text": "this link"})
    assert fake_qr["text"] == clip["text"]
    assert "what you copied" in reply
    assert "token" not in reply


def test_qr_empty_clipboard(fake_qr, clip):
    assert "clipboard is empty" in g.generate({"kind": "qr"})
    assert "text" not in fake_qr


def test_qr_too_long(fake_qr):
    assert "too long" in g.generate({"kind": "qr", "text": "x" * (g.QR_MAX_CHARS + 1)})


def test_qr_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "qrcode", None)  # import raises ImportError
    assert "pip install qrcode" in g.generate({"kind": "qr", "text": "hello"})


def test_qr_open_fails(fake_qr, monkeypatch):
    monkeypatch.setattr(g, "_open_file", mock.Mock(side_effect=OSError))
    assert "couldn't open" in g.generate({"kind": "qr", "text": "hi"})


def test_qr_real_png(monkeypatch, tmp_path):
    """Uses the real qrcode package when it is installed."""
    pytest.importorskip("qrcode")
    pytest.importorskip("PIL")
    monkeypatch.setattr(g.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(g, "_open_file", lambda p: None)
    assert "QR code" in g.generate({"kind": "qr", "text": "hello"})
    data = (tmp_path / g.QR_FILE).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ---------- catalog ----------

def test_catalog_matches_handlers():
    assert set(g.CATALOG) == set(g.HANDLERS) == {"generate"}
    assert set(g.CATALOG["generate"]["properties"]["kind"]["enum"]) == set(g._KINDS)
    assert not g.CATALOG["generate"].get("info")
