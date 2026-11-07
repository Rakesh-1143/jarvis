"""Recipes and cook mode (piece BE). Network is faked: recipes._fetch is replaced."""
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import recipes as rc  # noqa: E402
from jarvis.actions import timers  # noqa: E402

PANEER = {
    "idMeal": "1", "strMeal": "Paneer Butter Masala", "strArea": "Indian", "strCategory": "Vegetarian",
    "strInstructions": "STEP 1\r\nHeat butter in a pan.\r\n\r\nSTEP 2\r\nAdd onions and fry for 5-7 minutes.\r\n"
                       "3. Add paneer and simmer for ten minutes.\r\nServe hot.",
    "strIngredient1": "Paneer", "strMeasure1": "200g",
    "strIngredient2": "Butter", "strMeasure2": "2 tbsp",
    "strIngredient3": "Onion", "strMeasure3": "",
    "strIngredient4": "", "strMeasure4": " ",
    "strIngredient5": None,
}
OMELETTE = {"idMeal": "2", "strMeal": "Spanish Omelette", "strArea": "Spanish", "strCategory": "Breakfast",
            "strInstructions": "Beat the eggs. Cook gently.", "strIngredient1": "Eggs", "strMeasure1": "4"}
SHAKSHUKA_SHORT = {"idMeal": "3", "strMeal": "Shakshuka", "strMealThumb": "x"}  # filter.php style (no details)
SHAKSHUKA = {"idMeal": "3", "strMeal": "Shakshuka", "strArea": "Egyptian", "strCategory": "Vegetarian",
             "strInstructions": "Fry the tomatoes.\nCrack in the eggs and cook for 8 minutes.",
             "strIngredient1": "Egg", "strMeasure1": "3", "strIngredient2": "Tomato", "strMeasure2": "4"}


class FakeApi:
    def __init__(self):
        self.calls = []
        self.search = {"paneer butter masala": [PANEER], "paneer": [PANEER], "omelette": [OMELETTE]}
        self.filter = {"egg": [SHAKSHUKA_SHORT, {"idMeal": "2", "strMeal": "Spanish Omelette"}],
                       "tomato": [SHAKSHUKA_SHORT], "chicken": [{"idMeal": "9", "strMeal": "Chicken Curry"}]}
        self.fail = False

    def __call__(self, endpoint, **params):
        self.calls.append((endpoint, params))
        if self.fail:
            raise urllib.error.URLError("offline")
        if endpoint == "search.php":
            return {"meals": self.search.get(params["s"])}
        if endpoint == "filter.php":
            return {"meals": self.filter.get(params["i"])}
        if endpoint == "lookup.php":
            return {"meals": [{"3": SHAKSHUKA, "2": OMELETTE, "1": PANEER}[params["i"]]]}
        if endpoint == "random.php":
            return {"meals": [OMELETTE]}
        return None


@pytest.fixture(autouse=True)
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(rc, "_fetch", fake)
    rc.stop()
    monkeypatch.setattr(rc, "_last_found", None)
    yield fake
    rc.stop()


@pytest.fixture
def timer_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(timers, "timer", lambda args: calls.append(args) or "Timer set.")
    return calls


# ---------- parts ----------

def test_ingredients_of():
    assert rc.ingredients_of(PANEER) == ["200g Paneer", "2 tbsp Butter", "Onion"]


def test_split_steps_drops_step_labels():
    assert rc.split_steps(PANEER["strInstructions"]) == [
        "Heat butter in a pan.", "Add onions and fry for 5-7 minutes.",
        "Add paneer and simmer for ten minutes.", "Serve hot."]


def test_split_steps_long_paragraph():
    text = " ".join(f"Sentence number {i} is here and it is long enough to matter." for i in range(12))
    steps = rc.split_steps(text)
    assert len(steps) > 1
    assert all(len(s) <= rc.MAX_STEP_CHARS for s in steps)
    assert " ".join(steps) == text


def test_split_steps_empty():
    assert rc.split_steps("") == []
    assert rc.split_steps("STEP 1\n2.\n") == []


@pytest.mark.parametrize("text,secs", [
    ("fry for 5-7 minutes", 300), ("simmer for ten minutes", 600), ("bake 1 hour", 3600),
    ("rest for 30 secs", 30), ("cook for half an hour", 1800), ("cook 10 to 15 mins", 600),
    ("bake for 1.5 hours", 5400), ("stir well", 0), ("add 2 cups water", 0), ("cook for a minute", 60),
])
def test_step_seconds(text, secs):
    assert rc.step_seconds(text) == secs


# ---------- recipe intent ----------

def test_find_exact():
    out = rc.recipe({"action": "find", "query": "Paneer Butter Masala"})
    assert "Paneer Butter Masala" in out and "Indian Vegetarian" in out
    assert "3 ingredients and 4 steps" in out
    assert rc._last_found is PANEER


def test_find_close_match(api):
    out = rc.recipe({"action": "find", "query": "spicy paneer"})
    assert "couldn't find spicy paneer exactly" in out and "Paneer Butter Masala" in out


def test_find_none():
    assert rc.recipe({"action": "find", "query": "dragon soup"}) == "I couldn't find a recipe for dragon soup."


def test_find_no_query():
    assert "Which recipe" in rc.recipe({"action": "find"})


def test_random():
    out = rc.recipe({"action": "random"})
    assert "Spanish Omelette" in out and "cook it" in out
    assert rc._last_found is OMELETTE


def test_offline(api):
    api.fail = True
    assert rc.recipe({"action": "find", "query": "paneer"}) == rc.NO_NET
    assert rc.cook({"action": "start", "name": "paneer"}) == rc.NO_NET
    assert not rc.is_active()


def test_by_ingredients_both():
    out = rc.recipe({"action": "by_ingredients", "query": "eggs and tomatoes"})
    assert out.startswith("You can make: Shakshuka")
    assert rc._last_found is SHAKSHUKA_SHORT  # one match: "cook it" works


def test_by_ingredients_one():
    out = rc.recipe({"action": "by_ingredients", "query": "eggs"})
    assert "With eggs you can make: Shakshuka and Spanish Omelette" in out


def test_by_ingredients_unknown_one():
    out = rc.recipe({"action": "by_ingredients", "query": "eggs, unobtainium"})
    assert "I don't know unobtainium" in out and "Shakshuka" in out


def test_by_ingredients_nothing_shared():
    out = rc.recipe({"action": "by_ingredients", "query": "chicken and tomato"})
    assert out.startswith("Nothing uses all of them. With chicken")


def test_by_ingredients_none():
    assert "couldn't find recipes with" in rc.recipe({"action": "by_ingredients", "query": "rocks"})


# ---------- cook mode ----------

def test_cook_flow(timer_calls):
    out = rc.cook({"action": "start", "name": "paneer butter masala"})
    assert rc.is_active()
    assert "Cook mode on for Paneer Butter Masala" in out and "200g Paneer" in out
    assert rc.cook({"action": "repeat"}).startswith("You need:")  # before step 1: repeat = ingredients
    assert rc.cook({"action": "previous"}).startswith("We have not started")
    assert rc.cook({"action": "timer"}).startswith("We have not started")
    out = rc.cook({"action": "next"})
    assert out == "Step 1 of 4: Heat butter in a pan."
    out = rc.cook({"action": "next"})
    assert out.startswith("Step 2 of 4: Add onions") and "start a timer for 5 minutes" in out
    assert rc.cook({"action": "repeat"}) == out
    assert rc.cook({"action": "timer"}) == "Timer set."
    assert timer_calls == [{"seconds": 300, "label": "step 2"}]
    assert rc.cook({"action": "previous"}) == "Step 1 of 4: Heat butter in a pan."
    assert "has no time" in rc.cook({"action": "timer"})
    assert rc.cook({"action": "goto", "step": 4}).endswith("That is the last step.")
    assert "step 4 of 4, 0 left" in rc.cook({"action": "status"})
    assert "only 4 steps" in rc.cook({"action": "goto", "step": 9})
    assert rc.cook({"action": "ingredients"}) == "You need: 200g Paneer; 2 tbsp Butter; Onion."
    assert rc.cook({"action": "stop"}).startswith("Cook mode off")
    assert not rc.is_active()
    rc.cook({"action": "start", "name": "paneer butter masala"})
    rc.cook({"action": "goto", "step": 4})
    assert "last step. Cook mode off" in rc.cook({"action": "next"})  # E1: "next"/"done" after the end stops
    assert not rc.is_active()
    assert rc.cook({"action": "stop"}) == "Cook mode is not on."


def test_cook_not_active():
    assert "not on" in rc.cook({"action": "next"})


def test_cook_it_uses_last_found_and_looks_up_details(api):
    rc.recipe({"action": "by_ingredients", "query": "eggs and tomatoes"})
    out = rc.cook({"action": "start", "name": "it"})
    assert "Cook mode on for Shakshuka" in out and "3 Egg" in out
    assert ("lookup.php", {"i": "3"}) in api.calls


def test_cook_no_name_no_last():
    assert rc.cook({"action": "start"}) == "Which dish should we cook?"


def test_cook_unknown_dish():
    assert rc.cook({"action": "start", "name": "dragon soup"}) == "I couldn't find a recipe for dragon soup."
    assert not rc.is_active()


def test_cook_recipe_without_steps(api):
    api.search["toast"] = [{"idMeal": "5", "strMeal": "Toast", "strInstructions": ""}]
    assert "no steps" in rc.cook({"action": "start", "name": "toast"})
    assert not rc.is_active()


def test_bad_goto():
    rc.cook({"action": "start", "name": "paneer"})
    assert rc.cook({"action": "goto", "step": "x"}) == "Which step number?"


# ---------- match_cook (main.py hook) ----------

def test_match_cook_only_when_active():
    assert rc.match_cook("next") is None


@pytest.mark.parametrize("text,args", [
    ("next", {"action": "next"}), ("Next step.", {"action": "next"}), ("okay next", {"action": "next"}),
    ("Jarvis, next step please", {"action": "next"}), ("what's next?", {"action": "next"}),
    ("go back", {"action": "previous"}), ("previous step", {"action": "previous"}),
    ("repeat", {"action": "repeat"}), ("say that again", {"action": "repeat"}),
    ("what do I need", {"action": "ingredients"}), ("stop cooking", {"action": "stop"}),
    ("start a timer", {"action": "timer"}), ("timer for this step", {"action": "timer"}),
    ("which step am I on", {"action": "status"}),
    ("go to step 3", {"action": "goto", "step": 3}), ("step five", {"action": "goto", "step": 5}),
])
def test_match_cook(text, args):
    rc.cook({"action": "start", "name": "paneer"})
    assert rc.match_cook(text) == ("cook", args)


@pytest.mark.parametrize("text", ["next song", "stop", "what time is it", "set a timer for 5 minutes",
                                  "open chrome", "volume up"])
def test_match_cook_leaves_other_commands(text):
    rc.cook({"action": "start", "name": "paneer"})
    assert rc.match_cook(text) is None


def test_yes_starts_timer_only_when_offered():
    rc.cook({"action": "start", "name": "paneer"})
    rc.cook({"action": "next"})  # step 1: no time
    assert rc.match_cook("yes") is None
    rc.cook({"action": "next"})  # step 2: 5 minutes offered
    assert rc.match_cook("yes") == ("cook", {"action": "timer"})


# ---------- parse (nlu_features) ----------

@pytest.mark.parametrize("text,expected", [
    ("cook paneer butter masala", ("cook", {"action": "start", "name": "paneer butter masala"})),
    ("let's cook chicken curry", ("cook", {"action": "start", "name": "chicken curry"})),
    ("bake a chocolate cake", ("cook", {"action": "start", "name": "chocolate cake"})),
    ("walk me through making biryani", ("cook", {"action": "start", "name": "biryani"})),
    ("start cook mode", ("cook", {"action": "start"})),
    ("cook mode for pasta", ("cook", {"action": "start", "name": "pasta"})),
    ("cook it", ("cook", {"action": "start"})),
    ("Jarvis, let's cook this", ("cook", {"action": "start"})),
    ("recipe for butter chicken", ("recipe", {"action": "find", "query": "butter chicken"})),
    ("find me a recipe for dal", ("recipe", {"action": "find", "query": "dal"})),
    ("show me the lasagne recipe", ("recipe", {"action": "find", "query": "lasagne"})),
    ("how do I cook rice", ("recipe", {"action": "find", "query": "rice"})),
    ("how to make pancakes recipe", ("recipe", {"action": "find", "query": "pancakes"})),
    ("random recipe", ("recipe", {"action": "random"})),
    ("suggest something to cook", ("recipe", {"action": "random"})),
    ("what should I cook tonight", ("recipe", {"action": "random"})),
    ("what can I make with eggs and tomatoes?",
     ("recipe", {"action": "by_ingredients", "query": "eggs and tomatoes"})),
    ("recipes with chicken", ("recipe", {"action": "by_ingredients", "query": "chicken"})),
])
def test_parse(text, expected):
    assert rc.parse(text) == expected


@pytest.mark.parametrize("text", ["cook", "open recipe", "delete the recipe", "how do I make a folder",
                                  "what time is it", "cook something", "next step", "play music"])
def test_parse_none(text):
    assert rc.parse(text) is None


def test_catalog_matches_handlers():
    assert set(rc.CATALOG) == set(rc.HANDLERS) == {"recipe", "cook"}
