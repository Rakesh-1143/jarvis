"""Volume, brightness, time, lock, shutdown, restart."""
from __future__ import annotations

import datetime as _dt
import subprocess

from jarvis.winutil import NO_WINDOW

DEFAULT_STEP = 10


def _clamp(v: float) -> int:
    return max(0, min(100, int(round(v))))


def _new_level(args: dict, current: int) -> int | None:
    if "level" in args and args["level"] is not None:
        return _clamp(float(args["level"]))
    step = int(args.get("step") or DEFAULT_STEP)
    change = args.get("change")
    if change == "up":
        return _clamp(current + step)
    if change == "down":
        return _clamp(current - step)
    return None


# ---------- volume (pycaw) ----------
def _endpoint():
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    speakers = AudioUtilities.GetSpeakers()
    # Newer pycaw exposes .EndpointVolume directly.
    ep = getattr(speakers, "EndpointVolume", None)
    if ep is not None:
        return ep
    iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def get_volume() -> int:
    return _clamp(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(level: int) -> None:
    ep = _endpoint()
    ep.SetMute(0, None)
    ep.SetMasterVolumeLevelScalar(_clamp(level) / 100, None)


def set_mute(on: bool) -> None:
    _endpoint().SetMute(1 if on else 0, None)


def volume(args: dict) -> str:
    change = args.get("change")
    if change == "mute":
        set_mute(True)
        return "Muted."
    if change == "unmute":
        set_mute(False)
        return "Unmuted."
    level = _new_level(args, get_volume())
    if level is None:
        return f"Volume is at {get_volume()} percent."
    set_volume(level)
    return f"Volume set to {level} percent."


# ---------- brightness (screen-brightness-control) ----------
def get_brightness() -> int:
    import screen_brightness_control as sbc

    vals = sbc.get_brightness()
    return _clamp(vals[0] if isinstance(vals, list) else vals)


def set_brightness(level: int) -> None:
    import screen_brightness_control as sbc

    sbc.set_brightness(_clamp(level))


def brightness(args: dict) -> str:
    try:
        current = get_brightness()
    except Exception:
        return "I can't change brightness on this screen."
    level = _new_level(args, current)
    if level is None:
        return f"Brightness is at {current} percent."
    set_brightness(level)
    return f"Brightness set to {level} percent."


# ---------- time ----------
def tell_time(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    t = now.strftime("%I:%M %p").lstrip("0")
    return f"It's {t}, {now.strftime('%A, %B')} {now.day}."


# ---------- power ----------
def lock() -> str:
    import ctypes

    ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
    return "Locking the computer."


def shutdown() -> str:
    subprocess.Popen(["shutdown", "/s", "/t", "5"], creationflags=NO_WINDOW)
    return "Shutting down in 5 seconds."


def restart() -> str:
    subprocess.Popen(["shutdown", "/r", "/t", "5"], creationflags=NO_WINDOW)
    return "Restarting in 5 seconds."


def sleep() -> str:
    # SetSuspendState(hibernate=False, force=True, wakeup_events_disabled=False)
    import ctypes

    ctypes.windll.powrprof.SetSuspendState(0, 1, 0)  # type: ignore[attr-defined]
    return "Going to sleep."


def empty_recycle_bin() -> str:
    import ctypes

    # flags: no confirm dialog (1) | no progress (2) | no sound (4)
    r = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)  # type: ignore[attr-defined]
    if r not in (0, -2147418113):  # E_UNEXPECTED is returned when the bin is already empty
        return "I couldn't empty the recycle bin."
    return "Recycle bin is empty."
