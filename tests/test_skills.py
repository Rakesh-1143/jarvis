import time

import pytest

from jarvis.skills import productivity
from jarvis.skills.basic import safe_eval


def match(j, text):
    hit = j.registry.match(text)
    return (hit[0].name, hit[1]) if hit else (None, {})


@pytest.mark.parametrize("text,name", [
    ("what time is it", "get_time"),
    ("what's the date today", "get_date"),
    ("hello jarvis", "greet"),
    ("tell me a joke", "tell_joke"),
    ("what is 12 times 3", "calculate"),
    ("what's the weather in Paris", "get_weather"),
    ("weather", "get_weather"),
    ("tell me about Albert Einstein", "wikipedia"),
    ("search for best python books", "web_search"),
    ("what's the news", "get_news"),
    ("open youtube", "open_website"),
    ("open github.com", "open_website"),
    ("open notepad", "open_app"),
    ("play believer by imagine dragons", "play_youtube"),
    ("system status", "system_info"),
    ("take a screenshot", "screenshot"),
    ("volume up", "volume"),
    ("mute", "volume"),
    ("shutdown the computer", "power"),
    ("lock the screen", "power"),
    ("remind me to call mom in 10 minutes", "set_reminder"),
    ("set a timer for 5 minutes", "set_timer"),
    ("take a note buy milk", "add_note"),
    ("read my notes", "read_notes"),
    ("add finish homework to my to do list", "add_todo"),
    ("show my to do list", "list_todos"),
    ("remember that my birthday is on May 5", "remember"),
    ("what do you know about me", "recall"),
    ("help", "help"),
])
def test_routing(jarvis, text, name):
    assert match(jarvis, text)[0] == name


def test_unknown_goes_to_ai(jarvis):
    assert match(jarvis, "why is the sky blue")[0] is None
    assert "help" in jarvis.handle("why is the sky blue").lower()


def test_calculator(jarvis):
    assert jarvis.handle("what is 12 times 3") == "The answer is 36."
    assert jarvis.handle("calculate (2 + 3) ^ 2") == "The answer is 25."
    assert jarvis.handle("what is the square root of 81") == "The answer is 9."
    assert jarvis.handle("calculate 20 percent of 50") == "The answer is 10."
    with pytest.raises(ValueError):
        safe_eval("__import__('os')")


def test_wake_word_stripped(jarvis):
    assert jarvis.handle("Hey Jarvis, what is 2 plus 2") == "The answer is 4."


def test_notes_todos_memory(jarvis):
    jarvis.handle("take a note buy milk")
    assert "buy milk" in jarvis.handle("read my notes")
    jarvis.handle("add finish homework to my to do list")
    assert "finish homework" in jarvis.handle("show my to do list")
    assert "1 task" in jarvis.handle("mark homework as done")
    assert "empty" in jarvis.handle("show my to do list")
    jarvis.handle("remember that my favourite color is blue")
    assert "your favourite color is blue" in jarvis.handle("what do you know about me")
    assert "Forgotten 1" in jarvis.handle("forget color")


def test_shutdown_needs_confirm(jarvis):
    assert "confirm shutdown" in jarvis.handle("shutdown the computer")


def test_durations_and_clock():
    assert productivity.parse_duration("in 10 minutes") == 600
    assert productivity.parse_duration("an hour and 30 minutes") == 5400
    assert productivity.parse_duration("half an hour") == 1800
    assert productivity.parse_duration("at 5 pm") is None
    import datetime as dt
    now = dt.datetime(2026, 1, 1, 18, 0)
    assert productivity.parse_clock("at 5 pm", now) == dt.datetime(2026, 1, 2, 17, 0)
    assert productivity.parse_clock("at 7:30 pm", now) == dt.datetime(2026, 1, 1, 19, 30)


def test_reminder_fires(jarvis):
    reply = jarvis.handle("remind me in 1 second to drink water")
    assert "drink water" in reply
    productivity.start_scheduler(jarvis.ctx, interval=0.1)
    time.sleep(1.5)
    jarvis.stop()
    assert jarvis.notified == ["Reminder: drink water."]
