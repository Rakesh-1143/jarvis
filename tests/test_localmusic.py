"""Piece BH: local music. Folders, config, tags and the player are faked."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import localmusic as lm  # noqa: E402

TAGS = {
    "a1.mp3": {"title": "Tum Hi Ho", "artist": "Arijit Singh", "album": "Aashiqui 2", "track": 2},
    "a2.mp3": {"title": "Sun Raha Hai", "artist": "Arijit Singh, Shreya Ghoshal", "album": "Aashiqui 2", "track": 1},
    "a3.flac": {"title": "Channa Mereya", "artist": "Arijit Singh", "album": "Ae Dil Hai Mushkil", "track": 1},
    "b1.m4a": {"title": "Yellow", "artist": "Coldplay", "album": "Parachutes", "track": 5},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    (music / "Bolly").mkdir(parents=True)
    (music / "Rock").mkdir()
    for name in ("a1.mp3", "a2.mp3", "a3.flac"):
        (music / "Bolly" / name).write_bytes(b"x")
    (music / "Rock" / "b1.m4a").write_bytes(b"x")
    (music / "Rock" / "cover.jpg").write_bytes(b"x")  # not audio
    cfg = {"music_index_file": str(tmp_path / "idx.json")}
    launched = []
    monkeypatch.setattr(lm, "_config", lambda: cfg)
    monkeypatch.setattr(lm, "_music_dir", lambda: music)
    monkeypatch.setattr(lm, "read_tags", lambda p: dict(TAGS.get(p.name) or lm._guess_from_name(p)))
    monkeypatch.setattr(lm, "_launch", lambda pl, c: launched.append(pl.read_text(encoding="utf-8")))
    monkeypatch.setattr(lm.tempfile, "gettempdir", lambda: str(tmp_path))
    return {"music": music, "cfg": cfg, "launched": launched, "tmp": tmp_path}


def run(**args):
    return lm.local_music(args)


def test_play_artist_includes_featured_songs(env):
    out = run(action="play", artist="Arijit Singh")
    assert out == "Playing Arijit Singh, 3 songs."
    pl = env["launched"][0]
    assert pl.startswith("#EXTM3U")
    assert "a1.mp3" in pl and "a2.mp3" in pl and "a3.flac" in pl and "b1.m4a" not in pl
    # album order then track number
    assert pl.index("a2.mp3") < pl.index("a1.mp3") < pl.index("a3.flac")


def test_play_song(env):
    assert run(action="play", song="tum hi ho") == "Playing Tum Hi Ho by Arijit Singh."
    assert "a1.mp3" in env["launched"][0]


def test_play_album(env):
    assert run(action="play", album="the album aashiqui 2") == "Playing the album Aashiqui 2, 2 songs."


def test_typo_in_artist(env):
    assert run(action="play", artist="arjit sing").startswith("Playing")


def test_free_query_tries_title_artist_album(env):
    assert run(action="play", query="coldplay") == "Playing Yellow by Coldplay."
    assert run(action="play", query="parachutes").startswith("Playing")


def test_not_found(env):
    assert run(action="play", artist="Taylor Swift") == "I couldn't find Taylor Swift in your music."
    assert env["launched"] == []


def test_shuffle_all(env):
    out = run(action="shuffle")
    assert out == "Shuffling your music, 4 songs."
    assert env["launched"][0].count(".mp3") + env["launched"][0].count(".m4a") + env["launched"][0].count(".flac") == 4


def test_shuffle_artist(env):
    assert run(action="shuffle", artist="coldplay") == "Shuffling coldplay."


def test_list_artist(env):
    out = run(action="list", artist="arijit singh")
    assert out.startswith("You have 3 songs for arijit singh:")
    assert "Tum Hi Ho" in out and "Albums:" in out
    assert env["launched"] == []


def test_list_summary(env):
    out = run(action="list")
    assert out.startswith("You have 4 songs from 3 artists and 3 albums.")


def test_empty_library(env):
    for f in env["music"].rglob("*.*"):
        f.unlink()
    assert run(action="play", artist="x") == lm.NO_MUSIC
    assert run(action="list") == lm.NO_MUSIC


def test_index_cached_and_rescan(env):
    run(action="list")
    idx = json.loads(open(env["cfg"]["music_index_file"], encoding="utf-8").read())
    assert len(idx["tracks"]) == 4
    (env["music"] / "Rock" / "Coldplay - Fix You.mp3").write_bytes(b"x")
    assert run(action="list").startswith("You have 4 songs")  # cached, fresh
    assert run(action="rescan") == "Updated your music library. 5 songs found."


def test_stale_index_rescans(env):
    run(action="list")
    p = env["cfg"]["music_index_file"]
    idx = json.loads(open(p, encoding="utf-8").read())
    idx["built"] = time.time() - lm.MAX_AGE - 10
    open(p, "w", encoding="utf-8").write(json.dumps(idx))
    (env["music"] / "new.mp3").write_bytes(b"x")
    assert run(action="list").startswith("You have 5 songs")


def test_no_match_rescans_old_index(env):
    run(action="list")
    p = env["cfg"]["music_index_file"]
    idx = json.loads(open(p, encoding="utf-8").read())
    idx["built"] = time.time() - lm.RETRY_AGE - 10
    open(p, "w", encoding="utf-8").write(json.dumps(idx))
    (env["music"] / "Rock" / "Coldplay - Fix You.mp3").write_bytes(b"x")
    assert run(action="play", song="fix you") == "Playing Fix You by Coldplay."


def test_extra_folders_and_folder_change(env, tmp_path):
    run(action="list")
    extra = tmp_path / "Songs"
    extra.mkdir()
    (extra / "Queen - Bohemian Rhapsody.ogg").write_bytes(b"x")
    env["cfg"]["music_folders"] = [str(extra), str(tmp_path / "missing")]
    assert run(action="list").startswith("You have 5 songs")  # folder list changed -> rescan


def test_guess_from_name():
    from pathlib import Path
    g = lm._guess_from_name(Path("/m/Album X/03 - Artist Y - Song Z.mp3"))
    assert g == {"title": "Song Z", "artist": "Artist Y", "album": "Album X", "track": 0}


def test_read_tags_without_mutagen(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "mutagen":
            raise ImportError
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    p = tmp_path / "Hits" / "Coldplay - Yellow.mp3"
    p.parent.mkdir()
    p.write_bytes(b"x")
    assert lm.read_tags(p) == {"title": "Yellow", "artist": "Coldplay", "album": "Hits", "track": 0}


def test_read_tags_with_mutagen(tmp_path, monkeypatch):
    import types
    fake = types.ModuleType("mutagen")
    fake.File = lambda path, easy=True: types.SimpleNamespace(
        tags={"title": ["Real Title"], "artist": ["Real Artist"], "album": ["Real Album"], "tracknumber": ["7/12"]})
    monkeypatch.setitem(sys.modules, "mutagen", fake)
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    assert lm.read_tags(p) == {"title": "Real Title", "artist": "Real Artist", "album": "Real Album", "track": 7}


def test_launch_prefers_vlc(tmp_path, monkeypatch):
    vlc = tmp_path / "vlc.exe"
    vlc.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(lm.subprocess, "Popen", lambda cmd, **k: calls.append(cmd))
    monkeypatch.setattr(lm, "_startfile", lambda p: calls.append(("start", p)))
    lm._launch(tmp_path / "pl.m3u8", {"vlc_path": str(vlc)})
    assert calls[0][0] == str(vlc) and calls[0][-1].endswith("pl.m3u8")
    monkeypatch.setattr(lm.shutil, "which", lambda n: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "none"))
    lm._launch(tmp_path / "pl.m3u8", {})
    assert calls[1][0] == "start"


def test_player_error(env, monkeypatch):
    def boom(pl, c):
        raise OSError

    monkeypatch.setattr(lm, "_launch", boom)
    assert run(action="play", artist="coldplay") == "I couldn't open a music player."


def test_unknown_action(env):
    assert run(action="dance") == "I can play, shuffle, list, or update your music library."


def test_catalog():
    assert set(lm.CATALOG) == set(lm.HANDLERS) == {"local_music"}
    assert lm.CATALOG["local_music"]["properties"]["action"]["enum"] == ["play", "shuffle", "list", "rescan"]
