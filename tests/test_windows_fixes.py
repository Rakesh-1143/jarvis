"""Tests for the "runs on real Windows" fixes (winutil, mic rate fallback, installer, single instance)."""
import array
import io
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jarvis import stt, winutil  # noqa: E402

sys.path.insert(0, str(ROOT / "packaging"))
import install_packages  # noqa: E402


# ---------- winutil ----------

def test_winutil_is_safe_off_windows():
    winutil.com_init()
    winutil.com_init()  # twice is fine
    assert winutil.single_instance() is True
    if sys.platform != "win32":
        assert winutil.NO_WINDOW == 0


def test_com_init_runs_once_per_thread(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(windll=types.SimpleNamespace(
        ole32=types.SimpleNamespace(CoInitializeEx=lambda *a: calls.append(a))))
    monkeypatch.setattr(winutil, "IS_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(winutil, "_local", type(winutil._local)())
    winutil.com_init()
    winutil.com_init()
    assert calls == [(None, 2)]


def test_fix_console_replaces_unprintable_letters(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    winutil.fix_console()
    print("Spent ₹500")
    out.flush()
    assert raw.getvalue().startswith(b"Spent ?500")


def test_fix_console_without_console(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    winutil.fix_console()  # pythonw.exe: no crash


# ---------- mic sample rate ----------

def _pcm(values):
    return array.array("h", values).tobytes()


def test_resample_48k_to_16k_keeps_length_and_shape():
    data = _pcm([i * 5 for i in range(6000)])  # 0.125 s at 48 kHz
    out = array.array("h")
    out.frombytes(stt.resample(data, 48000))
    assert len(out) == 2000
    assert out[0] == 0 and out[-1] == 29995
    assert all(b >= a for a, b in zip(out, out[1:]))


def test_resample_same_rate_is_unchanged():
    data = _pcm([1, 2, 3])
    assert stt.resample(data, 16000) is data


def test_mic_rate_falls_back_to_device_rate():
    class SD:
        def check_input_settings(self, **kw):
            raise Exception("Invalid sample rate")

        def query_devices(self, kind=None):
            return {"default_samplerate": 48000.0}

    assert stt._mic_rate(SD()) == 48000


def test_mic_rate_prefers_16k():
    class SD:
        def check_input_settings(self, **kw):
            return None

    assert stt._mic_rate(SD()) == 16000


def test_mic_chunks_converts_to_16k(monkeypatch):
    opened = {}

    class Stream:
        def __init__(self, samplerate, blocksize, callback, **kw):
            opened.update(rate=samplerate, block=blocksize)
            self.cb = callback

        def __enter__(self):
            self.cb(_pcm([0] * 6000), 6000, None, None)
            return self

        def __exit__(self, *a):
            return False

    sd = types.SimpleNamespace(
        check_input_settings=lambda **kw: (_ for _ in ()).throw(Exception("bad rate")),
        query_devices=lambda kind=None: {"default_samplerate": 48000},
        RawInputStream=Stream)
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    chunks = stt._mic_chunks()
    first = next(chunks)
    chunks.close()
    assert opened == {"rate": 48000, "block": 6000}
    assert len(first) == 2 * 2000


# ---------- installer ----------

def test_requirement_lines_and_names():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = install_packages.requirement_lines(text)
    names = {install_packages.package_name(x) for x in lines}
    assert {"pyyaml", "vosk", "sounddevice", "pyttsx3"} <= names
    assert not any(x.startswith("#") or "  #" in x for x in lines)
    assert install_packages.package_name('winrt-Windows.Foundation>=2.0; sys_platform == "win32"') == \
        "winrt-windows-foundation"


def test_installer_continues_when_optional_package_fails(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("PyYAML>=6.0  # core\nspotipy>=2.24  # optional\n", encoding="utf-8")
    monkeypatch.setattr(install_packages, "REQUIREMENTS", req)
    monkeypatch.setattr(install_packages, "_pip", lambda *a: 1 if a[0] in ("-r", "spotipy>=2.24") else 0)
    assert install_packages.main() == 0


def test_installer_fails_when_core_package_fails(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("vosk>=0.3.45\nspotipy>=2.24\n", encoding="utf-8")
    monkeypatch.setattr(install_packages, "REQUIREMENTS", req)
    monkeypatch.setattr(install_packages, "_pip", lambda *a: 1 if a[0] in ("-r", "vosk>=0.3.45") else 0)
    assert install_packages.main() == 1


@pytest.mark.parametrize("name", ["install.bat", "uninstall.bat"])
def test_bat_files_use_windows_line_endings(name):
    # cmd.exe can jump to the wrong place ("goto :fail") in .bat files with Unix (LF only) line endings.
    data = (ROOT / "packaging" / name).read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n") > 0


def test_install_bat_uses_package_helper():
    assert "install_packages.py" in (ROOT / "packaging" / "install.bat").read_text(encoding="utf-8")


# ---------- one Jarvis at a time ----------

def test_second_voice_jarvis_stops(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(winutil, "single_instance", lambda *a: False)
    monkeypatch.setattr(main, "setup_logging", lambda *a: None)
    monkeypatch.setattr(main, "run", lambda *a, **k: pytest.fail("must not start"))
    assert main.main([]) == 0


# ---------- config.yaml mistakes ----------

def test_config_windows_path_in_double_quotes_gives_clear_error(tmp_path):
    from jarvis.config import ConfigError, load_config

    bad = tmp_path / "config.yaml"
    bad.write_text('apps:\n  music: "C:\\Users\\me\\Music"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="line 2.*single quotes"):
        load_config(bad)


def test_config_with_notepad_bom_loads(tmp_path):
    from jarvis.config import load_config

    f = tmp_path / "config.yaml"
    f.write_bytes("\ufeffwake_word: friday\n".encode("utf-8"))
    assert load_config(f)["wake_word"] == "friday"


def test_main_reports_config_mistake_and_stops(monkeypatch, tmp_path):
    import main

    bad = tmp_path / "config.yaml"
    bad.write_text("wake_word: [oops\n", encoding="utf-8")
    said = []
    monkeypatch.setattr(main, "_config_problem", said.append)
    monkeypatch.setattr(main, "run", lambda *a, **k: pytest.fail("must not start"))
    assert main.main(["--text", "--config", str(bad)]) == 1
    assert "config.yaml has a mistake" in said[0]


# ---------- voice backup (SAPI) ----------

def test_tts_falls_back_to_sapi_on_windows(monkeypatch):
    from unittest import mock

    from jarvis import tts

    spoken = []
    monkeypatch.setattr(tts.sys, "platform", "win32")
    monkeypatch.setattr(tts, "_speak_sapi", spoken.append)
    with mock.patch.object(tts, "pyttsx3") as p:
        p.init.side_effect = RuntimeError("pyttsx3 broke")
        tts.say("hello")
    assert spoken == ["hello"]


def test_tts_no_sapi_fallback_off_windows(monkeypatch):
    from unittest import mock

    from jarvis import tts

    monkeypatch.setattr(tts.sys, "platform", "linux")
    monkeypatch.setattr(tts, "_speak_sapi", lambda t: pytest.fail("no SAPI off Windows"))
    with mock.patch.object(tts, "pyttsx3") as p:
        p.init.side_effect = RuntimeError("no audio")
        tts.say("hello")  # never raises


# ---------- open Start menu / Store apps ----------

START = [("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"), ("Zoom Workplace", "zoom.us.Zoom.Video.Meetings"),
         ("Uninstall Zoom", "zoom.uninstall"), ("Discord", "com.squirrel.Discord.Discord"),
         ("Microsoft Teams", "MSTeams_8wekyb3d8bbwe!MSTeams")]


@pytest.mark.parametrize("said, name", [("whatsapp", "WhatsApp"), ("zoom", "Zoom Workplace"),
                                        ("teams", "Microsoft Teams"), ("discrod", "Discord")])
def test_find_start_app(said, name):
    from jarvis.actions import apps

    assert apps.find_start_app(said, START)[0] == name


def test_find_start_app_unknown():
    from jarvis.actions import apps

    assert apps.find_start_app("blender", START) is None
    assert apps.find_start_app("whatsapp", []) is None


def test_open_app_uses_start_menu(monkeypatch):
    from unittest import mock

    from jarvis.actions import apps

    opened = []

    def startfile(target):
        if not target.startswith("shell:AppsFolder"):
            raise OSError("not found")
        opened.append(target)

    monkeypatch.setattr(apps, "start_menu_apps", lambda: START)
    with mock.patch.object(apps.shutil, "which", return_value=None), \
            mock.patch.object(apps.os, "startfile", create=True, side_effect=startfile):
        assert apps.open_app("whatsapp") == "Opening WhatsApp."
    assert opened == ["shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"]


def test_start_menu_apps_off_windows_is_empty(monkeypatch):
    from jarvis.actions import apps

    monkeypatch.setattr(apps, "_start_cache", None)
    if sys.platform != "win32":
        assert apps.start_menu_apps() == []
