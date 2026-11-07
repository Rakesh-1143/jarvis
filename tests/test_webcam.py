"""Tests for actions/webcam.py with a fake camera and registry (no Windows or camera needed)."""
import pytest

from jarvis.actions import webcam as wc


@pytest.fixture
def env(tmp_path, monkeypatch):
    box = {"beeps": [], "slept": 0.0, "opened": [], "captured": 0, "cfg": {"folder": str(tmp_path / "pics")},
           "frame": (b"\xff\xd8fakejpeg\xff\xd9", 120.0), "error": None, "entries": []}

    def capture(index):
        box["captured"] += 1
        box["index"] = index
        if box["error"]:
            raise box["error"]
        return box["frame"]

    monkeypatch.setattr(wc, "_capture", capture)
    monkeypatch.setattr(wc, "_config", lambda: box["cfg"])
    monkeypatch.setattr(wc, "_beep", lambda f: box["beeps"].append(f))
    monkeypatch.setattr(wc, "_sleep", lambda s: box.__setitem__("slept", box["slept"] + s))
    monkeypatch.setattr(wc, "_open", lambda p: box["opened"].append(p))
    monkeypatch.setattr(wc, "_consent_entries", lambda: box["entries"])
    monkeypatch.setattr(wc.sys, "platform", "win32")
    box["dir"] = tmp_path / "pics"
    return box


def test_photo_saved_and_opened(env):
    out = wc.webcam({"action": "photo"})
    files = list(env["dir"].glob("Photo *.jpg"))
    assert len(files) == 1 and files[0].read_bytes() == env["frame"][0]
    assert out == f"Photo taken. I saved it as {files[0].name} in pics."
    assert env["opened"] == [files[0]]
    assert env["beeps"] == [] and env["captured"] == 1 and env["index"] == 0


def test_two_photos_same_second_do_not_overwrite(env, monkeypatch):
    class Frozen(wc.datetime):
        @classmethod
        def now(cls, tz=None):
            return wc.datetime(2026, 11, 7, 10, 0, 0)

    monkeypatch.setattr(wc, "datetime", Frozen)
    wc.webcam({"action": "photo"})
    wc.webcam({"action": "photo"})
    names = sorted(p.name for p in env["dir"].iterdir())
    assert names == ["Photo 2026-11-07 10-00-00 (2).jpg", "Photo 2026-11-07 10-00-00.jpg"]


def test_countdown_beeps(env):
    wc.webcam({"action": "photo", "delay": 3})
    assert env["beeps"] == [880, 880, 880, 1320]
    assert env["slept"] == pytest.approx(3 * 0.85)


def test_countdown_capped(env):
    out = wc.webcam({"action": "photo", "delay": "60 seconds"})
    assert env["beeps"].count(880) == wc.MAX_DELAY
    assert out.startswith("I waited 10 seconds")


def test_delay_words():
    assert wc._delay("five seconds") == 5
    assert wc._delay("a few") == 3
    assert wc._delay(None) == 0 and wc._delay(True) == 0 and wc._delay(-2) == 0


def test_dark_photo_warns(env):
    env["frame"] = (b"jpg", 1.0)
    assert "camera cover" in wc.webcam({"action": "photo"})


def test_no_open_when_config_says_no(env):
    env["cfg"]["open_after"] = False
    wc.webcam({"action": "photo"})
    assert env["opened"] == []


def test_camera_index_from_config(env):
    env["cfg"]["camera"] = 1
    wc.webcam({"action": "selfie"})
    assert env["index"] == 1


def test_camera_error_said(env):
    env["error"] = wc.CameraError("I couldn't open the camera.")
    assert wc.webcam({"action": "photo"}) == "I couldn't open the camera."
    assert not env["dir"].exists() or not list(env["dir"].iterdir())


def test_other_error_said(env):
    env["error"] = RuntimeError("driver crash")
    assert "driver crash" in wc.webcam({"action": "photo"})


def test_status_not_in_use(env):
    env["entries"] = [("Microsoft.WindowsCamera_8wekyb3d8bbwe", 133000, 133100)]
    assert wc.webcam({"action": "status"}) == "Your camera is not in use right now."


def test_status_in_use(env):
    env["entries"] = [("Microsoft.WindowsCamera_8wekyb3d8bbwe", 133000, 0),
                      ("NonPackaged\\C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe", 133000, 0),
                      ("NonPackaged\\C:#Program Files#Google#Chrome#Application#chrome.exe", 133000, 133500),
                      ("MicrosoftTeams_8wekyb3d8bbwe", 0, 0)]
    assert wc.webcam({"action": "status"}) == "Your camera is on. Camera and Zoom are using it."


def test_app_names():
    assert wc._app_name("Microsoft.WindowsCamera_8wekyb3d8bbwe") == "Camera"
    assert wc._app_name("MicrosoftTeams_8wekyb3d8bbwe") == "Microsoft Teams"
    assert wc._app_name("NonPackaged\\C:#Program Files (x86)#Microsoft#Edge#Application#msedge.exe") == "Edge"


def test_bad_action(env):
    assert "I can take a photo" in wc.webcam({"action": "record video"})


def test_capture_without_opencv(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "cv2":
            raise ImportError("no cv2")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(wc.CameraError, match="opencv-python"):
        wc._capture(0)


def test_capture_releases_camera(monkeypatch):
    import sys
    import types

    released = []

    class Cap:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def read(self):
            return True, types.SimpleNamespace(mean=lambda: 100.0)

        def release(self):
            released.append(1)

    fake_cv2 = types.SimpleNamespace(VideoCapture=Cap, CAP_DSHOW=700, IMWRITE_JPEG_QUALITY=1,
                                     imencode=lambda ext, f, p: (True, types.SimpleNamespace(tobytes=lambda: b"jpg")))
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    assert wc._capture(0) == (b"jpg", 100.0)
    assert released == [1]


@pytest.mark.parametrize("text,args", [
    ("take a photo", {"action": "photo"}),
    ("take a picture", {"action": "photo"}),
    ("click a selfie", {"action": "photo"}),
    ("take a photo of me", {"action": "photo"}),
    ("take a photo with the webcam", {"action": "photo"}),
    ("please take a photo in 3 seconds", {"action": "photo", "delay": 3}),
    ("take a picture in five seconds", {"action": "photo", "delay": 5}),
    ("take a selfie with a timer", {"action": "photo", "delay": 3}),
    ("is my camera on", {"action": "status"}),
    ("is the webcam in use", {"action": "status"}),
    ("which app is using my camera", {"action": "status"}),
    ("who is using my webcam", {"action": "status"}),
    ("is anyone using my camera", {"action": "status"}),
])
def test_parse(text, args):
    assert wc.parse(text) == ("webcam", args)


@pytest.mark.parametrize("text", [
    "take a screenshot", "take a screen shot", "open camera", "camera settings", "show my photos", "",
    "take a note",
])
def test_parse_no_match(text):
    assert wc.parse(text) is None


def test_catalog_matches_handlers():
    assert set(wc.CATALOG) == set(wc.HANDLERS) == {"webcam"}
    assert wc.CATALOG["webcam"]["properties"]["action"]["enum"] == list(wc.ACTIONS)
