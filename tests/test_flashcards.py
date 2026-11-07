"""Tests for flashcards.py (piece AZ). Data goes to a temp file; quiz state is reset after each test."""
import datetime as dt
import json

import pytest

from jarvis.actions import flashcards as fc


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "FLASHCARDS_FILE", str(tmp_path / "flashcards.json"))
    yield
    fc._QUIZ.clear()
    fc._QUIZ["active"] = False


def _data():
    return json.loads(fc._path().read_text(encoding="utf-8"))


def _add(deck, front, back):
    return fc.flashcard_add({"deck": deck, "front": front, "back": back})


def test_catalog_and_handlers_match():
    assert set(fc.CATALOG) == set(fc.HANDLERS) == {"flashcard_add", "flashcard_quiz", "flashcard_status", "deck_delete"}
    assert fc.CATALOG["flashcard_status"].get("info") is True
    for spec in fc.CATALOG.values():
        assert "description" in spec and "properties" in spec


def test_add_creates_deck_and_card():
    reply = _add("Spanish", "hello", "hola")
    assert "Added to Spanish" in reply and "1 card" in reply
    card = _data()["decks"]["spanish"]["cards"][0]
    assert card["front"] == "hello" and card["back"] == "hola" and card["box"] == 1
    assert card["due"] == dt.date.today().isoformat()


def test_add_same_front_updates():
    _add("Spanish", "hello", "ola")
    assert "Updated" in _add("spanish", "Hello", "hola")
    assert len(_data()["decks"]["spanish"]["cards"]) == 1
    assert _data()["decks"]["spanish"]["cards"][0]["back"] == "hola"


def test_add_needs_both_sides_and_default_deck():
    assert "Say it like" in fc.flashcard_add({"front": "x"})
    _add(None, "2+2", "4")
    assert "general" in _data()["decks"]


def test_is_right_is_forgiving():
    assert fc.is_right("Hola", "hola")
    assert fc.is_right("it's hola", "hola")
    assert fc.is_right("cafe", "café")
    assert fc.is_right("paris", "Paris / Paree")
    assert fc.is_right("goodbye", "good bye")
    assert fc.is_right("adios", "adiós")
    assert fc.is_right("the answer is mitochondria", "mitochondria")
    assert fc.is_right("mitocondria", "mitochondria")  # small slip
    assert not fc.is_right("adios", "hola")
    assert not fc.is_right("", "hola")
    assert not fc.is_right("no", "si")


def test_status():
    assert "no flashcards" in fc.flashcard_status({})
    _add("Spanish", "hello", "hola")
    _add("Spanish", "dog", "perro")
    _add("Capitals", "France", "Paris")
    reply = fc.flashcard_status({})
    assert "3 cards due today" in reply and "Spanish has 2 cards, 2 due" in reply
    assert "Capitals has 1 card, 1 due" in fc.flashcard_status({"deck": "capitals"})
    assert "don't have" in fc.flashcard_status({"deck": "german"})


def test_delete_asks_then_deletes():
    _add("Spanish", "hello", "hola")
    assert fc.needs_confirm({"deck": "spanish"})
    assert "Spanish flashcard deck with 1 card" in fc.risky_text({"deck": "spanish"})
    assert "Are you sure" in fc.deck_delete({"deck": "spanish"})
    assert "spanish" in _data()["decks"]
    assert "Deleted" in fc.deck_delete({"deck": "Spanish deck", "confirm": True})
    assert "spanish" not in _data()["decks"]
    assert "don't have" in fc.deck_delete({"deck": "spanish", "confirm": True})


def test_quiz_flow_right_wrong_and_boxes():
    _add("Spanish", "hello", "hola")
    _add("Spanish", "dog", "perro")
    reply = fc.flashcard_quiz({"deck": "spanish"})
    assert fc.is_active() and "2 cards" in reply and "Card 1 of 2: hello?" in reply
    assert fc.process("hola").startswith("Right!")
    reply = fc.process("gato")
    assert "Not quite. It's perro" in reply and "Quiz over" in reply and "1 out of 2" in reply
    assert not fc.is_active()
    cards = {c["front"]: c for c in _data()["decks"]["spanish"]["cards"]}
    today = dt.date.today()
    assert cards["hello"]["box"] == 2 and cards["hello"]["due"] == (today + dt.timedelta(days=2)).isoformat()
    assert cards["dog"]["box"] == 1 and cards["dog"]["due"] == (today + dt.timedelta(days=1)).isoformat()
    assert cards["hello"]["right"] == 1 and cards["dog"]["wrong"] == 1


def test_wrong_answer_sends_card_back_to_box_one():
    _add("Spanish", "hello", "hola")
    d = _data()
    d["decks"]["spanish"]["cards"][0]["box"] = 4
    fc._save(d)
    fc.flashcard_quiz({})
    fc.process("adios")
    assert _data()["decks"]["spanish"]["cards"][0]["box"] == 1


def test_box_caps_at_max():
    _add("Spanish", "hello", "hola")
    d = _data()
    d["decks"]["spanish"]["cards"][0]["box"] = fc.MAX_BOX
    fc._save(d)
    fc.flashcard_quiz({})
    fc.process("hola")
    card = _data()["decks"]["spanish"]["cards"][0]
    assert card["box"] == fc.MAX_BOX
    assert card["due"] == (dt.date.today() + dt.timedelta(days=2 ** (fc.MAX_BOX - 1))).isoformat()


def test_quiz_stop_skip_repeat_dont_know_score():
    for w in ("one", "two", "three"):
        _add("Numbers", w, w + "x")
    fc.flashcard_quiz({"deck": "numbers"})
    assert fc.process("repeat") == "Card 1 of 3: one?"
    assert "Skipped. It was onex" in fc.process("skip")
    assert _data()["decks"]["numbers"]["cards"][0]["box"] == 1  # skip does not move the card
    assert _data()["decks"]["numbers"]["cards"][0]["due"] == dt.date.today().isoformat()
    assert "It's twox" in fc.process("I don't know")
    assert _data()["decks"]["numbers"]["cards"][1]["wrong"] == 1
    assert "0 out of 1" in fc.process("what's my score")
    reply = fc.process("stop")
    assert "Quiz over" in reply and not fc.is_active()


@pytest.mark.parametrize("word", ["stop", "Stop.", "enough", "that's enough", "I'm done", "cancel", "stop the quiz"])
def test_stop_words_end_quiz(word):
    _add("Spanish", "hello", "hola")
    fc.flashcard_quiz({})
    assert "Quiz over" in fc.process(word)
    assert not fc.is_active()


def test_takes_lets_clear_commands_through():
    _add("Verbs", "to open", "open")
    fc.flashcard_quiz({})
    assert fc.takes("stop", "cancel")
    assert fc.takes("skip", "media")
    assert fc.takes("perro", "unknown")
    assert fc.takes("open", "open_app")  # the expected answer wins even if it looks like a command
    assert not fc.takes("open chrome", "open_app")
    assert not fc.takes("what time is it", "time")
    assert fc.is_active()  # a command does not end the quiz
    fc.stop()
    assert not fc.takes("perro", "unknown")


def test_quiz_nothing_due_and_no_decks():
    assert "no flashcards" in fc.flashcard_quiz({})
    _add("Spanish", "hello", "hola")
    d = _data()
    d["decks"]["spanish"]["cards"][0]["due"] = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    fc._save(d)
    reply = fc.flashcard_quiz({"deck": "spanish"})
    assert "No Spanish cards are due" in reply and "tomorrow" in reply
    assert not fc.is_active()
    assert "don't have" in fc.flashcard_quiz({"deck": "klingon"})


def test_quiz_size_and_hardest_first():
    for i in range(fc.QUIZ_SIZE + 5):
        _add("Big", f"q{i}", f"a{i}")
    d = _data()
    d["decks"]["big"]["cards"][7]["box"] = 1
    for c in d["decks"]["big"]["cards"]:
        if c["front"] != "q7":
            c["box"] = 3
    fc._save(d)
    reply = fc.flashcard_quiz({"deck": "big"})
    assert f"{fc.QUIZ_SIZE} cards" in reply and "q7?" in reply


def test_quiz_times_out(monkeypatch):
    _add("Spanish", "hello", "hola")
    fc.flashcard_quiz({})
    fc._QUIZ["last"] -= fc.QUIZ_TIMEOUT + 1
    assert not fc.is_active()
    assert "no flashcard quiz" in fc.process("hola")


def test_bad_file_is_ignored():
    fc._path().parent.mkdir(parents=True, exist_ok=True)
    fc._path().write_text("{not json", encoding="utf-8")
    assert "no flashcards" in fc.flashcard_status({})
    _add("Spanish", "hello", "hola")
    assert "spanish" in _data()["decks"]


def test_delete_deck_ends_its_quiz():
    _add("Spanish", "hello", "hola")
    fc.flashcard_quiz({})
    fc.deck_delete({"deck": "spanish", "confirm": True})
    assert not fc.is_active()


@pytest.mark.parametrize("text,expected", [
    ("add flashcard to Spanish hello means hola", ("flashcard_add", {"deck": "spanish", "front": "hello", "back": "hola"})),
    ("add a flashcard to spanish deck: good night means buenas noches",
     ("flashcard_add", {"deck": "spanish", "front": "good night", "back": "buenas noches"})),
    ("Jarvis add flashcard the capital of France is Paris",
     ("flashcard_add", {"deck": "general", "front": "the capital of France", "back": "Paris"})),
    ("new card in biology: powerhouse of the cell answer mitochondria",
     ("flashcard_add", {"deck": "biology", "front": "powerhouse of the cell", "back": "mitochondria"})),
    ("how many flashcards are due", ("flashcard_status", {})),
    ("how many cards are due in Spanish", ("flashcard_status", {"deck": "spanish"})),
    ("what decks do I have", ("flashcard_status", {})),
    ("delete the Spanish deck", ("deck_delete", {"deck": "spanish"})),
    ("delete my spanish flashcards", ("deck_delete", {"deck": "spanish"})),
    ("quiz me on my spanish flashcards", ("flashcard_quiz", {"deck": "spanish"})),
    ("quiz me on flashcards", ("flashcard_quiz", {})),
    ("study my flashcards", ("flashcard_quiz", {})),
    ("practice spanish flashcards", ("flashcard_quiz", {"deck": "spanish"})),
])
def test_parse(text, expected):
    assert fc.parse(text) == expected


def test_parse_known_multiword_deck_and_fun_quiz_untouched():
    _add("World capitals", "France", "Paris")
    assert fc.parse("add flashcard to world capitals Japan means Tokyo") == (
        "flashcard_add", {"deck": "world capitals", "front": "Japan", "back": "Tokyo"})
    assert fc.parse("quiz me on world capitals") == ("flashcard_quiz", {"deck": "world capitals"})
    assert fc.parse("study world capitals") == ("flashcard_quiz", {"deck": "world capitals"})
    for text in ("quiz me", "quiz me on maths", "quiz me on general knowledge", "open chrome", "what time is it"):
        assert fc.parse(text) is None


def test_main_hook_shape_with_fakes():
    """What the wiring note asks main.handle to do, with a fake nlu."""
    _add("Spanish", "hello", "hola")
    fc.flashcard_quiz({})

    def handle(text, intent):
        if fc.is_active() and fc.takes(text, intent):
            return fc.process(text)
        return f"ran {intent}"

    assert handle("open chrome", "open_app") == "ran open_app"
    assert handle("hola", "unknown").startswith("Right!")
    assert handle("open chrome", "open_app") == "ran open_app"
