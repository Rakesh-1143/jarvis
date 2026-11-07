"""Tests for actions/tray.py (system tray icon). Uses a fake pystray: no real tray, no files opened."""
import threading
import types

import pytest

from jarvis.actions import assistant, tray


class FakeIcon:
    def __init__(self, name, image, title, menu=None):
        self.name, self.icon, self.title, self.menu = name, image, title, menu
        self.stopped = threading.Event()
        self.ran = threading.Event()
        self.notes = []

    def run(self):
        self.ran.set()
        self.stopped.wait(5)

    def stop(self):
        self.stopped.set()

    def notify(self, text, title=""):
        self.notes.append(text)


class FakeMenuItem:
    def __init__(self, text, action, default=False):
        self.text, self.action, self.default = text, action, default


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


def fake_pystray():
    return types.SimpleNamespace(Icon=FakeIcon, MenuItem=FakeMenuItem, Menu=FakeMenu)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    tray.stop()
    assistant.resume_listening({})
    monkeypatch.setattr(tray, "_import_pystray", fake_pystray)
    tray._state = tray.IDLE
    yield
    tray.stop()
    assistant.resume_listening({})
    tray._say = tray._on_quit = tray._on_pause = tray._on_restart = None


def _items(icon):
    return {(i.text if isinstance(i.text, str) else "pause"): i for i in icon.menu.items if isinstance(i, FakeMenuItem)}


def test_no_intents():
    assert tray.CATALOG == {} and tray.HANDLERS == {}


def test_image_per_state_has_its_colour():
    for state, color in tray.COLORS.items():
        img = tray.make_image(state)
        assert img.size == (tray.ICON_SIZE, tray.ICON_SIZE)
        assert img.getpixel((8, 32))[:3] == color  # left edge of the circle, away from the J
    assert tray.make_image("nonsense").getpixel((8, 32))[:3] == tray.COLORS[tray.IDLE]


def test_set_state_without_tray_does_nothing_bad():
    tray.set_state(tray.SPEAKING)
    assert tray.get_state() == tray.SPEAKING and not tray.is_running()
    tray.set_state("bogus")
    assert tray.get_state() == tray.IDLE


def test_start_runs_icon_in_thread_and_set_state_updates_it():
    assert tray.start() is True
    icon = tray._icon
    assert icon.ran.wait(2) and tray.is_running()
    assert tray.start() is True and tray._icon is icon  # second start is a no-op
    tray.set_state(tray.THINKING)
    assert icon.title == tray.TITLES[tray.THINKING]
    assert icon.icon.getpixel((8, 32))[:3] == tray.COLORS[tray.THINKING]
    tray.stop()
    assert icon.stopped.is_set() and not tray.is_running()
    tray.stop()  # twice is fine


def test_start_without_pystray_returns_false(monkeypatch):
    def missing():
        raise ImportError("No module named 'pystray'")

    monkeypatch.setattr(tray, "_import_pystray", missing)
    assert tray.start() is False and not tray.is_running()
    tray.set_state(tray.LISTENING)  # still safe


def test_menu_items_and_default():
    tray.start()
    icon = tray._icon
    texts = [i.text for i in icon.menu.items if isinstance(i, FakeMenuItem)]
    assert texts[1:] == ["Open config", "Open log", "Run self-check", "Restart Jarvis", "Quit"]
    first = icon.menu.items[0]
    assert first.default and callable(first.text) and first.text(None) == "Pause listening"


def test_pause_toggle_uses_assistant_and_shows_paused():
    calls = []
    tray.start(on_pause=calls.append)
    icon = tray._icon
    tray.set_state(tray.LISTENING)
    assert tray.toggle_pause() is True
    assert assistant.is_paused() and calls == [True]
    assert tray.pause_label() == "Resume listening"
    assert icon.title == tray.TITLES[tray.PAUSED]
    tray.set_state(tray.SPEAKING)  # speaking still shows (e.g. a timer goes off while paused)
    assert icon.title == tray.TITLES[tray.SPEAKING]
    tray.set_state(tray.IDLE)
    assert icon.title == tray.TITLES[tray.PAUSED]
    assert tray.toggle_pause() is False
    assert not assistant.is_paused() and calls == [True, False]
    assert icon.title == tray.TITLES[tray.IDLE]


def test_voice_pause_also_shows_paused():
    assistant.pause_listening({"minutes": 5})
    assert tray.shown_state(tray.LISTENING) == tray.PAUSED
    assert tray.shown_state(tray.THINKING) == tray.THINKING


def test_open_config_and_log(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(tray.os, "startfile", lambda p: opened.append(p), raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("x: 1")
    logf = tmp_path / "jarvis.log"
    logf.write_text("")
    tray.start(config_file=cfg, log_file=logf)
    assert tray.open_config() and tray.open_log()
    assert opened == [str(cfg), str(logf)]


def test_relative_log_file_uses_working_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tray.start(log_file="jarvis.log")
    assert tray._log_file == tmp_path / "jarvis.log"


def test_open_missing_file_tells_user(monkeypatch, tmp_path):
    said = []
    monkeypatch.setattr(tray.os, "startfile", lambda p: pytest.fail("must not open"), raising=False)
    tray.start(say=said.append, log_file=tmp_path / "nope.log")
    assert tray.open_log() is False
    assert said == ["I could not find nope.log."]
    assert tray._icon.notes == said


def test_self_check_runs_doctor_in_background(monkeypatch):
    said = []
    monkeypatch.setattr(tray, "_run_self_check", lambda: "All 9 checks OK.")
    tray.start(say=said.append)
    tray.self_check().join(2)
    assert said == ["All 9 checks OK."]


def test_self_check_error_is_told(monkeypatch):
    said = []

    def boom():
        raise RuntimeError("no mic")

    monkeypatch.setattr(tray, "_run_self_check", boom)
    tray.start(say=said.append)
    tray.self_check().join(2)
    assert said == ["Self-check failed: no mic"]


def test_self_check_calls_real_doctor(monkeypatch):
    from jarvis.actions import doctor

    monkeypatch.setattr(doctor, "self_check", lambda args: "doctor says hi")
    assert tray._run_self_check() == "doctor says hi"


def test_quit_stops_icon_then_calls_on_quit():
    order = []
    tray.start(on_quit=lambda: order.append("quit"))
    icon = tray._icon
    tray.quit_jarvis()
    assert icon.stopped.is_set() and order == ["quit"] and not tray.is_running()


def test_restart_starts_new_process_then_quits(monkeypatch):
    started, quits = [], []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda cmd, cwd=None: started.append(cmd))
    monkeypatch.setattr(tray.sys, "argv", ["main.py"])
    tray.start(on_quit=lambda: quits.append(1))
    tray.restart()
    cmd = started[0]
    assert cmd[:2] == [tray.sys.executable, "-c"] and cmd[3] == str(tray.os.getpid())  # waits for this Jarvis
    assert cmd[4:] == [tray.sys.executable, "main.py"] and quits == [1]


def test_restart_failure_does_not_quit(monkeypatch):
    said, quits = [], []

    def fail(cmd, cwd=None):
        raise OSError("denied")

    monkeypatch.setattr(tray.subprocess, "Popen", fail)
    tray.start(on_quit=lambda: quits.append(1), say=said.append)
    tray.restart()
    assert quits == [] and said == ["I could not restart: denied"] and tray.is_running()


def test_custom_restart_callback():
    calls = []
    tray.start(on_restart=lambda: calls.append("r"))
    tray.restart()
    assert calls == ["r"] and tray.is_running()
