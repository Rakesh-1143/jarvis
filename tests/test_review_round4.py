"""Tests for REVIEW.md Rounds 4-6 fixes (U1, U6, U7, U9, V1). Outside calls are faked."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import corrections, interpreter, notifications as nt, podcasts, security  # noqa: E402

FEED = b"""<rss><channel>
<item><title>Bad 1</title><enclosure url="C:\\\\Windows\\\\System32\\\\cmd.exe"/></item>
<item><title>Bad 2</title><enclosure url="\\\\\\\\evil.host\\\\share\\\\x.exe"/></item>
<item><title>Bad 3</title><enclosure url="file:///C:/x.exe"/></item>
<item><title>Bad 4</title><enclosure url="ms-msdt:/id x"/></item>
<item><title>Good</title><enclosure url="https://cdn.example.com/ep1.mp3"/></item>
</channel></rss>"""


def test_u1_podcast_feed_only_web_links():
    eps = podcasts.parse_feed(FEED)
    assert [e["title"] for e in eps] == ["Good"]
    with pytest.raises(ValueError):
        podcasts._open("C:/Windows/System32/cmd.exe")
    with pytest.raises(ValueError):
        podcasts._fetch("file:///etc/passwd")
    assert podcasts.is_web_link("http://x.com/feed") and not podcasts.is_web_link("https://")


def test_u6_teach_and_corrections_need_pin_and_safe_words():
    for intent in ("teach", "taught", "correction", "corrections"):
        assert intent in security.DEFAULT_PROTECT
    assert "number" in corrections._check("four", "for")
    assert "can't let" in corrections._check("lights", "yes do it")
    assert "can't let" in corrections._check("lights", "shut down")
    assert corrections._check("note pad", "notepad") is None


def test_u7_bare_stop_leaves_translate_mode():
    for text in ("stop", "cancel", "Jarvis stop", "that's enough"):
        assert interpreter._STOP.match(interpreter._plain(text)), text
    assert not interpreter._STOP.match(interpreter._plain("stop the car"))


def test_v1_notifications_private_when_locked(monkeypatch):
    items = [{"id": "1", "app": "WhatsApp", "title": "Bank", "body": "OTP 482913"}]
    monkeypatch.setattr(nt, "_fetch", lambda: items)
    monkeypatch.setattr(nt, "_settings", lambda: {"announce_apps": [], "poll_seconds": 1})
    monkeypatch.setattr(nt, "_primed", True)
    nt._seen.clear()
    lines = nt.poll_once(private=True)
    assert lines == ["New notification from WhatsApp."]
    with mock.patch.object(security, "pending", return_value=False), \
            mock.patch.object(security, "is_locked", return_value=True):
        assert nt._privacy() == "private"
    with mock.patch.object(security, "pending", return_value=True):
        assert nt._privacy() == "quiet"
    nt._seen.clear()


def test_u2_u3_y1_ai_blocked_when_locked_guest_or_pin(monkeypatch):
    import main

    class Sec:
        locked = guest = False

        def pending(self):
            return False

        def is_locked(self):
            return self.locked

        def is_guest(self):
            return self.guest

        spoken_digits = staticmethod(security.spoken_digits)

        def check(self, cmd):
            return "Guest mode is on, so I can't do that." if self.guest else None

        def cancel_pending(self):
            pass

    acts = type("A", (), {})()
    acts.security = Sec()
    from jarvis import nlu
    assert main._ai_blocked("what are my emails", None, nlu, acts) is None
    assert main._ai_blocked("my pin is one two three four unlock", None, nlu, acts)
    assert main._ai_blocked("unlock with 1234", None, nlu, acts)
    acts.security.guest = True
    assert "Guest mode" in main._ai_blocked("what are my emails", None, nlu, acts)
    acts.run = lambda c: "EMAILS"
    assert "Not allowed" in main.guarded_runner(acts)(nlu.Command("check_email", {}))
    from jarvis import actions as real
    assert "pin" not in real.CATALOG["jarvis_lock"]["properties"]


def test_y2_y3_setup_and_wake_guarded():
    from jarvis import brain
    assert "setup" in security.DEFAULT_PROTECT and "wake_sensitivity" in brain.GUARDED_ACTIONS


def test_v4_generic_score_words():
    from jarvis import nlu
    assert nlu.parse("score of the match").args.get("team") is None


def test_y2_first_pin_not_by_voice(monkeypatch):
    from jarvis.actions import onboarding

    monkeypatch.setitem(onboarding._io, "say", lambda t: None)
    monkeypatch.setitem(onboarding._io, "listen", lambda: None)
    monkeypatch.setitem(onboarding._io, "voice", True)
    monkeypatch.setattr(onboarding, "_has_pin", lambda: False)
    ran = []
    monkeypatch.setattr(onboarding, "run", lambda *a, **k: ran.append(k.get("parts")) or "ok")
    assert "on the laptop" in onboarding.setup({"part": "pin"})
    assert ran == []
    onboarding.setup({"part": "all"})
    assert "pin" not in ran[0]


def test_round7_module_fixes(tmp_path, monkeypatch):
    from jarvis import brain, nlu
    from jarvis.actions import documents, flashcards
    assert {"web_search", "email"} <= brain.GUARDED_ACTIONS
    assert {"contact_add", "contact_delete"} <= set(security.DEFAULT_PROTECT)
    # Z3: secret-looking names and files outside the user's folders are not read
    p = tmp_path / "passwords.txt"
    p.write_text("x")
    monkeypatch.setattr("jarvis.actions.fileops.inside_home", lambda q: True)
    assert "private" in documents.resolve(None, str(p))[1]
    monkeypatch.setattr("jarvis.actions.fileops.inside_home", lambda q: False)
    assert "own folders" in documents.resolve(None, str(tmp_path / "x.txt") if (tmp_path / "x.txt").write_text("y") else "")[1]
    # Z5
    assert nlu.parse("tell me when google.com is back").args == {"what": "website", "target": "google.com"}
    assert flashcards.parse("add a flashcard")[0] == "flashcard_add"


def test_z2_contact_change_asks(monkeypatch):
    from jarvis.actions import contacts
    monkeypatch.setattr(contacts, "all_contacts", lambda: {"mom": {"name": "Mom", "phone": "9876543210"}})
    q = contacts.change_text({"name": "mom", "phone": "9123451234"})
    assert q and "...3210" in q and "...1234" in q
    assert contacts.change_text({"name": "mom", "phone": "9876543210"}) is None
    assert contacts.change_text({"name": "ravi", "phone": "9123451234"}) is None


def test_round8_fixes(monkeypatch):
    from jarvis import brain, nlu
    from jarvis.actions import birthdays, recipes
    # E1: cook mode ends by itself after a quiet while, then says why once
    monkeypatch.setattr(recipes, "_active", True)
    monkeypatch.setattr(recipes, "_recipe", {"name": "x", "steps": ["a"]})
    monkeypatch.setattr(recipes, "_last_use", recipes.time.monotonic() - recipes.COOK_TIMEOUT - 5)
    assert recipes.match_cook("next") == ("cook", {"action": "timed_out"})
    assert not recipes.is_active()
    assert recipes.match_cook("next") is None  # only once; "next" is free again
    assert "ended" in recipes.cook({"action": "timed_out"})
    # E2, E5
    assert "accessibility" in brain.GUARDED_ACTIONS
    assert not {"recipe", "cook", "radio", "local_music", "track_report"} & set(brain.UNTRUSTED_INFO)
    # E3: no names while locked
    import datetime as dt
    said = []
    monkeypatch.setattr(birthdays, "_private", lambda: True)
    monkeypatch.setattr(birthdays, "_remind_at", lambda: dt.time(0, 0))
    monkeypatch.setattr(birthdays, "_alerted_on", None)
    monkeypatch.setattr(birthdays, "_load", lambda: {"last_alert": "", "entries": {}})
    monkeypatch.setattr(birthdays, "_save", lambda d: None)
    monkeypatch.setattr(birthdays, "notify", said.append, raising=False)
    monkeypatch.setattr(birthdays, "all_events", lambda: [{"name": "mom", "date": "03-12", "kind": "birthday"}])
    assert "Mom" in birthdays.check(dt.datetime(2026, 3, 12, 10, 0))
    assert said and "Mom" not in said[0]
    # E4
    assert nlu.parse("moms birthday is 12 march").args == {"name": "mom", "date": "12 march", "kind": "birthday"}
    assert nlu.parse("when is moms birthday").args == {"name": "mom", "kind": "birthday"}
    assert nlu.parse("play some local music").args == {"action": "play"}
    assert nlu.parse("play some arijit from my music").args == {"action": "play", "query": "arijit"}


def test_round9_module_fixes(monkeypatch):
    from jarvis.actions import devtools, documents, fileconvert, printer, recent
    from jarvis.actions.fileops import is_network_path
    # N1: network paths are refused before anything touches them
    for p in ("\\\\host\\share\\x.pdf", "//host/share/x.pdf", "\\\\?\\UNC\\host\\s\\x.pdf", "file://host/x.pdf"):
        assert is_network_path(p)
    for p in ("C:\\Users\\me\\a.pdf", "report.pdf", "", None):
        assert not is_network_path(p)
    assert fileconvert.find_by_name("\\\\host\\share\\x.pdf") is None
    with pytest.raises(fileconvert.ConvertError):
        fileconvert.resolve("\\\\host\\share\\x.pdf")
    with pytest.raises(printer.PrinterError):
        printer._stored_paths({"paths": ["\\\\host\\share\\x.pdf"]})
    assert documents.resolve(None, "\\\\host\\share\\x.pdf")[0] is None
    assert documents.resolve("//host/share/x.pdf")[0] is None
    # N2: push question names the branch and project
    monkeypatch.setattr(devtools, "projects", lambda: {"jarvis": {"path": "."}})
    monkeypatch.setattr(devtools, "_run", lambda *a, **k: (0, "main\n"))
    assert devtools.risky_text({"action": "git_push", "project": "jarvis"}) == "push branch main of jarvis to the remote"
    # N4
    assert {".chm", ".search-ms", ".svg", ".docm", ".xlsm", ".pptm"} <= recent.RUNNABLE


def test_round9_shared_fixes(monkeypatch):
    import importlib.util
    from jarvis import nlu
    from jarvis.brain import Brain
    # N1: the AI cannot pick the files or the printer
    b = Brain.__new__(Brain)
    b._intent_of = {"print_file": "print_file"}
    blk = mock.Mock(name="x", input={"name": "report", "paths": ["\\\\h\\s\\x.pdf"], "path": "y", "printer": "P"})
    blk.name = "print_file"
    assert b._command(blk).args == {"name": "report"}
    # N2
    assert {"dev:git_push", "dev:git_commit"} <= set(security.DEFAULT_PROTECT)
    # N3: one wrapper keeps background voices generic while locked
    spec = importlib.util.spec_from_file_location("jarvis_main_n3", os.path.join(os.path.dirname(__file__), "..", "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    said = []
    say = main._unlocked_say(said.append, "Recap ready.")
    monkeypatch.setattr(security, "is_locked", lambda: True)
    say("You spent 500 rupees")
    monkeypatch.setattr(security, "is_locked", lambda: False)
    monkeypatch.setattr(security, "is_guest", lambda: False)
    say("You spent 500 rupees")
    assert said == ["Recap ready.", "You spent 500 rupees"]
    # N5
    assert nlu.parse("whats in the print queue").intent == "print_queue"
    assert nlu.parse("close desktop").args == {"action": "close"}


def test_round10_fixes(monkeypatch):
    import importlib.util
    from jarvis import brain, nlu
    from jarvis.actions import generate, hotspot, multilang, voiceid
    # K1: PIN words in Hindi / Telugu are read on this PC
    for said in ("ek do teen chaar", "एक दो तीन चार", "ఒకటి రెండు మూడు నాలుగు", "१२३४"):
        assert security.spoken_digits(said) == "1234"
    # K1: a PIN or yes/no answer is never translated online
    monkeypatch.setattr(multilang, "record", lambda timeout=5: b"x" * 10)
    monkeypatch.setattr(multilang, "recognize", lambda audio: ("ek do teen chaar", "hi"))
    online = []
    monkeypatch.setattr(multilang, "_claude_english", lambda t, l: online.append(t) or "one two three four")
    monkeypatch.setattr(multilang, "_google_english", lambda t: online.append(t) or "x")
    multilang.private_next()
    assert multilang.listen() == "ek do teen chaar" and online == []
    monkeypatch.setattr(multilang, "recognize", lambda audio: ("haan", "hi"))
    with mock.patch.object(security, "pending", return_value=True):
        assert multilang.listen() == "yes" and online == []
    # K2: voice never replaces the PIN for the worst actions; 3 failed matches -> PIN only
    monkeypatch.setattr(voiceid, "is_on", lambda: True)
    for intent, args in (("software", {}), ("delete_file", {}), ("device", {"action": "unlock"}),
                         ("phone", {"action": "sms"}), ("dev", {"action": "git_push"}), ("voice_id", {"action": "off"})):
        assert not voiceid._voice_may_replace_pin(intent, args, security)
    voiceid.pin_ok()
    calls = []
    monkeypatch.setattr(voiceid, "verify", lambda pcm: calls.append(1) or (False, 0.4))
    for _ in range(3):
        assert not voiceid.owner_spoke()
    monkeypatch.setattr(voiceid, "verify", lambda pcm: calls.append(1) or (True, 0.9))
    assert not voiceid.owner_spoke() and len(calls) == 3  # locked out of voice until a right PIN
    voiceid.pin_ok()
    assert voiceid.owner_spoke()
    # K3: private replies are spoken in English
    monkeypatch.setattr(multilang, "reply_language", lambda: "hi")
    multilang.keep_english("Your OTP is 4821")
    with mock.patch("jarvis.actions.interpreter.translate") as tr:
        assert multilang.say_reply("Your OTP is 4821") is False
        tr.assert_not_called()
    spec = importlib.util.spec_from_file_location("jarvis_main_k3", os.path.join(os.path.dirname(__file__), "..", "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    assert {"check_email", "notifications", "read_clipboard", "generate", "hotspot", "recap"} <= main.PRIVATE_REPLIES
    # K4, K5
    assert {"hotspot", "display", "drives"} <= brain.GUARDED_ACTIONS
    assert {"hotspot:on", "hotspot:password", "webcam:photo"} <= set(security.DEFAULT_PROTECT)
    copied, cleared = [], []
    monkeypatch.setattr(generate, "_copy", lambda t: copied.append(t) or True)
    monkeypatch.setattr(generate, "_schedule_clear", lambda t, s: cleared.append(s))
    hotspot._copy("secret")
    assert copied == ["secret"] and cleared == [60]
    # K6
    assert nlu.parse("stop replying in hindi").args == {"action": "reply", "lang": "en"}
    assert nlu.parse("whats my hotspot password").args == {"action": "password"}
