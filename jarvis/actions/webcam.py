"""Piece BS: webcam photo and "is my camera on".

"take a photo", "take a photo in 3 seconds", "take a selfie", "is my camera on", "which app is using my camera".

Intent: webcam {action: photo|status, delay?}
  photo  - one still photo from the webcam, saved to Pictures/Jarvis/Photo <date time>.jpg, then opened.
           Optional countdown (0-10 s) with a beep each second. The camera is released at once.
  status - (info) is the camera in use now, and by which apps (Windows privacy registry, no camera access)

Privacy: one photo only when asked, never video, never in the background; the reply always says a photo was taken.
Photo needs opencv-python (optional package). Status needs nothing extra (winreg).
Config (optional):
  webcam:
    folder: "~/Pictures/Jarvis"
    camera: 0            # camera number when there is more than one
    open_after: true     # open the photo after taking it
Tests swap `_capture()`, `_consent_entries()`, `_open()`, `_beep()` and `_sleep()` for fakes.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ACTIONS = ("photo", "status")
_SYNONYMS = {
    "picture": "photo", "pic": "photo", "selfie": "photo", "snap": "photo", "capture": "photo", "take_photo": "photo",
    "in_use": "status", "check": "status", "on": "status", "using": "status", "who": "status",
}
MAX_DELAY = 10
WARMUP_FRAMES = 10  # first frames are dark while the camera adjusts exposure
_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "a few": 3, "few": 3, "couple of": 2, "a couple of": 2}


class CameraError(Exception):
    """Said to the user as it is."""


# ---------- config ----------

def _config() -> dict:
    try:
        from jarvis.config import load_config

        cfg = (load_config() or {}).get("webcam") or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _pictures() -> Path:
    home = Path.home()
    for p in (home / "Pictures", home / "OneDrive" / "Pictures"):
        if p.is_dir():
            return p
    return home / "Pictures"


def _folder() -> Path:
    custom = _config().get("folder")
    return Path(os.path.expanduser(str(custom))) if custom else _pictures() / "Jarvis"


# ---------- hardware ----------

def _capture(index: int) -> tuple[bytes, float]:
    """(JPEG bytes, mean brightness 0-255). Camera is always released."""
    try:
        import cv2
    except ImportError as e:
        raise CameraError("I need the opencv-python package to take photos. Install it with: pip install opencv-python") from e
    cap = None
    try:
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index)  # Media Foundation backend
        if not cap.isOpened():
            raise CameraError("I couldn't open the camera. It may be in use, unplugged, or blocked in "
                              "Settings, Privacy, Camera (let desktop apps use the camera).")
        frame = None
        for _ in range(WARMUP_FRAMES + 1):
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
        if frame is None:
            raise CameraError("The camera opened but gave no picture. Another app may be using it.")
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            raise CameraError("I couldn't save the photo.")
        return buf.tobytes(), float(frame.mean())
    finally:
        if cap is not None:
            cap.release()


def _beep(freq: int) -> None:
    try:
        import winsound

        winsound.Beep(freq, 150)
    except Exception:
        pass


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _open(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]


def _consent_entries() -> list[tuple[str, int, int]]:
    """[(app key name, LastUsedTimeStart, LastUsedTimeStop)] from HKCU and HKLM. Never raises."""
    try:
        import winreg
    except ImportError:
        return []
    out: list[tuple[str, int, int]] = []

    def read(root, path, name_prefix=""):
        try:
            with winreg.OpenKey(root, path) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    if sub == "NonPackaged":
                        read(root, path + "\\" + sub, "NonPackaged\\")
                        continue
                    try:
                        with winreg.OpenKey(key, sub) as k:
                            start = int(winreg.QueryValueEx(k, "LastUsedTimeStart")[0])
                            stop = int(winreg.QueryValueEx(k, "LastUsedTimeStop")[0])
                        out.append((name_prefix + sub, start, stop))
                    except OSError:
                        continue
        except OSError:
            pass

    read(winreg.HKEY_CURRENT_USER, _STORE)
    read(winreg.HKEY_LOCAL_MACHINE, _STORE)
    return out


# ---------- words ----------

def _app_name(key: str) -> str:
    """'Microsoft.WindowsCamera_8wekyb3d8bbwe' -> 'Camera'; 'NonPackaged\\C:#Program Files#Zoom#bin#Zoom.exe' -> 'Zoom'."""
    if key.startswith("NonPackaged\\"):
        exe = key.split("#")[-1]
        name = re.sub(r"\.exe$", "", exe, flags=re.I)
        return {"msedge": "Edge", "msedgewebview2": "Edge", "chrome": "Chrome", "firefox": "Firefox",
                "ms-teams": "Teams", "teams": "Teams", "python": "Jarvis", "pythonw": "Jarvis"}.get(name.lower(), name)
    base = key.split("_")[0].split(".")[-1]
    base = re.sub(r"^Windows(?=[A-Z])", "", base)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base) or key


def apps_using_camera() -> list[str]:
    names: list[str] = []
    for key, start, stop in _consent_entries():
        if start and not stop:
            n = _app_name(key)
            if n not in names:
                names.append(n)
    return names


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _delay(value) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower()
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    for word, n in sorted(_NUM_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{word}\b", text):
            return n
    return 0


# ---------- handler ----------

def _status() -> str:
    if sys.platform != "win32":
        return "I can only check the camera on Windows."
    users = apps_using_camera()
    if not users:
        return "Your camera is not in use right now."
    return f"Your camera is on. {_join(users)} {'is' if len(users) == 1 else 'are'} using it."


def _photo(args: dict) -> str:
    delay = _delay(args.get("delay"))
    capped = delay > MAX_DELAY
    delay = min(delay, MAX_DELAY)
    for _ in range(delay):
        _beep(880)
        _sleep(0.85)
    if delay:
        _beep(1320)
    cfg = _config()
    try:
        index = int(cfg.get("camera", 0) or 0)
    except (TypeError, ValueError):
        index = 0
    try:
        data, brightness = _capture(index)
    except CameraError as e:
        return str(e)
    except Exception as e:
        return f"I couldn't take a photo: {e}"
    folder = _folder()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Photo {datetime.now():%Y-%m-%d %H-%M-%S}.jpg"
        n = 2
        while path.exists():
            path = folder / f"Photo {datetime.now():%Y-%m-%d %H-%M-%S} ({n}).jpg"
            n += 1
        path.write_bytes(data)  # write_bytes, not cv2.imwrite: works with non-English folder names
    except OSError as e:
        return f"I took a photo but couldn't save it: {e}"
    reply = f"Photo taken. I saved it as {path.name} in {folder.name}."
    if capped:
        reply = f"I waited {MAX_DELAY} seconds, the longest I wait. " + reply
    if brightness < 4:
        reply += " It looks black. Is the camera cover closed?"
    if cfg.get("open_after", True):
        try:
            _open(path)
        except Exception:
            pass
    return reply


def webcam(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "photo").strip().lower().replace(" ", "_")
    action = _SYNONYMS.get(action, action)
    if action not in ACTIONS:
        return "I can take a photo with your webcam, or tell you if your camera is in use."
    if action == "status":
        return _status()
    return _photo(args)


# ---------- phrases (for nlu_features) ----------

_SHOT = r"(?:a |one )?(?:photo|picture|pic|selfie|snap(?:shot)?|photograph)(?: of me)?"
_CAM = r"(?:(?:my|the|laptop|web) )*(?:web ?cam(?:era)?|camera|cam)"


def parse(text: str):
    """(intent, args) or None. "take a screenshot" is NOT matched (screenshot intent). Call before open_app."""
    t = re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip("?.! ")
    if not t or "screen" in t:
        return None
    t = re.sub(r"^(?:please |can you |could you |jarvis )+", "", t)
    m = re.fullmatch(rf"(?:take|click|capture|snap|shoot|grab) {_SHOT}(?: (?:with|using|from) {_CAM})?"
                     rf"(?: (?:in|after) ((?:\d+|a few|few|a couple of|one|two|three|four|five|six|seven|eight|nine|ten)"
                     rf"(?: seconds?| secs?)?)| with (?:a )?(?:timer|countdown))?(?: please)?", t)
    if m:
        args: dict = {"action": "photo"}
        if m.group(1):
            args["delay"] = _delay(m.group(1))
        elif re.search(r"timer|countdown", t):
            args["delay"] = 3
        return "webcam", args
    if re.fullmatch(rf"(?:is|are) {_CAM} (?:on|in use|being used|recording|active|working)"
                    rf"|(?:which|what) (?:apps?|programs?) (?:is|are) using {_CAM}|who(?:'s| is) using {_CAM}"
                    rf"|is (?:anyone|anything|any app|something) using {_CAM}|{_CAM} status", t):
        return "webcam", {"action": "status"}
    return None


CATALOG: dict[str, dict] = {
    "webcam": {
        "description": ("Webcam: take ONE still photo (only when the user asks; optional countdown 0-10 s with beeps; "
                        "saved to Pictures/Jarvis and opened), or say whether the camera is in use now and by which "
                        "apps. Never records video."),
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "delay": {"type": "integer", "description": "Seconds to count down before the photo (0-10)."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"webcam": webcam}
