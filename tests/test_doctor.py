"""Tests for actions/doctor.py (self-check). No real mic, TTS, network or API calls."""
from pathlib import Path

import pytest

from jarvis.actions import doctor
from jarvis.actions.doctor import OK, OPTIONAL, PROBLEM, SKIPPED


def test_catalog_and_handlers_match():
    assert set(doctor.CATALOG) == set(doctor.HANDLERS) == {"self_check"}
    assert doctor.CATALOG["self_check"]["info"] is True


def test_python_version():
    assert doctor.check_python((3, 12, 1)).status == OK
    bad = doctor.check_python((3, 9, 0))
    assert bad.status == PROBLEM and "3.9.0" in bad.detail and bad.fix


def test_parse_requirements_markers_and_names():
    text = ("PyYAML>=6.0  # core\n# comment\n\npycaw>=1 ; sys_platform == \"win32\"\n"
            "screen-brightness-control>=0.20\nPillow>=10\nwinrt-Windows.Media.Ocr>=2.0; sys_platform == \"win32\"\n")
    linux = doctor.parse_requirements(text, windows=False)
    assert linux == [("PyYAML", "yaml"), ("screen-brightness-control", "screen_brightness_control"), ("Pillow", "PIL")]
    win = dict(doctor.parse_requirements(text, windows=True))
    assert win["pycaw"] == "pycaw" and win["winrt-Windows.Media.Ocr"] == "winrt.windows.media.ocr"


def test_real_requirements_file_parses():
    reqs = doctor.parse_requirements(doctor.REQUIREMENTS.read_text(encoding="utf-8"), windows=True)
    assert ("anthropic", "anthropic") in reqs and len(reqs) > 10


def test_packages(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text("PyYAML>=6\nnot-a-real-pkg-xyz>=1\n")
    r = doctor.check_packages(req)
    assert r.status == PROBLEM and "not-a-real-pkg-xyz" in r.detail and "PyYAML" not in r.detail
    req.write_text("PyYAML>=6\n")
    assert doctor.check_packages(req).status == OK
    assert doctor.check_packages(tmp_path / "nope.txt").status == PROBLEM


def test_vosk_model(tmp_path):
    cfg = {"stt": {"model_path": str(tmp_path / "model")}}
    assert doctor.check_vosk_model(cfg).short == "speech model missing"
    (tmp_path / "model").mkdir()
    assert doctor.check_vosk_model(cfg).short == "speech model broken"
    (tmp_path / "model" / "am").mkdir()
    assert doctor.check_vosk_model(cfg).status == OK


def test_microphone(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "sounddevice", types.ModuleType("sounddevice"))
    monkeypatch.setattr(doctor, "_default_input_name", lambda: None)
    assert doctor.check_microphone().short == "no microphone"
    monkeypatch.setattr(doctor, "_default_input_name", lambda: "USB Mic")
    monkeypatch.setattr(doctor, "_record_level", lambda s: 0.0)
    assert doctor.check_microphone().short == "no microphone sound"
    monkeypatch.setattr(doctor, "_record_level", lambda s: 0.05)
    r = doctor.check_microphone()
    assert r.status == OK and "USB Mic" in r.detail

    def boom(s):
        raise OSError("access denied")

    monkeypatch.setattr(doctor, "_record_level", boom)
    assert doctor.check_microphone().short == "microphone blocked"


def test_tts(monkeypatch):
    monkeypatch.setattr(doctor, "_voices", lambda: ["Microsoft David", "Microsoft Zira"])
    assert doctor.check_tts({}).status == OK
    assert doctor.check_tts({"voice": {"voice_name": "zira"}}).status == OK
    assert doctor.check_tts({"voice": {"voice_name": "Hazel"}}).short == "chosen voice not found"
    monkeypatch.setattr(doctor, "_voices", lambda: [])
    assert doctor.check_tts({}).short == "no speech voices"

    def missing():
        raise ImportError

    monkeypatch.setattr(doctor, "_voices", missing)
    assert doctor.check_tts({}).short == "speech voice missing"


def test_config_type_errors():
    defaults = {"listen_timeout": 5, "voice": {"rate": 180, "voice_name": ""}, "apps": {}, "exit_phrases": [],
                "phone": {}, "ai": {"enabled": True}}
    data = {"listen_timeout": "five", "voice": {"rate": 200.5, "voice_name": 3}, "apps": None,
            "exit_phrases": "bye", "phone": {"device": "x"}, "ai": {"enabled": "yes"}, "unknown": 1}
    errs = doctor.config_type_errors(data, defaults)
    assert "listen_timeout should be number, got text" in errs
    assert "voice.voice_name should be text, got number" in errs
    assert "exit_phrases should be list, got text" in errs
    assert "ai.enabled should be yes/no, got text" in errs
    assert len(errs) == 4  # float rate is fine, empty section fine, unknown keys ignored


def test_check_config_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("wake_word: jarvis\nvoice:\n  rate: 170\n")
    assert doctor.check_config(f).status == OK
    f.write_text("voice:\n  rate: [1\n")
    r = doctor.check_config(f)
    assert r.short == "config.yaml broken" and "line" in r.detail
    f.write_text("listen_timeout: soon\n")
    assert doctor.check_config(f).short == "1 config setting wrong"
    assert doctor.check_config(tmp_path / "missing.yaml").status == OK


def test_real_config_is_valid():
    r = doctor.check_config()
    assert r.status == OK, r.detail


def test_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert doctor.check_api_key({"ai": {"enabled": False}}).status == SKIPPED
    assert doctor.check_api_key({"ai": {}}).status == OPTIONAL
    calls = []
    monkeypatch.setattr(doctor, "_tiny_call", lambda cfg, key: calls.append(key))
    assert doctor.check_api_key({"ai": {"api_key": "sk-1"}}).status == OK
    assert calls == []  # no API call unless full
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert doctor.check_api_key({"ai": {}}, full=True).status == OK and calls == ["sk-env"]

    def fail(cfg, key):
        raise RuntimeError("401 invalid x-api-key")

    monkeypatch.setattr(doctor, "_tiny_call", fail)
    r = doctor.check_api_key({"ai": {}}, full=True)
    assert r.short == "AI key not working" and "401" in r.detail


def test_internet(monkeypatch):
    monkeypatch.setattr(doctor, "_online", lambda: True)
    assert doctor.check_internet().status == OK
    monkeypatch.setattr(doctor, "_online", lambda: False)
    assert doctor.check_internet().short == "no internet"


def test_data_files(tmp_path, monkeypatch):
    cfg = {"notes_file": str(tmp_path / "sub" / "notes.txt"), "lists_file": str(tmp_path / "lists.json"),
           "memory_file": ""}
    r = doctor.check_data_files(cfg)
    assert r.status == OK and r.detail == "2 writable"
    assert not (tmp_path / "sub").exists()  # check creates nothing
    monkeypatch.setattr(doctor, "_writable", lambda p: "lists" not in p.name)
    r = doctor.check_data_files(cfg)
    assert r.status == PROBLEM and "lists_file" in r.detail and "notes_file" not in r.detail


def test_windows_extras(monkeypatch):
    monkeypatch.setattr(doctor, "_is_windows", lambda: False)
    assert [c.status for c in doctor.check_windows_extras({})] == [SKIPPED]
    monkeypatch.setattr(doctor, "_is_windows", lambda: True)
    monkeypatch.setattr(doctor, "_importable", lambda m: m == "pycaw")
    monkeypatch.setattr(doctor, "_find_kdeconnect", lambda cfg: None)
    monkeypatch.setattr(doctor, "_find_ffmpeg", lambda cfg: "C:/ffmpeg.exe")
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)

    def no_winreg():
        raise ImportError("winreg")

    monkeypatch.setattr(doctor, "_outlook_installed", no_winreg)
    res = {c.name: c.status for c in doctor.check_windows_extras({})}
    assert res["Volume control (pycaw)"] == OK and res["ffmpeg"] == OK
    assert res["Phone (KDE Connect)"] == OPTIONAL and res["winget"] == OPTIONAL and res["Outlook"] == OPTIONAL


def _fake_all(monkeypatch, mic_level=0.05):
    monkeypatch.setattr(doctor, "check_python", lambda: doctor._ok("Python"))
    monkeypatch.setattr(doctor, "check_packages", lambda: doctor._ok("Packages"))
    monkeypatch.setattr(doctor, "check_config", lambda: doctor._ok("Config"))
    monkeypatch.setattr(doctor, "check_vosk_model", lambda cfg: doctor._ok("Speech model"))
    monkeypatch.setattr(doctor, "check_microphone",
                        lambda: doctor._ok("Microphone") if mic_level else
                        doctor._bad("Microphone", "x", "y", "no microphone sound"))
    monkeypatch.setattr(doctor, "check_tts", lambda cfg: doctor._ok("Voice"))
    monkeypatch.setattr(doctor, "check_internet", lambda: doctor._ok("Internet"))
    monkeypatch.setattr(doctor, "check_data_files", lambda cfg: doctor._ok("Data"))
    monkeypatch.setattr(doctor, "check_windows_extras",
                        lambda cfg: [doctor._opt("ffmpeg", "not found", "winget", "ffmpeg missing")])


def test_summary_and_report(monkeypatch, tmp_path):
    _fake_all(monkeypatch, mic_level=0)
    monkeypatch.setattr(doctor, "REPORT_FILE", tmp_path / "doctor-report.txt")
    results = doctor.run_checks(cfg={"ai": {"api_key": "k"}})
    text = doctor.summary(results)
    assert text.startswith("8 OK, 1 problem: no microphone sound.")
    assert "Optional, not set up: ffmpeg missing." in text
    reply = doctor.self_check({})
    assert "doctor-report.txt" in reply
    report = (tmp_path / "doctor-report.txt").read_text(encoding="utf-8")
    assert "[FAIL] Microphone: x" in report and "Fix: y" in report and "[OPT ] ffmpeg" in report


def test_all_ok_summary(monkeypatch):
    _fake_all(monkeypatch)
    monkeypatch.setattr(doctor, "check_windows_extras", lambda cfg: [])
    assert doctor.summary(doctor.run_checks(cfg={"ai": {"api_key": "k"}})) == "All 9 checks OK."


def test_crashing_check_does_not_stop_others(monkeypatch):
    _fake_all(monkeypatch)

    def boom():
        raise ValueError("bad")

    monkeypatch.setattr(doctor, "check_internet", boom)
    results = doctor.run_checks(cfg={"ai": {"api_key": "k"}})
    assert any("crashed" in r.detail for r in results)
    assert sum(r.status == OK for r in results) == 8


def test_full_flag_reaches_api_check(monkeypatch, tmp_path):
    _fake_all(monkeypatch)
    seen = []
    monkeypatch.setattr(doctor, "check_api_key", lambda cfg, full: seen.append(full) or doctor._ok("AI"))
    monkeypatch.setattr(doctor, "_load_cfg", lambda: {})
    monkeypatch.setattr(doctor, "REPORT_FILE", tmp_path / "r.txt")
    doctor.self_check({"full": True})
    doctor.self_check({"full": "false"})
    doctor.self_check({})
    assert seen == [True, False, False]


def test_run_cli_exit_code(monkeypatch, tmp_path, capsys):
    _fake_all(monkeypatch, mic_level=0)
    monkeypatch.setattr(doctor, "check_api_key", lambda cfg, full: doctor._ok("AI"))
    monkeypatch.setattr(doctor, "_load_cfg", lambda: {})
    monkeypatch.setattr(doctor, "REPORT_FILE", tmp_path / "r.txt")
    assert doctor.run_cli([]) == 1
    assert "no microphone sound" in capsys.readouterr().out
    _fake_all(monkeypatch)
    assert doctor.run_cli(["--doctor"]) == 0


def test_writable_real_paths(tmp_path):
    f = tmp_path / "a.txt"
    assert doctor._writable(f)
    f.write_text("x")
    assert doctor._writable(f)
    assert not doctor._writable(tmp_path)  # a folder is not a file
