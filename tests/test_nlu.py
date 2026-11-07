import pytest

from jarvis.nlu import Command, parse

CASES = [
    ("open chrome", "open_app", {"name": "chrome"}),
    ("Jarvis, can you please open the notepad app", "open_app", {"name": "notepad"}),
    ("launch spotify", "open_app", {"name": "spotify"}),
    ("close notepad", "close_app", {"name": "notepad"}),
    ("quit chrome please", "close_app", {"name": "chrome"}),
    ("search for python tutorials", "web_search", {"query": "python tutorials"}),
    ("google weather today", "web_search", {"query": "weather today"}),
    ("look up cricket score on google", "web_search", {"query": "cricket score"}),
    ("what is machine learning", "web_search", {"query": "what is machine learning"}),
    ("volume up", "volume", {"change": "up"}),
    ("make it louder", "volume", {"change": "up"}),
    ("turn the volume down", "volume", {"change": "down"}),
    ("set volume to 40", "volume", {"level": 40}),
    ("volume 75 percent", "volume", {"level": 75}),
    ("volume max", "volume", {"level": 100}),
    ("mute", "volume", {"change": "mute"}),
    ("unmute the sound", "volume", {"change": "unmute"}),
    ("brightness 70", "brightness", {"level": 70}),
    ("increase brightness", "brightness", {"change": "up"}),
    ("dim the screen", "brightness", {"change": "down"}),
    ("set brightness to fifty", "brightness", {"level": 50}),
    ("take a screenshot", "screenshot", {}),
    ("capture the screen", "screenshot", {}),
    ("what time is it", "time", {}),
    ("what's the time", "time", {}),
    ("lock the laptop", "lock", {}),
    ("shut down", "shutdown", {}),
    ("shutdown the computer", "shutdown", {}),
    ("shut down the laptop now", "shutdown", {}),
    ("turn off the computer", "shutdown", {}),
    ("restart", "restart", {}),
    ("reboot the pc", "restart", {}),
    ("yes", "confirm", {}),
    ("do it", "confirm", {}),
    ("no", "cancel", {}),
    ("cancel", "cancel", {}),
    ("blah blah", "unknown", {"text": "blah blah"}),
    ("", "unknown", {"text": ""}),
]


@pytest.mark.parametrize("text,intent,args", CASES)
def test_parse(text, intent, args):
    assert parse(text) == Command(intent, args)


def test_type_text_keeps_case():
    assert parse("type Hello World") == Command("type_text", {"text": "Hello World"})


def test_type_does_not_trigger_other_intents():
    assert parse("type shut down").intent == "type_text"


def test_none_safe():
    assert parse("   ").intent == "unknown"


def test_power_words_inside_other_sentences_do_nothing_risky():
    for text in ("restart chrome", "restart the song", "yes restart chrome", "press caps lock",
                 "open lock screen settings", "yes shut down", "reboot I'm sure"):
        cmd = parse(text)
        assert cmd.intent not in ("restart", "lock", "shutdown"), text
        assert not cmd.args.get("confirm"), text
