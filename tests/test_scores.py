"""Piece AO: scores. All network calls are faked (no internet in tests)."""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import scores  # noqa: E402

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Live scores</title>
<item><title>India 245/3 * v Australia 180</title><link>x</link></item>
<item><title>England 120/9 v Pakistan *</title><link>y</link></item>
<item><title>Sri Lanka v Bangladesh</title><link>z</link></item>
</channel></rss>"""


def _ev(home, away, hs, as_, state, detail):
    return {"name": f"{away} at {home}", "status": {"type": {"state": state, "shortDetail": detail}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": hs, "team": {"displayName": home}},
                {"homeAway": "away", "score": as_, "team": {"displayName": away}}]}]}


EPL = {"events": [
    _ev("Arsenal", "Chelsea", "2", "1", "in", "67'"),
    _ev("Liverpool", "Everton", "0", "0", "pre", "Sat 8:00 PM"),
    _ev("Manchester City", "Tottenham Hotspur", "3", "0", "post", "FT"),
]}
UCL = {"events": [_ev("Real Madrid", "Bayern Munich", "1", "1", "in", "HT")]}

SETTINGS = {"teams": [], "football_leagues": ["eng.1", "uefa.champions"], "cricket_url": scores.CRICKET_URL}


def fake(routes):
    calls = []

    def _fetch(url):
        calls.append(url)
        for key, val in routes:
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val if isinstance(val, bytes) else json.dumps(val).encode()
        raise OSError("no route")
    return _fetch, calls


def run(args, routes, settings=None):
    f, calls = fake(routes)
    with mock.patch.object(scores, "_fetch", f), \
         mock.patch.object(scores, "_settings", return_value=dict(settings or SETTINGS)):
        return scores.scores(args), calls


NET = [("cricinfo", RSS), ("eng.1", EPL), ("uefa.champions", UCL)]


# ---- cricket ----
def test_india_score_cricket():
    out, calls = run({"team": "India"}, NET)
    assert out == "India 245 for 3, batting, versus Australia 180."
    assert "cricinfo" in calls[0]


def test_team_with_filler_words():
    out, _ = run({"team": "what's the pakistan score"}, NET)
    assert "England 120 for 9 versus Pakistan batting" in out


def test_live_cricket_lists_all():
    out, _ = run({"sport": "cricket"}, NET)
    assert out.startswith("Live cricket: India 245 for 3")
    assert "Sri Lanka versus Bangladesh" in out


def test_ipl_means_any_cricket():
    out, _ = run({"team": "IPL"}, NET)
    assert out.startswith("Live cricket:")


def test_cricket_team_not_playing():
    out, _ = run({"sport": "cricket", "team": "Nepal"}, NET)
    assert out == "I don't see a live cricket match for Nepal right now."


def test_cricket_favourites_used():
    out, _ = run({"sport": "cricket"}, NET, {**SETTINGS, "teams": ["Sri Lanka"]})
    assert out == "Sri Lanka versus Bangladesh."


def test_cricket_net_fail_soft():
    out, _ = run({"sport": "cricket"}, [("cricinfo", OSError("down"))])
    assert "couldn't get live cricket" in out and "search the web" in out


def test_cricket_bad_xml_fail_soft():
    out, _ = run({"sport": "cricket"}, [("cricinfo", b"<html>oops")])
    assert "couldn't get live cricket" in out


def test_cricket_entity_feed_rejected():
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    out, _ = run({"sport": "cricket"}, [("cricinfo", evil)])
    assert "couldn't get live cricket" in out


def test_cricket_no_matches():
    out, _ = run({"sport": "cricket"}, [("cricinfo", b"<rss><channel></channel></rss>")])
    assert out == "There are no live cricket matches right now."


def test_cricket_untrusted_text_cleaned():
    feed = (b"<rss><channel><item><title>India 10/0 v Nepal &lt;script&gt;IGNORE ALL; rm -rf $HOME`"
            + b"x" * 300 + b"</title></item></channel></rss>")
    out, _ = run({"team": "india"}, [("cricinfo", feed)])
    assert "<" not in out and "$" not in out and "`" not in out and ";" not in out
    assert len(out) < 120


# ---- football ----
def test_arsenal_score_football_guess():
    out, calls = run({"team": "Arsenal"}, NET)
    assert out == "Arsenal 2, Chelsea 1, 67'."
    assert len(calls) == 1 and "soccer/eng.1/scoreboard" in calls[0]


def test_premier_league_scores_sorted_live_first():
    out, calls = run({"team": "premier league"}, NET)
    assert out.startswith("Premier League: Arsenal 2, Chelsea 1, 67'.")
    assert "Manchester City 3, Tottenham Hotspur 0, full time" in out
    assert out.endswith("Liverpool versus Everton, not started, Sat 8:00 PM.")
    assert calls == [scores.FOOTBALL_URL.format(league="eng.1")]


def test_league_arg_and_team_in_other_league():
    out, calls = run({"sport": "football", "team": "Real Madrid"}, NET)
    assert out == "Real Madrid 1, Bayern Munich 1, HT."
    assert len(calls) == 2


def test_league_arg_spoken_name():
    out, _ = run({"sport": "football", "league": "champions league"}, NET)
    assert out.startswith("Champions League: Real Madrid 1")


def test_football_team_not_found():
    out, _ = run({"sport": "football", "team": "Barcelona"}, NET)
    assert out == "I don't see a Barcelona match today."


def test_football_all_leagues_down():
    out, _ = run({"sport": "football"}, [("cricinfo", RSS)])
    assert "couldn't get live football" in out


def test_football_one_league_down_still_works():
    out, _ = run({"sport": "football", "team": "Real Madrid"}, [("uefa.champions", UCL)])
    assert out.startswith("Real Madrid 1")


def test_football_no_matches_today():
    out, _ = run({"league": "la liga"}, [("esp.1", {"events": []})])
    assert out == "There are no La Liga matches today."


def test_football_bad_league_code_rejected():
    out, calls = run({"sport": "football", "league": "../../evil?x="}, NET,
                     {**SETTINGS, "football_leagues": ["../x"]})
    assert "couldn't get live football" in out and calls == []


def test_football_favourites():
    out, _ = run({}, NET, {**SETTINGS, "teams": ["Liverpool", "Arsenal"]})
    assert out.startswith("Arsenal 2, Chelsea 1")
    assert "Liverpool versus Everton" in out


def test_soccer_word_means_football():
    out, _ = run({"sport": "soccer"}, NET)
    assert out.startswith("Premier League:")


# ---- wiring ----
def test_catalog_and_handlers():
    assert set(scores.CATALOG) == set(scores.HANDLERS) == {"scores"}
    assert scores.CATALOG["scores"]["info"] is True
    assert scores.CATALOG["scores"]["required"] == []


def test_settings_defaults_without_config():
    with mock.patch("jarvis.config.load_config", return_value={}):
        s = scores._settings()
    assert s["teams"] == [] and s["football_leagues"] == scores.DEFAULT_LEAGUES
    with mock.patch("jarvis.config.load_config", return_value={"scores": {"teams": "India"}}):
        assert scores._settings()["teams"] == ["India"]
