"""Piece BU: owner voice check. All faked: no mic, no resemblyzer."""
import os
from types import SimpleNamespace as NS

import pytest

from jarvis.actions import security, voiceid

OWNER = [1.0, 0.0] + [0.0] * 30
STRANGER = [0.0, 1.0] + [0.0] * 30
SEC = voiceid.SAMPLE_RATE * 2  # bytes in one second
_REAL = (voiceid.embed, voiceid._get_encoder)  # before the autouse fakes


def _pcm(who: bytes, seconds: float = 2) -> bytes:
    return who * int(SEC * seconds)


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(security, "_now", lambda: clock["t"])
    monkeypatch.setattr(voiceid, "_now", lambda: clock["t"])
    monkeypatch.setattr(security, "ITERATIONS", 1000)
    security.reset()
    voiceid.reset()
    security.configure({"pin_file": str(tmp_path / "pin"), "protect": security.DEFAULT_PROTECT + voiceid.PROTECT})
    voiceid.configure({"file": str(tmp_path / "voiceid.json")})
    # b"O" audio = owner, anything else = stranger
    monkeypatch.setattr(voiceid, "embed", lambda pcm: OWNER if pcm[:1] == b"O" else STRANGER)
    monkeypatch.setattr(voiceid, "_get_encoder", lambda: object())
    said = []
    voiceid.set_io(said.append, voice=True)
    voiceid._record = lambda s: _pcm(b"O", s)
    yield NS(clock=clock, said=said, tmp=tmp_path)
    security.reset()
    voiceid.reset()


def _pin_ok():
    """Act as if security.check asked the PIN and it was right."""
    security.save_pin("1234")
    assert security.check("voice_id", {"action": "enrol"}) == "Say your PIN."
    assert security.verify("one two three four")[0]


def _enrol():
    _pin_ok()
    return voiceid.voice_id({"action": "enrol"})


class IO:
    def __init__(self, heard=None, no_ask=False):
        self.heard, self.said, self.no_ask = heard, [], no_ask

    def say(self, t):
        self.said.append(t)

    def listen(self):
        return self.heard


# ---------- enrolment ----------

def test_enrol_without_pin_never_sets_pin(setup):
    reply = voiceid.voice_id({"action": "enrol"})
    assert "set-pin" in reply
    assert not security.has_pin() and not voiceid.enrolled()


def test_enrol_needs_recent_pin(setup):
    security.save_pin("1234")
    assert "PIN" in voiceid.voice_id({"action": "enrol"})
    assert not voiceid.enrolled()


def test_enrol_pin_expires(setup):
    _pin_ok()
    setup.clock["t"] += security.AUTH_SECONDS + 1
    assert not voiceid.enrolled() and "PIN" in voiceid.voice_id({"action": "enrol"})


def test_enrol_saves_print_and_turns_lock_on(setup):
    assert "voice lock is on" in _enrol()
    assert voiceid.enrolled() and voiceid.is_on()
    assert sum("Sentence" in s for s in setup.said) == 5
    if os.name != "nt":
        assert oct(os.stat(setup.tmp / "voiceid.json").st_mode)[-3:] == "600"


def test_enrol_mixed_voices_refused(setup):
    n = {"i": 0}

    def rec(s):
        n["i"] += 1
        return _pcm(b"O" if n["i"] % 2 else b"S", s)
    voiceid._record = rec
    assert "didn't match" in _enrol()
    assert not voiceid.enrolled()


def test_enrol_text_mode_and_missing_package(setup, monkeypatch):
    voiceid.set_io(print, voice=False)
    assert "microphone" in _enrol()

    voiceid.set_io(print, voice=True)

    def missing():
        raise ImportError
    monkeypatch.setattr(voiceid, "_get_encoder", missing)
    security.cancel_pending()
    assert security.check("voice_id", {"action": "enrol"}) == "Say your PIN."
    security.verify("1234")
    assert "resemblyzer" in voiceid.voice_id({"action": "enrol"})


def test_short_recording(setup):
    voiceid._record = lambda s: b"O" * 100
    assert "couldn't record" in _enrol()


def test_enrol_is_protected_by_default_list():
    assert set(voiceid.PROTECT) == {"voice_id:enrol", "voice_id:off", "voice_id:forget"}


# ---------- check / verify ----------

def test_who_am_i(setup):
    assert "learn my voice" in voiceid.voice_id({"action": "check"})
    _enrol()
    voiceid.remember_audio(_pcm(b"O"))
    assert voiceid.voice_id({"action": "check"}) == "You sound like my owner."
    voiceid.remember_audio(_pcm(b"S"))
    assert voiceid.voice_id({"action": "check"}) == "I don't know this voice."
    voiceid.clear_audio()
    assert "by voice" in voiceid.voice_id({"action": "check"})


def test_old_audio_not_trusted(setup):
    _enrol()
    voiceid.remember_audio(_pcm(b"O"))
    setup.clock["t"] += voiceid.AUDIO_SECONDS + 1
    assert not voiceid.owner_spoke()


def test_verify_short_and_threshold(setup):
    _enrol()
    assert voiceid.verify(b"O" * 100) == (False, 0.0)
    assert voiceid.verify(_pcm(b"O"))[0]
    assert voiceid.similarity([1, 0], [0, 1]) == 0.0
    assert voiceid.similarity([1, 0], [1]) == 0.0


def test_bad_threshold_is_ignored(setup):
    voiceid.configure({"threshold": 0.1})
    assert voiceid._cfg()["threshold"] == voiceid.DEFAULT_THRESHOLD
    voiceid.configure({"threshold": "x"})
    assert voiceid._cfg()["threshold"] == voiceid.DEFAULT_THRESHOLD


def test_broken_print_file(setup):
    (setup.tmp / "voiceid.json").write_text("{not json")
    assert not voiceid.enrolled()
    assert voiceid.verify(_pcm(b"O")) == (False, 0.0)


# ---------- lock on / off ----------

def test_lock_on_needs_print_and_pin(setup):
    assert "learn my voice" in voiceid.voice_id({"action": "on"})
    _enrol()
    voiceid.voice_id({"action": "on"})
    assert voiceid.is_on()


def test_lock_off_needs_voice_or_pin(setup):
    _enrol()
    setup.clock["t"] += 60
    voiceid.remember_audio(_pcm(b"S"))
    assert "needs your voice or your PIN" in voiceid.voice_id({"action": "off"})
    assert voiceid.is_on()
    voiceid.remember_audio(_pcm(b"O"))
    assert voiceid.owner_spoke()
    assert voiceid.voice_id({"action": "off"}) == "Voice lock is off."
    assert "already off" in voiceid.voice_id({"action": "off"})


# ---------- forget (risky) ----------

def test_forget_needs_confirm(setup):
    assert voiceid.risky_text({"action": "forget"}) is None  # nothing to forget
    _enrol()
    assert voiceid.needs_confirm({"action": "forget"})
    assert "voice print" in voiceid.risky_text({"action": "forget"})
    assert "Say yes" in voiceid.voice_id({"action": "forget"})
    assert voiceid.enrolled()
    assert "forgot" in voiceid.voice_id({"action": "forget", "confirm": True})
    assert not voiceid.enrolled() and not voiceid.is_on()
    assert "don't have" in voiceid.voice_id({"action": "forget"})


# ---------- guard (main.py hook) ----------

def _cmd(intent, **args):
    return NS(intent=intent, args=args)


def _ready(setup):
    _enrol()
    setup.clock["t"] += 60  # PIN window over


def test_guard_owner_voice_replaces_pin(setup):
    _ready(setup)
    voiceid.remember_audio(_pcm(b"O"))
    io = IO()
    assert voiceid.guard(_cmd("shutdown"), io, security) is None
    assert io.said == [] and not security.pending()


def test_guard_stranger_falls_back_to_pin(setup):
    _ready(setup)
    voiceid.remember_audio(_pcm(b"S"))
    io = IO(heard="9999")
    assert "Wrong PIN" in voiceid.guard(_cmd("shutdown"), io, security)
    io = IO(heard="1234")
    assert voiceid.guard(_cmd("shutdown"), io, security) is None
    assert io.said == ["Say your PIN."]


def test_guard_lock_off_means_normal_pin(setup):
    _ready(setup)
    voiceid._lock_on = False
    voiceid.remember_audio(_pcm(b"O"))
    io = IO(heard="1234")
    assert voiceid.guard(_cmd("shutdown"), io, security) is None
    assert io.said == ["Say your PIN."]  # voice not used when lock is off


def test_guard_voice_never_unlocks_or_enrols(setup):
    _ready(setup)
    voiceid.remember_audio(_pcm(b"O"))
    for cmd in (_cmd("voice_id", action="enrol"), _cmd("setup")):
        io = IO(heard=None)
        assert voiceid.guard(cmd, io, security)  # PIN asked, none heard -> refused
        assert io.said == ["Say your PIN."]
    security.jarvis_lock({"state": "on"})
    io = IO(heard=None)
    assert voiceid.guard(_cmd("time"), io, security)
    assert security.is_locked()


def test_guard_guest_and_lockout_still_win(setup):
    _ready(setup)
    security.guest_mode({"state": "on"})
    voiceid.remember_audio(_pcm(b"O"))
    io = IO()
    assert "Guest mode" in voiceid.guard(_cmd("shutdown"), io, security)
    assert io.said == []


def test_guard_risky_unprotected_needs_voice(setup, monkeypatch):
    _ready(setup)
    cmd = _cmd("phone", action="sms")
    monkeypatch.setattr(security, "_cfg", lambda: dict(security._settings, protect=[]))
    voiceid.remember_audio(_pcm(b"O"))
    assert voiceid.guard(cmd, IO(), security, risky=True) is None
    voiceid.remember_audio(_pcm(b"S"))
    # no ask_pin in security.py (or no PIN set) -> refused
    monkeypatch.delattr(security, "ask_pin", raising=False)
    assert voiceid.guard(cmd, IO(), security, risky=True) == "That needs the owner's voice."

    def ask_pin():
        security._pending_until = security._now() + 30
        return "Say your PIN."
    monkeypatch.setattr(security, "ask_pin", ask_pin, raising=False)
    io = IO(heard="1234")
    assert voiceid.guard(cmd, io, security, risky=True) is None
    assert io.said == ["I don't know this voice. Say your PIN."]
    # not risky -> no voice check
    assert voiceid.guard(_cmd("time"), IO(), security) is None


def test_guard_background_never_asks(setup):
    _ready(setup)
    voiceid.remember_audio(_pcm(b"O"))
    io = IO(no_ask=True)
    assert voiceid.guard(_cmd("shutdown"), io, security) == "Say your PIN."
    assert io.said == [] and not security.pending()


def test_guard_no_pin_no_voice_lock(setup):
    assert voiceid.guard(_cmd("shutdown"), IO(), security) is None  # same as security.py today
    assert voiceid.guard(_cmd("x"), IO(), None) is None


def test_catalog_shape():
    spec = voiceid.CATALOG["voice_id"]
    assert set(spec["properties"]["action"]["enum"]) >= {"enrol", "check", "forget", "on", "off"}
    assert voiceid.HANDLERS["voice_id"] is voiceid.voice_id
    assert "unknown" not in voiceid.voice_id({"action": "dance"})


def test_embed_uses_resemblyzer_on_16k_floats(monkeypatch):
    np = pytest.importorskip("numpy")
    import sys
    import types
    seen = {}

    class Enc:
        def __init__(self, *a, **k):
            pass

        def embed_utterance(self, wav):
            seen["wav"] = wav
            return np.array([0.6, 0.8], dtype=np.float32)
    fake = types.ModuleType("resemblyzer")
    fake.VoiceEncoder = Enc
    fake.preprocess_wav = lambda wav, source_sr: (seen.update(sr=source_sr), wav)[1]
    monkeypatch.setitem(sys.modules, "resemblyzer", fake)
    monkeypatch.setattr(voiceid, "_get_encoder", _REAL[1])
    voiceid.reset()
    out = _REAL[0](np.array([16384, -16384, 0], dtype=np.int16).tobytes() + b"x")
    assert out == pytest.approx([0.6, 0.8])
    assert seen["sr"] == 16000 and list(seen["wav"]) == [0.5, -0.5, 0.0]
