"""Small tests for REVIEW.md fixes (L items, M2, M7, M8). OS calls are faked."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis import calc, stt  # noqa: E402
from jarvis.actions import desktop, dictation, fileops, network  # noqa: E402
from jarvis.actions.inputs import parse_keys  # noqa: E402


def test_huge_maths_is_refused_fast():
    with pytest.raises(ValueError):
        calc.evaluate("((9**99)**99)**99")


def test_f_zero_does_not_crash():
    assert parse_keys("f zero") is None


def test_ping_rejects_option_like_hosts():
    with mock.patch.object(network, "_run") as run:
        assert network.ping("-t google.com") == (None, 0, 4)
        run.assert_not_called()


def test_locate_cache_keeps_only_hits(monkeypatch, tmp_path):
    found = {"p": None}
    monkeypatch.setattr(fileops, "locate", lambda name: found["p"])
    fileops._cache.clear()
    assert fileops.locate_cached("new.txt") is None
    f = tmp_path / "new.txt"
    f.write_text("x")
    found["p"] = f
    assert fileops.locate_cached("new.txt") == f  # not the cached "not found"


def test_selected_text_skips_terminals(monkeypatch):
    monkeypatch.setattr(desktop, "_foreground_is_console", lambda: True)
    assert "terminal" in desktop.get_selected_text({})


def test_dictation_new_line_uses_shift_enter(monkeypatch):
    calls = []
    fake_pg = mock.Mock(hotkey=lambda *k: calls.append(k))
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pg)
    with mock.patch("jarvis.actions.keyboard.type_text", lambda t: calls.append(t)):
        dictation._Keys().type("hi\nthere")
    assert calls == ["hi", ("shift", "enter"), "there"]


def test_common_words_do_not_wake():
    assert "service" not in stt.SOUND_ALIKES["jarvis"] and "harvest" not in stt.SOUND_ALIKES["jarvis"]
