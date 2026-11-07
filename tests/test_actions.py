"""Tests for jarvis.actions. OS calls are mocked, so they run anywhere."""
import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis import actions  # noqa: E402
from jarvis.actions import apps, system, web  # noqa: E402


@dataclass
class Cmd:
    intent: str
    args: dict = field(default_factory=dict)


def setup_function(_):
    actions._pending = None


def test_unknown():
    assert "didn't understand" in actions.run(Cmd("unknown"))


def test_open_app_no_shell():
    with mock.patch.object(apps.shutil, "which", return_value="C:/x/notepad.exe"), \
            mock.patch.object(apps.subprocess, "Popen") as p:
        assert actions.run(Cmd("open_app", {"name": "Notepad"})) == "Opening notepad."
        assert p.call_args[0][0] == ["C:/x/notepad.exe"]
        assert "shell" not in p.call_args[1]
    with mock.patch.object(apps.shutil, "which", return_value=None), \
            mock.patch.object(apps.os, "startfile", create=True) as sf:
        assert actions.run(Cmd("open_app", {"name": "zoom"})) == "Opening zoom."
        sf.assert_called_once_with("zoom")
    with mock.patch.object(apps.shutil, "which", return_value=None), \
            mock.patch.object(apps.os, "startfile", create=True, side_effect=OSError):
        assert actions.run(Cmd("open_app", {"name": "nothing"})) == "I couldn't find nothing."


def test_open_app_rejects_shell_chars():
    with mock.patch.object(apps.subprocess, "Popen") as p, \
            mock.patch.object(apps.os, "startfile", create=True) as sf:
        assert "can't" in actions.run(Cmd("open_app", {"name": 'x" & calc & "'}))
        p.assert_not_called()
        sf.assert_not_called()


def test_close_app_ok_and_missing():
    ok = mock.Mock(returncode=0)
    bad = mock.Mock(returncode=128)
    with mock.patch.object(apps.subprocess, "run", return_value=ok) as r:
        assert actions.run(Cmd("close_app", {"name": "vs code"})) == "Closing vs code."
        assert r.call_args[0][0] == ["taskkill", "/IM", "Code.exe"]  # no /F: app can ask to save
    with mock.patch.object(apps.subprocess, "run", return_value=bad):
        assert "couldn't find" in actions.run(Cmd("close_app", {"name": "notepad"}))


def test_close_app_protected():
    with mock.patch.object(apps.subprocess, "run") as r:
        for name in ("python", "explorer", "file explorer"):
            assert "won't close" in actions.run(Cmd("close_app", {"name": name}))
        r.assert_not_called()


def test_web_search():
    with mock.patch.object(web.webbrowser, "open") as o:
        assert actions.run(Cmd("web_search", {"query": "python 3"})) == "Searching for python 3."
        assert o.call_args[0][0].endswith("q=python+3")


def test_volume_up_and_level_and_mute():
    with mock.patch.object(system, "get_volume", return_value=95), \
         mock.patch.object(system, "set_volume") as s, \
         mock.patch.object(system, "set_mute") as m:
        assert actions.run(Cmd("volume", {"change": "up"})) == "Volume set to 100 percent."
        actions.run(Cmd("volume", {"level": 30}))
        assert s.call_args[0][0] == 30
        assert actions.run(Cmd("volume", {"change": "mute"})) == "Muted."
        m.assert_called_with(True)


def test_brightness_down():
    with mock.patch.object(system, "get_brightness", return_value=50), \
         mock.patch.object(system, "set_brightness") as s:
        assert actions.run(Cmd("brightness", {"change": "down", "step": 20})) == "Brightness set to 30 percent."
        s.assert_called_with(30)


def test_time():
    assert system.tell_time(dt.datetime(2026, 11, 7, 9, 5)) == "It's 9:05 AM, Saturday, November 7."


def test_shutdown_asks_then_confirm():
    with mock.patch.object(system.subprocess, "Popen") as p:
        r = actions.run(Cmd("shutdown"))
        assert r.startswith("Are you sure")
        p.assert_not_called()
        assert actions.run(Cmd("confirm")) == "Shutting down in 5 seconds."
        assert p.call_args[0][0] == ["shutdown", "/s", "/t", "5"]


def test_restart_with_flag_and_cancel():
    with mock.patch.object(system.subprocess, "Popen") as p:
        actions.run(Cmd("restart"))
        assert actions.run(Cmd("cancel")) == "Okay, cancelled."
        assert actions.run(Cmd("confirm")) == "There is nothing to confirm."
        p.assert_not_called()
        assert actions.run(Cmd("restart", {"confirm": True})) == "Restarting in 5 seconds."


def test_other_command_drops_pending():
    with mock.patch.object(system.subprocess, "Popen") as p, \
         mock.patch.object(web.webbrowser, "open"):
        actions.run(Cmd("shutdown"))
        actions.run(Cmd("web_search", {"query": "x"}))
        assert actions.run(Cmd("confirm")) == "There is nothing to confirm."
        p.assert_not_called()


def test_errors_do_not_crash():
    with mock.patch.object(apps.subprocess, "Popen", side_effect=ValueError("boom")), \
            mock.patch.object(apps.shutil, "which", return_value="C:/x.exe"):
        assert actions.run(Cmd("open_app", {"name": "x"})).startswith("Sorry, that failed")


def test_config_loaded():
    # config.yaml sets chrome to a full path and a screenshot folder.
    assert apps.APP_PATHS["chrome"].endswith("chrome.exe")
    from jarvis.actions import screen
    assert "~" not in screen.SCREENSHOT_DIR


def test_old_pending_expires():
    with mock.patch.object(system.subprocess, "Popen") as p:
        actions.run(Cmd("shutdown"))
        actions._pending_at -= actions.PENDING_SECONDS + 1
        assert actions.run(Cmd("confirm")) == "There is nothing to confirm."
        p.assert_not_called()
