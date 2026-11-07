"""Screenshots."""
from __future__ import annotations

import datetime as _dt
import os

SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis")


def screenshot() -> str:
    import pyautogui

    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    name = _dt.datetime.now().strftime("screenshot_%Y-%m-%d_%H-%M-%S.png")
    path = os.path.join(SCREENSHOT_DIR, name)
    pyautogui.screenshot(path)
    return f"Screenshot saved in your {os.path.basename(os.path.normpath(SCREENSHOT_DIR))} folder."
