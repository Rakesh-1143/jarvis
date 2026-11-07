"""Fun and quiz (piece R). Offline, no mocks needed."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import fun  # noqa: E402


@pytest.fixture(autouse=True)
def reset_quiz():
    fun._QUIZ_STATE.update(question=None, answers=(), asked_at=0.0, right=0, asked=0)
    yield


def test_catalog_matches_handlers():
    assert set(fun.CATALOG) == set(fun.HANDLERS) == {"random_pick", "quiz"}
    for spec in fun.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)


def test_coin():
    for _ in range(20):
        assert fun.random_pick({"kind": "coin"}) in ("It's heads.", "It's tails.")
    reply = fun.random_pick({"kind": "coin", "count": 3})
    m = re.search(r"(\d) heads and (\d) tails", reply)
    assert m and int(m.group(1)) + int(m.group(2)) == 3


def test_dice_range_and_count():
    for _ in range(50):
        n = int(re.search(r"\d+", fun.random_pick({"kind": "dice"})).group())
        assert 1 <= n <= 6
    reply = fun.random_pick({"kind": "dice", "count": "two", "sides": 20})
    rolls = [int(x) for x in re.search(r"rolled ([\d, ]+)\.", reply).group(1).split(", ")]
    assert len(rolls) == 2 and all(1 <= r <= 20 for r in rolls)
    assert f"Total {sum(rolls)}" in reply


def test_dice_limits():
    reply = fun.random_pick({"kind": "dice", "count": 999, "sides": 1})
    rolls = re.search(r"rolled ([\d, ]+)\.", reply).group(1).split(", ")
    assert len(rolls) == fun.MAX_DICE
    assert all(1 <= int(r) <= 2 for r in rolls)


def test_number_range_and_swap():
    for _ in range(50):
        n = int(fun.random_pick({"kind": "number", "low": 10, "high": 5}).rstrip("."))
        assert 5 <= n <= 10
    assert fun.random_pick({"kind": "number", "low": 7, "high": 7}) == "7."


def test_choice():
    for _ in range(20):
        reply = fun.random_pick({"kind": "choice", "options": "pizza, pasta or burger"})
        assert reply in ("I pick pizza.", "I pick pasta.", "I pick burger.")
    assert "at least two" in fun.random_pick({"kind": "choice", "options": ["tea"]})
    assert fun.split_options("Tea or tea or coffee") == ["Tea", "coffee"]


def test_rps():
    assert fun.random_pick({"kind": "rps"}).startswith("I choose ")
    for _ in range(30):
        reply = fun.random_pick({"kind": "rps", "move": "rock"})
        if "scissors" in reply.split(".")[0]:
            assert "you win" in reply
        elif "paper" in reply.split(".")[0]:
            assert "I win" in reply
        else:
            assert "tie" in reply


def test_unknown_kind():
    assert "coin" in fun.random_pick({"kind": "lottery"})


def test_quiz_flow(monkeypatch):
    monkeypatch.setattr(fun, "_maths_question", lambda: ("What is 2 plus 2?", ("4",)))
    monkeypatch.setattr(fun._rng, "random", lambda: 0.0)  # always maths
    reply = fun.quiz({})
    assert "What is 2 plus 2?" in reply and fun.quiz_pending()
    reply = fun.quiz({"action": "answer", "answer": "I think it's four"})
    assert reply.startswith("Correct!") and "1 out of 1" in reply
    reply = fun.quiz({"answer": "5"})  # no action = answer while pending
    assert reply.startswith("Not quite. It's 4.") and "1 out of 2" in reply
    assert fun.quiz({"action": "score"}) == "You got 1 out of 3."
    assert "1 out of 3" in fun.quiz({"action": "stop"})
    assert not fun.quiz_pending()


def test_quiz_gk_answers():
    assert fun._is_right("paris", ("Paris",))
    assert fun._is_right("the answer is New Delhi", ("New Delhi", "Delhi"))
    assert fun._is_right("seven", ("7", "seven"))
    assert fun._is_right("forty two", ("42",))
    assert fun._is_right("zero", ("0", "zero"))
    assert not fun._is_right("london", ("Paris",))
    assert not fun._is_right("", ("Paris",))
    assert not fun._is_right("17", ("7",))


def test_quiz_skip_and_timeout(monkeypatch):
    fun.quiz({"action": "start", "topic": "gk"})
    first = fun._QUIZ_STATE["answers"][0]
    assert fun.quiz({"action": "skip"}).startswith(f"The answer was {first}.")
    monkeypatch.setattr(fun.time, "time", lambda: fun._QUIZ_STATE["asked_at"] + fun.QUIZ_TIMEOUT + 1)
    assert not fun.quiz_pending()
    assert "no question" in fun.quiz({"action": "answer", "answer": "x"})


def test_quiz_all_gk_questions_valid():
    for question, answers in fun.GK_QUESTIONS:
        assert question.endswith("?") and answers
        assert fun._is_right(answers[0], answers)


@pytest.mark.parametrize("text,intent,args", [
    ("flip a coin", "random_pick", {"kind": "coin", "count": 1}),
    ("heads or tails", "random_pick", {"kind": "coin", "count": 1}),
    ("toss three coins", "random_pick", {"kind": "coin", "count": 3}),
    ("roll a dice", "random_pick", {"kind": "dice"}),
    ("roll", "random_pick", {"kind": "dice"}),
    ("roll two dice", "random_pick", {"kind": "dice", "count": 2}),
    ("roll a 20 sided die", "random_pick", {"kind": "dice", "sides": 20}),
    ("roll a d12", "random_pick", {"kind": "dice", "sides": 12}),
    ("roll 3d8", "random_pick", {"kind": "dice", "count": 3, "sides": 8}),
    ("give me a random number between 5 and 50", "random_pick", {"kind": "number", "low": 5, "high": 50}),
    ("pick a number up to 10", "random_pick", {"kind": "number", "low": 1, "high": 10}),
    ("random number", "random_pick", {"kind": "number"}),
    ("pick one: pizza or pasta", "random_pick", {"kind": "choice", "options": ["pizza", "pasta"]}),
    ("help me decide between tea, coffee and juice", "random_pick",
     {"kind": "choice", "options": ["tea", "coffee", "juice"]}),
    ("should i watch a movie or read a book", "random_pick",
     {"kind": "choice", "options": ["a movie", "read a book"]}),
    ("let's play rock paper scissors", "random_pick", {"kind": "rps"}),
    ("i choose paper", "random_pick", {"kind": "rps", "move": "paper"}),
    ("Jarvis, quiz me", "quiz", {"action": "start"}),
    ("ask me a question", "quiz", {"action": "start"}),
    ("start a maths quiz", "quiz", {"action": "start", "topic": "maths"}),
    ("stop the quiz", "quiz", {"action": "stop"}),
    ("what's my quiz score", "quiz", {"action": "score"}),
])
def test_parse(text, intent, args):
    assert fun.parse(text) == (intent, args)


@pytest.mark.parametrize("text", ["open chrome", "roll down the volume", "what time is it", "",
                                  "why did the dinosaurs die", "skip"])
def test_parse_ignores_other_commands(text):
    assert fun.parse(text) is None


def test_parse_skip_only_during_quiz():
    fun.quiz({"action": "start"})
    assert fun.parse("skip") == ("quiz", {"action": "skip"})
    assert fun.parse("I don't know") == ("quiz", {"action": "skip"})
