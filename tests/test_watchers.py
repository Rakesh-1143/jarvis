"""Tests for watchers.py (piece BB). No real psutil, network or thread: sensors are faked."""
import os

import pytest

from jarvis.actions import watchers as W


@pytest.fixture(autouse=True)
def fake(monkeypatch, tmp_path):
    W.reset()
    said = []
    state = {"bat": (50.0, True), "cpu": 50.0, "apps": {"zoom", "chrome"}, "up": False}
    monkeypatch.setattr(W, "notify", said.append)
    monkeypatch.setattr(W, "_ensure_thread", lambda: None)
    monkeypatch.setattr(W, "downloads_dir", lambda: str(tmp_path))
    monkeypatch.setattr(W, "battery", lambda: state["bat"])
    monkeypatch.setattr(W, "cpu_percent", lambda: state["cpu"])
    monkeypatch.setattr(W, "running_apps", lambda: state["apps"])
    monkeypatch.setattr(W, "site_up", lambda url: state["up"])
    monkeypatch.setattr(W, "_apps_cfg", lambda: {})
    state["said"] = said
    state["dir"] = tmp_path
    yield state
    W.reset()


def _file(d, name, mtime=None):
    p = d / name
    p.write_text("x")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_catalog_and_handlers_match():
    assert set(W.CATALOG) == set(W.HANDLERS) == {"watch", "watches"}
    assert W.CATALOG["watch"]["properties"]["what"]["enum"] == list(W.KINDS)


def test_set_notifier():
    got = []
    W.set_notifier(got.append)
    assert W.notify == got.append
    W.set_notifier(None)
    assert W.notify is print


def test_download_finishes(fake):
    part = _file(fake["dir"], "movie.mp4.crdownload")
    assert "download finishes" in W.watch({"what": "download"})
    assert W.tick() == []
    part.unlink()
    _file(fake["dir"], "movie.mp4")
    assert W.tick() == ["Your download finished: movie.mp4."]
    assert fake["said"] == ["Your download finished: movie.mp4."]
    assert W._watches == []


def test_download_two_files_waits_for_all(fake):
    a = _file(fake["dir"], "a.zip.part")
    b = _file(fake["dir"], "b.zip.crdownload")
    assert "2 downloads" in W.watch({"what": "download"})
    a.unlink()
    assert W.tick() == []
    b.unlink()
    _file(fake["dir"], "b.zip")
    assert W.tick() == ["Your download finished: b.zip."]


def test_download_cancelled(fake):
    part = _file(fake["dir"], "x.crdownload")
    W.watch({"what": "download"})
    part.unlink()
    assert "cancelled" in W.tick()[0]


def test_download_not_started_waits_then_gives_up(fake):
    reply = W.watch({"what": "download"})
    assert "don't see a download" in reply
    start = W._watches[0]["started"]
    assert W.tick(start + 30) == []
    _file(fake["dir"], "late.pdf.crdownload")
    assert W.tick(start + 60) == []
    assert W._watches[0]["seen"]
    (fake["dir"] / "late.pdf.crdownload").unlink()
    _file(fake["dir"], "late.pdf")
    assert W.tick(start + 90) == ["Your download finished: late.pdf."]


def test_download_none_gives_up(fake):
    W.watch({"what": "download"})
    start = W._watches[0]["started"]
    assert "No download started" in W.tick(start + W.DOWNLOAD_WAIT)[0]


def test_old_files_not_named(fake):
    _file(fake["dir"], "old.txt", mtime=1000)
    part = _file(fake["dir"], "new.iso.part")
    W.watch({"what": "download"})
    part.unlink()
    assert "cancelled" in W.tick()[0]


def test_website_back(fake):
    reply = W.watch({"what": "website", "target": "google dot com"})
    assert "google.com is down" in reply
    w = W._watches[0]
    assert w["url"] == "https://google.com/"
    assert W.tick(w["started"] + 10) == []  # not due yet
    assert W.tick(w["started"] + 60) == []  # still down
    fake["up"] = True
    assert W.tick(w["started"] + 120) == ["google.com is back up."]


def test_website_already_up(fake):
    fake["up"] = True
    assert W.watch({"what": "website", "target": "example.org"}) == "example.org is up right now."
    assert W._watches == []


def test_website_gives_up(fake):
    W.watch({"what": "website", "target": "example.org"})
    s = W._watches[0]["started"]
    assert "6 hours" in W.tick(s + W.WEBSITE_MAX)[0]


@pytest.mark.parametrize("target,url", [
    ("google", "https://google.com/"),
    ("http://site.in/status", "http://site.in/status"),
    ("the website github.com", "https://github.com/"),
])
def test_clean_url(target, url):
    assert W._clean_url(target)[0] == url


@pytest.mark.parametrize("bad", ["", "ftp://x.com", "file:///c:/x", "a b$c"])
def test_clean_url_bad(bad):
    assert W._clean_url(bad) is None


def test_battery_up(fake):
    reply = W.watch({"what": "battery", "value": 80})
    assert "charges up to 80" in reply
    fake["bat"] = (79.4, True)
    assert W.tick() == []
    fake["bat"] = (80.2, True)
    assert W.tick() == ["The battery is at 80 percent."]


def test_battery_down_and_spoken_text(fake):
    fake["bat"] = (90.0, False)
    assert "drops to 30" in W.watch({"what": "battery", "target": "30%"})
    fake["bat"] = (29.0, False)
    assert W.tick() == ["The battery is at 29 percent."]


def test_battery_edge_cases(fake):
    assert "already at 50" in W.watch({"what": "battery", "value": 50})
    assert "percent" in W.watch({"what": "battery", "value": 150})
    fake["bat"] = None
    assert "can't read a battery" in W.watch({"what": "battery", "value": 80})
    assert W._watches == []


def test_app_closed(fake):
    assert W.watch({"what": "app_closed", "target": "zoom"}) == "Okay, I'll tell you when Zoom closes."
    assert W.tick() == []
    fake["apps"] = {"chrome"}
    assert W.tick() == ["Zoom has closed."]


def test_app_not_running(fake):
    assert W.watch({"what": "app_closed", "target": "teams"}) == "Teams is not running."
    assert W.watch({"what": "app_closed"}) == "Which app should I watch?"


def test_cpu_idle_needs_two_minutes(fake):
    W.watch({"what": "cpu_idle"})
    s = W._watches[0]["started"]
    fake["cpu"] = 5.0
    assert W.tick(s + 10) == []
    fake["cpu"] = 40.0
    assert W.tick(s + 60) == []  # busy again: restart the clock
    fake["cpu"] = 3.0
    assert W.tick(s + 70) == []
    assert W.tick(s + 150) == []
    assert W.tick(s + 190) == ["The CPU is idle now. Your task may be done."]


def test_cpu_custom_limit(fake):
    assert "under 25 percent" in W.watch({"what": "cpu", "value": 25})


def test_unknown_kind():
    assert "I can watch" in W.watch({"what": "weather"})


def test_duplicate_and_limit(fake):
    W.watch({"what": "app_closed", "target": "zoom"})
    assert "already waiting for Zoom" in W.watch({"what": "app_closed", "target": "Zoom"})
    for i in range(W.MAX_WATCHES - 1):
        W.watch({"what": "website", "target": f"site{i}.com"})
    assert "at once" in W.watch({"what": "website", "target": "one-more.com"})


def test_list_and_cancel(fake):
    assert W.watches({}) == "I'm not watching anything."
    W.watch({"what": "app_closed", "target": "zoom"})
    W.watch({"what": "battery", "value": 80})
    W.watch({"what": "website", "target": "google.com"})
    assert W.watches({"action": "list"}) == (
        "I'm waiting for Zoom to close, the battery to reach 80 percent, and google.com to come back.")
    assert W.watches({"action": "cancel", "target": "zoom"}) == "Stopped waiting for Zoom to close."
    assert W.watches({"action": "cancel", "target": "teams"}) == "I'm not watching teams."
    assert W.watches({"action": "cancel"}) == "Stopped 2 watches."
    assert W._watches == []


def test_two_items_list(fake):
    W.watch({"what": "app_closed", "target": "zoom"})
    W.watch({"what": "cpu_idle"})
    assert W.watches({}) == "I'm waiting for Zoom to close and the CPU to go idle."


def test_check_error_does_not_crash(fake, monkeypatch):
    W.watch({"what": "app_closed", "target": "zoom"})

    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(W, "running_apps", boom)
    assert W.tick() == []
    assert len(W._watches) == 1


def test_notify_error_still_removes(fake, monkeypatch):
    W.watch({"what": "app_closed", "target": "zoom"})
    monkeypatch.setattr(W, "notify", lambda m: 1 / 0)
    fake["apps"] = set()
    assert W.tick() == ["Zoom has closed."]
    assert W._watches == []


def test_loop_calls_tick_until_stopped(monkeypatch):
    import threading

    hit = threading.Event()
    monkeypatch.setattr(W, "TICK", 0.01)
    monkeypatch.setattr(W, "tick", lambda now=None: hit.set())
    W._stop.clear()
    t = threading.Thread(target=W._loop, daemon=True)
    t.start()
    assert hit.wait(2)
    W._stop.set()
    t.join(2)
    assert not t.is_alive()
