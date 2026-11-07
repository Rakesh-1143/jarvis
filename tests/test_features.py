"""New features: nlu rules + actions. OS / network calls are mocked."""
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from types import SimpleNamespace as NS
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis import actions  # noqa: E402
from jarvis.actions import desktop, files, info, radios, system, timers  # noqa: E402
from jarvis.nlu import Command, _clock_seconds, parse  # noqa: E402


@dataclass
class Cmd:
    intent: str
    args: dict = field(default_factory=dict)


def setup_function(_):
    actions._pending = None


NLU_CASES = [
    ("set a timer for five minutes", "timer", {"seconds": 300}),
    ("start a timer for 1 hour and 30 minutes", "timer", {"seconds": 5400}),
    ("remind me to call mom in 10 minutes", "reminder", {"seconds": 600, "text": "call mom"}),
    ("remind me in twenty five minutes to check the oven", "reminder", {"seconds": 1500, "text": "check the oven"}),
    ("remind me to restart the server in an hour", "reminder", {"seconds": 3600, "text": "restart the server"}),
    ("cancel all timers", "timers", {"action": "cancel"}),
    ("stop the timer", "timers", {"action": "cancel"}),
    ("what timers do I have", "timers", {"action": "list"}),
    ("take a note buy milk", "add_note", {"text": "buy milk"}),
    ("write down meeting at 3", "add_note", {"text": "meeting at 3"}),
    ("read my notes", "read_notes", {}),
    ("send an email to mom about dinner", "email", {"to": "mom", "subject": "dinner"}),
    ("write an email", "email", {}),
    ("go to sleep", "sleep", {}),
    ("empty the recycle bin", "empty_recycle_bin", {}),
    ("turn off wifi", "wifi", {"state": "off"}),
    ("turn on the wi-fi", "wifi", {"state": "on"}),
    ("open wifi settings", "wifi", {}),
    ("bluetooth on", "bluetooth", {"state": "on"}),
    ("minimize this window", "window", {"action": "minimize"}),
    ("maximise window", "window", {"action": "maximize"}),
    ("close this window", "window", {"action": "close"}),
    ("show desktop", "window", {"action": "show_desktop"}),
    ("switch window", "window", {"action": "switch"}),
    ("snap window left", "window", {"action": "snap_left"}),
    ("pause", "media", {"action": "play_pause"}),
    ("play some music", "media", {"action": "play_pause"}),
    ("next song", "media", {"action": "next"}),
    ("previous track", "media", {"action": "previous"}),
    ("stop the music", "media", {"action": "stop"}),
    ("play lofi beats on youtube", "play", {"query": "lofi beats"}),
    ("open downloads", "open_folder", {"name": "downloads"}),
    ("open my documents folder", "open_folder", {"name": "documents"}),
    ("open file budget report", "open_file", {"name": "budget report"}),
    ("how much battery is left", "system_info", {"what": "battery"}),
    ("cpu usage", "system_info", {"what": "cpu"}),
    ("how much ram", "system_info", {"what": "memory"}),
    ("disk space", "system_info", {"what": "disk"}),
    ("system status", "system_info", {"what": "all"}),
    ("what's the weather", "weather", {}),
    ("weather in new york today", "weather", {"city": "new york"}),
    ("will it rain tomorrow", "weather", {}),
    ("latest news", "news", {}),
    ("what is the news", "news", {}),
    ("cricket news", "news", {"topic": "cricket"}),
    ("news about the election", "news", {"topic": "the election"}),
    ("what's the date", "time", {}),
    ("tell me a joke", "unknown", {"text": "tell me a joke"}),
]


@pytest.mark.parametrize("text,intent,args", NLU_CASES)
def test_new_nlu_rules(text, intent, args):
    assert parse(text) == Command(intent, args)


def test_clock_reminder():
    now = dt.datetime(2026, 1, 1, 14, 0)
    assert _clock_seconds("at 5 pm", now) == 3 * 3600
    assert _clock_seconds("at five thirty p m", now) == 3 * 3600 + 1800
    assert _clock_seconds("at 9 am", now) == 19 * 3600  # tomorrow
    assert _clock_seconds("at a cafe", now) == 0


# ---------- timers ----------
def test_timer_fires_and_notifies():
    said = []
    actions.set_notifier(said.append)
    with mock.patch.object(timers, "_beep"):
        assert actions.run(Cmd("timer", {"seconds": 1})) == "Timer set for 1 second."
        assert "1 second" in actions.run(Cmd("timers", {"action": "list"}))
        deadline = time.time() + 3
        while not said and time.time() < deadline:
            time.sleep(0.05)
    assert said == ["Your timer is done."]
    actions.set_notifier(print)


def test_reminder_and_cancel():
    assert actions.run(Cmd("reminder", {"seconds": 600, "text": "stretch"})) == "Okay, I will remind you in 10 minutes."
    assert actions.run(Cmd("reminder", {"seconds": 600})) == "What should I remind you about?"
    assert actions.run(Cmd("timers", {"action": "cancel"})) == "Cancelled 1 timer."
    assert actions.run(Cmd("timers", {"action": "list"})) == "You have no timers or reminders."


# ---------- info ----------
WTTR = {
    "current_condition": [{"temp_C": "31", "temp_F": "88", "weatherDesc": [{"value": "Partly cloudy"}]}],
    "nearest_area": [{"areaName": [{"value": "Pune"}]}],
    "weather": [{"maxtempC": "33", "mintempC": "22", "hourly": [{"chanceofrain": "10"}, {"chanceofrain": "60"}]}],
}


def test_weather():
    with mock.patch.object(info, "_get", return_value=json.dumps(WTTR).encode()):
        r = actions.run(Cmd("weather"))
    assert r == "In Pune it's 31 degrees and partly cloudy. Today's high is 33, low 22. Chance of rain up to 60 percent."


def test_weather_offline():
    with mock.patch.object(info, "_get", side_effect=OSError):
        assert "couldn't get the weather" in actions.run(Cmd("weather", {"city": "x"}))


RSS = b"""<rss><channel><item><title>Big thing happens - Daily News</title></item>
<item><title>Second story - Other</title></item><item><title>Third - X</title></item>
<item><title>Fourth - X</title></item></channel></rss>"""


def test_news():
    with mock.patch.object(info, "_get", return_value=RSS) as g:
        r = actions.run(Cmd("news", {"topic": "space"}))
    assert r == "Top news about space: 1. Big thing happens. ... 2. Second story. ... 3. Third."
    assert "q=space" in g.call_args[0][0]


def test_system_info():
    fake = NS(
        sensors_battery=lambda: NS(percent=81.4, power_plugged=False, secsleft=5400),
        cpu_percent=lambda interval: 12.0,
        virtual_memory=lambda: NS(percent=40.0, available=8 * 2**30),
        disk_usage=lambda p: NS(free=100 * 2**30, total=500 * 2**30),
    )
    with mock.patch.dict(sys.modules, {"psutil": fake}):
        assert actions.run(Cmd("system_info", {"what": "battery"})) == "Battery is at 81 percent, about 1 hours 30 minutes left."
        r = actions.run(Cmd("system_info", {"what": "all"}))
    assert "CPU is at 12 percent." in r and "8.0 gigabytes free" in r and "100 gigabytes free of 500" in r


# ---------- desktop ----------
def test_media_and_window_keys():
    fake = mock.Mock()
    with mock.patch.dict(sys.modules, {"pyautogui": fake}):
        assert actions.run(Cmd("media", {"action": "next"})) == "Next track."
        fake.press.assert_called_with("nexttrack")
        assert actions.run(Cmd("window", {"action": "show_desktop"})) == "Showing the desktop."
        fake.hotkey.assert_called_with("win", "d")
    assert "I can minimize" in actions.run(Cmd("window", {"action": "fly"}))


def test_play_opens_youtube():
    with mock.patch.object(desktop.webbrowser, "open") as o:
        assert actions.run(Cmd("play", {"query": "lofi beats"})) == "Playing lofi beats."
    assert o.call_args[0][0].endswith("search_query=lofi+beats")


# ---------- files / notes / email ----------
def test_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "NOTES_FILE", str(tmp_path / "n" / "notes.txt"))
    assert actions.run(Cmd("read_notes")) == "You have no notes."
    assert actions.run(Cmd("add_note", {"text": "buy milk"})) == "Noted."
    actions.run(Cmd("add_note", {"text": "call bob"}))
    assert actions.run(Cmd("read_notes")) == "Your last 2 notes: buy milk ... call bob."


def test_find_and_open_file(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "Budget Report 2026.xlsx").write_text("x")
    assert files.find_file("budget report", [tmp_path]).name == "Budget Report 2026.xlsx"
    assert files.find_file("nothing", [tmp_path]) is None
    monkeypatch.setattr(files, "find_file", lambda n: tmp_path / "a" / "Budget Report 2026.xlsx")
    with mock.patch.object(files, "_startfile") as s:
        assert actions.run(Cmd("open_file", {"name": "budget"})) == "Opening Budget Report 2026.xlsx."
    s.assert_called_once()


def test_open_folder(tmp_path, monkeypatch):
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(files.Path, "home", lambda: tmp_path)
    with mock.patch.object(files, "_startfile") as s:
        assert actions.run(Cmd("open_folder", {"name": "downloads"})) == "Opening downloads."
    assert s.call_args[0][0] == str(tmp_path / "Downloads")


def test_email_uses_contacts_and_never_sends(monkeypatch):
    monkeypatch.setitem(files.CONTACTS, "mom", "mom@example.com")
    with mock.patch("webbrowser.open") as o:
        r = actions.run(Cmd("email", {"to": "Mom", "subject": "dinner plans"}))
    assert "press send" in r
    assert o.call_args[0][0] == "mailto:mom@example.com?subject=dinner%20plans"


# ---------- risky actions need yes ----------
def test_wifi_off_needs_confirm():
    with mock.patch.object(radios, "set_radio", return_value=True) as sr:
        assert actions.needs_confirm(Cmd("wifi", {"state": "off"}))
        assert not actions.needs_confirm(Cmd("wifi", {"state": "on"}))
        assert actions.run(Cmd("wifi", {"state": "off"})).startswith("Are you sure")
        sr.assert_not_called()
        assert actions.run(Cmd("confirm")) == "Wi-Fi is off."
        sr.assert_called_once_with("wifi", False)
        assert actions.run(Cmd("bluetooth", {"state": "on"})) == "Bluetooth is on."


def test_radio_falls_back_to_settings():
    with mock.patch.object(radios, "set_radio", side_effect=ImportError), \
         mock.patch.object(radios.os, "startfile", create=True) as sf:
        assert "opened the settings" in actions.run(Cmd("bluetooth", {"state": "off"}))
    sf.assert_called_with("ms-settings:bluetooth")


@pytest.mark.parametrize("intent,fn", [("sleep", "sleep"), ("empty_recycle_bin", "empty_recycle_bin")])
def test_sleep_and_recycle_bin_confirm(intent, fn):
    with mock.patch.object(system, fn, return_value="done") as f:
        assert actions.run(Cmd(intent)).startswith("Are you sure")
        f.assert_not_called()
        assert actions.run(Cmd("cancel")) == "Okay, cancelled."
        assert actions.run(Cmd(intent, {"confirm": True})) == "done"
    f.assert_called_once()


# ---------- round 2: real-time features ----------
NLU_CASES_2 = [
    ("what is 15 times 4", "calculate", {"expression": "15*4"}),
    ("what is fifteen percent of two thousand four hundred", "calculate", {"expression": "(15/100)*2400"}),
    ("square root of eighty one", "calculate", {"expression": "sqrt(81)"}),
    ("set an alarm for 7 am", "reminder", None),
    ("wake me up in 20 minutes", "reminder", {"seconds": 1200, "text": "alarm"}),
    ("remember that my sister is Priya", "remember", {"fact": "my sister is Priya"}),
    ("what do you remember about me", "recall", {}),
    ("forget everything", "forget_memory", {}),
    ("whatsapp mom saying I'm on my way", "whatsapp", {"to": "mom", "text": "I'm on my way"}),
    ("send a whatsapp message to mom saying I'm on my way", "whatsapp", {"to": "mom", "text": "I'm on my way"}),
    ("message rahul on whatsapp saying call me", "whatsapp", {"to": "rahul", "text": "call me"}),
    ("read my clipboard", "read_clipboard", {}),
    ("go to youtube", "open_app", {"name": "youtube"}),
]


@pytest.mark.parametrize("text,intent,args", NLU_CASES_2)
def test_round2_nlu(text, intent, args):
    cmd = parse(text)
    if intent:
        assert cmd.intent == intent
    if args is not None:
        assert cmd.args == args


def test_calculator_answers():
    assert actions.run(Cmd("calculate", {"expression": "(15/100)*2400"})) == "The answer is 360."
    assert actions.run(Cmd("calculate", {"expression": "1/0"})) == "You can't divide by zero."
    assert actions.run(Cmd("calculate", {"expression": "__import__('os')"})) == "I couldn't work that out."
    assert parse("what is machine learning").intent == "web_search"  # not maths


def test_websites_open_in_browser():
    from jarvis.actions import apps

    with mock.patch.object(apps.webbrowser, "open") as o:
        assert actions.run(Cmd("open_app", {"name": "youtube"})) == "Opening youtube."
        assert o.call_args[0][0] == "https://www.youtube.com"
        actions.run(Cmd("open_app", {"name": "example.com"}))
        assert o.call_args[0][0] == "https://example.com"


def test_clipboard(monkeypatch):
    clip = {"v": "hello world"}
    fake = NS(paste=lambda: clip["v"], copy=lambda t: clip.update(v=t))
    with mock.patch.dict(sys.modules, {"pyperclip": fake}):
        assert actions.run(Cmd("read_clipboard")) == "hello world"
        assert actions.run(Cmd("copy_text", {"text": "namaste"})) == "Copied to the clipboard."
    assert clip["v"] == "namaste"


def test_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "MEMORY_FILE", str(tmp_path / "m.txt"))
    assert "don't remember" in actions.run(Cmd("recall"))
    assert actions.run(Cmd("remember", {"fact": "User likes chai"})) == "Got it, I will remember that."
    assert actions.memories() == ["User likes chai"]
    assert actions.run(Cmd("forget_memory")).startswith("Are you sure")
    assert actions.run(Cmd("confirm")).startswith("Okay, I forgot")
    assert actions.memories() == []


def test_whatsapp_draft_and_auto_send(monkeypatch):
    monkeypatch.setitem(files.CONTACTS, "mom", {"phone": "+91 98765 43210"})
    with mock.patch.object(files, "_startfile") as sf:
        assert "Press Enter to send" in actions.run(Cmd("whatsapp", {"to": "mom", "text": "on my way"}))
        assert sf.call_args[0][0] == "whatsapp://send?phone=919876543210&text=on%20my%20way"
        assert "don't have a phone number" in actions.run(Cmd("whatsapp", {"to": "bob", "text": "hi"}))

        monkeypatch.setattr(files, "WHATSAPP_AUTO_SEND", True)
        monkeypatch.setattr(files, "WHATSAPP_SEND_DELAY", 0)
        cmd = Cmd("whatsapp", {"to": "mom", "text": "hi"})
        assert actions.needs_confirm(cmd)
        assert actions.run(cmd).startswith("Are you sure you want to send")
        fake = mock.Mock()
        fake.getActiveWindowTitle.return_value = "WhatsApp"
        with mock.patch.dict(sys.modules, {"pyautogui": fake}):
            assert actions.run(Cmd("confirm")) == "Sent your WhatsApp message to mom."
        fake.press.assert_called_with("enter")
        # another window in front: Enter is NOT pressed
        actions.run(cmd)
        fake = mock.Mock()
        fake.getActiveWindowTitle.return_value = "Notepad"
        with mock.patch.dict(sys.modules, {"pyautogui": fake}):
            assert "not in front" in actions.run(Cmd("confirm"))
        fake.press.assert_not_called()


def test_alarm_and_reminders_survive_restart(tmp_path, monkeypatch):
    store = tmp_path / "r.json"
    actions.start_reminders(str(store))
    try:
        assert actions.run(Cmd("reminder", {"seconds": 3600, "text": "alarm"})).startswith("Alarm set for")
        actions.run(Cmd("timer", {"seconds": 60}))  # timers are not saved
        saved = json.loads(store.read_text())
        assert [s["kind"] for s in saved] == ["alarm"]
        with timers._lock:
            timers._active.clear()
        timers.load_saved()
        assert "alarm in 59 minutes" in actions.run(Cmd("timers", {"action": "list"})) or \
               "alarm in 1 hour" in actions.run(Cmd("timers", {"action": "list"}))
    finally:
        actions.run(Cmd("timers", {"action": "cancel"}))
        timers.STORE_FILE = ""
