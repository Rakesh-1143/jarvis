"""Piece AR: system tray icon. No intents.

Jarvis runs with no window, so this small icon near the clock shows what it is doing and lets the
user control it with the mouse.

- Icon colour = state: idle (grey), listening (green), thinking (amber), speaking (blue), paused (red).
- Menu: Pause / Resume listening, Open config, Open log, Run self-check, Restart Jarvis, Quit.
- Pause uses assistant.pause_listening / resume_listening (same pause as "stop listening"), so voice
  and tray never disagree. While paused, set_state("idle"/"listening") shows "paused" instead.

main.py:  tray.start(on_quit=..., on_pause=..., say=io.say)  when not --text,
          tray.set_state("listening" | "thinking" | "speaking" | "idle") at each loop step.
Needs `pystray` + `Pillow`. If pystray is missing or there is no desktop, start() returns False
and every other call does nothing, so Jarvis keeps working without a tray icon.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

IDLE, LISTENING, THINKING, SPEAKING, PAUSED = "idle", "listening", "thinking", "speaking", "paused"
COLORS = {
    IDLE: (128, 128, 128),
    LISTENING: (40, 180, 70),
    THINKING: (235, 170, 20),
    SPEAKING: (40, 120, 230),
    PAUSED: (210, 50, 50),
}
TITLES = {
    IDLE: "Jarvis: waiting for wake word",
    LISTENING: "Jarvis: listening",
    THINKING: "Jarvis: thinking",
    SPEAKING: "Jarvis: speaking",
    PAUSED: "Jarvis: paused",
}
ICON_SIZE = 64

# CATALOG / HANDLERS stay empty: the tray has no voice commands. Kept so the module looks like the others.
CATALOG: dict = {}
HANDLERS: dict = {}

_lock = threading.Lock()
_icon = None                     # pystray.Icon while running
_state = IDLE
_say: Callable[[str], None] | None = None
_on_quit: Callable[[], None] | None = None
_on_pause: Callable[[bool], None] | None = None
_on_restart: Callable[[], None] | None = None
_config_file: Path = CONFIG_FILE
_log_file: Path = PROJECT_ROOT / "jarvis.log"


# ---------- icon picture ----------

def make_image(state: str):
    """A filled circle in the state's colour, with a white 'J'. Returns a PIL Image."""
    from PIL import Image, ImageDraw

    color = COLORS.get(state, COLORS[IDLE])
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, ICON_SIZE - 3, ICON_SIZE - 3), fill=color + (255,))
    # simple "J" from two rectangles and an arc, so no font file is needed
    w = (255, 255, 255, 255)
    d.rectangle((36, 14, 44, 40), fill=w)
    d.rectangle((26, 14, 48, 21), fill=w)
    d.arc((18, 28, 44, 52), start=0, end=180, fill=w, width=8)
    return img


# ---------- state ----------

def _paused() -> bool:
    try:
        from jarvis.actions import assistant

        return assistant.is_paused()
    except Exception:
        return False


def shown_state(state: str) -> str:
    """What the icon should show. A paused Jarvis shows 'paused' while it waits or listens."""
    state = state if state in COLORS else IDLE
    if state in (IDLE, LISTENING) and _paused():
        return PAUSED
    return state


def set_state(state: str) -> None:
    """Change the icon colour and tooltip. Safe to call any time, from any thread, even with no tray."""
    global _state
    with _lock:
        _state = state if state in COLORS else IDLE
        icon = _icon
    if icon is None:
        return
    shown = shown_state(_state)
    try:
        icon.icon = make_image(shown)
        icon.title = TITLES[shown]
    except Exception:
        log.debug("tray: could not update icon", exc_info=True)


def get_state() -> str:
    return _state


def is_running() -> bool:
    return _icon is not None


# ---------- menu actions ----------

def _open(path: Path) -> bool:
    """Open a file in its default app (Notepad for .yaml/.log on most PCs)."""
    path = Path(path)
    if not path.exists():
        _tell(f"I could not find {path.name}.")
        return False
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
        else:
            webbrowser.open(path.resolve().as_uri())
        return True
    except Exception as e:
        log.warning("tray: could not open %s: %s", path, e)
        _tell(f"I could not open {path.name}.")
        return False


def _tell(text: str) -> None:
    """Speak (if main gave a say function) and show a tray balloon."""
    if _say is not None:
        try:
            _say(text)
        except Exception:
            log.debug("tray: say failed", exc_info=True)
    icon = _icon
    if icon is not None:
        try:
            icon.notify(text, "Jarvis")
        except Exception:
            pass  # notify is not supported everywhere


def toggle_pause(*_args) -> bool:
    """Pause or resume listening. Returns True if Jarvis is now paused."""
    from jarvis.actions import assistant

    if assistant.is_paused():
        assistant.resume_listening({})
        now = False
    else:
        assistant.pause_listening({})
        now = True
    if _on_pause is not None:
        try:
            _on_pause(now)
        except Exception:
            log.exception("tray: on_pause failed")
    set_state(_state)
    return now


def pause_label(*_args) -> str:
    return "Resume listening" if _paused() else "Pause listening"


def open_config(*_args) -> bool:
    return _open(_config_file)


def open_log(*_args) -> bool:
    return _open(_log_file)


def _run_self_check() -> str:
    from jarvis.actions import doctor

    return doctor.self_check({})


def self_check(*_args) -> threading.Thread:
    """Run the doctor in the background (takes a few seconds) and tell the result."""
    def work():
        try:
            _tell(_run_self_check())
        except Exception as e:
            log.exception("tray: self-check failed")
            _tell(f"Self-check failed: {e}")

    t = threading.Thread(target=work, name="jarvis-tray-doctor", daemon=True)
    t.start()
    return t


def restart_command() -> list[str]:
    """Command that starts Jarvis again the same way it was started."""
    return [sys.executable, *sys.argv]


# Small helper process: waits until the old Jarvis has really exited (mic closed), then starts the new one.
# Without it, two Jarvis could listen and answer at the same time.
_WAIT_THEN_START = """
import subprocess, sys, time
pid, cmd = int(sys.argv[1]), sys.argv[2:]
try:
    import psutil
    end = time.time() + 30
    while psutil.pid_exists(pid) and time.time() < end:
        time.sleep(0.2)
except ImportError:
    time.sleep(3)
subprocess.Popen(cmd)
"""


def restart_launcher() -> list[str]:
    return [sys.executable, "-c", _WAIT_THEN_START, str(os.getpid()), *restart_command()]


def restart(*_args) -> None:
    """Quit this Jarvis; a helper starts the new one after this one has exited."""
    if _on_restart is not None:
        _on_restart()
        return
    try:
        subprocess.Popen(restart_launcher(), cwd=os.getcwd())
    except Exception as e:
        log.exception("tray: restart failed")
        _tell(f"I could not restart: {e}")
        return
    quit_jarvis()


def quit_jarvis(*_args) -> None:
    """Remove the icon, then call main's on_quit (which must end the program)."""
    stop()
    if _on_quit is not None:
        try:
            _on_quit()
        except SystemExit:
            raise
        except Exception:
            log.exception("tray: on_quit failed")


def _menu(pystray):
    item = pystray.MenuItem
    return pystray.Menu(
        item(pause_label, toggle_pause, default=True),  # default = double-click the icon
        pystray.Menu.SEPARATOR,
        item("Open config", open_config),
        item("Open log", open_log),
        item("Run self-check", self_check),
        pystray.Menu.SEPARATOR,
        item("Restart Jarvis", restart),
        item("Quit", quit_jarvis),
    )


# ---------- start / stop ----------

def _import_pystray():
    import pystray

    return pystray


def start(on_quit: Callable[[], None] | None = None, on_pause: Callable[[bool], None] | None = None,
          say: Callable[[str], None] | None = None, on_restart: Callable[[], None] | None = None,
          config_file: str | Path | None = None, log_file: str | Path | None = None) -> bool:
    """Show the tray icon in its own thread. Returns False (and logs why) if it can't, never raises.

    on_quit: called after "Quit"; must end Jarvis (main can stop recordings, then os._exit(0)).
    on_pause(paused): optional, called after Pause/Resume.
    say: optional, speaks self-check results and errors.
    on_restart: optional; default starts `python <same args>` and then quits.
    """
    global _icon, _say, _on_quit, _on_pause, _on_restart, _config_file, _log_file
    if _icon is not None:
        return True
    _say, _on_quit, _on_pause, _on_restart = say, on_quit, on_pause, on_restart
    _config_file = Path(config_file) if config_file else CONFIG_FILE
    if log_file:
        _log_file = Path(log_file).expanduser()
        if not _log_file.is_absolute():
            _log_file = Path.cwd() / _log_file  # main's logging writes relative to the working folder
    try:
        pystray = _import_pystray()
        shown = shown_state(_state)
        icon = pystray.Icon("jarvis", make_image(shown), TITLES[shown], menu=_menu(pystray))
    except Exception as e:
        log.warning("tray: no tray icon (%s). Install pystray and Pillow to get one.", e)
        return False

    def run():
        global _icon
        try:
            icon.run()
        except Exception:
            log.exception("tray: icon stopped with an error")
        finally:
            with _lock:
                if _icon is icon:
                    _icon = None

    with _lock:
        _icon = icon
    threading.Thread(target=run, name="jarvis-tray", daemon=True).start()
    return True


def stop() -> None:
    """Remove the icon. Safe to call twice or with no tray."""
    global _icon
    with _lock:
        icon, _icon = _icon, None
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            log.debug("tray: stop failed", exc_info=True)
