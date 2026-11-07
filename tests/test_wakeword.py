"""Piece AQ: wake word engine + sensitivity. Mic, model and config are faked."""
import json
import sys
import types

import numpy as np
import pytest

from jarvis.actions import wakeword as ww


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = {"wake_word": "jarvis", "wake_file": str(tmp_path / "wake.json"), "stt": {}}
    monkeypatch.setattr(ww, "_config", lambda: c)
    return c


class FakeModel:
    def __init__(self, scores):
        self.scores = list(scores)
        self.frames = []
        self.resets = 0

    def predict(self, frame):
        self.frames.append(frame)
        return {"hey_jarvis": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


def mic(n_chunks=20, size=2000):
    def gen():
        for _ in range(n_chunks):
            yield b"\x00\x00" * size
    return gen


# ---------- catalog ----------

def test_catalog_and_handlers():
    assert set(ww.CATALOG) == set(ww.HANDLERS) == {"wake_sensitivity"}
    props = ww.CATALOG["wake_sensitivity"]["properties"]
    assert props["change"]["enum"] == ["up", "down"]
    assert ww.CATALOG["wake_sensitivity"]["required"] == []


# ---------- levels ----------

@pytest.mark.parametrize("raw,want", [(0.6, 0.6), (6, 0.6), (60, 0.6), ("70%", 0.7), ("0.3", 0.3),
                                      (0, 0.1), (1, 0.9), (100, 0.9), (0.05, 0.1)])
def test_as_level(raw, want):
    assert ww._as_level(raw) == want


@pytest.mark.parametrize("raw", ["loud", None, -3])
def test_as_level_bad(raw):
    assert ww._as_level(raw) is None


def test_threshold_goes_down_when_more_sensitive():
    assert ww.threshold(0.5) == 0.5
    assert ww.threshold(0.8) == 0.2
    assert ww.threshold(0.99) == 0.1  # clamped


def test_sensitivity_sources(cfg, tmp_path):
    assert ww.sensitivity() == 0.5
    cfg["stt"]["wake_sensitivity"] = 0.7
    assert ww.sensitivity() == 0.7
    (tmp_path / "wake.json").write_text(json.dumps({"sensitivity": 0.3}))
    assert ww.sensitivity() == 0.3  # wake.json wins
    (tmp_path / "wake.json").write_text("not json")
    assert ww.sensitivity() == 0.7


@pytest.mark.parametrize("val,want", [("openwakeword", "openwakeword"), ("OpenWakeWord", "openwakeword"),
                                      ("open_wake_word", "openwakeword"), ("oww", "openwakeword"),
                                      ("vosk", "vosk"), ("", "vosk"), ("other", "vosk")])
def test_engine_name(cfg, val, want):
    cfg["stt"]["wake_engine"] = val
    assert ww.engine_name() == want


# ---------- intent ----------

def test_ask_current(cfg):
    out = ww.wake_sensitivity({})
    assert "50 percent" in out and "vosk" in out


def test_up_down_saves_to_wake_json(cfg, tmp_path):
    cfg["stt"]["wake_engine"] = "openwakeword"
    assert ww.wake_sensitivity({"change": "up"}) == "Wake word sensitivity is now 60 percent."
    assert json.loads((tmp_path / "wake.json").read_text())["sensitivity"] == 0.6
    ww.wake_sensitivity({"change": "down"})
    ww.wake_sensitivity({"change": "down"})
    assert ww.sensitivity() == 0.4


def test_value(cfg):
    cfg["stt"]["wake_engine"] = "openwakeword"
    assert "80 percent" in ww.wake_sensitivity({"value": 8})
    assert "30 percent" in ww.wake_sensitivity({"value": "30%"})
    assert "level from 1 to 9" in ww.wake_sensitivity({"value": "very"})


def test_limits(cfg):
    cfg["stt"]["wake_engine"] = "openwakeword"
    ww.wake_sensitivity({"value": 0.9})
    assert "already at the most sensitive" in ww.wake_sensitivity({"change": "up"})
    ww.wake_sensitivity({"value": 0.1})
    assert "already at the least sensitive" in ww.wake_sensitivity({"change": "down"})


def test_vosk_note(cfg):
    out = ww.wake_sensitivity({"change": "up"})
    assert "60 percent" in out and "openWakeWord engine" in out


def test_save_error(cfg, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ww, "_save_state", boom)
    assert "couldn't save" in ww.wake_sensitivity({"change": "up"})


# ---------- openWakeWord loop ----------

def test_frames_recut():
    frames = list(ww._frames(iter([b"\x01\x00" * 2000, b"\x01\x00" * 2000])))
    assert len(frames) == 3  # 4000 samples -> 3 full 1280 frames
    assert all(f.shape == (1280,) and f.dtype == np.int16 for f in frames)


def test_wait_oww_wakes_over_threshold():
    m = FakeModel([0.1, 0.4, 0.55, 0.9])
    score = ww.wait_oww(m, 0.5, mic_chunks=mic())
    assert score == 0.55
    assert len(m.frames) == 3
    assert m.resets == 2  # before and after


def test_wait_oww_more_sensitive_wakes_sooner():
    m = FakeModel([0.1, 0.4, 0.55])
    assert ww.wait_oww(m, 0.6, mic_chunks=mic()) == 0.4


def test_wait_oww_closes_mic():
    closed = []

    def chunks():
        try:
            while True:
                yield b"\x00\x00" * 2000
        finally:
            closed.append(True)

    ww.wait_oww(FakeModel([0.0, 0.95]), 0.5, mic_chunks=chunks)
    assert closed == [True]


def test_wait_oww_mic_end_is_an_error_not_a_wake():
    with pytest.raises(ww.MicStreamEnded):
        ww.wait_oww(FakeModel([]), 0.5, mic_chunks=mic(n_chunks=2))


# ---------- choose ----------

@pytest.fixture
def vosk_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(ww, "_vosk_wait", lambda word: calls.append(word))
    return calls


def test_choose_vosk_default(cfg, vosk_calls):
    name, fn = ww.choose(cfg)
    assert name == "vosk"
    fn()
    assert vosk_calls == ["jarvis"]


def test_choose_oww_missing_package_falls_back(cfg, vosk_calls, monkeypatch):
    cfg["stt"]["wake_engine"] = "openwakeword"
    monkeypatch.setitem(sys.modules, "openwakeword", None)  # import fails
    name, fn = ww.choose(cfg)
    assert name == "vosk"
    fn()
    assert vosk_calls == ["jarvis"]


def test_choose_oww_no_model_for_word(cfg, vosk_calls):
    cfg["stt"]["wake_engine"] = "openwakeword"
    cfg["wake_word"] = "computer"
    assert ww.choose(cfg)[0] == "vosk"


def test_choose_oww_custom_model(cfg, monkeypatch):
    cfg["stt"]["wake_engine"] = "openwakeword"
    cfg["stt"]["wake_model"] = "~/my_word.onnx"
    cfg["wake_word"] = "computer"
    seen = []
    monkeypatch.setattr(ww, "_load_oww", lambda ref: seen.append(ref) or FakeModel([]))
    assert ww.choose(cfg)[0] == "openwakeword"
    assert seen[0].endswith("my_word.onnx") and "~" not in seen[0]


def test_choose_oww_uses_live_sensitivity(cfg, monkeypatch, vosk_calls):
    cfg["stt"]["wake_engine"] = "openwakeword"
    model = FakeModel([])
    monkeypatch.setattr(ww, "_load_oww", lambda ref: model)
    levels = []
    monkeypatch.setattr(ww, "wait_oww", lambda m, level: levels.append(level) or 0.9)
    name, fn = ww.choose(cfg)
    assert name == "openwakeword"
    fn()
    ww.wake_sensitivity({"change": "up"})
    fn()
    assert levels == [0.5, 0.6]
    assert vosk_calls == []


def test_choose_oww_runtime_error_switches_to_vosk(cfg, monkeypatch, vosk_calls):
    cfg["stt"]["wake_engine"] = "openwakeword"
    monkeypatch.setattr(ww, "_load_oww", lambda ref: FakeModel([]))
    tries = []

    def broken(m, level):
        tries.append(1)
        raise RuntimeError("mic gone")
    monkeypatch.setattr(ww, "wait_oww", broken)
    _, fn = ww.choose(cfg)
    fn()
    fn()
    assert tries == [1]  # not retried after it broke
    assert vosk_calls == ["jarvis", "jarvis"]


def test_load_oww_with_fake_package(monkeypatch):
    made = []

    class Model:
        def __init__(self, wakeword_models, inference_framework="tflite"):
            made.append((wakeword_models, inference_framework))

    pkg = types.ModuleType("openwakeword")
    model_mod = types.ModuleType("openwakeword.model")
    model_mod.Model = Model
    utils = types.ModuleType("openwakeword.utils")
    downloads = []
    utils.download_models = lambda model_names: downloads.append(model_names)
    monkeypatch.setitem(sys.modules, "openwakeword", pkg)
    monkeypatch.setitem(sys.modules, "openwakeword.model", model_mod)
    monkeypatch.setitem(sys.modules, "openwakeword.utils", utils)
    ww._load_oww("hey_jarvis")
    assert downloads == [["hey_jarvis"]]
    assert made == [(["hey_jarvis"], "onnx")]


def test_wait_with_level_uses_oww(cfg, monkeypatch, vosk_calls):
    cfg["stt"]["wake_engine"] = "openwakeword"
    monkeypatch.setattr(ww, "_load_oww", lambda ref: FakeModel([]))
    levels = []
    monkeypatch.setattr(ww, "wait_oww", lambda m, level: levels.append(level))
    ww.wait("jarvis", 0.7, cfg=cfg)
    assert levels == [0.7] and vosk_calls == []


def test_wait_vosk(cfg, vosk_calls):
    ww.wait("jarvis", cfg=cfg)
    assert vosk_calls == ["jarvis"]
