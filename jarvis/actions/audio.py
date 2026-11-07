"""Audio: what's playing, mic mute, per-app volume, switch speakers/headphones.

Windows only at run time:
- now_playing: WinRT media session (package winrt-Windows.Media.Control).
- mic, app_volume, audio_output: pycaw (+ comtypes).
Every Windows call sits in a small `_xxx()` function so tests can replace it.
"""
from __future__ import annotations

import asyncio
import os
import re

_SOUND_SETTINGS = "ms-settings:sound"

# Spoken app name -> process names (lower case, no ".exe").
_APP_ALIASES = {
    "chrome": ["chrome"],
    "google chrome": ["chrome"],
    "edge": ["msedge"],
    "microsoft edge": ["msedge"],
    "firefox": ["firefox"],
    "teams": ["ms-teams", "teams"],
    "microsoft teams": ["ms-teams", "teams"],
    "zoom": ["zoom"],
    "vlc": ["vlc"],
    "media player": ["microsoft.media.player", "wmplayer"],
    "windows media player": ["microsoft.media.player", "wmplayer"],
    "whatsapp": ["whatsapp", "whatsapp.root"],
    "brave": ["brave"],
    "opera": ["opera"],
    "skype": ["skype"],
}

# Spoken output kind -> words that may be in the device name.
_DEVICE_WORDS = {
    "headphones": ["headphone", "headset", "earphone", "earbud", "buds", "airpods", "hands-free"],
    "headset": ["headset", "headphone", "hands-free"],
    "earbuds": ["earbud", "buds", "airpods", "headphone"],
    "speakers": ["speaker"],
    "speaker": ["speaker"],
    "tv": ["tv", "hdmi", "display"],
    "monitor": ["hdmi", "display", "monitor"],
    "hdmi": ["hdmi"],
    "bluetooth": ["bluetooth", "hands-free", "airpods", "buds"],
}

_APP_NAMES = {  # AppUserModelId part -> nice name for "what's playing"
    "spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
    "zunemusic": "Media Player", "microsoft.media.player": "Media Player", "vlc": "VLC",
}


def _clamp(v: float) -> int:
    return max(0, min(100, int(round(v))))


def _open(uri: str) -> None:
    os.startfile(uri)  # type: ignore[attr-defined]


def _simple(name: str) -> str:
    """'Spotify.exe' -> 'spotify', 'Google Chrome' -> 'googlechrome'."""
    name = name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return re.sub(r"[^a-z0-9]", "", name)


# ======================= now playing (WinRT) =======================
async def _media_info_async() -> dict | None:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    mgr = await Manager.request_async()
    session = mgr.get_current_session()
    if session is None:
        return None
    props = await session.try_get_media_properties_async()
    status = session.get_playback_info().playback_status
    return {
        "title": (props.title if props else "") or "",
        "artist": (props.artist if props else "") or "",
        "app": session.source_app_user_model_id or "",
        "playing": int(status) == 4,  # 4 = PLAYING, 5 = PAUSED
    }


def _media_info() -> dict | None:
    """{title, artist, app, playing} of the current media, or None."""
    return asyncio.run(_media_info_async())


def _app_label(app_id: str) -> str:
    low = app_id.lower()
    for key, nice in _APP_NAMES.items():
        if key in low:
            return nice
    # "Spotify.exe" or "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
    part = re.split(r"[!\\/]", app_id)[-1]
    part = part[:-4] if part.lower().endswith(".exe") else part
    return part.split(".")[-1] or "an app"


def now_playing(args: dict) -> str:
    try:
        info = _media_info()
    except Exception:
        return "I can't see what's playing on this computer."
    if not info or not (info.get("title") or info.get("artist")):
        return "Nothing is playing right now."
    title, artist = info.get("title", ""), info.get("artist", "")
    song = f"{title} by {artist}" if title and artist else (title or artist)
    where = f" on {_app_label(info['app'])}" if info.get("app") else ""
    if info.get("playing", True):
        return f"Playing {song}{where}."
    return f"Paused: {song}{where}."


# ======================= microphone (pycaw) =======================
def _mic_endpoints() -> list:
    """Endpoint volume objects of the default mic(s) (normal + calls role)."""
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    if hasattr(AudioUtilities, "GetDeviceEnumerator"):
        enum = AudioUtilities.GetDeviceEnumerator()
    else:  # older pycaw
        from pycaw.pycaw import CLSID_MMDeviceEnumerator, IMMDeviceEnumerator

        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
    eps, seen = [], set()
    for role in (0, 2):  # eConsole, eCommunications
        try:
            dev = enum.GetDefaultAudioEndpoint(1, role)  # 1 = eCapture
        except Exception:
            continue
        if dev is None or dev.GetId() in seen:
            continue
        seen.add(dev.GetId())
        iface = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
        eps.append(iface.QueryInterface(IAudioEndpointVolume))
    return eps


def mic(args: dict) -> str:
    state = str(args.get("state") or "").lower()
    try:
        eps = _mic_endpoints()
    except Exception:
        eps = []
    if not eps:
        return "I can't find a microphone."
    if state not in ("on", "off"):
        muted = all(ep.GetMute() for ep in eps)
        return "Your mic is muted." if muted else "Your mic is on."
    for ep in eps:
        ep.SetMute(1 if state == "off" else 0, None)
    return "Mic muted." if state == "off" else "Mic is on."


# ======================= per-app volume (pycaw) =======================
def _sessions() -> list[tuple[str, object]]:
    """(process name, ISimpleAudioVolume) for every app that has a sound session."""
    from pycaw.pycaw import AudioUtilities

    out = []
    for s in AudioUtilities.GetAllSessions():
        proc = s.Process
        if proc is None:
            continue
        try:
            out.append((proc.name(), s.SimpleAudioVolume))
        except Exception:
            continue
    return out


def _find_sessions(app: str, sessions: list[tuple[str, object]]) -> list[tuple[str, object]]:
    want = app.lower().strip()
    names = _APP_ALIASES.get(want) or [want]
    wanted = [_simple(n) for n in names if _simple(n)]
    exact = [s for s in sessions if _simple(s[0]) in wanted]
    if exact:
        return exact
    return [s for s in sessions if any(w in _simple(s[0]) for w in wanted)]


def app_volume(args: dict) -> str:
    app = str(args.get("app") or "").strip()
    if not app:
        return "Which app?"
    try:
        found = _find_sessions(app, _sessions())
    except Exception:
        found = []
    nice = app.title() if app.islower() else app
    if not found:
        return f"{nice} isn't playing any sound right now."
    change = str(args.get("change") or "").lower()
    if change in ("mute", "unmute"):
        for _, vol in found:
            vol.SetMute(1 if change == "mute" else 0, None)
        return f"{nice} {'muted' if change == 'mute' else 'unmuted'}."
    current = _clamp(found[0][1].GetMasterVolume() * 100)
    if args.get("level") is not None:
        level = _clamp(float(args["level"]))
    elif change in ("up", "down"):
        step = int(args.get("step") or 10)
        level = _clamp(current + (step if change == "up" else -step))
    else:
        return f"{nice} volume is at {current} percent."
    for _, vol in found:
        vol.SetMute(0, None)
        vol.SetMasterVolume(level / 100, None)
    return f"{nice} volume set to {level} percent."


# ======================= output device (pycaw) =======================
def _output_devices() -> list[dict]:
    """[{id, name, default}] for active speakers/headphones."""
    from pycaw.pycaw import AudioUtilities

    try:
        default_id = AudioUtilities.GetSpeakers().id
    except Exception:
        default_id = None
    out = []
    for d in AudioUtilities.GetAllDevices(data_flow=0, device_state=1):  # render, active
        if d is None or not d.FriendlyName:
            continue
        out.append({"id": d.id, "name": str(d.FriendlyName), "default": d.id == default_id})
    return out


def _set_default_output(dev_id: str) -> None:
    from pycaw.constants import ERole
    from pycaw.pycaw import AudioUtilities

    AudioUtilities.SetDefaultDevice(dev_id, roles=[ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])


def _match_device(name: str, devices: list[dict]) -> dict | None:
    want = name.lower().strip()
    for prefix in ("my ", "the "):
        if want.startswith(prefix):
            want = want[len(prefix):]
    words = _DEVICE_WORDS.get(want, [want])
    for w in words:
        for d in devices:
            if w in d["name"].lower():
                return d
    # every spoken word appears in the device name
    parts = [p for p in re.split(r"\W+", want) if p]
    for d in devices:
        if parts and all(p in d["name"].lower() for p in parts):
            return d
    return None


def audio_output(args: dict) -> str:
    name = str(args.get("name") or "").strip()
    try:
        devices = _output_devices()
    except Exception:
        _open(_SOUND_SETTINGS)
        return "I can't read your audio devices, so I opened Sound settings."
    if not devices:
        return "I can't find any speakers or headphones."
    if not name:
        names = ", ".join(d["name"] + (" (in use)" if d["default"] else "") for d in devices)
        return f"Your audio outputs: {names}."
    dev = _match_device(name, devices)
    if dev is None:
        names = ", ".join(d["name"] for d in devices)
        return f"I can't find {name}. You have: {names}."
    if dev["default"]:
        return f"Already using {dev['name']}."
    try:
        _set_default_output(dev["id"])
    except Exception:
        _open(_SOUND_SETTINGS)
        return "I couldn't switch it myself, so I opened Sound settings."
    return f"Switched sound to {dev['name']}."


# ======================= wiring =======================
_STR = {"type": "string"}
_INT = {"type": "integer"}

CATALOG: dict[str, dict] = {
    "now_playing": {
        "description": "Say which song or video is playing now (title, artist, app).",
        "properties": {}, "required": [], "info": True,
    },
    "mic": {
        "description": "Mute or unmute the microphone. state off = mute, on = unmute. Leave out state to ask if it is muted.",
        "properties": {"state": {"type": "string", "enum": ["on", "off"]}},
        "required": [],
    },
    "app_volume": {
        "description": "Set the volume of one app only (e.g. spotify, chrome, zoom). Give level OR change.",
        "properties": {
            "app": {"description": "Spoken app name, lower case.", **_STR},
            "level": {"description": "0-100", **_INT},
            "change": {"type": "string", "enum": ["up", "down", "mute", "unmute"]},
        },
        "required": ["app"],
    },
    "audio_output": {
        "description": "Switch sound output (speakers, headphones, a device name). Leave out name to list the outputs.",
        "properties": {"name": {"description": "Device or kind, e.g. headphones, speakers, airpods.", **_STR}},
        "required": [],
    },
}

HANDLERS = {
    "now_playing": now_playing,
    "mic": mic,
    "app_volume": app_volume,
    "audio_output": audio_output,
}
