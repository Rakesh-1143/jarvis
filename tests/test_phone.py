"""Tests for actions/phone.py (fake kdeconnect-cli, no real phone)."""
import subprocess

import pytest

from jarvis.actions import phone as p

CONTACTS = {"mom": {"email": "mom@x.com", "phone": "+91 98765 43210"}, "boss": "boss@x.com"}


class FakeCli:
    def __init__(self, devices="abc123 Pixel 8\n", code=0, err=""):
        self.calls = []
        self.devices = devices
        self.code = code
        self.err = err
        self.battery = {"charge": "73", "isCharging": "true"}

    def __call__(self, cmd):
        self.calls.append(cmd)
        if "--id-name-only" in cmd:
            return 0, self.devices, ""
        if cmd[0].endswith("qdbus"):
            return 0, self.battery[cmd[-1].rsplit(".", 1)[1]] + "\n", ""
        return self.code, "", self.err

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def fake(monkeypatch):
    f = FakeCli()
    cfg = {"phone": {}, "contacts": CONTACTS}
    monkeypatch.setattr(p, "_run", f)
    monkeypatch.setattr(p, "_config", lambda: cfg)
    monkeypatch.setattr(p, "find_cli", lambda s: "kdeconnect-cli")
    monkeypatch.setattr(p, "_find_qdbus", lambda cli: "qdbus")
    f.cfg = cfg
    return f


def test_ring_uses_first_device(fake):
    assert p.phone({"action": "ring"}) == "Ringing your phone."
    assert fake.last == ["kdeconnect-cli", "-d", "abc123", "--ring"]


def test_configured_device_by_name(fake):
    fake.devices = "id1 Old Tab\nid2 Pixel 8\n"
    fake.cfg["phone"] = {"device": "pixel 8"}
    p.phone({"action": "ring"})
    assert fake.last[:3] == ["kdeconnect-cli", "-d", "id2"]


def test_configured_device_missing(fake):
    fake.cfg["phone"] = {"device": "galaxy"}
    assert "not connected" in p.phone({"action": "ring"})
    assert len(fake.calls) == 1  # only the device list, no ring


def test_no_device(fake):
    fake.devices = ""
    assert p.phone({"action": "ring"}) == p.NO_PHONE_MSG


def test_not_installed(monkeypatch):
    monkeypatch.setattr(p, "_config", lambda: {})
    monkeypatch.setattr(p, "find_cli", lambda s: None)
    assert p.phone({"action": "ring"}) == p.INSTALL_MSG


def test_cli_missing_file_and_timeout(fake, monkeypatch):
    def boom(cmd):
        raise FileNotFoundError
    monkeypatch.setattr(p, "_run", boom)
    assert p.phone({"action": "ring"}) == p.INSTALL_MSG

    def slow(cmd):
        raise subprocess.TimeoutExpired(cmd, 15)
    monkeypatch.setattr(p, "_run", slow)
    assert "did not answer" in p.phone({"action": "ring"})


def test_cli_error_is_reported(fake):
    fake.code, fake.err = 1, "Couldn't find device\n"
    assert "Couldn't find device" in p.phone({"action": "ring"})


# ---------- sms ----------
def test_sms_asks_first_and_sends_nothing(fake):
    r = p.phone({"action": "sms", "to": "mom", "text": "I'm late"})
    assert r.startswith("Are you sure you want to send a text to mom (+919876543210)")
    assert fake.calls == []


def test_sms_sends_after_confirm(fake):
    r = p.phone({"action": "sms", "to": "Mom", "text": "I'm late", "confirm": True})
    assert r == "Sent your text to Mom."
    assert fake.last == ["kdeconnect-cli", "-d", "abc123", "--send-sms", "I'm late",
                         "--destination", "+919876543210"]


def test_sms_to_spoken_number(fake):
    assert p.resolve_number("98765 43210") == "9876543210"
    p.phone({"action": "sms", "to": "98765 43210", "text": "hi", "confirm": True})
    assert fake.last[-1] == "9876543210"


def test_sms_missing_parts(fake):
    assert p.phone({"action": "sms", "text": "hi"}) == "Who should I text?"
    assert "don't have a phone number for boss" in p.phone({"action": "sms", "to": "boss", "text": "hi"})
    assert "What should the text" in p.phone({"action": "sms", "to": "mom"})
    assert fake.calls == []


def test_risky_text(fake):
    assert p.needs_confirm({"action": "sms", "to": "mom", "text": "hi"})
    assert not p.needs_confirm({"action": "sms", "to": "mom"})  # handler asks for the text
    assert not p.needs_confirm({"action": "ring"})
    assert p.risky_text({"action": "sms", "to": "12345678", "text": "x"}) == "send a text to 12345678 saying: x"


def test_number_not_injected_as_option(fake):
    # Text that looks like a flag is still one list item (no shell, no splitting).
    p.phone({"action": "sms", "to": "mom", "text": "--ring & del x", "confirm": True})
    assert fake.last[4] == "--ring & del x"


# ---------- share ----------
def test_share_url(fake):
    assert p.phone({"action": "share", "what": "https://example.com/a"}) == "Sent the link to your phone."
    assert fake.last[-2:] == ["--share", "https://example.com/a"]
    p.phone({"action": "share", "what": "www.example.com"})
    assert fake.last[-1] == "https://www.example.com"


def test_share_clipboard(fake, monkeypatch):
    monkeypatch.setattr(p, "_clipboard", lambda: "https://clip.me")
    p.phone({"action": "share", "what": "this link"})
    assert fake.last[-1] == "https://clip.me"
    monkeypatch.setattr(p, "_clipboard", lambda: "buy milk")
    assert p.phone({"action": "share"}) == "Sent the text to your phone."
    assert fake.last[-2:] == ["--share-text", "buy milk"]
    monkeypatch.setattr(p, "_clipboard", lambda: "")
    assert "clipboard is empty" in p.phone({"action": "share"})


def test_share_last_download(fake, monkeypatch, tmp_path):
    f = tmp_path / "ticket.pdf"
    f.write_text("x")
    monkeypatch.setattr(p, "_last_download", lambda: f)
    assert p.phone({"action": "share", "what": "my last download"}) == "Sent ticket.pdf to your phone."
    assert fake.last[-2:] == ["--share", str(f)]
    monkeypatch.setattr(p, "_last_download", lambda: None)
    assert "empty" in p.phone({"action": "share", "what": "last download"})


def test_share_file_only_inside_home(fake, monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    inside = home / "a.txt"
    inside.write_text("x")
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    p.phone({"action": "share", "what": str(inside)})
    assert fake.last[-2:] == ["--share", str(inside.resolve())]
    p.phone({"action": "share", "what": str(outside)})
    assert fake.last[-2] == "--share-text"  # not sent as a file


# ---------- battery ----------
def test_battery(fake):
    assert p.phone_battery({}) == "Your phone is at 73 percent and charging."
    fake.battery = {"charge": "40", "isCharging": "false"}
    assert p.phone_battery({}) == "Your phone is at 40 percent."
    fake.battery = {"charge": "-1", "isCharging": "false"}
    assert "couldn't read" in p.phone_battery({})


def test_battery_without_qdbus(fake, monkeypatch):
    monkeypatch.setattr(p, "_find_qdbus", lambda cli: None)
    assert "KDE Connect app shows it" in p.phone_battery({})


def test_battery_only_reads(fake):
    p.phone_battery({})
    flags = {a for c in fake.calls for a in c}
    assert not flags & {"--ring", "--send-sms", "--share", "--share-text"}


# ---------- misc ----------
def test_unknown_action(fake):
    assert "ring your phone" in p.phone({"action": "dance"})


def test_find_cli_config_path(tmp_path, monkeypatch):
    exe = tmp_path / "kdeconnect-cli.exe"
    exe.write_text("")
    assert p.find_cli({"kdeconnect_path": str(exe)}) == str(exe)
    monkeypatch.setattr(p.shutil, "which", lambda n: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert p.find_cli({}) is None
    (tmp_path / "pf" / "KDE Connect" / "bin").mkdir(parents=True)
    real = tmp_path / "pf" / "KDE Connect" / "bin" / "kdeconnect-cli.exe"
    real.write_text("")
    assert p.find_cli({}) == str(real)


def test_catalog_matches_handlers():
    assert set(p.CATALOG) == set(p.HANDLERS)
    assert p.CATALOG["phone_battery"].get("info") is True
    assert not p.CATALOG["phone"].get("info")
