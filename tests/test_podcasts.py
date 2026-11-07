"""Piece AI: podcasts. Network, config and the player are faked."""
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import podcasts  # noqa: E402


def feed(*eps):
    """eps: (guid, title, pubDate) newest first."""
    items = "".join(
        f"<item><title>{t}</title><guid>{g}</guid><pubDate>{d}</pubDate>"
        f'<enclosure url="https://cdn.example/{g}.mp3" type="audio/mpeg"/></item>' for g, t, d in eps)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>X</title>{items}</channel></rss>'.encode()


DAILY = feed(("d3", "Episode 3", "Wed, 05 Nov 2026 10:00:00 GMT"),
             ("d2", "Episode 2", "Tue, 04 Nov 2026 10:00:00 GMT"),
             ("d1", "Episode 1", "Mon, 03 Nov 2026 10:00:00 GMT"))
ITUNES = json.dumps({"results": [{"collectionName": "Hard Fork", "feedUrl": "https://feeds.example/hardfork"}]}).encode()
HARDFORK = feed(("h2", "AI news", "Thu, 06 Nov 2026 10:00:00 GMT"), ("h1", "Old one", "Mon, 03 Nov 2026 10:00:00 GMT"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = {"podcasts": {"The Daily": "https://feeds.example/daily"}, "podcasts_file": str(tmp_path / "p.json")}
    routes = {"itunes.apple.com": ITUNES, "feeds.example/daily": DAILY, "feeds.example/hardfork": HARDFORK}
    opened, calls = [], []

    def fake_fetch(url):
        calls.append(url)
        for key, val in routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(podcasts, "_config", lambda: cfg)
    monkeypatch.setattr(podcasts, "_fetch", fake_fetch)
    monkeypatch.setattr(podcasts, "_open", opened.append)
    return {"cfg": cfg, "routes": routes, "opened": opened, "calls": calls, "file": tmp_path / "p.json"}


def run(**args):
    return podcasts.podcast(args)


def test_catalog_and_handlers():
    assert set(podcasts.CATALOG) == set(podcasts.HANDLERS) == {"podcast"}
    assert "whats_new" in podcasts.CATALOG["podcast"]["properties"]["action"]["enum"]


def test_parse_feed_sorts_newest_first_and_skips_items_without_audio():
    xml = feed(("a", "Old", "Mon, 03 Nov 2026 10:00:00 GMT"), ("b", "New", "Wed, 05 Nov 2026 10:00:00 GMT"))
    xml = xml.replace(b"</channel>", b"<item><title>No audio</title></item></channel>")
    eps = podcasts.parse_feed(xml)
    assert [e["title"] for e in eps] == ["New", "Old"]
    assert eps[0]["url"] == "https://cdn.example/b.mp3"


def test_parse_feed_without_dates_keeps_feed_order():
    xml = feed(("a", "First", ""), ("b", "Second", ""))
    assert [e["id"] for e in podcasts.parse_feed(xml)] == ["a", "b"]


def test_play_latest_from_config_show(env):
    out = run(action="play_latest", name="daily")
    assert out == "Playing Episode 3 from the daily."
    assert env["opened"] == ["https://cdn.example/d3.mp3"]
    saved = json.loads(env["file"].read_text())
    assert saved["played"]["the daily"] == "d3" and saved["last_show"] == "the daily"


def test_play_latest_unknown_show_uses_itunes_search(env):
    out = run(action="play_latest", name="hard fork podcast")
    assert "AI news" in out
    assert any("itunes.apple.com" in c and "hard%20fork" in c for c in env["calls"])


def test_play_latest_not_found(env):
    env["routes"]["itunes.apple.com"] = json.dumps({"results": []}).encode()
    assert "couldn't find a podcast" in run(action="play_latest", name="zzz qqq")
    assert env["opened"] == []


def test_next_episode_walks_forward_then_up_to_date(env):
    state = podcasts._load_state()
    state["played"]["the daily"] = "d1"
    state["last_show"] = "the daily"
    podcasts._save_state(state)
    assert "Episode 2" in run(action="next")
    assert "Episode 3" in run(action="next")
    assert "up to date" in run(action="next")
    assert env["opened"] == ["https://cdn.example/d2.mp3", "https://cdn.example/d3.mp3"]


def test_next_without_history(env):
    assert "Play a podcast first" in run(action="next")
    assert "Episode 3" in run(action="next", name="the daily")  # never played -> newest


def test_next_unknown_show_does_not_search(env):
    assert "not one of your podcasts" in run(action="next", name="random show")
    assert not any("itunes" in c for c in env["calls"])


def test_subscribe_list_unsubscribe(env):
    q = run(action="subscribe", name="hard fork")
    assert q.startswith("Are you sure you want to subscribe to")
    assert "hard fork" not in run(action="list")  # nothing saved before "yes"
    assert run(action="subscribe", name="hard fork", confirm=True) == "Subscribed to hard fork."
    assert run(action="subscribe", name="hard fork", confirm=True) == "You're already subscribed to hard fork."
    assert run(action="list") == "Your podcasts: hard fork, the daily."
    assert run(action="unsubscribe", name="hard fork") == "Unsubscribed from hard fork."
    assert "hard fork" not in run(action="list")


def test_unsubscribe_config_show_points_to_config(env):
    assert "config.yaml" in run(action="unsubscribe", name="the daily")
    assert "not subscribed" in run(action="unsubscribe", name="nothing here")


def test_whats_new_counts_since_last_check(env):
    run(action="subscribe", name="hard fork", confirm=True)  # marks h2 as seen
    state = podcasts._load_state()
    state["seen"]["the daily"] = "d1"
    podcasts._save_state(state)
    out = run(action="whats_new")
    assert "the daily: 2 new episodes, latest is Episode 3" in out
    assert "hard fork" not in out
    assert run(action="whats_new") == "No new podcast episodes."


def test_whats_new_no_shows(env):
    env["cfg"]["podcasts"] = {}
    assert "no podcasts" in run(action="whats_new")
    assert "no podcasts" in run(action="list")


def test_network_errors_are_spoken(env):
    env["routes"]["feeds.example/daily"] = urllib.error.URLError("down")
    assert run(action="play_latest", name="the daily") == podcasts.NO_NET
    assert run(action="whats_new") == podcasts.NO_NET


def test_broken_feed(env):
    env["routes"]["feeds.example/daily"] = b"<rss><channel><item>"
    assert "broken" in run(action="play_latest", name="the daily")


def test_bad_state_file_is_ignored(env):
    env["file"].write_text("not json")
    assert "Episode 3" in run(action="play_latest", name="the daily")


def test_unknown_action(env):
    assert "I can play" in run(action="dance")
