"""Screen recording (piece S).

- With ffmpeg (in PATH or config `recorder.ffmpeg_path`): records the whole screen with
  gdigrab to an .mp4 in `Videos/Jarvis`. No sound (screen only).
- Without ffmpeg: presses Win+Alt+R (Xbox Game Bar). It records only the active app and
  saves to `Videos/Captures`. Game Bar must be on in Windows Settings.

Intent: `screen_record {action: start|stop|open}` -> HANDLERS["screen_record"].
Not risky. No main.py hooks needed. Optional: call `recorder.stop_all()` on exit so a
running recording is saved.

Config (all optional), in config.yaml:
    recorder:
      ffmpeg_path: ""          # full path to ffmpeg.exe; empty = look in PATH
      folder: "~/Videos/Jarvis"
      fps: 30
      max_minutes: 60          # safety limit; 0 = no limit
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

DEFAULTS: dict = {"ffmpeg_path": "", "folder": "~/Videos/Jarvis", "fps": 30, "max_minutes": 60}
GAMEBAR_FOLDER = "~/Videos/Captures"

_proc = None            # running ffmpeg process
_file: Path | None = None
_started: float = 0.0
_gamebar = False        # True while a Game Bar recording is (probably) running


def settings(cfg: dict | None = None) -> dict:
    """DEFAULTS + config `recorder:` (top-level `ffmpeg_path` also works)."""
    if cfg is None:
        try:
            from jarvis.config import load_config

            cfg = load_config()
        except Exception:
            cfg = {}
    user = cfg.get("recorder") or {}
    out = {**DEFAULTS, **(user if isinstance(user, dict) else {})}
    if not out.get("ffmpeg_path") and cfg.get("ffmpeg_path"):
        out["ffmpeg_path"] = cfg["ffmpeg_path"]
    return out


def find_ffmpeg(s: dict) -> str | None:
    """Config path if it exists, else ffmpeg from PATH, else None."""
    p = (s.get("ffmpeg_path") or "").strip().strip('"')
    if p:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            return p
    return shutil.which("ffmpeg")


def _folder(s: dict) -> Path:
    return Path(os.path.expanduser(s.get("folder") or DEFAULTS["folder"]))


def ffmpeg_cmd(ffmpeg: str, out: Path, fps: int = 30, max_minutes: float = 0) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "gdigrab", "-framerate", str(int(fps)), "-draw_mouse", "1", "-i", "desktop"]
    if max_minutes and float(max_minutes) > 0:
        cmd += ["-t", str(int(float(max_minutes) * 60))]
    # Even width/height are required by libx264 + yuv420p.
    cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            # fragmented mp4: the video still plays if ffmpeg is killed or Jarvis crashes
            "-movflags", "+frag_keyframe+empty_moov", str(out)]
    return cmd


# ---------- small wrappers (tests replace these) ----------
def _popen(cmd: list[str]):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)


def _hotkey(*keys: str) -> None:
    import pyautogui

    pyautogui.hotkey(*keys)


def _open(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _running() -> bool:
    return _proc is not None and _proc.poll() is None


def _length(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    if m and s:
        return f"{m} minute{'s' if m != 1 else ''} {s} second{'s' if s != 1 else ''}"
    if m:
        return f"{m} minute{'s' if m != 1 else ''}"
    return f"{s} second{'s' if s != 1 else ''}"


# ---------- actions ----------
def start(s: dict | None = None) -> str:
    global _proc, _file, _started, _gamebar
    s = s or settings()
    if _running():
        return "I'm already recording the screen."
    if _gamebar:
        return "Game Bar is already recording. Say stop recording first."
    ffmpeg = find_ffmpeg(s)
    if ffmpeg:
        folder = _folder(s)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            out = folder / f"Recording {datetime.now():%Y-%m-%d %H-%M-%S}.mp4"
            _proc = _popen(ffmpeg_cmd(ffmpeg, out, s.get("fps", 30), s.get("max_minutes", 0)))
        except Exception as e:
            _proc = None
            return f"I couldn't start recording: {e}"
        _file, _started = out, time.time()
        return "Recording the screen. Say stop recording when you're done."
    try:
        _hotkey("win", "alt", "r")
    except Exception as e:
        return f"I couldn't start recording. Install ffmpeg or turn on Xbox Game Bar. ({e})"
    _gamebar, _started = True, time.time()
    return ("ffmpeg isn't installed, so I started Xbox Game Bar recording. "
            "It records only the active window.")


def stop(s: dict | None = None) -> str:
    global _proc, _gamebar
    if _proc is not None:
        proc, out = _proc, _file
        took = time.time() - _started
        _proc = None
        if proc.poll() is not None:  # ended by itself (time limit or error)
            if out and out.exists() and out.stat().st_size > 0:
                return f"The recording had already stopped. It's saved in {out.parent.name}."
            return "The recording stopped by itself and nothing was saved."
        try:
            proc.stdin.write(b"q")  # ask ffmpeg to finish the file properly
            proc.stdin.flush()
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        return f"Stopped recording after {_length(took)}. Saved to {out.parent.name if out else 'your Videos'} folder."
    if _gamebar:
        try:
            _hotkey("win", "alt", "r")
        except Exception as e:
            return f"I couldn't stop the Game Bar recording: {e}"
        _gamebar = False
        return "Stopped recording. It's saved in Videos, Captures."
    return "I'm not recording right now."


def open_folder(s: dict | None = None) -> str:
    s = s or settings()
    # ffmpeg recordings go to Videos/Jarvis; Game Bar ones to Videos/Captures.
    folder = _folder(s) if find_ffmpeg(s) else Path(os.path.expanduser(GAMEBAR_FOLDER))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _open(folder)
    except Exception as e:
        return f"I couldn't open the recordings folder: {e}"
    return "Opening your recordings."


def stop_all() -> None:
    """Call on exit: saves a running ffmpeg recording."""
    if _running():
        stop()


def reset() -> None:
    """Clear state (tests)."""
    global _proc, _file, _started, _gamebar
    _proc, _file, _started, _gamebar = None, None, 0.0, False


def screen_record(args: dict) -> str:
    action = str(args.get("action") or "start").lower().strip()
    if action in ("start", "begin", "record", "on"):
        return start()
    if action in ("stop", "end", "finish", "off"):
        return stop()
    if action in ("open", "show", "folder", "where"):
        return open_folder()
    return "Say start recording, stop recording, or where are my recordings."


CATALOG: dict[str, dict] = {
    "screen_record": {
        "description": "Record the laptop screen to a video. start = begin recording, "
                       "stop = stop and save, open = open the recordings folder.",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "open"]},
        },
        "required": ["action"],
    },
}

HANDLERS: dict[str, Callable[[dict], str]] = {"screen_record": screen_record}
