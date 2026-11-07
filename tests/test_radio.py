"""Tests for piece BG radio.py (network and player faked)."""
import json

import pytest

from jarvis.actions import radio as r

REAL_GET = r._get_json  # saved before the autouse fixture fakes it

MIRCHI = {"name": "Radio Mirchi", "url_resolved": "https://stream.example.com/mirchi", "stationuuid": "u1",
          "country": "India"}
JAZZ1 = {"name": "Smooth Jazz", "url_resolved": "https://jazz.example.com/1", "stationuuid": "j1"}
JAZZ2 = {"name": "Jazz FM", "url_resolved": "http://jazz.example.com/2", "stationuuid": "j2"}


class FakeProc:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    cfg = {"radio_file": str(tmp_path / "radio.json")}
    monkeypatch.setattr(r, "_config", lambda: cfg)
    r._SESSION.update(results=[], index=-1, query="", country="", proc=None)
    calls = {"get": [], "opened": [], "popen": []}

    def fake_get(path, params):
        calls["get"].append(params)
        return calls.get("answer", lambda p: [])(params)

    monkeypatch.setattr(r, "_get_json", fake_get)

    def fake_popen(cmd, **kw):
        calls["popen"].append(cmd)
        return FakeProc()

    monkeypatch.setattr(r.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(r, "find_vlc", lambda: "vlc.exe")
    calls["cfg"] = cfg
    calls["path"] = tmp_path / "radio.json"
    yield calls
    r._SESSION.update(results=[], index=-1, proc=None)


def answer(calls, fn):
    calls["answer"] = fn


def test_play_by_name_uses_vlc(setup):
    answer(setup, lambda p: [MIRCHI] if p.get("name") == "radio mirchi" else [])
    out = r.radio({"action": "play", "query": "Radio Mirchi"})
    assert out == "Playing Radio Mirchi."
    assert setup["popen"][0][0] == "vlc.exe"
    assert setup["popen"][0][-1] == MIRCHI["url_resolved"]
    p = setup["get"][0]
    assert p["hidebroken"] == "true" and p["order"] == "clickcount" and p["limit"] == 5
    saved = json.loads(setup["path"].read_text())
    assert saved["last"]["name"] == "Radio Mirchi"


def test_play_falls_back_to_tag(setup):
    answer(setup, lambda p: [JAZZ1, JAZZ2] if p.get("tag") == "jazz" else [])
    assert r.radio({"action": "play", "query": "some jazz radio"}) == "Playing Smooth Jazz."
    assert setup["get"][0] == {**setup["get"][0], "name": "some jazz radio"}
    assert setup["get"][1]["tag"] == "jazz"


def test_country_passed(setup):
    answer(setup, lambda p: [MIRCHI])
    r.radio({"action": "play", "country": "India"})
    assert setup["get"][0]["country"] == "India"


def test_not_found(setup):
    assert "couldn't find" in r.radio({"action": "play", "query": "zzz qqq"})


def test_unsafe_links_dropped(setup):
    bad = [{"name": "Evil", "url_resolved": "file:///C:/x.exe"}, {"name": "Evil2", "url": "\\\\host\\a.exe"},
           {"name": "", "url": "https://x.example.com"}, JAZZ1]
    answer(setup, lambda p: bad)
    assert r.radio({"action": "play", "query": "jazz"}) == "Playing Smooth Jazz."


def test_next_station_cycles(setup):
    answer(setup, lambda p: [JAZZ1, JAZZ2])
    r.radio({"action": "play", "query": "jazz"})
    first = setup["popen"]
    assert r.radio({"action": "next"}) == "Playing Jazz FM."
    assert r.radio({"action": "next"}) == "Playing Smooth Jazz."
    assert len(first) == 3


def test_new_station_stops_old_player(setup):
    answer(setup, lambda p: [JAZZ1, JAZZ2])
    r.radio({"action": "play", "query": "jazz"})
    old = r._SESSION["proc"]
    r.radio({"action": "next"})
    assert old.stopped and not r._SESSION["proc"].stopped


def test_next_without_play(setup):
    assert "Play a station first" in r.radio({"action": "next"})


def test_stop(setup):
    answer(setup, lambda p: [MIRCHI])
    r.radio({"action": "play", "query": "mirchi"})
    proc = r._SESSION["proc"]
    assert r.radio({"action": "stop"}) == "Radio stopped."
    assert proc.stopped
    assert "didn't start" in r.radio({"action": "stop"})


def test_save_and_favourite(setup):
    answer(setup, lambda p: [MIRCHI])
    assert "Play a station first" in r.radio({"action": "save"})
    r.radio({"action": "play", "query": "radio mirchi"})
    assert r.radio({"action": "save"}) == "Saved Radio Mirchi to your favourite stations."
    assert "already" in r.radio({"action": "save"})
    answer(setup, lambda p: [JAZZ1])
    r.radio({"action": "play", "query": "jazz"})
    r.radio({"action": "save"})
    assert r.radio({"action": "list"}) == "Your stations: Radio Mirchi, Smooth Jazz."
    assert r.radio({"action": "favourite", "query": "my favourite station"}) == "Playing Radio Mirchi."
    assert r.radio({"action": "favourite", "query": "jazz"}) == "Playing Smooth Jazz."
    assert "not in your favourite" in r.radio({"action": "favourite", "query": "bbc news"})


def test_next_walks_favourites(setup):
    setup["path"].write_text(json.dumps({"favourites": [
        {"name": "A", "url": "https://a.example.com"}, {"name": "B", "url": "https://b.example.com"}]}))
    assert r.radio({"action": "favourite"}) == "Playing A."
    assert r.radio({"action": "next"}) == "Playing B."
    assert r.radio({"action": "next"}) == "Playing A."


def test_play_without_query_uses_favourite(setup):
    assert "Which station" in r.radio({"action": "play"})
    setup["path"].write_text(json.dumps({"favourites": [{"name": "A", "url": "https://a.example.com"}]}))
    assert r.radio({"action": "play"}) == "Playing A."


def test_no_favourites(setup):
    assert "no favourite stations" in r.radio({"action": "favourite"})
    assert "no favourite stations" in r.radio({"action": "list"})


def test_bad_saved_file(setup):
    setup["path"].write_text("not json")
    assert "no favourite" in r.radio({"action": "list"})
    setup["path"].write_text(json.dumps({"favourites": [{"name": "X", "url": "file:///c:/x"}], "last": 3}))
    assert "no favourite" in r.radio({"action": "list"})
    assert "Play a station first" in r.radio({"action": "save"})


def test_no_network(setup):
    def boom(p):
        raise OSError("down")
    answer(setup, boom)
    assert r.radio({"action": "play", "query": "jazz"}) == r.NO_NET


def test_bad_json(setup):
    def bad(p):
        raise ValueError("bad")
    answer(setup, bad)
    assert "bad answer" in r.radio({"action": "play", "query": "jazz"})


def test_no_vlc_opens_default_player(setup, monkeypatch):
    monkeypatch.setattr(r, "find_vlc", lambda: None)
    opened = []
    monkeypatch.setattr(r.sys, "platform", "linux")
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    answer(setup, lambda p: [MIRCHI])
    out = r.radio({"action": "play", "query": "mirchi"})
    assert "Install VLC" in out and opened == [MIRCHI["url_resolved"]]
    assert "didn't start" in r.radio({"action": "stop"})


def test_find_vlc_from_config(setup, tmp_path, monkeypatch):
    monkeypatch.undo()
    exe = tmp_path / "vlc.exe"
    exe.write_text("")
    monkeypatch.setattr(r, "_config", lambda: {"vlc_path": str(exe)})
    assert r.find_vlc() == str(exe)


def test_get_json_tries_next_mirror(monkeypatch):
    tried = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"[]"

    def fake_open(req, timeout):
        tried.append(req.full_url)
        if len(tried) == 1:
            raise OSError("down")
        return Resp()

    monkeypatch.setattr(r.urllib.request, "urlopen", fake_open)
    assert REAL_GET("/json/stations/search", {"name": "x"}) == []
    assert len(tried) == 2 and tried[1].startswith(r.HOSTS[1])


def test_catalog():
    assert set(r.CATALOG) == set(r.HANDLERS) == {"radio"}
    assert "favourite" in r.CATALOG["radio"]["properties"]["action"]["enum"]


def test_unknown_action(setup):
    assert "I can play" in r.radio({"action": "dance"})
