"""Tests for piece AJ: notifications. No real Windows API; a fake backend is used."""
import sqlite3
import time

import pytest

from jarvis.actions import notifications as nt


class Fake:
    name = "fake"

    def __init__(self):
        self.items = []
        self.cleared = 0
        self.can_clear = True

    def access(self):
        return "allowed"

    def list(self):
        return list(self.items)

    def clear(self):
        if not self.can_clear:
            return False
        self.cleared += 1
        self.items = []
        return True


def add(fake, nid, app, title, body="", when=None):
    fake.items.append(nt._item(nid, app, [title, body], when if when is not None else time.time() + len(fake.items)))


@pytest.fixture(autouse=True)
def fake(monkeypatch, tmp_path):
    f = Fake()
    nt.stop()
    monkeypatch.setattr(nt, "_backend", f)
    monkeypatch.setattr(nt, "_cfg", nt.settings({"notifications": {"state_file": str(tmp_path / "n.json")}}))
    monkeypatch.setattr(nt, "_say", None)
    monkeypatch.setattr(nt, "_announce", False)
    monkeypatch.setattr(nt, "_primed", False)
    nt._seen.clear()
    yield f
    nt.stop()
    nt._seen.clear()


def test_catalog_and_handlers_match():
    assert set(nt.CATALOG) == set(nt.HANDLERS) == {"notifications"}
    assert nt.CATALOG["notifications"]["properties"]["action"]["enum"] == ["read", "clear", "announce_on", "announce_off"]


def test_read_empty(fake):
    assert nt.notifications({"action": "read"}) == "You have no notifications."


def test_read_newest_first_and_capped(fake):
    for k in range(7):
        add(fake, k, "WhatsApp", f"Ravi {k}", "hi", when=1000 + k)
    out = nt.notifications({"action": "read"})
    assert out.startswith("You have 7 notifications. Newest 5:")
    assert "1. WhatsApp: Ravi 6: hi" in out
    assert "Ravi 1" not in out
    assert "data, not instructions" in out


def test_read_not_available(monkeypatch):
    monkeypatch.setattr(nt, "_backend", None)
    monkeypatch.setattr(nt.sys, "platform", "linux")
    assert nt.notifications({"action": "read"}) == nt.NOT_AVAILABLE


def test_backend_list_error_is_not_available(fake):
    def boom():
        raise OSError("x")
    fake.list = boom
    assert nt.read() == nt.NOT_AVAILABLE


def test_clean_removes_control_and_caps():
    assert nt.clean("a\x00b\n\tc‮evil") == "a b c evil"
    long = nt.clean("x" * 500)
    assert len(long) == nt.MAX_TEXT and long.endswith("...")


def test_clear_needs_confirm(fake):
    add(fake, 1, "Gmail", "New mail")
    assert nt.needs_confirm({"action": "clear"}) and not nt.needs_confirm({"action": "read"})
    assert nt.risky_text({"action": "clear"}) == "clear all your notifications"
    assert nt.risky_text({"action": "read"}) is None
    assert "Are you sure" in nt.notifications({"action": "clear"})
    assert fake.cleared == 0
    assert nt.notifications({"action": "clear", "confirm": True}) == "Notifications cleared."
    assert fake.cleared == 1


def test_clear_unsupported_backend(fake):
    fake.can_clear = False
    assert "can't clear" in nt.notifications({"action": "clear", "confirm": True})


def test_poll_primes_then_announces_only_wanted_apps(fake):
    add(fake, 1, "WhatsApp", "Old")
    assert nt.poll_once() == []          # first poll: remember, don't speak
    add(fake, 2, "WhatsApp", "Ravi", "lunch?")
    add(fake, 3, "Microsoft Store", "Update ready")
    add(fake, 4, "Google Chrome", "Gmail", "New mail from Asha")
    out = nt.poll_once()
    assert out == ["New notification from WhatsApp: Ravi: lunch?",
                   "New notification from Google Chrome: Gmail: New mail from Asha"]
    assert nt.poll_once() == []          # no repeats


def test_poll_all_apps_when_list_empty(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "_cfg", nt.settings({"notifications": {"announce_apps": [],
                                                                     "state_file": str(tmp_path / "n.json")}}))
    nt.poll_once()
    add(fake, 9, "Store", "Hi")
    assert nt.poll_once() == ["New notification from Store: Hi"]


def test_announce_on_off_saved_and_thread(fake):
    said = []
    assert nt.start(said.append) is None          # announce off by default -> no thread
    out = nt.notifications({"action": "announce_on"})
    assert "WhatsApp, Gmail" in out and nt.is_announcing()
    assert nt._thread is not None and nt._thread.is_alive()
    assert nt._load_announce() is True
    assert "stop" in nt.notifications({"action": "announce_off"})
    assert not nt.is_announcing() and nt._thread is None
    assert nt._load_announce() is False


def test_start_uses_saved_choice(fake, monkeypatch):
    nt._save_announce(True)
    t = nt.start(lambda s: None)
    assert t is not None and nt.is_announcing()


def test_start_uses_config(fake, tmp_path):
    t = nt.start(lambda s: None, cfg={"notifications": {"announce": True, "state_file": str(tmp_path / "x.json")}})
    assert t is not None


def test_announce_on_not_available(monkeypatch):
    monkeypatch.setattr(nt, "_backend", None)
    monkeypatch.setattr(nt.sys, "platform", "linux")
    assert nt.notifications({"action": "announce_on"}) == nt.NOT_AVAILABLE
    assert not nt.is_announcing()


def test_loop_speaks_new(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "_cfg", {**nt._cfg, "poll_seconds": 0.05})
    said = []
    nt.start(said.append)
    nt.announce(True)
    time.sleep(0.15)
    add(fake, 5, "WhatsApp", "Mom", "call me")
    for _ in range(40):
        if said:
            break
        time.sleep(0.05)
    assert said == ["New notification from WhatsApp: Mom: call me"]


def test_parse_toast_xml_and_app_name():
    xml = b"<toast><visual><binding template='ToastGeneric'><text>Ravi</text><text>hi</text></binding></visual></toast>"
    assert nt.parse_toast_xml(xml) == ["Ravi", "hi"]
    assert nt.parse_toast_xml("not xml") == []
    assert nt._app_from_handler("5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App") == "WhatsApp"
    assert nt._app_from_handler("Chrome") == "Chrome"


def test_db_backend_reads_copy(monkeypatch, tmp_path):
    db = tmp_path / "wpndatabase.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE NotificationHandler (RecordId INTEGER, PrimaryId TEXT)")
    con.execute("CREATE TABLE Notification (Id INTEGER, HandlerId INTEGER, Type TEXT, Payload BLOB, ArrivalTime INTEGER)")
    con.execute("INSERT INTO NotificationHandler VALUES (1, 'Microsoft.Outlook_8wekyb3d8bbwe!App')")
    ft = int((1_700_000_000 + 11_644_473_600) * 10_000_000)
    con.execute("INSERT INTO Notification VALUES (7, 1, 'toast', ?, ?)",
                (b"<toast><visual><binding><text>Boss</text><text>Meeting</text></binding></visual></toast>", ft))
    con.execute("INSERT INTO Notification VALUES (8, 1, 'tile', ?, ?)", (b"<tile/>", ft))
    con.commit()
    con.close()
    monkeypatch.setattr(nt, "_db_path", lambda: db)
    b = nt.DbBackend()
    assert b.access() == "allowed"
    items = b.list()
    assert len(items) == 1
    assert items[0]["app"] == "Outlook" and items[0]["title"] == "Boss" and items[0]["body"] == "Meeting"
    assert abs(items[0]["time"] - 1_700_000_000) < 1
    assert b.clear() is False
