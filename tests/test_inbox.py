"""Tests for actions/inbox.py with a fake IMAP server and fake Outlook (no network)."""
import imaplib
import sys
import types

import pytest

from jarvis.actions import inbox

MSGS = {  # uid -> (from header, subject, unread)
    b"1": ("Amazon <ship@amazon.com>", "Your order has shipped", False),
    b"2": ("Mom <mom@example.com>", "Dinner on Sunday", False),
    b"3": ("=?utf-8?b?UHJpeWE=?= <priya@example.com>", "=?utf-8?q?Caf=C3=A9_plans?=", True),
    b"4": ("Mom <mom@example.com>", "Call me", True),
    b"5": ("Bank <alerts@bank.com>", "Statement ready", True),
}


class FakeIMAP:
    instances = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        FakeIMAP.instances.append(self)

    def login(self, user, pw):
        if FakeIMAP.fail_login:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        self.user, self.pw = user, pw

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [b"5"]

    def uid(self, cmd, *args):
        self.calls.append((cmd, args))
        if cmd == "SEARCH":
            ids = list(MSGS)
            if "UNSEEN" in args:
                ids = [u for u in ids if MSGS[u][2]]
            if "FROM" in args:
                who = args[args.index("FROM") + 1].strip('"').lower()
                ids = [u for u in ids if who in MSGS[u][0].lower()]
            return "OK", [b" ".join(ids)]
        if cmd == "FETCH":
            frm, subj, _ = MSGS[args[0]]
            raw = f"From: {frm}\r\nSubject: {subj}\r\n\r\n".encode()
            return "OK", [(args[0] + b" (BODY[...] {50}", raw), b")"]
        raise AssertionError(f"unexpected IMAP command {cmd}")

    def logout(self):
        pass


@pytest.fixture
def imap(monkeypatch):
    FakeIMAP.instances.clear()
    FakeIMAP.fail_login = False
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.delenv(inbox.PASSWORD_ENV, raising=False)
    settings = {"user": "me@gmail.com", "password": "app-pass",
                "_contacts": {"mom": {"email": "mom@example.com", "phone": "1"}}}
    monkeypatch.setattr(inbox, "_settings", lambda: dict(settings))
    return settings


def test_new_emails_lists_unread_newest_first(imap):
    out = inbox.check_email({})
    assert out.startswith("You have 3 new emails.")
    assert out.index("Statement ready") < out.index("Call me") < out.index("Café plans")
    assert "From Priya" in out and "shipped" not in out
    conn = FakeIMAP.instances[0]
    assert conn.host == "imap.gmail.com" and conn.readonly is True and conn.pw == "app-pass"


def test_never_writes_and_uses_peek(imap):
    inbox.check_email({"count": 10})
    cmds = {c for c, _ in FakeIMAP.instances[0].calls}
    assert cmds <= {"SEARCH", "FETCH"}
    assert all("PEEK" in a[1] for c, a in FakeIMAP.instances[0].calls if c == "FETCH")


def test_count_limits_and_latest(imap):
    out = inbox.check_email({"count": 1})
    assert "Here is the latest." in out and "Statement ready" in out and "Call me" not in out
    out = inbox.check_email({"count": 2, "unread_only": False})
    assert out.startswith("Your latest emails. You have 3 new.")


def test_from_contact_uses_contacts_email(imap):
    out = inbox.check_email({"from": "mom"})
    assert out.startswith("You have 2 emails from mom, 1 new.")
    assert "Call me" in out and "Dinner on Sunday" in out
    search = [a for c, a in FakeIMAP.instances[0].calls if c == "SEARCH"]
    assert ("FROM", '"mom@example.com"', "UNSEEN") in search


def test_from_unknown_sender(imap):
    assert inbox.check_email({"from": "boss"}) == "I found no emails from boss."


def test_no_new_mail(imap):
    for k in list(MSGS):
        MSGS[k] = (MSGS[k][0], MSGS[k][1], False)
    try:
        assert inbox.check_email({}) == "No new emails."
    finally:
        for k, unread in ((b"3", True), (b"4", True), (b"5", True)):
            MSGS[k] = (MSGS[k][0], MSGS[k][1], unread)


def test_env_password_wins(imap, monkeypatch):
    monkeypatch.setenv(inbox.PASSWORD_ENV, "env-pass")
    inbox.check_email({})
    assert FakeIMAP.instances[0].pw == "env-pass"


def test_login_failure(imap):
    FakeIMAP.fail_login = True
    assert "login failed" in inbox.check_email({})


def test_network_error(imap, monkeypatch):
    def boom(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", boom)
    assert "internet" in inbox.check_email({})


def test_not_set_up(monkeypatch):
    monkeypatch.delenv(inbox.PASSWORD_ENV, raising=False)
    monkeypatch.setattr(inbox, "_settings", lambda: {"_contacts": {}})
    monkeypatch.setattr(inbox, "_outlook_available", lambda: False)
    assert inbox.check_email({}) == inbox.SETUP_HELP


def test_host_guess_and_override():
    assert inbox._host({"user": "a@yahoo.com"}) == "imap.mail.yahoo.com"
    assert inbox._host({"user": "a@mycorp.org"}) == "imap.mycorp.org"
    assert inbox._host({"user": "a@gmail.com", "host": "mail.x.com"}) == "mail.x.com"


# ---------- Outlook desktop (fake win32com) ----------
class FakeMail:
    Class = 43

    def __init__(self, name, addr, subject, unread):
        self.SenderName, self.SenderEmailAddress, self.Subject, self.UnRead = name, addr, subject, unread


class FakeItems:
    def __init__(self, mails):
        self.mails, self.i = mails, 0

    def Sort(self, key, desc):
        assert key == "[ReceivedTime]" and desc is True

    def GetFirst(self):
        self.i = 0
        return self.GetNext()

    def GetNext(self):
        if self.i >= len(self.mails):
            return None
        self.i += 1
        return self.mails[self.i - 1]


@pytest.fixture
def outlook(monkeypatch):
    mails = [FakeMail("Boss", "boss@work.com", "Meeting moved", True),
             FakeMail("Mom", "mom@example.com", "Call me", True),
             FakeMail("Shop", "news@shop.com", "Sale", False)]
    inbox_folder = types.SimpleNamespace(Items=FakeItems(mails))
    ns = types.SimpleNamespace(GetDefaultFolder=lambda n: inbox_folder)
    app = types.SimpleNamespace(GetNamespace=lambda name: ns)
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: app
    pkg = types.ModuleType("win32com")
    pkg.client = client
    monkeypatch.setitem(sys.modules, "win32com", pkg)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.delenv(inbox.PASSWORD_ENV, raising=False)
    monkeypatch.setattr(inbox, "_settings", lambda: {"_contacts": {}})
    return mails


def test_outlook_new_emails(outlook):
    out = inbox.check_email({})
    assert out.startswith("You have 2 new emails.")
    assert "From Boss: Meeting moved." in out and "Sale" not in out
    assert all(m.UnRead for m in outlook[:2])  # still unread


def test_outlook_from(outlook):
    out = inbox.check_email({"from": "mom"})
    assert out == "You have 1 email from mom, 1 new. 1. From Mom: Call me."


# ---------- wiring ----------
def test_catalog_matches_handlers():
    assert set(inbox.CATALOG) == set(inbox.HANDLERS) == {"check_email"}
    spec = inbox.CATALOG["check_email"]
    assert spec["info"] is True and spec["required"] == []
    assert set(spec["properties"]) == {"from", "count", "unread_only"}
