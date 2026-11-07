"""Piece AE: voice PIN, lock Jarvis, guest mode. Time is faked; the PIN file is in tmp_path."""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import security as s  # noqa: E402
from jarvis.nlu import Command  # noqa: E402

PIN = "4821"


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(s, "_now", c)
    return c


@pytest.fixture
def sec(tmp_path, clock, monkeypatch):
    """Security set up with a PIN (fast hash for tests)."""
    s.reset()
    real = s.hash_pin
    monkeypatch.setattr(s, "hash_pin", lambda pin, salt=None, iterations=1000: real(pin, salt, iterations))
    s.configure({"pin_file": str(tmp_path / "pin")})
    s.save_pin(PIN)
    yield s
    s.reset()


def ask_and_answer(intent, spoken, args=None):
    msg = s.check(intent, args or {})
    assert msg and msg.endswith("Say your PIN.")
    assert s.pending()
    return s.verify(spoken)


# ---------- hashing ----------

def test_pin_is_stored_hashed_never_plain(sec, tmp_path):
    text = (tmp_path / "pin").read_text()
    assert PIN not in text
    assert text.startswith("pbkdf2_sha256$")
    assert s.has_pin()


def test_hash_has_random_salt_and_checks():
    a, b = s.hash_pin("1234", iterations=1000), s.hash_pin("1234", iterations=1000)
    assert a != b
    assert s._check_hash("1234", a) and not s._check_hash("1235", a)
    assert not s._check_hash("1234", "garbage")


def test_save_pin_rejects_bad_pins(sec):
    for bad in ("12", "abcd", "1" * 13):
        with pytest.raises(ValueError):
            s.save_pin(bad)


def test_pin_hash_in_config_wins(tmp_path, clock):
    s.reset()
    s.configure({"pin_hash": s.hash_pin("9999", iterations=1000), "pin_file": str(tmp_path / "none")})
    assert ask_and_answer("shutdown", "nine nine nine nine")[0]
    s.reset()


def test_plain_pin_in_config_is_ignored(tmp_path, clock, caplog):
    s.reset()
    with caplog.at_level(logging.WARNING):
        s.configure({"pin": "1234", "pin_file": str(tmp_path / "none")})
    assert not s.has_pin()
    assert "ignored" in caplog.text and "1234" not in caplog.text
    s.reset()


# ---------- spoken digits ----------

@pytest.mark.parametrize("spoken,digits", [
    ("one two three four", "1234"),
    ("1234", "1234"),
    ("12 34", "1234"),
    ("my pin is four eight two one", "4821"),
    ("oh four for to", "0442"),
    ("double five six seven", "5567"),
    ("triple nine one", "9991"),
    ("", ""),
    (None, ""),
])
def test_spoken_digits(spoken, digits):
    assert s.spoken_digits(spoken) == digits


def test_redact_hides_pin_like_runs(sec):
    assert "4821" not in s.redact("unlock jarvis 4821")
    assert "four" not in s.redact("unlock jarvis four eight two one")
    assert s.redact("open chrome") == "open chrome"
    s.check("shutdown")
    assert s.redact("anything") == "<PIN hidden>"


# ---------- no PIN set ----------

def test_no_pin_means_everything_runs(tmp_path, clock):
    s.reset()
    s.configure({"pin_file": str(tmp_path / "none")})
    assert s.check("shutdown") is None
    assert "Set a PIN" in s.jarvis_lock({"state": "on"})
    assert "Set a PIN" in s.guest_mode({"state": "on"})
    assert not s.is_locked() and not s.is_guest()
    s.reset()


# ---------- protected intents ----------

def test_safe_intent_runs_without_pin(sec):
    assert s.check("time") is None
    assert s.check(Command("open_app", {"name": "chrome"})) is None


def test_protected_intent_needs_pin(sec):
    ok, reply = ask_and_answer("shutdown", "four eight two one")
    assert ok and reply == "PIN accepted."
    assert not s.pending()


def test_command_object_and_sub_action(sec):
    assert s.check(Command("history", {"action": "list"})) is None
    assert s.check(Command("history", {"action": "clear"})) == "Say your PIN."


def test_wrong_pin_counts_and_locks_out(sec, clock):
    assert ask_and_answer("shutdown", "1111") == (False, "Wrong PIN. 2 tries left.")
    assert ask_and_answer("shutdown", "2222") == (False, "Wrong PIN. 1 try left.")
    ok, reply = ask_and_answer("shutdown", "3333")
    assert not ok and "5 minutes" in reply
    # locked out: protected intents blocked, no PIN prompt; simple ones still work
    msg = s.check("shutdown")
    assert "Too many wrong PINs" in msg and not s.pending()
    assert s.check("time") is None
    clock.t += 5 * 60 + 1
    assert ask_and_answer("shutdown", PIN)[0]


def test_right_pin_resets_wrong_count(sec):
    ask_and_answer("shutdown", "1111")
    ask_and_answer("shutdown", "2222")
    assert ask_and_answer("shutdown", PIN)[0]
    assert ask_and_answer("shutdown", "1111")[1] == "Wrong PIN. 2 tries left."


def test_verify_without_prompt_or_silence(sec, clock):
    assert s.verify(PIN) == (False, "I wasn't waiting for a PIN.")
    s.check("shutdown")
    assert s.verify(None) == (False, "I didn't hear a PIN. Cancelled.")
    s.check("shutdown")
    clock.t += s.PENDING_SECONDS + 1
    assert not s.verify(PIN)[0]


def test_silence_does_not_count_as_wrong(sec):
    s.check("shutdown")
    s.verify("")
    assert ask_and_answer("shutdown", "1111")[1] == "Wrong PIN. 2 tries left."


def test_grace_seconds(tmp_path, clock, sec):
    s.configure({"pin_file": str(tmp_path / "pin"), "grace_seconds": 60})
    assert ask_and_answer("shutdown", PIN)[0]
    assert s.check("restart") is None
    clock.t += 61
    assert s.check("restart") == "Say your PIN."


def test_custom_protect_list(tmp_path, sec):
    s.configure({"pin_file": str(tmp_path / "pin"), "protect": ["open_app"]})
    assert s.check("open_app") == "Say your PIN."
    assert s.check("shutdown") is None


def test_pin_never_logged(sec, caplog):
    with caplog.at_level(logging.DEBUG, logger="jarvis.security"):
        ask_and_answer("shutdown", "1111")
        ask_and_answer("shutdown", PIN)
        s.jarvis_lock({"state": "on"})
        s.jarvis_lock({"state": "off", "pin": PIN})
    assert PIN not in caplog.text and "1111" not in caplog.text


# ---------- lock Jarvis ----------

def test_lock_blocks_everything_until_pin(sec):
    assert "locked" in s.jarvis_lock({"state": "on"})
    assert s.is_locked()
    msg = s.check("time")
    assert msg == "Jarvis is locked. Say your PIN."
    ok, _ = s.verify("four eight two one")
    assert ok and not s.is_locked()
    assert s.check("time") is None


def test_unlock_by_voice_flow(sec):
    s.jarvis_lock({"state": "on"})
    assert s.check("jarvis_lock", {"state": "off"}) == "Jarvis is locked. Say your PIN."
    assert s.verify(PIN)[0]
    assert s.jarvis_lock({"state": "off"}) == "Jarvis is unlocked."


def test_unlock_with_pin_in_sentence(sec):
    s.jarvis_lock({"state": "on"})
    assert s.check("jarvis_lock", {"state": "off", "pin": "4821"}) is None
    assert s.jarvis_lock({"state": "off", "pin": "1111"}).startswith("Wrong PIN")
    assert s.is_locked()
    assert s.jarvis_lock({"state": "off", "pin": "four eight two one"}) == "Jarvis is unlocked."
    assert not s.is_locked()


def test_unlock_handler_without_pin_stays_locked(sec):
    """The AI brain could call jarvis_lock off directly: it must not unlock."""
    s.jarvis_lock({"state": "on"})
    assert "PIN" in s.jarvis_lock({"state": "off"})
    assert s.is_locked()


def test_locked_and_locked_out(sec):
    s.jarvis_lock({"state": "on"})
    for wrong in ("1111", "2222", "3333"):
        s.check("time")
        s.verify(wrong)
    msg = s.check("time")
    assert "Too many wrong PINs" in msg and not s.pending()
    assert "blocked" in s.jarvis_lock({"state": "off", "pin": PIN})
    assert s.is_locked()


def test_lock_status(sec):
    assert s.jarvis_lock({"state": "status"}) == "Jarvis is not locked."
    s.jarvis_lock({"state": "on"})
    assert s.jarvis_lock({"state": "status"}) == "Jarvis is locked."


# ---------- guest mode ----------

def test_guest_mode_only_safe_intents(sec):
    assert "on" in s.guest_mode({"state": "on"})
    assert s.check("time") is None
    assert s.check("weather") is None
    assert s.check("confirm") is None
    msg = s.check("open_app")
    assert "Guest mode" in msg and not s.pending()
    assert "Guest mode" in s.check("shutdown")  # blocked, no PIN prompt


def test_guest_mode_off_needs_pin(sec):
    s.guest_mode({"state": "on"})
    assert "needs your PIN" in s.guest_mode({"state": "off"})  # AI calling it directly
    assert s.is_guest()
    assert s.check("guest_mode", {"state": "off"}) == "Say your PIN."
    assert s.verify("1111")[0] is False
    assert s.is_guest()
    s.check("guest_mode", {"state": "off"})
    assert s.verify(PIN)[0]
    assert s.guest_mode({"state": "off"}) == "Guest mode is off."
    assert s.check("open_app") is None


def test_guest_auth_expires(sec, clock):
    s.guest_mode({"state": "on"})
    s.check("guest_mode", {"state": "off"})
    s.verify(PIN)
    clock.t += s.AUTH_SECONDS + 1
    assert "needs your PIN" in s.guest_mode({"state": "off"})


def test_guest_mode_already_off_and_status(sec):
    assert s.check("guest_mode", {"state": "off"}) is None
    assert s.guest_mode({"state": "off"}) == "Guest mode is already off."
    assert s.guest_mode({"state": "status"}) == "Guest mode is off."


def test_custom_guest_list(tmp_path, sec):
    s.configure({"pin_file": str(tmp_path / "pin"), "guest_mode_intents": ["open_app"]})
    s.guest_mode({"state": "on"})
    assert s.check("open_app") is None
    assert "Guest mode" in s.check("time")


# ---------- catalog ----------

def test_catalog_matches_handlers():
    assert set(s.CATALOG) == set(s.HANDLERS) == {"jarvis_lock", "guest_mode"}
    for spec in s.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])
