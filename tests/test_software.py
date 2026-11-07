"""Tests for piece V (actions/software.py). winget is faked; nothing is installed."""
import subprocess

import pytest

from jarvis.actions import software

SEARCH = """\r  \r-\r\\\r
Name                Id                       Version   Match        Source
---------------------------------------------------------------------------
VLC media player    VideoLAN.VLC             3.0.21    Moniker: vlc winget
VLC UWP             XPDM1ZW6815MQM           Unknown                msstore
Bad                 Some.Truncated.Id…       1.0                    winget

"""
LIST = """Name   Id              Version  Available Source
--------------------------------------------------
Zoom   Zoom.Zoom       5.17.0   6.0.0     winget
"""
UPGRADE = """Name             Id                 Version  Available Source
----------------------------------------------------------------
Google Chrome    Google.Chrome      129.0    130.0     winget
7-Zip            7zip.7zip          23.01    24.08     winget
2 upgrades available.
"""


class Fake:
    def __init__(self, outputs=None, code=0):
        self.calls = []
        self.outputs = outputs or {}
        self.code = code

    def __call__(self, cmd, **kw):
        assert isinstance(cmd, list), "must pass a list"
        assert not kw.get("shell"), "never shell=True"
        self.calls.append(cmd)
        out = self.outputs.get(cmd[1], "")
        return subprocess.CompletedProcess(cmd, self.code, out, "")


@pytest.fixture
def fake(monkeypatch):
    f = Fake({"search": SEARCH, "list": LIST, "upgrade": UPGRADE})
    monkeypatch.setattr(software.shutil, "which", lambda n: "C:/winget.exe")
    monkeypatch.setattr(software.subprocess, "run", f)
    software._cache.clear()
    said = []
    software.set_notifier(said.append)
    f.said = said
    yield f
    t = software._job and software._job["thread"]
    if t:
        t.join(5)
    software._job = None
    software.set_notifier(None)


def _wait():
    software._job["thread"].join(5)


def test_parse_table_skips_spinner_and_truncated_ids():
    rows = software.parse_table(SEARCH)
    assert [r["id"] for r in rows] == ["VideoLAN.VLC", "XPDM1ZW6815MQM"]
    assert rows[0]["name"] == "VLC media player"


def test_parse_upgrade_table():
    rows = software.parse_table(UPGRADE)
    assert [(r["name"], r["available"]) for r in rows] == [("Google Chrome", "130.0"), ("7-Zip", "24.08")]


def test_no_winget(monkeypatch):
    monkeypatch.setattr(software.shutil, "which", lambda n: None)
    assert "App Installer" in software.software({"action": "install", "name": "vlc"})


def test_unknown_action(fake):
    assert "install" in software.software({"action": "explode"})
    assert fake.calls == []


def test_check_updates(fake):
    r = software.software({"action": "check_updates"})
    assert r == "2 apps can be updated: Google Chrome, 7-Zip."
    assert fake.calls[0][1] == "upgrade" and "--all" not in fake.calls[0]


def test_check_updates_none(fake):
    fake.outputs["upgrade"] = "No installed package found matching input criteria.\n"
    assert "up to date" in software.software({"action": "check_updates"})


def test_install_asks_first_and_does_nothing(fake):
    r = software.software({"action": "install", "name": "VLC"})
    assert r.startswith("Are you sure you want to install VLC media player (VideoLAN.VLC)")
    assert all(c[1] != "install" for c in fake.calls)


def test_risky_text_stores_id_for_the_yes(fake):
    args = {"action": "install", "name": "vlc"}
    assert software.needs_confirm(args)
    assert software.risky_text(args) == "install VLC media player (VideoLAN.VLC)"
    assert args["id"] == "VideoLAN.VLC"
    n = len(fake.calls)
    software.risky_text(dict(args, id=None))  # cached search, no new winget call
    assert len(fake.calls) == n


def test_install_after_yes_runs_in_background(fake):
    args = {"action": "install", "name": "vlc"}
    software.risky_text(args)
    r = software.software({**args, "confirm": True})
    assert "background" in r
    _wait()
    cmd = fake.calls[-1]
    assert cmd[:4] == ["C:/winget.exe", "install", "--id", "VideoLAN.VLC"]
    assert "--exact" in cmd and "--accept-package-agreements" in cmd
    assert fake.said == ["VLC media player is installed."]


def test_install_failure_is_spoken(fake):
    fake.code = 1
    fake.outputs["install"] = "Installer failed with exit code: 1603\n"
    software.software({"action": "install", "name": "vlc", "confirm": True})
    _wait()
    assert fake.said[-1].startswith("Could not install VLC media player.")
    assert "1603" in fake.said[-1]


def test_not_found(fake):
    fake.outputs["search"] = "No package found matching input criteria.\n"
    assert software.risky_text({"action": "install", "name": "nothing"}) is None
    assert "couldn't find" in software.software({"action": "install", "name": "nothing"})


def test_uninstall_uses_installed_list(fake):
    args = {"action": "uninstall", "name": "zoom"}
    assert software.risky_text(args) == "uninstall Zoom (Zoom.Zoom)"
    assert fake.calls[0][1:4] == ["list", "--name", "zoom"]
    software.software({**args, "confirm": True})
    _wait()
    assert fake.calls[-1][1:4] == ["uninstall", "--id", "Zoom.Zoom"]
    assert fake.said == ["Zoom is uninstalled."]


def test_update_all_needs_yes(fake):
    assert "update all" in software.risky_text({"action": "update_all"})
    assert software.software({"action": "update_all"}).startswith("Are you sure")
    assert fake.calls == []
    software.software({"action": "update_all", "confirm": True})
    _wait()
    assert fake.calls[-1][1:3] == ["upgrade", "--all"]


def test_check_updates_is_not_risky():
    assert not software.needs_confirm({"action": "check_updates"})
    assert software.risky_text({"action": "check_updates"}) is None


def test_bad_names_rejected(fake):
    for bad in ["--force", "a\"&calc", "x" * 80, ""]:
        assert software.risky_text({"action": "install", "name": bad}) is None
        assert "search" not in [c[1] for c in fake.calls]


def test_bad_id_from_winget_skipped(fake):
    fake.outputs["search"] = SEARCH.replace("VideoLAN.VLC    ", "-bad&id         ")
    row = software.find("VLC")
    assert row["id"] == "XPDM1ZW6815MQM"


def test_one_job_at_a_time(fake, monkeypatch):
    import threading
    gate = threading.Event()
    real = software._run

    def slow(args, timeout):
        if args[0] == "upgrade" and "--all" in args:
            gate.wait(5)
        return real(args, timeout)

    monkeypatch.setattr(software, "_run", slow)
    software.software({"action": "update_all", "confirm": True})
    r = software.software({"action": "install", "name": "vlc", "confirm": True})
    assert "still busy" in r
    gate.set()
    _wait()


def test_timeout_is_spoken(fake, monkeypatch):
    def boom(args, timeout):
        raise subprocess.TimeoutExpired("winget", timeout)

    monkeypatch.setattr(software, "_run", boom)
    software.software({"action": "update_all", "confirm": True})
    _wait()
    assert "15 minutes" in fake.said[-1]


def test_catalog_matches_handlers():
    assert set(software.CATALOG) == set(software.HANDLERS) == {"software"}
    assert software.CATALOG["software"]["properties"]["action"]["enum"] == list(software._ACTIONS)
