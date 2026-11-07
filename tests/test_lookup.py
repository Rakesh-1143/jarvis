"""Piece N: lookup. All network calls are faked (no internet in tests)."""
import os
import sys
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import lookup  # noqa: E402

DICT = [{"word": "serendipity", "meanings": [
    {"partOfSpeech": "noun", "definitions": [
        {"definition": "A combination of events which have come about by chance to make a surprisingly good result.",
         "example": "It was pure serendipity."},
        {"definition": "Second meaning."}]},
    {"partOfSpeech": "noun", "definitions": [{"definition": "Duplicate noun, skipped."}]},
    {"partOfSpeech": "verb", "definitions": [{"definition": "Made-up verb sense"}]},
]}]
WIKI_PARIS = {"type": "standard", "title": "Paris",
              "extract": "Paris is the capital of France. It has about 2 million people. It is on the Seine."}
WIKI_DISAMBIG = {"type": "disambiguation", "title": "Mercury", "extract": "Mercury may refer to:"}
WIKI_PLANET = {"type": "standard", "title": "Mercury (planet)",
               "extract": "Mercury is the first planet from the Sun. It is the smallest planet. More text."}


def fake(routes):
    """routes: list of (substring, result). Result may be an Exception to raise."""
    calls = []

    def _get(url):
        calls.append(url)
        for key, val in routes:
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        return None
    return _get, calls


def run(func, args, routes):
    g, calls = fake(routes)
    with mock.patch.object(lookup, "_get_json", g), \
         mock.patch.object(lookup, "_settings", return_value={"wiki_lang": "en", "sentences": 2}):
        return func(args), calls


# ---- define ----
def test_define_two_parts_of_speech_with_example():
    out, calls = run(lookup.define, {"word": "Serendipity"}, [("dictionaryapi", DICT)])
    assert out.startswith("Serendipity. As a noun: A combination")
    assert "For example: It was pure serendipity." in out
    assert "As a verb: Made-up verb sense." in out
    assert "Duplicate" not in out and "Second meaning" not in out
    assert calls[0].endswith("/entries/en/serendipity")


def test_define_cleans_spoken_words():
    _, calls = run(lookup.define, {"word": "the word 'hello'?"}, [("dictionaryapi", DICT)])
    assert calls[0].endswith("/en/hello")


def test_define_not_found_and_offline_and_empty():
    assert "couldn't find a meaning for blarg" in run(lookup.define, {"word": "blarg"}, [])[0]
    assert run(lookup.define, {"word": "x"}, [("dictionaryapi", OSError("down"))])[0] == lookup.NO_NET
    assert run(lookup.define, {}, [])[0] == "Which word should I define?"


# ---- wikipedia ----
def test_wikipedia_two_sentences():
    out, calls = run(lookup.wikipedia, {"topic": "Paris"}, [("summary/Paris", WIKI_PARIS)])
    assert out == "Paris is the capital of France. It has about 2 million people."
    assert len(calls) == 1


def test_wikipedia_strips_who_is_and_uses_underscores():
    _, calls = run(lookup.wikipedia, {"topic": "who is Albert Einstein?"}, [("summary/Albert_Einstein", WIKI_PARIS)])
    assert calls[0].endswith("summary/Albert_Einstein")


def test_wikipedia_falls_back_to_search_when_missing():
    routes = [("opensearch", ["paris city", ["Paris"], [""], [""]]), ("summary/Paris", WIKI_PARIS)]
    out, calls = run(lookup.wikipedia, {"topic": "paris city"}, routes)
    assert out.startswith("Paris is the capital")
    assert any("opensearch" in c for c in calls)


def test_wikipedia_disambiguation_uses_search_result():
    routes = [("summary/Mercury_%28planet%29", WIKI_PLANET), ("opensearch", ["mercury", ["Mercury (planet)"]]),
              ("summary/Mercury", WIKI_DISAMBIG)]
    out, _ = run(lookup.wikipedia, {"topic": "Mercury"}, routes)
    assert out == "Mercury is the first planet from the Sun. It is the smallest planet."


def test_wikipedia_still_ambiguous_and_not_found_and_offline():
    routes = [("opensearch", ["mercury", ["Mercury"]]), ("summary/Mercury", WIKI_DISAMBIG)]
    assert "can mean several things" in run(lookup.wikipedia, {"topic": "Mercury"}, routes)[0]
    assert "couldn't find zzqx on Wikipedia" in run(lookup.wikipedia, {"topic": "zzqx"}, [])[0]
    assert run(lookup.wikipedia, {"topic": "x"}, [("summary", OSError())])[0] == lookup.NO_NET
    assert "What should I look up" in run(lookup.wikipedia, {"topic": "  "}, [])[0]


def test_first_sentences_keeps_abbreviations():
    t = "Dr. Smith was born in 1950. He was a doctor. He died."
    assert lookup._first_sentences(t, 2) == "Dr. Smith was born in 1950. He was a doctor."
    assert lookup._first_sentences("J. R. R. Tolkien was a writer. He wrote books. Third.", 1) \
        == "J. R. R. Tolkien was a writer."


# ---- spell ----
def test_spell():
    assert lookup.spell({"word": "Cat"}) == "Cat is spelled: C, A, T."
    assert lookup.spell({"word": "spell well-being"}) == \
        "Well-being is spelled: W, E, L, L, dash, B, E, I, N, G."
    assert lookup.spell({}) == "Which word should I spell?"


# ---- synonyms ----
def test_synonyms_and_antonyms():
    data = [{"word": "glad"}, {"word": "joyful"}, {"word": "happy"}]
    out, calls = run(lookup.synonyms, {"word": "happy"}, [("rel_syn", data)])
    assert out == "Words like happy: glad, joyful."
    out, calls = run(lookup.synonyms, {"word": "happy", "kind": "antonyms"}, [("rel_ant", [{"word": "sad"}])])
    assert out == "Opposites happy: sad."
    assert "rel_ant=happy" in calls[0]


def test_synonyms_fallback_means_like_and_none():
    out, calls = run(lookup.synonyms, {"word": "laptop"}, [("rel_syn", []), ("ml=", [{"word": "notebook"}])])
    assert out == "Words like laptop: notebook."
    assert "couldn't find synonyms" in run(lookup.synonyms, {"word": "qq"}, [])[0]
    assert run(lookup.synonyms, {"word": "a"}, [("datamuse", OSError())])[0] == lookup.NO_NET


# ---- http helper ----
def test_get_json_404_returns_none_other_errors_raise():
    err404 = urllib.error.HTTPError("u", 404, "nf", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err404):
        assert lookup._get_json("https://x") is None
    err500 = urllib.error.HTTPError("u", 500, "bad", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err500):
        try:
            lookup._get_json("https://x")
            assert False
        except urllib.error.HTTPError:
            pass


# ---- wiring shape ----
def test_catalog_matches_handlers():
    assert set(lookup.CATALOG) == set(lookup.HANDLERS) == {"define", "wikipedia", "spell", "synonyms"}
    for name, spec in lookup.CATALOG.items():
        assert spec["description"] and "properties" in spec and "required" in spec
    assert lookup.CATALOG["define"]["info"] and lookup.CATALOG["wikipedia"]["info"]
    assert lookup.CATALOG["synonyms"]["info"] and not lookup.CATALOG["spell"].get("info")
