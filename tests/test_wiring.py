"""Wiring of the new features (pieces A-K): nlu phrases, actions merge, risky checks, main.py hooks."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from jarvis import actions, nlu  # noqa: E402
from jarvis.actions import assistant, dictation, focus, lists, shortcuts  # noqa: E402
from jarvis.config import DEFAULTS  # noqa: E402

NEW_INTENTS = ["list_add", "list_remove", "list_read", "list_clear", "lists", "help", "pause_listening",
               "resume_listening", "repeat", "voice", "shortcut", "snippet", "agenda", "next_event", "free_at",
               "briefing", "dictation", "read_aloud", "convert", "world_time", "date_calc", "network",
               "now_playing", "mic", "app_volume", "audio_output", "focus", "dnd", "alerts", "check_email"]


# ---------- nlu ----------

PHRASES = [
    ("add milk to my shopping list", "list_add", {"list": "shopping", "item": "milk"}),
    ("remove milk from my shopping list", "list_remove", {"list": "shopping", "item": "milk"}),
    ("what's on my to-do list", "list_read", {"list": "to-do"}),
    ("clear my shopping list", "list_clear", {"list": "shopping"}),
    ("what lists do I have", "lists", {}),
    ("what can I say", "help", {}),
    ("help with timers", "help", {"topic": "timers"}),
    ("stop listening for 10 minutes", "pause_listening", {"minutes": 10}),
    ("stop listening", "pause_listening", {}),
    ("go to sleep jarvis", "pause_listening", {}),
    ("start listening", "resume_listening", {}),
    ("repeat that", "repeat", {}),
    ("speak slower", "voice", {"change": "slower"}),
    ("speak louder", "voice", {"change": "louder"}),
    ("what's on my calendar tomorrow", "agenda", {"day": "tomorrow"}),
    ("when is my next meeting", "next_event", {}),
    ("am I free at 3 pm", "free_at", {"time": "3 pm"}),
    ("good morning briefing", "briefing", {}),
    ("start dictation", "dictation", {"state": "on"}),
    ("read this aloud", "read_aloud", {}),
    ("stop reading", "read_aloud", {"action": "stop"}),
    ("convert 5 miles to km", "convert", {"amount": 5, "from": "miles", "to": "km"}),
    ("2.5 kg in pounds", "convert", {"amount": 2.5, "from": "kg", "to": "pounds"}),
    ("how many cm in 6 feet", "convert", {"amount": 6, "from": "feet", "to": "cm"}),
    ("10 dollars in rupees", "convert", {"amount": 10, "from": "dollars", "to": "rupees"}),
    ("what time is it in Tokyo", "world_time", {"city": "tokyo"}),
    ("how many days until 25 December", "date_calc", {"question": "how many days until 25 December"}),
    ("what day was 15/08/1947", "date_calc", {"question": "what day was 15/08/1947"}),
    ("am I online", "network", {"what": "online"}),
    ("what's my IP", "network", {"what": "ip"}),
    ("what Wi-Fi am I on", "network", {"what": "wifi"}),
    ("internet speed", "network", {"what": "speed"}),
    ("ping google", "network", {"what": "ping", "host": "google"}),
    ("what's playing", "now_playing", {}),
    ("mute my mic", "mic", {"state": "off"}),
    ("set spotify volume to 30", "app_volume", {"app": "spotify", "level": 30}),
    ("switch to headphones", "audio_output", {"name": "headphones"}),
    ("start focus for 25 minutes", "focus", {"action": "start", "minutes": 25}),
    ("stop focus", "focus", {"action": "stop"}),
    ("turn on do not disturb", "dnd", {"state": "on"}),
    ("turn off battery alerts", "alerts", {"state": "off", "kind": "battery"}),
    ("do I have new emails", "check_email", {}),
    ("any email from mom", "check_email", {"from": "mom"}),
    # old phrases must keep working
    ("open focus settings", "open_settings", {"page": "notifications"}),
    ("turn off wifi", "wifi", {"state": "off"}),
    ("set volume to 30", "volume", {"level": 30}),
    ("volume up", "volume", {"change": "up"}),
    ("what time is it", "time", {}),
    ("how much time is left", "timers", {"action": "list"}),
    ("go to sleep", "sleep", {}),
    ("send an email to mom about dinner", "email", {"to": "mom", "subject": "dinner"}),
    ("read my clipboard", "read_clipboard", {}),
    ("switch window", "window", {"action": "switch"}),
    ("what is 15 percent of 2400", "calculate", {"expression": "(15/100)*2400"}),
]


@pytest.mark.parametrize("text,intent,args", PHRASES)
def test_nlu_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


# ---------- actions ----------

def test_every_new_intent_is_wired():
    for intent in NEW_INTENTS:
        assert intent in actions.CATALOG, intent
        assert intent in actions._HANDLERS, intent


def test_list_clear_asks_first(tmp_path):
    with mock.patch.object(lists, "LISTS_FILE", str(tmp_path / "l.json")):
        actions.run(nlu.Command("list_add", {"list": "shopping", "item": "milk"}))
        cmd = nlu.Command("list_clear", {"list": "shopping"})
        assert actions.needs_confirm(cmd)
        assert "sure" in actions.run(cmd).lower()
        actions.run(nlu.Command("confirm", {}))
        assert "milk" not in actions.run(nlu.Command("list_read", {"list": "shopping"}))


def test_shortcut_run_is_risky_but_open_is_not():
    sc = {"backup": {"run": "echo hi"}, "my site": {"open": "https://example.com"}}
    with mock.patch.dict(shortcuts.SHORTCUTS, sc, clear=True):
        assert actions.needs_confirm(nlu.Command("shortcut", {"name": "backup"}))
        assert not actions.needs_confirm(nlu.Command("shortcut", {"name": "my site"}))


def test_exit_phrases_do_not_catch_pause():
    assert not main.is_exit("stop listening for 10 minutes", DEFAULTS["exit_phrases"])


# ---------- main.py hooks ----------

class FakeIO:
    def __init__(self, heard):
        self.heard, self.said = list(heard), []

    def wait_for_wake_word(self):
        if not self.heard:
            raise KeyboardInterrupt

    def listen(self, timeout=None):
        return self.heard.pop(0) if self.heard else None

    def say(self, text):
        self.said.append(text)
        main._record(text)


def _cfg(**extra):
    import copy

    cfg = copy.deepcopy(DEFAULTS)
    cfg["ai"]["enabled"] = False
    cfg.update(extra)
    return cfg


@pytest.fixture(autouse=True)
def clean():
    assistant._paused_until = None
    dictation.stop()
    main._recorder = None
    yield
    assistant._paused_until = None
    dictation.stop()
    main._recorder = None


def test_pause_ignores_commands_until_resumed():
    io = FakeIO(["stop listening", "what time is it", "start listening", "what time is it"])
    main.run(io, _cfg(), nlu, actions)
    times = [s for s in io.said if s.lower().startswith("it") and ("am" in s.lower() or "pm" in s.lower())]
    assert len(times) == 1  # only the one after "start listening"


def test_dictation_types_phrases_instead_of_running_them():
    typed = []
    fake = mock.Mock(type=lambda s: typed.append(s))
    with mock.patch.object(dictation, "_keys", fake):
        io = FakeIO(["start dictation", "shut down the meeting", "stop dictation"])
        main.run(io, _cfg(), nlu, actions)
    assert "".join(typed).lower().startswith("shut down the meeting")
    assert not any("sure" in s.lower() for s in io.said)  # no shutdown question


def test_shortcut_matched_before_nlu():
    with mock.patch.dict(shortcuts.SHORTCUTS, {"open my project": {"open": "C:/code"}}, clear=True), \
            mock.patch.object(shortcuts, "_open") as op:
        reply = main.handle("open my project", FakeIO([]), _cfg(), nlu, actions)
    op.assert_called_once()
    assert reply == "Opening open my project." or "open my project" in reply


def test_repeat_says_last_reply():
    main._recorder = assistant.record
    io = FakeIO(["what lists do I have", "repeat that"])
    with mock.patch.object(lists, "_load", return_value={}):
        main.run(io, _cfg(), nlu, actions)
    answers = [s for s in io.said if s not in ("Jarvis is ready.", "Goodbye.", "Yes?")]
    assert len(answers) == 2 and answers[0] == answers[1]


def test_focus_start_runs_focus_routine():
    cfg = _cfg(routines={"focus": ["what time is it"]})
    io = FakeIO([])
    with mock.patch.object(actions, "run", side_effect=lambda c: "Focus started." if c.intent == "focus" else "It is 10 AM."), \
            mock.patch.object(focus, "take_routine", return_value="focus"):
        main.handle("start focus", io, cfg, nlu, actions)
    assert io.said[:2] == ["Focus started.", "It is 10 AM."]


def test_wire_features_starts_background_parts():
    io = FakeIO([])
    with mock.patch.object(actions.monitor, "start") as mon, mock.patch.object(actions.agenda, "start_alerts") as ag:
        main._wire_features(io, actions)
    mon.assert_called_once_with(io.say)
    ag.assert_called_once()  # agenda gets a wrapper that stays generic while locked (review N3)
    sayer = ag.call_args.args[0]
    with mock.patch("jarvis.actions.security.is_locked", return_value=False), \
            mock.patch("jarvis.actions.security.is_guest", return_value=False):
        sayer("Meeting X starts in 5 minutes")
    assert io.said[-1] == "Meeting X starts in 5 minutes"
    assert focus.notify == io.say
    assert main._recorder == assistant.record


def test_yes_works_even_if_yaml_turned_it_into_true():
    assert main.is_yes("yes", [True, "sure"])
    import yaml

    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
    assert "yes" in cfg["yes_words"]


# ================= Round 2 (pieces L-S) =================
from jarvis.actions import fun, memos, recorder, recurring  # noqa: E402

ROUND2 = [
    ("remind me to drink water every hour", "repeat_reminder", {"every_minutes": 60, "text": "drink water"}),
    ("stop all repeating reminders", "repeat_reminders", {"action": "cancel", "text": "all"}),
    ("remind me to call mom in 10 minutes", "reminder", {"seconds": 600, "text": "call mom"}),
    ("open a new tab", "browser", {"action": "new_tab"}),
    ("close this tab", "browser", {"action": "close_tab"}),
    ("find price on this page", "browser", {"action": "find", "text": "price"}),
    ("summarize this page", "page_text", {}),
    ("read this page out loud", "page_text", {"read": True}),
    ("define serendipity", "define", {"word": "serendipity"}),
    ("what does serendipity mean", "define", {"word": "serendipity"}),
    ("how do you spell necessary", "spell", {"word": "necessary"}),
    ("opposite of happy", "synonyms", {"word": "happy", "kind": "antonyms"}),
    ("wikipedia Albert Einstein", "wikipedia", {"topic": "albert einstein"}),
    ("open my last download", "recent_files", {"action": "open"}),
    ("what did I download today", "recent_files", {"when": "today"}),
    ("I spent 250 on lunch", "expense_add", {"amount": "250", "note": "lunch"}),
    ("spent 2.5k on shopping", "expense_add", {"amount": "2.5k", "note": "shopping"}),
    ("how much did I spend on food this week", "expense_report", {"category": "food", "period": "week"}),
    ("delete the last expense", "expense_undo", {}),
    ("record a voice memo", "memo", {"action": "record"}),
    ("delete my last memo", "memo", {"action": "delete", "which": "last"}),
    ("record my screen", "screen_record", {"action": "start"}),
    ("stop recording", "screen_record", {"action": "stop"}),
    ("quiz me", "quiz", {"action": "start"}),
    ("rock paper scissors", "random_pick", {"kind": "rps"}),
    # old phrases still work
    ("open file budget", "open_file", {"name": "budget"}),
    ("open downloads", "open_folder", {"name": "downloads"}),
    ("look up cricket score on google", "web_search", {"query": "cricket score"}),
    ("what is the meaning of life", "web_search", {"query": "what is the meaning of life"}),
    ("zoom in", "press_keys", {"keys": "ctrl+="}),
]


@pytest.mark.parametrize("text,intent,args", ROUND2)
def test_round2_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_stop_recording_goes_to_memo_while_memo_records():
    with mock.patch.object(memos, "is_recording", return_value=True), mock.patch.object(recorder, "_running", return_value=False):
        assert nlu.parse("stop recording").intent == "memo"


def test_round2_risky():
    assert actions.needs_confirm(nlu.Command("repeat_reminders", {"action": "cancel", "text": "all"}))
    assert not actions.needs_confirm(nlu.Command("repeat_reminders", {"action": "list"}))
    with mock.patch.object(memos, "risky_text", side_effect=lambda a: "delete memo 1" if a.get("action") == "delete" else None):
        assert actions.needs_confirm(nlu.Command("memo", {"action": "delete"}))
        assert not actions.needs_confirm(nlu.Command("memo", {"action": "play"}))


def test_recent_files_is_not_info_only():
    assert not actions.CATALOG["recent_files"].get("info")


def test_quiz_answer_goes_to_quiz():
    fun._QUIZ_STATE.update(question="What is the capital of France?", answers=("paris",), asked_at=__import__("time").time())
    reply = main.handle("Paris", FakeIO([]), _cfg(), nlu, actions)
    assert "right" in reply.lower() or "correct" in reply.lower() or "yes" in reply.lower()


class FakeBrain:
    available = True

    def __init__(self, cmds):
        self.cmds = cmds

    def ask(self, text, on_sentence=None):
        return self.cmds


@pytest.mark.parametrize("cmd", [nlu.Command("memo", {"action": "record"}),
                                 nlu.Command("screen_record", {"action": "start"}),
                                 nlu.Command("recent_files", {"action": "open"})])
def test_ai_started_recording_asks_first(cmd):
    io = FakeIO(["no"])
    with mock.patch.object(actions, "run") as run:
        reply = main.handle("blah blah unknown thing", io, _cfg(), nlu, actions, brain=FakeBrain([cmd]))
    run.assert_not_called()
    assert reply == "Okay, cancelled." and "Say yes" in io.said[0]


def test_user_said_recording_does_not_ask_twice():
    io = FakeIO([])
    with mock.patch.object(actions, "run", return_value="Recording the screen.") as run:
        reply = main.handle("record my screen", io, _cfg(), nlu, actions)
    run.assert_called_once()
    assert reply == "Recording the screen."


def test_memo_record_begins_after_reply():
    io = FakeIO([])
    with mock.patch.object(actions, "run", return_value="Recording. Speak now."), \
            mock.patch.object(memos, "is_recording", return_value=True), mock.patch.object(memos, "begin") as begin:
        reply = main.handle("record a voice memo", io, _cfg(), nlu, actions)
    assert io.said == ["Recording. Speak now."] and reply == ""
    begin.assert_called_once()


def test_exit_stops_screen_recording():
    with mock.patch.object(recorder, "stop_all") as stop_all:
        main.run(FakeIO(["goodbye"]), _cfg(), nlu, actions)
    stop_all.assert_called_once()


def test_wire_features_starts_round2_parts():
    io = FakeIO([])
    with mock.patch.object(actions.monitor, "start"), mock.patch.object(actions.agenda, "start_alerts"), \
            mock.patch.object(recurring, "start") as rec, mock.patch.object(memos, "set_notifier") as mn, \
            mock.patch.object(main.atexit, "register") as reg:
        main._wire_features(io, actions)
    rec.assert_called_once_with(io.say)
    mn.assert_called_once_with(io.say)
    reg.assert_called_once_with(recorder.stop_all)


def _start_quiz():
    fun._QUIZ_STATE.update(question="What is the capital of France?", answers=("paris",), asked_at=__import__("time").time())


@pytest.mark.parametrize("text", ["stop", "cancel", "enough"])
def test_quiz_can_be_stopped(text):
    _start_quiz()
    main.handle(text, FakeIO([]), _cfg(), nlu, actions)
    assert not fun.quiz_pending()


def test_quiz_skip_and_real_commands():
    _start_quiz()
    reply = main.handle("skip", FakeIO([]), _cfg(), nlu, actions)
    assert fun.quiz_pending() and "paris" in reply.lower()
    with mock.patch.object(actions, "run", return_value="It's 9 AM.") as run:
        assert main.handle("what time is it", FakeIO([]), _cfg(), nlu, actions) == "It's 9 AM."
    assert run.call_args[0][0].intent == "time"


# ================= Round 3 (pieces T-AA) =================
from jarvis.actions import cliphistory, phone, smarthome, software  # noqa: E402

ROUND3 = [
    ("ring my phone", "phone", {"action": "ring"}),
    ("phone battery", "phone_battery", {}),
    ("text mom saying I'm Late", "phone", {"action": "sms", "to": "mom", "text": "I'm Late"}),
    ("send this link to my phone", "phone", {"action": "share", "what": "clipboard"}),
    ("install VLC", "software", {"action": "install", "name": "vlc"}),
    ("uninstall Zoom", "software", {"action": "uninstall", "name": "zoom"}),
    ("update all my apps", "software", {"action": "update_all"}),
    ("what apps need updates", "software", {"action": "check_updates"}),
    ("copy the text on my screen", "ocr", {"source": "screen", "action": "copy"}),
    ("read the text in this window", "ocr", {"source": "window", "action": "read"}),
    ("read the text in my last screenshot", "ocr", {"source": "last_screenshot", "action": "read"}),
    ("what did I copy before", "clip_history", {"action": "list"}),
    ("paste the second last thing I copied", "clip_history", {"action": "paste", "index": 2}),
    ("copy item 3 again", "clip_history", {"action": "copy", "index": 3}),
    ("clear clipboard history", "clip_history", {"action": "clear"}),
    ("play shape of you on spotify", "spotify", {"action": "play", "query": "shape of you"}),
    ("like this song", "spotify", {"action": "like"}),
    ("add this song to my gym playlist", "spotify", {"action": "add_to_playlist", "playlist": "gym"}),
    ("word of the day", "daily", {"what": "word"}),
    ("quote of the day", "daily", {"what": "quote"}),
    ("what happened on this day", "daily", {"what": "on_this_day"}),
    ("generate a password", "generate", {"kind": "password"}),
    ("random 6 digit pin", "generate", {"kind": "pin", "length": "6"}),
    ("QR code for Hello World", "generate", {"kind": "qr", "text": "Hello World"}),
    # old phrases still work
    ("another word for happy", "synonyms", {"word": "happy"}),
    ("how much battery", "system_info", {"what": "battery"}),
    ("whatsapp mom saying hi", "whatsapp", {"to": "mom", "text": "hi"}),
    ("read my clipboard", "read_clipboard", {}),
    ("paste", "press_keys", {"keys": "ctrl+v"}),
    ("play believer", "play", {"query": "believer"}),
    ("what's playing", "now_playing", {}),
    ("good morning briefing", "briefing", {}),
    ("delete the file old notes", "delete_file", {"name": "old notes"}),
    ("open the garage", "open_app", {"name": "garage"}),  # no Home Assistant set up
]


@pytest.mark.parametrize("text,intent,args", ROUND3)
def test_round3_phrases(text, intent, args, monkeypatch):
    monkeypatch.delenv("HASS_URL", raising=False)
    with mock.patch("jarvis.nlu_features._home_ready", return_value=False):
        cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


HOME = [
    ("turn on the bedroom light", "device", {"name": "bedroom light", "action": "on"}),
    ("set AC to 24", "device", {"name": "ac", "action": "set", "value": 24}),
    ("is the front door locked", "device", {"name": "front door", "action": "status"}),
    ("unlock the front door", "device", {"name": "front door", "action": "unlock"}),
    ("open the garage", "device", {"name": "garage", "action": "open"}),
    ("turn off everything", "device", {"name": "everything", "action": "off"}),
    ("activate movie night scene", "scene", {"name": "movie night"}),
    # laptop rules win even with Home Assistant
    ("turn on wifi", "wifi", {"state": "on"}),
    ("turn off the screen", "screen_off", {}),
    ("lock", "lock", {}),
    ("set volume to 30", "volume", {"level": 30}),
    ("turn off do not disturb", "dnd", {"state": "off"}),
    ("open chrome", "open_app", {"name": "chrome"}),
]


@pytest.mark.parametrize("text,intent,args", HOME)
def test_smarthome_phrases_when_set_up(text, intent, args):
    with mock.patch("jarvis.nlu_features._home_ready", return_value=True):
        cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_round3_intents_wired():
    for intent in ("phone", "phone_battery", "device", "scene", "software", "ocr", "clip_history", "spotify",
                   "daily", "generate"):
        assert intent in actions.CATALOG and intent in actions._HANDLERS, intent


def test_round3_risky_goes_through_module_checks():
    cases = [(phone, "phone", {"action": "sms"}), (smarthome, "device", {"name": "x", "action": "unlock"}),
             (software, "software", {"action": "install", "name": "vlc"})]
    for mod, intent, args in cases:
        with mock.patch.object(mod, "risky_text", return_value="do it") as rt:
            assert actions.needs_confirm(nlu.Command(intent, dict(args)))
        rt.assert_called()
        with mock.patch.object(mod, "risky_text", return_value=None):
            assert not actions.needs_confirm(nlu.Command(intent, dict(args)))
    assert actions.needs_confirm(nlu.Command("clip_history", {"action": "clear"}))
    assert not actions.needs_confirm(nlu.Command("clip_history", {"action": "list"}))


def test_confirmed_risky_runs_handler():
    with mock.patch.dict(actions._HANDLERS, {"device": lambda a: f"done {a.get('confirm')}"}), \
            mock.patch.object(smarthome, "risky_text", return_value="unlock the front door"):
        assert "sure" in actions.run(nlu.Command("device", {"name": "front door", "action": "unlock"})).lower()
        assert actions.run(nlu.Command("confirm", {})) == "done True"


def test_wire_features_starts_round3_parts():
    io = FakeIO([])
    with mock.patch.object(actions.monitor, "start"), mock.patch.object(actions.agenda, "start_alerts"), \
            mock.patch.object(recurring, "start"), mock.patch.object(main.atexit, "register"), \
            mock.patch.object(software, "set_notifier") as sn, mock.patch.object(cliphistory, "start") as cs:
        main._wire_features(io, actions)
    sn.assert_called_once_with(io.say)
    cs.assert_called_once_with()


def test_ai_untrusted_and_guarded_lists():
    from jarvis import brain

    assert {"ocr", "daily"} <= brain.UNTRUSTED_INFO
    assert {"device", "scene", "phone", "clip_history"} <= brain.GUARDED_ACTIONS


# ================= Round 4 (pieces AB-AI) =================
from jarvis.actions import history, layouts, localai, screentime, security, triggers  # noqa: E402

ROUND4 = [
    ("list my triggers", "triggers", {"action": "list"}),
    ("join the 3 pm meeting", "meeting", {"action": "join", "when": "3 pm"}),
    ("hang up", "meeting", {"action": "leave"}),
    ("mute me", "meeting", {"action": "mute"}),
    ("my screen time today", "screen_time", {}),
    ("how long did I use chrome today", "screen_time", {"app": "chrome"}),
    ("warn me after 1 hour of youtube", "app_limit", {"app": "youtube", "minutes": 60}),
    ("remove the youtube limit", "app_limit", {"app": "youtube", "minutes": 0}),
    ("lock jarvis", "jarvis_lock", {"state": "on"}),
    ("unlock jarvis 4 8 2 1", "jarvis_lock", {"state": "off", "pin": "4 8 2 1"}),
    ("guest mode on", "guest_mode", {"state": "on"}),
    ("what did I ask you yesterday", "history", {"action": "list", "day": "yesterday"}),
    ("what did I ask about weather", "history", {"action": "search", "query": "weather"}),
    ("do that again", "history", {"action": "repeat_last"}),
    ("clear my history", "history", {"action": "clear"}),
    ("use local AI", "ai_mode", {"mode": "local"}),
    ("is local AI ready", "local_ai_status", {}),
    ("save this layout as coding", "layout", {"action": "save", "name": "coding"}),
    ("restore my coding layout", "layout", {"action": "restore", "name": "coding"}),
    ("play the daily podcast", "podcast", {"action": "play_latest", "name": "the daily"}),
    ("next episode", "podcast", {"action": "next"}),
    # old phrases still work
    ("mute", "volume", {"change": "mute"}),
    ("lock", "lock", {}),
    ("repeat that", "repeat", {}),
    ("clear clipboard history", "clip_history", {"action": "clear"}),
    ("next song", "media", {"action": "next"}),
    ("when is my next meeting", "next_event", {}),
    ("take a screenshot", "screenshot", {}),
    ("set a timer for 1 hour", "timer", {"seconds": 3600}),
    ("open coding", "open_app", {"name": "coding"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND4)
def test_round4_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_round4_risky():
    with mock.patch.object(history, "needs_confirm", return_value=True), \
            mock.patch.object(history, "risky_text", return_value="clear your history"):
        assert actions.needs_confirm(nlu.Command("history", {"action": "clear"}))
    with mock.patch.object(layouts, "risky_text", return_value="delete the coding layout"):
        assert actions.needs_confirm(nlu.Command("layout", {"action": "delete", "name": "coding"}))


def test_security_blocks_before_confirm():
    io = FakeIO([])
    with mock.patch.object(security, "check", return_value="Guest mode is on."), \
            mock.patch.object(security, "pending", return_value=False), mock.patch.object(actions, "run") as run:
        reply = main._run_one(nlu.Command("shutdown", {}), io, _cfg(), actions)
    assert reply == "Guest mode is on." and io.said == []
    run.assert_not_called()


def test_security_asks_pin_then_runs():
    io = FakeIO(["4 8 2 1"])
    with mock.patch.object(security, "check", return_value="Say your PIN."), \
            mock.patch.object(security, "pending", return_value=True), \
            mock.patch.object(security, "verify", return_value=(True, "")) as verify, \
            mock.patch.object(actions, "run", return_value="It is 9 AM."):
        reply = main._run_one(nlu.Command("time", {}), io, _cfg(), actions)
    verify.assert_called_once_with("4 8 2 1")
    assert reply == "It is 9 AM." and io.said == ["Say your PIN."]


def test_dictation_checked_by_security():
    typed = []
    with mock.patch.object(dictation, "_keys", mock.Mock(type=lambda s: typed.append(s))), \
            mock.patch.object(security, "check", return_value="Jarvis is locked. Say your PIN."):
        dictation.start()
        reply = main.handle("hello there", FakeIO([]), _cfg(), nlu, actions)
    assert "locked" in reply and typed == []


def test_history_logged_and_do_again_reconfirms():
    logged = []
    with mock.patch.object(history, "log", side_effect=lambda *a, **k: logged.append(a)), \
            mock.patch.object(actions, "run", return_value="It is 9 AM."):
        main.handle("what time is it", FakeIO([]), _cfg(), nlu, actions)
    assert logged and logged[0][1].intent == "time"
    io = FakeIO(["no"])
    with mock.patch.object(history, "last_command", return_value=nlu.Command("shutdown", {})), \
            mock.patch.object(history, "last_was_ai", return_value=False), mock.patch.object(history, "log"), \
            mock.patch("jarvis.actions.system.shutdown") as sd:
        reply = main.handle("do that again", io, _cfg(), nlu, actions)
    sd.assert_not_called()
    assert reply == "Okay, cancelled." and "sure" in io.said[0].lower()


def test_ai_cannot_repeat_last():
    reply = main._run_one(nlu.Command("history", {"action": "repeat_last"}), FakeIO([]), _cfg(), actions, from_ai=True)
    assert "won't" in reply


def test_trigger_runner_never_auto_confirms():
    io = FakeIO([])
    run_step = main._trigger_runner(io, _cfg(), nlu, actions, None)
    with mock.patch("jarvis.actions.system.shutdown") as sd, mock.patch.object(history, "log"):
        reply = run_step("shut down")
    sd.assert_not_called()
    assert "skipped" in reply


def test_pin_never_in_log_or_repeat():
    main._redactor = security.redact
    try:
        with mock.patch.object(security, "redact", side_effect=lambda t: "[hidden]" if "4821" in t else t):
            main._redactor = security.redact
            assert main._redact("unlock jarvis 4821") == "[hidden]"
    finally:
        main._redactor = None


def test_brain_falls_back_to_local_ai():
    from jarvis.brain import Brain

    b = Brain.__new__(Brain)
    b.ai = {"stream": True}
    b.client = None  # no Claude key
    b.error = "no key"
    with mock.patch.object(localai, "use_local", return_value=True), \
            mock.patch.object(localai, "ask", return_value="Paris.") as ask:
        cmds = b.ask("capital of france", on_sentence=lambda s: None)
    ask.assert_called_once()
    assert cmds[0].intent == "answer" and cmds[0].args["text"] == "Paris." and cmds[0].args["spoken"]


def test_round4_guarded_lists():
    from jarvis import brain

    assert {"meeting", "jarvis_lock", "guest_mode", "history", "layout", "podcast"} <= brain.GUARDED_ACTIONS
    assert not {"history", "podcast"} & brain.UNTRUSTED_INFO  # actions, not lookups (review Y4)


def test_exit_stops_screentime_and_triggers():
    with mock.patch.object(recorder, "stop_all"), mock.patch.object(screentime, "stop") as st, \
            mock.patch.object(triggers, "stop") as tr:
        main.run(FakeIO(["goodbye"]), _cfg(), nlu, actions)
    st.assert_called_once()
    tr.assert_called_once()


# ---------- round 5 (notifications, pchealth, teach, calendar_add, interpreter, scores) + AP doctor ----------
from jarvis.actions import calendar_add, doctor, interpreter, teach  # noqa: E402

ROUND5 = [
    ("read my notifications", "notifications", {"action": "read"}),
    ("clear my notifications", "notifications", {"action": "clear"}),
    ("check my pc health", "pc_health", {"what": "all"}),
    ("what have you learned", "taught", {"action": "list"}),
    ("add meeting with Ravi on Friday at 10", "calendar_add", {"title": "meeting with Ravi", "start": "friday at 10"}),
    ("schedule an event called launch party on saturday at 6 pm", "calendar_add",
     {"title": "launch party", "start": "saturday at 6 pm"}),
    ("start interpreter mode in spanish", "interpreter", {"state": "on", "language": "spanish"}),
    ("stop translating", "interpreter", {"state": "off"}),
    ("run a self check", "self_check", {}),
    # old phrases still work
    ("forget everything", "forget_memory", {}),
    ("add milk to my shopping list", "list_add", {"list": "shopping", "item": "milk"}),
    ("what's my score", "quiz", {"action": "score"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND5)
def test_round5_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_round5_scores_and_teach_parse():
    assert nlu.parse("whats the score").intent == "scores"
    assert nlu.parse("whats the score").args.get("team") is None
    cmd = nlu.parse("when I say movie time, open netflix and dim the screen")
    assert cmd.intent == "teach"


def test_round5_risky():
    assert actions.needs_confirm(nlu.Command("calendar_add", {"title": "gym", "start": "tomorrow at 7 am"}))
    assert actions.needs_confirm(nlu.Command("notifications", {"action": "clear"}))
    assert not actions.needs_confirm(nlu.Command("notifications", {"action": "read"}))


def test_calendar_add_cancelled_on_no():
    io = FakeIO(["no"])
    with mock.patch.object(calendar_add, "calendar_add") as add, \
            mock.patch.dict(actions._HANDLERS, {"calendar_add": add}):
        reply = main._run_one(nlu.Command("calendar_add", {"title": "gym", "start": "tomorrow at 7 am"}),
                              io, _cfg(), actions)
    add.assert_not_called()
    assert reply == "Okay, cancelled."


def test_interpreter_hook_skips_nlu():
    with mock.patch.object(interpreter, "is_active", return_value=True), \
            mock.patch.object(interpreter, "process", return_value="Hola.") as proc, \
            mock.patch.object(nlu, "parse") as parse:
        reply = main.handle("hello", FakeIO([]), _cfg(), nlu, actions)
    proc.assert_called_once_with("hello")
    parse.assert_not_called()
    assert reply == "Hola."


def test_teach_hook_runs_steps():
    with mock.patch.object(teach, "run", return_value="Done.") as run:
        reply = main.handle("movie time", FakeIO([]), _cfg(), nlu, actions)
    run.assert_called_once()
    assert reply == "Done."


def test_doctor_flag_exits_before_io():
    with mock.patch.object(doctor, "run_cli", return_value=0) as cli, mock.patch.object(main, "VoiceIO") as vio:
        assert main.main(["--doctor"]) == 0
    cli.assert_called_once_with([])
    vio.assert_not_called()


def test_round5_guarded_lists():
    from jarvis import brain

    assert {"notifications", "teach", "taught", "calendar_add"} <= brain.GUARDED_ACTIONS
    assert {"pc_health", "scores"} <= brain.UNTRUSTED_INFO and "notifications" not in brain.UNTRUSTED_INFO


def test_round5_help_groups():
    names = [g[0] for g in assistant._GROUPS]
    assert {"notifications", "pc health", "teach", "calendar add", "interpreter", "scores", "self check"} <= set(names)
    assert "score" in assistant.help({"topic": "scores"}).lower()


# ---------- round 6 (wakeword, tray, corrections, fuzzy, onboarding) ----------
from jarvis.actions import apps, corrections, fileops, onboarding, tray, wakeword  # noqa: E402

ROUND6 = [
    ("make the wake word more sensitive", "wake_sensitivity", {"change": "up"}),
    ("you wake up too often", "wake_sensitivity", {"change": "down"}),
    ("set wake word sensitivity to 6", "wake_sensitivity", {"value": 6}),
    ("wake word sensitivity", "wake_sensitivity", {}),
    ("when you hear note pad I mean notepad", "correction", {"heard": "note pad", "meant": "notepad"}),
    ("when I say chrome I mean google chrome", "correction", {"heard": "chrome", "meant": "google chrome"}),
    ("you misheard", "misheard", {}),
    ("list corrections", "corrections", {"action": "list"}),
    ("run setup", "setup", {}),
    ("change my city", "setup", {"part": "city"}),
    ("test my mic", "setup", {"part": "mic"}),
    ("set up a pin", "setup", {"part": "pin"}),
    # old phrases still work
    ("when I say movie time, open netflix", "teach", {"phrase": "movie time", "steps": ["open netflix"]}),
    ("create a pin", "generate", {"kind": "pin"}),
    ("call mom", "call", None),
    ("open chrome", "open_app", {"name": "chrome"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND6)
def test_round6_phrases(text, intent, args):
    cmd = nlu.parse(text)
    if args is None:  # only check that setup did not take it
        assert cmd.intent != "setup"
    else:
        assert (cmd.intent, cmd.args) == (intent, args)


def test_corrections_applied_before_nlu():
    corrections.HANDLERS["correction"]({"heard": "note pad", "meant": "notepad"})
    with mock.patch.object(actions, "run", return_value="Opening notepad.") as run:
        main.handle("open note pad", FakeIO([]), _cfg(), nlu, actions)
    assert run.call_args[0][0].args == {"name": "notepad"}


def test_corrections_not_applied_to_steps():
    with mock.patch.object(corrections, "apply", side_effect=lambda t: t) as ap, \
            mock.patch.object(actions, "run", return_value="ok"):
        main.handle("what time is it", FakeIO([]), _cfg(), nlu, actions, depth=1)
    ap.assert_not_called()


def test_fuzzy_only_after_exact_fails():
    launched = []

    def fake_launch(target):
        if target == "crome":
            raise OSError
        launched.append(target)
    with mock.patch.object(apps, "_launch", side_effect=fake_launch):
        assert apps.open_app("crome") == "Opening chrome."
        assert apps.open_app("notepad") == "Opening notepad."
    assert launched == [apps.APP_PATHS["chrome"], apps.APP_PATHS["notepad"]]


def test_fuzzy_folder_and_number():
    assert fileops.known_folder("down loads") == fileops.known_folder("downloads")
    assert phone.resolve_number("+91 98765 43210", {}) == "+919876543210"
    assert phone.resolve_number("rohith", {"Rohit": {"phone": "9876543210"}}) == "9876543210"


def test_round6_merge_and_guarded():
    from jarvis import brain

    for intent in ("wake_sensitivity", "correction", "corrections", "misheard", "setup"):
        assert intent in actions.CATALOG and intent in actions._HANDLERS
    assert {"interpreter", "dictation", "pause_listening", "ai_mode", "triggers", "app_limit",
            "correction", "corrections", "setup"} <= brain.GUARDED_ACTIONS
    assert "corrections" not in brain.UNTRUSTED_INFO  # not a lookup (review Y4)
    assert "misheard" not in brain.GUARDED_ACTIONS


def test_voiceio_uses_wake_engine():
    waited = []
    with mock.patch.object(wakeword, "choose", return_value=("openwakeword", lambda: waited.append(1))), \
            mock.patch.dict(sys.modules, {"jarvis.stt": mock.Mock(), "jarvis.tts": mock.Mock(spec=[])}):
        io = main.VoiceIO({"voice": {}, "wake_word": "jarvis", "listen_timeout": 5})
        io.wait_for_wake_word()
    assert io.wake_engine == "openwakeword" and waited == [1]


def test_tray_state_and_stop_on_exit():
    states = []
    main._tray = mock.Mock(set_state=states.append)
    try:
        with mock.patch.object(tray, "stop") as stop, mock.patch.object(actions, "run", return_value="ok"):
            main.run(FakeIO(["what time is it", "goodbye"]), _cfg(), nlu, actions)
        stop.assert_called_once()
        assert "thinking" in states
    finally:
        main._tray = None


def test_onboarding_overrides_config(tmp_path):
    from jarvis.config import load_config

    onboarding.USER_FILE.write_text('{"name": "Rakesh", "city": "Hyderabad", "units": "metric", "done": true}',
                                    encoding="utf-8")
    cfg = load_config(str(tmp_path / "none.yaml"))
    assert cfg["user_name"] == "Rakesh" and cfg["weather"]["city"] == "Hyderabad"


def test_setup_flag_runs_onboarding(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("ai:\n  enabled: false\n", encoding="utf-8")
    with mock.patch.object(onboarding, "run", return_value="Setup done.") as run, \
            mock.patch.object(main, "run") as loop, mock.patch.object(main, "setup_logging"), \
            mock.patch.object(main, "_wire_features"), mock.patch.object(actions, "start_reminders"), \
            mock.patch.object(actions.triggers, "start"):
        main.main(["--text", "--setup", "--config", str(cfg_file)])
    run.assert_called_once()
    loop.assert_called_once()


# ---------- round 7 (maps, documents, contacts, habits, flashcards, watchers, fileconvert) ----------
from jarvis.actions import contacts, documents, files, flashcards, habits, watchers  # noqa: E402

ROUND7 = [
    ("how long to drive to Hyderabad", "travel_time", {"to": "how long to drive to Hyderabad"}),
    ("navigate to Charminar", "directions", {"to": "navigate to Charminar"}),
    ("read this pdf", "document", {"action": "read"}),
    ("read page 3", "document", {"action": "page", "page": 3}),
    ("add contact Ravi phone 98765 43210", "contact_add", {"name": "Ravi", "phone": "98765 43210"}),
    ("delete contact Ravi", "contact_delete", {"name": "Ravi"}),
    ("I did my workout", "habit_done", {"name": "workout"}),
    ("add flashcard to Spanish hello means hola", "flashcard_add", {"deck": "spanish", "front": "hello", "back": "hola"}),
    ("tell me when my download finishes", "watch", {"what": "download"}),
    ("tell me when battery is 80 percent", "watch", {"what": "battery", "value": 80}),
    ("stop watching", "watches", {"action": "cancel"}),
    ("convert this to pdf", "convert_file", {"action": "to_pdf"}),
    ("convert this image to png", "convert_file", {"action": "to_format", "format": "png"}),
    ("merge these pdfs", "convert_file", {"action": "merge_pdfs"}),
    # old phrases still work: units stay with convert.py, quizzes with fun.py
    ("convert 5 km to miles", "convert", {"amount": 5, "from": "km", "to": "miles"}),
    ("quiz me", "quiz", {"action": "start"}),
    ("read this", "read_aloud", {}),
    ("read the screen", "ocr", {"source": "screen", "action": "read"}),
    ("set a timer for 5 minutes", "timer", {"seconds": 300}),
]


@pytest.mark.parametrize("text,intent,args", ROUND7)
def test_round7_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_continue_only_with_open_document():
    assert nlu.parse("continue").intent != "document"
    documents._STATE["doc"] = object()
    try:
        assert nlu.parse("continue").args == {"action": "continue"}
    finally:
        documents.reset()


def test_flashcards_before_fun_quiz():
    flashcards.HANDLERS["flashcard_add"]({"deck": "spanish", "front": "hello", "back": "hola"})
    assert nlu.parse("quiz me on spanish").intent == "flashcard_quiz"


def test_flashcard_quiz_hook():
    with mock.patch.object(flashcards, "is_active", return_value=True), \
            mock.patch.object(flashcards, "takes", side_effect=lambda t, i: i != "open_app"), \
            mock.patch.object(flashcards, "process", return_value="Right!") as proc, \
            mock.patch.object(actions, "run", return_value="Opening chrome."):
        assert main.handle("hola", FakeIO([]), _cfg(), nlu, actions) == "Right!"
        assert main.handle("open chrome", FakeIO([]), _cfg(), nlu, actions) == "Opening chrome."
    proc.assert_called_once_with("hola")


def test_round7_risky():
    with mock.patch.object(contacts, "risky_text", return_value="delete contact Ravi"):
        assert actions.needs_confirm(nlu.Command("contact_delete", {"name": "Ravi"}))
    with mock.patch.object(habits, "risky_text", return_value="delete the habit workout"):
        assert actions.needs_confirm(nlu.Command("habit_remove", {"name": "workout"}))
    with mock.patch.object(flashcards, "risky_text", return_value="delete the spanish deck"):
        assert actions.needs_confirm(nlu.Command("deck_delete", {"deck": "spanish"}))


def test_saved_contacts_used_by_phone_and_email():
    contacts.HANDLERS["contact_add"]({"name": "Ravi", "phone": "98765 43210", "email": "ravi@example.com"})
    assert phone.resolve_number("Ravi") == "9876543210"
    assert files._contact("ravi", "email") == "ravi@example.com"


def test_round7_wire_and_lists():
    from jarvis import brain

    said = []
    with mock.patch.object(habits, "start") as hs, mock.patch.object(watchers, "set_notifier") as wn:
        main._wire_features(mock.Mock(say=said.append), actions)
    hs.assert_called_once()
    wn.assert_called_once()
    assert {"document", "travel_time"} <= brain.UNTRUSTED_INFO
    assert {"directions", "contact_add", "contact_delete", "habit_remove", "deck_delete", "convert_file"} \
        <= brain.GUARDED_ACTIONS


# ---------- round 8 (airquality, recipes, accessibility, radio, localmusic, timetrack) + BA birthdays ----------
from jarvis.actions import birthdays, radio, recipes  # noqa: E402

ROUND8 = [
    ("aqi in delhi", "air_quality", {"city": "delhi"}),
    ("will it rain in the next hour", "rain_soon", {}),
    ("when is sunset", "sun_times", {}),
    ("uv index today", "uv", {}),
    ("cook pasta", "cook", {"action": "start", "name": "pasta"}),
    ("recipe for dal", "recipe", {"action": "find", "query": "dal"}),
    ("turn on the magnifier", "accessibility", {"feature": "magnifier", "action": "on"}),
    ("play radio mirchi", "radio", {"action": "play", "query": "radio mirchi"}),
    ("next station", "radio", {"action": "next"}),
    ("stop the radio", "radio", {"action": "stop"}),
    ("play my music", "local_music", {"action": "play"}),
    ("play the album aashiqui 2 from my music", "local_music", {"action": "play", "album": "aashiqui 2"}),
    ("start tracking college project", "track", {"action": "start", "project": "college project"}),
    ("delete last session", "track_undo", {}),
    ("mom's birthday is 12 March", "birthday_add", {"name": "mom", "date": "12 march", "kind": "birthday"}),
    ("birthdays this month", "birthday_get", {"period": "month"}),
    # old phrases still work
    ("what's the weather", "weather", {}),
    ("will it rain tomorrow", "weather", {}),
    ("zoom in", "press_keys", {"keys": "ctrl+="}),
    ("next song", "media", {"action": "next"}),
    ("turn off wifi", "wifi", {"state": "off"}),
    ("play arijit singh", "play", {"query": "arijit singh"}),
    ("how much time did I spend on chrome", "screen_time", {"app": "chrome"}),
    ("I did my workout", "habit_done", {"name": "workout"}),
    ("add contact Ravi phone 98765 43210", "contact_add", {"name": "Ravi", "phone": "98765 43210"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND8)
def test_round8_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_cook_mode_hook():
    with mock.patch.object(recipes, "is_active", return_value=True), \
            mock.patch.object(recipes, "match_cook", side_effect=lambda t: ("cook", {"action": "next"}) if t == "next" else None), \
            mock.patch.object(actions, "run", side_effect=lambda c, *a, **k: f"ran {c.intent}") as run:
        assert main.handle("next", FakeIO([]), _cfg(), nlu, actions) == "ran cook"
        assert main.handle("what time is it", FakeIO([]), _cfg(), nlu, actions) == "ran time"
    assert run.call_count == 2


def test_cook_mode_skipped_for_trigger_steps():
    with mock.patch.object(recipes, "is_active", return_value=True), \
            mock.patch.object(recipes, "match_cook") as mc, mock.patch.object(actions, "run", return_value="ok"):
        main.handle("next", FakeIO([]), _cfg(), nlu, actions, depth=1, skip_modes=True)
    mc.assert_not_called()


def test_round8_risky_and_lists():
    from jarvis import brain
    from jarvis.actions import timetrack

    with mock.patch.object(timetrack, "risky_text", return_value="delete the last session"):
        assert actions.needs_confirm(nlu.Command("track_undo", {}))
    assert {"air_quality", "sun_times", "rain_soon", "uv"} <= brain.UNTRUSTED_INFO  # E5: own data is trusted
    assert {"radio", "track_undo", "birthday_add"} <= brain.GUARDED_ACTIONS


def test_round8_wire_and_exit():
    with mock.patch.object(birthdays, "start") as bs:
        main._wire_features(mock.Mock(), actions)
    bs.assert_called_once()
    with mock.patch.object(birthdays, "stop") as bst, mock.patch.object(radio, "stop_all") as rs:
        main._stop_recordings(actions)
    bst.assert_called_once()
    rs.assert_called_once()


# ---------- round 9 (printer, vdesktops, sleeptimer, filesearch, devtools, recap) ----------
from jarvis.actions import devtools, filesearch, printer, recap, sleeptimer  # noqa: E402

ROUND9 = [
    ("print this document", "print_file", {"name": "this"}),
    ("print my last download", "print_file", {"name": "last download"}),
    ("cancel printing", "print_queue", {"action": "cancel"}),
    ("which printer", "printer_info", {}),
    ("new desktop", "vdesktop", {"action": "new"}),
    ("go to desktop 2", "vdesktop", {"action": "go", "number": "2"}),
    ("move this window to desktop 3", "vdesktop", {"action": "move_window", "number": "3"}),
    ("close this desktop", "vdesktop", {"action": "close"}),
    ("stop the music in 30 minutes", "sleep_timer", {"minutes": 30, "action": "stop_media"}),
    ("shut down in 2 hours", "sleep_timer", {"minutes": 120, "action": "shutdown"}),
    ("sleep the laptop in 1 hour", "sleep_timer", {"minutes": 60, "action": "sleep"}),
    ("cancel sleep timer", "sleep_timer_cancel", {}),
    ("find the file that mentions invoice", "find_files", {"text": "invoice"}),
    ("files I edited today", "find_files", {"modified": "today"}),
    ("run the tests", "dev", {"action": "test"}),
    ("push my changes", "dev", {"action": "git_push"}),
    ("how was my day", "recap", {"day": "today"}),
    # old phrases still work
    ("print this", "press_keys", {"keys": "ctrl+p"}),
    ("press print", "press_keys", {"keys": "print"}),
    ("open printer settings", "open_settings", {"page": "printer"}),
    ("show desktop", "window", {"action": "show_desktop"}),
    ("close this window", "window", {"action": "close"}),
    ("shut down", "shutdown", {}),
    ("set a timer for 5 minutes", "timer", {"seconds": 300}),
    ("cancel the timer", "timers", {"action": "cancel"}),
    ("open chrome", "open_app", {"name": "chrome"}),
    ("close chrome", "close_app", {"name": "chrome"}),
    ("stop the music", "media", {"action": "stop"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND9)
def test_round9_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_open_result_only_after_a_search():
    with mock.patch.object(filesearch, "has_results", return_value=False):
        assert nlu.parse("open the second one").intent != "open_result"
    with mock.patch.object(filesearch, "has_results", return_value=True):
        assert nlu.parse("open the second one").args == {"number": "second"}


def test_round9_risky():
    assert actions.needs_confirm(nlu.Command("sleep_timer", {"minutes": 60, "action": "shutdown"}))
    assert not actions.needs_confirm(nlu.Command("sleep_timer", {"minutes": 30, "action": "stop_media"}))
    with mock.patch.object(devtools, "needs_confirm", return_value=True), \
            mock.patch.object(devtools, "risky_text", return_value="push jarvis to the remote"):
        assert actions.needs_confirm(nlu.Command("dev", {"action": "git_push"}))
    with mock.patch.object(printer, "needs_confirm", return_value=True), \
            mock.patch.object(printer, "risky_text", return_value="print report.pdf"):
        assert actions.needs_confirm(nlu.Command("print_file", {"name": "report.pdf"}))


def test_shutdown_timer_cancelled_on_no():
    io = FakeIO(["no"])
    with mock.patch.object(sleeptimer, "sleep_timer" if hasattr(sleeptimer, "sleep_timer") else "risky_text") as st:
        reply = main._run_one(nlu.Command("sleep_timer", {"minutes": 60, "action": "shutdown"}), io, _cfg(), actions)
    assert reply == "Okay, cancelled."
    if hasattr(sleeptimer, "sleep_timer"):
        st.assert_not_called()


def test_round9_lists_and_wire():
    from jarvis import brain

    assert {"printer_info", "find_files"} <= brain.UNTRUSTED_INFO
    assert {"print_file", "print_queue", "vdesktop", "sleep_timer", "open_result", "dev"} <= brain.GUARDED_ACTIONS
    with mock.patch.object(sleeptimer, "set_notifier") as sn, mock.patch.object(recap, "start") as rs:
        main._wire_features(mock.Mock(), actions)
    sn.assert_called_once()
    rs.assert_called_once()


# ---------- rounds 10-11 (drives, hotspot, display, webcam, multilang, voiceid) ----------
from jarvis.actions import multilang, security as _security, voiceid  # noqa: E402

ROUND10 = [
    ("what drives are connected", "drives", {"action": "list"}),
    ("open my pen drive", "drives", {"action": "open", "drive": "pen drive"}),
    ("turn on hotspot", "hotspot", {"action": "on"}),
    ("extend my screen", "display", {"action": "extend"}),
    ("take a photo", "webcam", {"action": "photo"}),
    ("understand hindi", "language", {"action": "on", "lang": "hi"}),
    ("learn my voice", "voice_id", {"action": "enrol"}),
    ("voice lock on", "voice_id", {"action": "on"}),
    ("forget my voice", "voice_id", {"action": "forget"}),
    # old phrases still work
    ("how much disk space", "system_info", {"what": "disk"}),
    ("open hotspot settings", "open_settings", {"page": "hotspot"}),
    ("turn off the screen", "screen_off", {}),
    ("take a screenshot", "screenshot", {}),
    ("open camera", "open_app", {"name": "camera"}),
    ("lock jarvis", "jarvis_lock", {"state": "on"}),
    ("forget everything", "forget_memory", {}),
    ("speak slower", "voice", {"change": "slower"}),
]


@pytest.mark.parametrize("text,intent,args", ROUND10)
def test_round10_phrases(text, intent, args):
    cmd = nlu.parse(text)
    assert (cmd.intent, cmd.args) == (intent, args)


def test_round10_security_and_lists():
    from jarvis import brain

    assert set(voiceid.PROTECT) <= set(_security.DEFAULT_PROTECT)
    assert callable(_security.ask_pin)
    assert {"webcam", "voice_id", "language"} <= brain.GUARDED_ACTIONS
    with mock.patch.object(voiceid, "needs_confirm", return_value=True):
        assert actions.needs_confirm(nlu.Command("voice_id", {"action": "forget"}))


def test_security_goes_through_voice_guard():
    with mock.patch.object(voiceid, "guard", return_value="Say your PIN.") as g:
        reply = main._run_one(nlu.Command("shutdown", {}), FakeIO([]), _cfg(), actions)
    assert reply == "Say your PIN."
    assert g.call_args.kwargs["risky"] is True


def test_command_audio_kept_for_voice_id():
    class VoiceLike(FakeIO):
        stt = mock.Mock(last_audio=b"abc")
    with mock.patch.object(voiceid, "remember_audio") as ra, mock.patch.object(actions, "run", return_value="ok"):
        main.run(VoiceLike(["what time is it", "goodbye"]), _cfg(), nlu, actions)
    ra.assert_any_call(b"abc")


def test_voiceio_uses_multilang():
    with mock.patch.object(wakeword, "choose", return_value=("vosk", None)), \
            mock.patch.dict(sys.modules, {"jarvis.stt": mock.Mock(), "jarvis.tts": mock.Mock(spec=["say"])}):
        io = main.VoiceIO({"voice": {}, "wake_word": "jarvis", "listen_timeout": 5})
        io.tts = mock.Mock()
        with mock.patch.object(multilang, "is_active", return_value=True), \
                mock.patch.object(multilang, "listen", return_value="open chrome") as ml:
            assert io.listen() == "open chrome"
        ml.assert_called_once_with(timeout=5)
        with mock.patch.object(multilang, "reply_language", return_value="hi"), \
                mock.patch.object(multilang, "say_reply", return_value=True) as sr:
            io.say("Opening Chrome.")
        sr.assert_called_once_with("Opening Chrome.")
        io.tts.say.assert_not_called()
