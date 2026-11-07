"""Core loop tests with fake stt/nlu/actions. Run: python -m pytest tests"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from jarvis.config import DEFAULTS, load_config  # noqa: E402


@dataclass
class Command:
    intent: str
    args: dict = field(default_factory=dict)


class FakeNLU:
    @staticmethod
    def parse(text):
        if "shut down" in text:
            return Command("shutdown")
        if "time" in text:
            return Command("time")
        if "crash" in text:
            return Command("crash")
        return Command("unknown")


class FakeActions:
    def __init__(self):
        self.done = []

    def run(self, cmd):
        if cmd.intent == "shutdown":
            if not cmd.args.get("confirm"):
                return "Are you sure you want to shut down?"
            self.done.append("shutdown")
            return "Shutting down."
        if cmd.intent == "cancel":
            return "Okay, cancelled."
        if cmd.intent == "crash":
            raise RuntimeError("boom")
        self.done.append(cmd.intent)
        return "It is 10 AM."


class FakeIO:
    def __init__(self, heard):
        self.heard, self.said = list(heard), []

    def wait_for_wake_word(self):
        if not self.heard:
            raise KeyboardInterrupt

    def listen(self):
        return self.heard.pop(0) if self.heard else None

    def say(self, text):
        self.said.append(text)


def go(heard):
    io, acts = FakeIO(heard), FakeActions()
    main.run(io, DEFAULTS, FakeNLU, acts)
    return io.said, acts.done


def test_simple_command():
    said, done = go(["what time is it"])
    assert "It is 10 AM." in said and done == ["time"]
    assert said[1] == "Yes?"


def test_unknown():
    said, _ = go(["blah"])
    assert "Sorry, I did not understand that." in said


def test_shutdown_yes():
    said, done = go(["shut down", "yes"])
    assert "Are you sure you want to shut down?" in said and done == ["shutdown"]


def test_shutdown_no():
    said, done = go(["shut down", "no don't do it"])
    assert "Okay, cancelled." in said and done == []


def test_shutdown_silence_cancels():
    said, done = go(["shut down"])
    assert "Okay, cancelled." in said and done == []


def test_error_does_not_crash():
    said, done = go(["crash", "what time is it"])
    assert any(s.startswith("Sorry, something went wrong") for s in said) and done == ["time"]


def test_exit_phrase():
    said, done = go(["goodbye jarvis", "what time is it"])
    assert said[-1] == "Goodbye." and done == []


def test_config_file_loads():
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
    assert cfg["wake_word"] == "jarvis" and "notepad" in cfg["apps"]


def test_real_nlu_and_actions_confirm(monkeypatch):
    """Real nlu + actions; the real shutdown is replaced so nothing turns off."""
    from jarvis import actions, nlu
    from jarvis.actions import system

    calls = []
    monkeypatch.setattr(system, "shutdown", lambda: calls.append("shutdown") or "Shutting down.")
    io = FakeIO(["shut down", "no", "yes"])  # "no" cancels; a later "yes" must NOT shut down
    main.run(io, DEFAULTS, nlu, actions)
    assert calls == []
    assert "Okay, cancelled." in io.said

    io = FakeIO(["please shut down the computer", "yes"])
    main.run(io, DEFAULTS, nlu, actions)
    assert calls == ["shutdown"]


def test_exit_needs_whole_phrase():
    p = DEFAULTS["exit_phrases"]
    assert main.is_exit("Goodbye.", p) and main.is_exit("goodbye jarvis", p) and main.is_exit("exit jarvis", p)
    assert not main.is_exit("whatsapp mom saying goodbye see you soon", p)
    assert not main.is_exit("remind me to say goodbye to Ravi", p)


def test_mic_error_does_not_stop_jarvis(monkeypatch):
    monkeypatch.setattr(main, "MIC_RETRY_SECONDS", 0)
    calls = {"n": 0}
    said = []

    class IO:
        follow_up = False

        def wait_for_wake_word(self):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise OSError("mic unplugged")
            raise KeyboardInterrupt

        def listen(self, timeout=None):
            return None

        def say(self, text):
            said.append(text)

    main.run(IO(), dict(DEFAULTS), FakeNLU, FakeActions())
    assert calls["n"] == 4
    assert sum("microphone" in s for s in said) == 1
