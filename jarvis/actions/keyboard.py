"""Typing text into the focused window."""
from __future__ import annotations


def type_text(text: str) -> str:
    if not text:
        return "What should I type?"
    import pyautogui

    # typewrite only handles ASCII; paste for anything else.
    if text.isascii():
        pyautogui.typewrite(text, interval=0.02)
    else:
        import time

        import pyperclip

        try:
            old = pyperclip.paste()
        except Exception:
            old = None
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)  # let the app read the clipboard before we put the old text back
        if old is not None:
            pyperclip.copy(old)  # note: only text is kept; an image on the clipboard is lost
    return "Done typing."
