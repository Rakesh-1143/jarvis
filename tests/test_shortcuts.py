"""Piece C: voice shortcuts and text snippets. OS calls are mocked."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import shortcuts as sc  # noqa: E402

CFG = {
    "shortcuts": {
        "Open my project": {"open": "C:/code/proj"},
        "open timesheet": {"open": "https://example.com/ts"},
        "mute teams": {"keys": "ctrl+shift+m"},
        "start backup": {"run": "robocopy C:/a D:/b /E"},
        "open downloads": "~/Downloads",
        "broken": {"open": "x", "run": "y"},   # two kinds -> ignored
        "empty": {},
    },
    "snippets": {"address": "12 Main Street", "Work Email": "me@work.com", "sig": "Hi\n{date}"},
}


@pytest.fixture(autouse=True)
def cfg():
    sc.load(CFG)
    yield
    sc.load({})


def test_load_normalises_and_skips_bad():
    assert set(sc.SHORTCUTS) == {"open my project", "open timesheet", "mute teams", "start backup", "open downloads"}
    assert sc.SHORTCUTS["open downloads"] == {"open": "~/Downloads"}
    assert set(sc.SNIPPETS) == {"address", "work email", "sig"}


@pytest.mark.parametrize("text, want", [
    ("mute teams", ("shortcut", {"name": "mute teams"})),
    ("Jarvis, open my project please", ("shortcut", {"name": "open my project"})),
    ("run shortcut start backup", ("shortcut", {"name": "start backup"})),
    ("type my address", ("snippet", {"name": "address"})),
    ("paste my work email", ("snippet", {"name": "work email"})),
    ("insert the sig snippet", ("snippet", {"name": "sig"})),
    ("type hello world", None),
    ("open notepad", None),
    ("", None),
])
def test_match(text, want):
    assert sc.match(text) == want


def test_open_shortcut():
    with mock.patch.object(sc, "_open") as op:
        assert sc.shortcut({"name": "open my project"}) == "Opening open my project."
    op.assert_called_once_with("C:/code/proj")


def test_keys_shortcut():
    from jarvis.actions import inputs

    with mock.patch.object(inputs, "_pg") as pg:
        assert sc.shortcut({"name": "mute teams"}) == "Done."
    pg.return_value.hotkey.assert_called_once_with("ctrl", "shift", "m")


def test_run_needs_yes():
    assert sc.risky_text({"name": "start backup"}).startswith("run the command for start backup")
    assert sc.risky_text({"name": "mute teams"}) is None
    assert sc.risky_text({"name": "nope"}) is None
    with mock.patch.object(sc.subprocess, "Popen") as po:
        reply = sc.shortcut({"name": "start backup"})
        assert reply.startswith("Are you sure") and "robocopy" in reply
        po.assert_not_called()
        assert sc.shortcut({"name": "start backup", "confirm": True}) == "Running start backup."
    po.assert_called_once()
    assert po.call_args.args[0] == "robocopy C:/a D:/b /E"


def test_unknown_and_list():
    assert "don't have a shortcut called foo" in sc.shortcut({"name": "foo"})
    assert sc.shortcut({}).startswith("Your shortcuts are: mute teams, open downloads")
    sc.load({})
    assert "none yet" in sc.shortcut({})


def test_open_error_is_spoken():
    with mock.patch.object(sc, "_open", side_effect=OSError("not found")):
        assert "didn't work: not found" in sc.shortcut({"name": "open timesheet"})


def test_snippet_pastes_and_restores_clipboard():
    pyperclip = mock.MagicMock()
    pyperclip.paste.return_value = "old"
    pyautogui = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"pyperclip": pyperclip, "pyautogui": pyautogui}), \
            mock.patch.object(sc.time, "sleep"):
        assert sc.snippet({"name": "my address"}) == "Typed your address."
    assert [c.args[0] for c in pyperclip.copy.call_args_list] == ["12 Main Street", "old"]
    pyautogui.hotkey.assert_called_once_with("ctrl", "v")


def test_snippet_fills_date():
    with mock.patch.object(sc, "_paste") as paste:
        sc.snippet({"name": "sig"})
    text = paste.call_args.args[0]
    assert text.startswith("Hi\n") and "{date}" not in text


def test_snippet_unknown_and_list():
    assert "don't have a snippet called phone" in sc.snippet({"name": "phone"})
    assert sc.snippet({}) == "Your snippets are: address, sig, work email."


def test_open_non_windows_url():
    with mock.patch.object(sc.os, "name", "posix"), mock.patch.object(sc.webbrowser, "open") as wb:
        sc._open("https://example.com")
    wb.assert_called_once_with("https://example.com")


def test_catalog_and_handlers():
    assert set(sc.CATALOG) == set(sc.HANDLERS) == {"shortcut", "snippet"}
    assert "mute teams" in sc.CATALOG["shortcut"]["description"]
    assert "address" in sc.CATALOG["snippet"]["description"]
    for spec in sc.CATALOG.values():
        assert spec["properties"]["name"]["type"] == "string"
