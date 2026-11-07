"""Tests for actions/recorder.py (no real ffmpeg, keys, or windows)."""
import pytest

from jarvis.actions import recorder as r


class FakeStdin:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, b):
        self.data += b

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, cmd, done=False):
        self.cmd = cmd
        self.stdin = FakeStdin()
        self._code = 0 if done else None
        self.waited = False

    def poll(self):
        return self._code

    def wait(self, timeout=None):
        self.waited = True
        self._code = 0
        return 0

    def terminate(self):
        self._code = 1

    def kill(self):
        self._code = 1


@pytest.fixture
def env(tmp_path, monkeypatch):
    r.reset()
    s = {**r.DEFAULTS, "folder": str(tmp_path / "Jarvis")}
    monkeypatch.setattr(r, "settings", lambda cfg=None: s)
    calls = {"popen": [], "keys": [], "open": []}

    def popen(cmd):
        p = FakeProc(cmd)
        calls["popen"].append(p)
        return p

    monkeypatch.setattr(r, "_popen", popen)
    monkeypatch.setattr(r, "_hotkey", lambda *k: calls["keys"].append(k))
    monkeypatch.setattr(r, "_open", lambda p: calls["open"].append(p))
    yield s, calls, tmp_path, monkeypatch
    r.reset()


def _ffmpeg(monkeypatch, path="C:/ffmpeg.exe"):
    monkeypatch.setattr(r, "find_ffmpeg", lambda s: path)


def test_catalog_matches_handlers():
    assert set(r.CATALOG) == set(r.HANDLERS) == {"screen_record"}
    assert r.CATALOG["screen_record"]["properties"]["action"]["enum"] == ["start", "stop", "open"]


def test_start_and_stop_with_ffmpeg(env):
    s, calls, tmp, mp = env
    _ffmpeg(mp)
    out = r.screen_record({"action": "start"})
    assert "Recording the screen" in out
    p = calls["popen"][0]
    assert p.cmd[0] == "C:/ffmpeg.exe" and "gdigrab" in p.cmd and "desktop" in p.cmd
    assert p.cmd[-1].endswith(".mp4") and "Jarvis" in p.cmd[-1]
    assert (tmp / "Jarvis").is_dir()
    assert "already" in r.screen_record({"action": "start"})
    assert len(calls["popen"]) == 1
    out = r.screen_record({"action": "stop"})
    assert out.startswith("Stopped recording") and "Jarvis" in out
    assert p.stdin.data == b"q" and p.stdin.closed and p.waited
    assert "not recording" in r.screen_record({"action": "stop"})
    assert calls["keys"] == []


def test_max_minutes_adds_time_limit():
    cmd = r.ffmpeg_cmd("ffmpeg", r.Path("x.mp4"), 25, 2)
    assert cmd[cmd.index("-t") + 1] == "120"
    assert cmd[cmd.index("-framerate") + 1] == "25"
    assert "-t" not in r.ffmpeg_cmd("ffmpeg", r.Path("x.mp4"), 30, 0)


def test_stop_when_ffmpeg_already_ended(env):
    s, calls, tmp, mp = env
    _ffmpeg(mp)
    r.start()
    calls["popen"][0]._code = 1
    assert "stopped by itself" in r.stop()
    assert "not recording" in r.stop()


def test_gamebar_fallback(env):
    s, calls, tmp, mp = env
    _ffmpeg(mp, None)
    out = r.screen_record({"action": "start"})
    assert "Game Bar" in out
    assert calls["keys"] == [("win", "alt", "r")]
    assert "already" in r.screen_record({"action": "start"})
    out = r.screen_record({"action": "stop"})
    assert "Captures" in out
    assert calls["keys"] == [("win", "alt", "r"), ("win", "alt", "r")]
    assert calls["popen"] == []


def test_gamebar_hotkey_error(env, monkeypatch):
    _ffmpeg(monkeypatch, None)

    def boom(*k):
        raise RuntimeError("no display")

    monkeypatch.setattr(r, "_hotkey", boom)
    assert "couldn't start" in r.start()
    assert "not recording" in r.stop()


def test_popen_error(env, monkeypatch):
    _ffmpeg(monkeypatch)

    def boom(cmd):
        raise OSError("bad exe")

    monkeypatch.setattr(r, "_popen", boom)
    assert "couldn't start" in r.start()
    assert "not recording" in r.stop()


def test_open_folder(env):
    s, calls, tmp, mp = env
    _ffmpeg(mp)
    assert "Opening" in r.screen_record({"action": "open"})
    assert calls["open"][-1] == tmp / "Jarvis"
    _ffmpeg(mp, None)
    mp.setattr(r, "GAMEBAR_FOLDER", str(tmp / "Captures"))
    r.screen_record({"action": "open"})
    assert calls["open"][-1] == tmp / "Captures"


def test_unknown_action(env):
    assert "Say start recording" in r.screen_record({"action": "dance"})


def test_find_ffmpeg_config_path(tmp_path, monkeypatch):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("")
    assert r.find_ffmpeg({"ffmpeg_path": str(exe)}) == str(exe)
    monkeypatch.setattr(r.shutil, "which", lambda n: None)
    assert r.find_ffmpeg({"ffmpeg_path": str(tmp_path / "missing.exe")}) is None


def test_settings_merge():
    s = r.settings({"recorder": {"fps": 15}, "ffmpeg_path": "D:/ff.exe"})
    assert s["fps"] == 15 and s["ffmpeg_path"] == "D:/ff.exe" and s["max_minutes"] == 60


def test_stop_all_saves(env):
    s, calls, tmp, mp = env
    _ffmpeg(mp)
    r.start()
    r.stop_all()
    assert calls["popen"][0].stdin.data == b"q"
