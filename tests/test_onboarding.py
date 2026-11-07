"""Piece AU: first-run voice setup. Temp user.json and PIN file; doctor is faked. No mic or OS calls."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import doctor, onboarding, security  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    user = tmp_path / "j" / "user.json"
    monkeypatch.setattr(onboarding, "USER_FILE", user)
    security.reset()  # reset() forgets settings, so configure after it
    security.configure({"pin_file": str(tmp_path / "pin")})
    monkeypatch.setattr(security, "hash_pin", lambda pin, salt=None, iterations=None: _fast_hash(pin, salt))
    checks = [doctor.Check("Python", doctor.OK), doctor.Check("Voice", doctor.OK)]
    monkeypatch.setattr(doctor, "run_checks", lambda cfg=None, full=False, mic=True: list(checks))
    monkeypatch.setattr(doctor, "write_report", lambda results, path=None: None)
    onboarding.set_io(None, None)
    yield user
    security.reset()


def _fast_hash(pin, salt=None):
    import hashlib
    import secrets

    salt = salt or secrets.token_bytes(16)
    return f"pbkdf2_sha256$1000${salt.hex()}${hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, 1000).hex()}"


class FakeIO:
    def __init__(self, answers):
        self.answers = list(answers)
        self.said = []

    def say(self, text):
        self.said.append(text)

    def listen(self):
        if not self.answers:
            return None
        a = self.answers.pop(0)
        if a is KeyboardInterrupt:
            raise KeyboardInterrupt
        return a

    def text(self):
        return " | ".join(self.said)


CFG = {"wake_word": "jarvis", "yes_words": ["yes", True]}


# ---------- parsers ----------
@pytest.mark.parametrize("text, expected", [
    ("Rakesh", "Rakesh"), ("my name is rakesh", "Rakesh"), ("call me Rakesh please", "Rakesh"),
    ("you can call me rakesh reddy", "Rakesh Reddy"), ("I'm Anu.", "Anu"), ("Jarvis, call me Sam", "Sam"),
    ("", None), (None, None), ("skip", None), ("1234", None), ("yes", None),
    ("this is a very long sentence that is not a name", None),
])
def test_parse_name(text, expected):
    assert onboarding.parse_name(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("hyderabad", "Hyderabad"), ("I live in new delhi", "New Delhi"), ("I'm in London.", "London"),
    ("my city is san francisco", "San Francisco"), ("skip", None), ("", None), ("12345", None),
])
def test_parse_city(text, expected):
    assert onboarding.parse_city(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Celsius", "metric"), ("celcius please", "metric"), ("metric", "metric"),
    ("fahrenheit", "imperial"), ("imperial", "imperial"), ("banana", None), (None, None),
])
def test_parse_units(text, expected):
    assert onboarding.parse_units(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("beep", "beep"), ("just a beep", "beep"), ("say yes", "Yes?"), ("voice", "Yes?"), ("hmm", None),
])
def test_parse_greeting(text, expected):
    assert onboarding.parse_greeting(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("yes", True), ("yeah sure", True), ("ok", True), ("no", False), ("no thanks", False),
    ("nope", False), ("maybe", None), ("", None), (None, None),
])
def test_parse_yes_no(text, expected):
    assert onboarding.parse_yes_no(text, CFG["yes_words"]) is expected


# ---------- user.json ----------
def test_needs_setup_when_missing(tmp_files):
    assert not tmp_files.exists()
    assert onboarding.needs_setup()
    assert onboarding.load_user() == {}


def test_broken_user_json_means_setup(tmp_files):
    tmp_files.parent.mkdir(parents=True)
    tmp_files.write_text("{not json", encoding="utf-8")
    assert onboarding.load_user() == {}
    assert onboarding.needs_setup()


def test_save_never_stores_pin(tmp_files):
    onboarding.save_user({"name": "A", "pin": "1234", "pin_hash": "x", "done": True})
    data = json.loads(tmp_files.read_text(encoding="utf-8"))
    assert data == {"name": "A", "done": True}
    assert not onboarding.needs_setup()


def test_config_overrides():
    over = onboarding.config_overrides({"name": "Rakesh", "city": "Hyderabad", "units": "metric",
                                        "greeting": "beep", "mic_ok": True})
    assert over == {"user_name": "Rakesh", "weather": {"city": "Hyderabad", "units": "metric"},
                    "greeting": "beep"}
    assert onboarding.config_overrides({}) == {}
    assert onboarding.config_overrides({"units": "kelvin"}) == {}


def test_config_overrides_reads_file():
    onboarding.save_user({"city": "Pune"})
    assert onboarding.config_overrides() == {"weather": {"city": "Pune"}}
    assert onboarding.user_name("there") == "there"


def test_module_imports_no_config_at_load():
    """config.py will import this module, so it must not import jarvis.config at the top."""
    src = Path(onboarding.__file__).read_text(encoding="utf-8")
    top_level = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert not [ln for ln in top_level if "jarvis" in ln]


# ---------- full flow ----------
FULL = ["call me rakesh", "hyderabad", "celsius", "beep", "good morning jarvis", "jarvis",
        "yes", "one two three four", "1 2 3 4"]


def test_full_setup_voice(tmp_files):
    io = FakeIO(FULL)
    reply = onboarding.run(io.say, io.listen, CFG, voice=True)
    assert reply.startswith("Setup done, Rakesh")
    data = json.loads(tmp_files.read_text(encoding="utf-8"))
    assert data["name"] == "Rakesh" and data["city"] == "Hyderabad" and data["units"] == "metric"
    assert data["greeting"] == "beep" and data["mic_ok"] and data["wake_ok"] and data["pin_set"]
    assert data["done"] is True and data["check_problems"] == 0
    assert "1234" not in tmp_files.read_text(encoding="utf-8")
    assert security.has_pin()
    assert "1234" not in io.text() and "one two three four" not in io.text()  # PIN never spoken back
    assert "All 2 checks OK." in io.text()
    assert not onboarding.needs_setup()


def test_pin_never_logged(caplog):
    caplog.set_level("INFO", logger="jarvis.onboarding")
    io = FakeIO(FULL)
    onboarding.run(io.say, io.listen, CFG, voice=True)
    assert "one two three four" not in caplog.text and "1 2 3 4" not in caplog.text
    assert "hyderabad" in caplog.text


def test_text_mode_skips_mic_and_wake(tmp_files):
    io = FakeIO(["Rakesh", "Pune", "fahrenheit", "say yes", "no"])
    onboarding.run(io.say, io.listen, CFG, voice=False)
    data = onboarding.load_user()
    assert data["units"] == "imperial" and data["greeting"] == "Yes?"
    assert "mic_ok" not in data and "wake_ok" not in data and "pin_set" not in data
    assert "microphone" not in io.text().lower()
    assert data["done"]


def test_skip_and_silence(tmp_files):
    # name skipped, city silent twice, units retry then ok, greeting skip, mic silent, wake wrong, pin no
    io = FakeIO(["skip", None, None, "kelvin", "celsius", "skip", None, "hello", "no"])
    reply = onboarding.run(io.say, io.listen, CFG, voice=True)
    data = onboarding.load_user()
    assert "name" not in data and "city" not in data and "greeting" not in data
    assert data["units"] == "metric"
    assert data["mic_ok"] is False and data["wake_ok"] is False
    assert reply.startswith("Setup done.")
    assert "Skipped." in io.said and "Let's skip that for now." in io.said


def test_stop_setup_early(tmp_files):
    io = FakeIO(["Rakesh", "stop setup"])
    reply = onboarding.run(io.say, io.listen, CFG)
    assert "stopped" in reply
    data = onboarding.load_user()
    assert data["name"] == "Rakesh" and data["done"] is True  # no nagging next start


def test_ctrl_c_saves_partial(tmp_files):
    io = FakeIO(["Rakesh", KeyboardInterrupt])
    with pytest.raises(KeyboardInterrupt):
        onboarding.run(io.say, io.listen, CFG)
    data = onboarding.load_user()
    assert data["name"] == "Rakesh" and data["done"] is False
    assert onboarding.needs_setup()


def test_first_run_only_once():
    io = FakeIO(FULL)
    assert onboarding.first_run(io.say, io.listen, CFG) is not None
    io2 = FakeIO(FULL)
    assert onboarding.first_run(io2.say, io2.listen, CFG) is None
    assert io2.said == []


# ---------- PIN step ----------
def test_pin_mismatch_then_skip():
    io = FakeIO(["yes", "1234", "5678", "12", ])
    onboarding.run(io.say, io.listen, CFG, parts=["pin"])
    assert not security.has_pin()
    assert "The two PINs did not match." in io.said
    assert "pin_set" not in onboarding.load_user()


def test_pin_retry_works():
    io = FakeIO(["sure", "1 2", "four four four four", "four four four four"])
    onboarding.run(io.say, io.listen, CFG, parts=["pin"])
    assert security.has_pin()


def test_pin_already_set():
    security.save_pin("9999")
    io = FakeIO(["yes"])
    onboarding.run(io.say, io.listen, CFG, parts=["pin"])
    assert "already have a PIN" in io.text()
    assert io.answers == ["yes"]  # nothing asked


def test_pin_declined():
    io = FakeIO(["no"])
    onboarding.run(io.say, io.listen, CFG, parts=["pin"])
    assert not security.has_pin()


def test_pin_save_error(monkeypatch):
    def boom(pin):
        raise OSError("read-only")

    monkeypatch.setattr(security, "save_pin", boom)
    io = FakeIO(["yes", "1234", "1234"])
    onboarding.run(io.say, io.listen, CFG, parts=["pin"])
    assert "could not save the PIN" in io.text()


# ---------- self-check step ----------
def test_check_problems_reported(monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", lambda cfg=None, full=False, mic=True: [
        doctor.Check("Python", doctor.OK), doctor.Check("Model", doctor.PROBLEM, short="speech model missing")])
    io = FakeIO([])
    onboarding.run(io.say, io.listen, CFG, parts=["check"])
    assert "speech model missing" in io.text() and "doctor-report.txt" in io.text()
    assert onboarding.load_user()["check_problems"] == 1


def test_check_uses_no_mic(monkeypatch):
    seen = {}

    def fake(cfg=None, full=False, mic=True):
        seen["mic"], seen["full"] = mic, full
        return []

    monkeypatch.setattr(doctor, "run_checks", fake)
    onboarding.run(lambda t: None, lambda: None, CFG, parts=["check"])
    assert seen == {"mic": False, "full": False}


def test_check_crash_is_safe(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(doctor, "run_checks", boom)
    io = FakeIO([])
    onboarding.run(io.say, io.listen, CFG, parts=["check"])
    assert "--doctor" in io.text()


# ---------- partial runs keep other data ----------
def test_change_name_keeps_rest():
    onboarding.save_user({"name": "Old", "city": "Pune", "done": True})
    io = FakeIO(["call me New"])
    assert onboarding.run(io.say, io.listen, CFG, parts=["name"]) == "Done."
    data = onboarding.load_user()
    assert data == {**data, "name": "New", "city": "Pune", "done": True}
    assert not any("Let's set me up" in s for s in io.said)


# ---------- intent ----------
def test_setup_intent_needs_io():
    assert "microphone" in onboarding.setup({})


def test_setup_intent_bad_part():
    onboarding.set_io(lambda t: None, lambda: None)
    assert onboarding.setup({"part": "colour"}).startswith("I can set up")


def test_setup_intent_city():
    io = FakeIO(["Chennai", "celsius"])
    onboarding.set_io(io.say, io.listen, voice=True)
    assert onboarding.setup({"part": "city"}) == "Done."
    assert onboarding.load_user()["city"] == "Chennai"


def test_setup_intent_mic_text_mode():
    onboarding.set_io(lambda t: None, lambda: None, voice=False)
    assert "voice mode" in onboarding.setup({"part": "mic"})


def test_setup_intent_all(monkeypatch):
    io = FakeIO(FULL)
    onboarding.set_io(io.say, io.listen, voice=True)
    monkeypatch.setattr(onboarding, "_has_pin", lambda: True)  # keep the PIN step (first-PIN-by-voice is tested elsewhere)
    assert onboarding.setup({}).startswith("Setup done")


def test_catalog_and_handlers():
    assert set(onboarding.CATALOG) == set(onboarding.HANDLERS) == {"setup"}
    enum = onboarding.CATALOG["setup"]["properties"]["part"]["enum"]
    for p in enum:
        assert p in onboarding._PART_ALIASES
    assert not onboarding.CATALOG["setup"].get("info")
