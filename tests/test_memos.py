"""Voice memos (piece Q). Fake mic, temp folder, no real audio."""
import array
import os
import sys
import threading
import wave
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import memos  # noqa: E402

LOUD = array.array("h", [3000, -3000] * 1000).tobytes()  # one 0.125 s chunk
QUIET = bytes(4000)


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(memos, "SETTINGS", {
        "folder": str(tmp_path / "memos"), "start_delay": 0, "play_delay": 0,
        "silence_seconds": 0.5, "no_speech_seconds": 1, "max_seconds": 3,
    })
    said = []
    memos.set_notifier(said.append)
    played = []
    monkeypatch.setattr(memos, "_play_file", played.append)
    monkeypatch.setattr(memos, "_delete_file", lambda p, trash=True: Path(p).unlink())
    monkeypatch.setattr(memos, "_stop_playing", lambda: False)
    yield {"said": said, "played": played, "folder": tmp_path / "memos"}
    memos.stop_recording()
    memos.set_notifier(None)


class FakeMic:
    def __init__(self, chunks, then=QUIET, block=None):
        self.chunks, self.then, self.block = list(chunks), then, block
        self.closed = False

    def __call__(self):
        def gen():
            try:
                for c in self.chunks:
                    yield c
                while True:
                    if self.block is not None:
                        self.block.wait(0.01)
                    yield self.then
            finally:
                self.closed = True
        return gen()


def wait_done(timeout=5):
    if memos._thread:
        memos._thread.join(timeout)
    assert not memos.is_recording()


def make_memo(folder, dt, seconds=2.0):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / dt.strftime("memo-%Y%m%d-%H%M%S.wav")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(int(seconds * 16000) * 2))
    return p


def test_record_stops_on_silence_and_saves(setup, monkeypatch):
    mic = FakeMic([LOUD] * 8)  # 1 s of talk, then quiet
    monkeypatch.setattr(memos, "_mic_chunks", mic)
    assert memos.memo({"action": "record"}).startswith("Recording")
    wait_done()
    assert mic.closed  # mic released
    files = list(setup["folder"].glob("*.wav"))
    assert len(files) == 1
    assert 1.4 <= memos._seconds(files[0]) <= 1.7
    assert setup["said"] == ["Memo saved, 2 seconds."]


def test_record_nothing_said_discards(setup, monkeypatch):
    monkeypatch.setattr(memos, "_mic_chunks", FakeMic([]))
    memos.memo({"action": "record"})
    wait_done()
    assert list(setup["folder"].glob("*.wav")) == []
    assert "didn't hear anything" in setup["said"][0]


def test_record_max_seconds(setup, monkeypatch):
    monkeypatch.setattr(memos, "_mic_chunks", FakeMic([], then=LOUD))
    memos.memo({"action": "record"})
    wait_done()
    f = list(setup["folder"].glob("*.wav"))[0]
    assert abs(memos._seconds(f) - 3.0) < 0.2


def test_stop_command_and_is_recording(setup, monkeypatch):
    block = threading.Event()
    monkeypatch.setattr(memos, "_mic_chunks", FakeMic([LOUD] * 2, then=LOUD, block=block))
    memos.memo({"action": "record"})
    assert memos.is_recording()
    assert memos.memo({"action": "record"}) == "I'm already recording a memo."
    assert "recording" in memos.memo({"action": "play"})
    reply = memos.memo({"action": "stop"})
    assert reply.startswith("Memo saved")
    assert not memos.is_recording()
    assert setup["said"] == []  # reply already said it, no double message
    assert memos.memo({"action": "stop"}) == "I'm not recording a memo."


def test_begin_starts_early(setup, monkeypatch):
    memos.SETTINGS["start_delay"] = 30
    monkeypatch.setattr(memos, "_mic_chunks", FakeMic([LOUD] * 2))
    memos.memo({"action": "record"})
    memos.begin()
    wait_done()
    assert len(list(setup["folder"].glob("*.wav"))) == 1


def test_stop_during_delay_cancels(setup, monkeypatch):
    memos.SETTINGS["start_delay"] = 30
    mic = FakeMic([LOUD])
    monkeypatch.setattr(memos, "_mic_chunks", mic)
    memos.memo({"action": "record"})
    assert memos.memo({"action": "stop"}) == "Memo cancelled."
    assert not mic.closed  # mic never opened


def test_mic_error(setup, monkeypatch):
    def broken():
        raise OSError("no mic")
    monkeypatch.setattr(memos, "_mic_chunks", broken)
    memos.memo({"action": "record"})
    wait_done()
    assert "microphone" in setup["said"][0]
    assert list(setup["folder"].glob("*.wav")) == []


def test_list(setup):
    assert memos.memo({"action": "list"}) == "You have no voice memos."
    now = datetime.now().replace(microsecond=0)
    make_memo(setup["folder"], now - timedelta(days=1), 65)
    make_memo(setup["folder"], now, 12)
    r = memos.memo({"action": "list"})
    assert r.startswith("You have 2 voice memos. 1: today at")
    assert "12 seconds" in r and "2: yesterday at" in r and "1 minute 5 seconds" in r


def test_play_pick(setup):
    now = datetime.now().replace(microsecond=0)
    old = make_memo(setup["folder"], now - timedelta(hours=2))
    new = make_memo(setup["folder"], now)
    assert memos.memo({"action": "play"}).startswith("Playing your memo from today")
    assert memos.memo({"action": "play", "which": "first"})
    assert memos.memo({"action": "play", "which": "memo 2"})
    import time
    time.sleep(0.2)  # timers
    assert setup["played"] == [new, old, old]
    assert "couldn't find" in memos.memo({"action": "play", "which": "seventh"})


def test_pick_words():
    files = ["a", "b", "c"]
    assert memos._pick(None, files) == "a"
    assert memos._pick("the last one", files) == "a"
    assert memos._pick("previous", files) == "b"
    assert memos._pick("oldest", files) == "c"
    assert memos._pick("number three", files) == "c"
    assert memos._pick("2", files) == "b"
    assert memos._pick("9", files) is None
    assert memos._pick("last", []) is None


def test_delete_needs_confirm(setup):
    p = make_memo(setup["folder"], datetime.now())
    q = memos.memo({"action": "delete"})
    assert q.startswith("Are you sure you want to delete your memo from today")
    assert p.exists()
    assert memos.needs_confirm({"action": "delete"})
    assert not memos.needs_confirm({"action": "play"})
    assert memos.risky_text({"action": "delete"}).startswith("delete your memo from today")
    assert memos.risky_text({"action": "list"}) is None
    assert memos.memo({"action": "delete", "confirm": True}).startswith("Deleted")
    assert not p.exists()
    assert memos.memo({"action": "delete", "confirm": True}) == "You have no voice memos."


def test_say_helpers():
    now = datetime(2026, 11, 7, 15, 5)
    assert memos._say_when(datetime(2026, 11, 7, 9, 0), now) == "today at 9:00 AM"
    assert memos._say_when(datetime(2026, 11, 6, 21, 30), now) == "yesterday at 9:30 PM"
    assert memos._say_when(datetime(2026, 11, 2, 8, 0), now) == "November 2 at 8:00 AM"
    assert memos._say_len(1) == "1 second"
    assert memos._say_len(120) == "2 minutes"


def test_level():
    assert memos._level(QUIET) == 0
    assert memos._level(LOUD) == 3000


def test_catalog_matches_handlers():
    assert set(memos.CATALOG) == set(memos.HANDLERS) == {"memo"}
    assert memos.memo({"action": "dance"}).startswith("I can record")


def test_delete_after_yes_uses_the_memo_that_was_named(setup):
    from datetime import timedelta

    old = make_memo(setup["folder"], datetime.now() - timedelta(hours=1))
    args = {"action": "delete"}
    memos.risky_text(args)  # "are you sure you want to delete <old>?"
    new = make_memo(setup["folder"], datetime.now())  # a new memo is saved before the user says yes
    memos.memo({**args, "confirm": True})
    assert not old.exists() and new.exists()
