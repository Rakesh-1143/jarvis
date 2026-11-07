"""What each action does and its args. The AI brain turns this into tools.

Keep it in sync with _HANDLERS in actions/__init__.py (a test checks this).
"info": True = the result goes back to the AI (it reads it, then answers),
instead of being spoken straight away.
"""
from __future__ import annotations


def _s(desc: str, **props) -> dict:
    return {"description": desc, **props}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_ONOFF = {"type": "string", "enum": ["on", "off"]}

# intent -> {"description", "properties", "required"}
CATALOG: dict[str, dict] = {
    "open_app": {"description": "Open an app or program on the laptop, e.g. chrome, notepad, spotify, settings.",
                 "properties": {"name": _s("Spoken app name, lower case.", **_STR)}, "required": ["name"]},
    "close_app": {"description": "Force close a running app by name (unsaved work is lost).",
                  "properties": {"name": _s("App name, lower case.", **_STR)}, "required": ["name"]},
    "web_search": {"description": "Open a Google search in the browser. Use when the user wants to SEE search results.",
                   "properties": {"query": _STR}, "required": ["query"]},
    "volume": {"description": "Set or change speaker volume. Give level OR change.",
               "properties": {"level": _s("0-100", **_INT),
                              "change": {"type": "string", "enum": ["up", "down", "mute", "unmute"]}},
               "required": []},
    "brightness": {"description": "Set or change screen brightness. Give level OR change.",
                   "properties": {"level": _s("0-100", **_INT), "change": {"type": "string", "enum": ["up", "down"]}},
                   "required": []},
    "screenshot": {"description": "Take a screenshot and save it.", "properties": {}, "required": []},
    "type_text": {"description": "Type text into the window that has focus.",
                  "properties": {"text": _STR}, "required": ["text"]},
    "time": {"description": "Say the current time and date.", "properties": {}, "required": [], "info": True},
    "lock": {"description": "Lock the computer.", "properties": {}, "required": []},
    "shutdown": {"description": "Shut down the computer (Jarvis asks the user to confirm).", "properties": {}, "required": []},
    "restart": {"description": "Restart the computer (Jarvis asks the user to confirm).", "properties": {}, "required": []},
    "sleep": {"description": "Put the computer to sleep (Jarvis asks the user to confirm).", "properties": {}, "required": []},
    "empty_recycle_bin": {"description": "Empty the recycle bin (Jarvis asks the user to confirm).",
                          "properties": {}, "required": []},
    "timer": {"description": "Start a countdown timer.",
              "properties": {"seconds": _s("Length in seconds.", **_INT), "label": _s("Optional name, e.g. pasta.", **_STR)},
              "required": ["seconds"]},
    "reminder": {"description": "Remind the user about something after some seconds. Work out seconds from the current time if they give a clock time.",
                 "properties": {"seconds": _s("Seconds from now.", **_INT), "text": _s("What to remind about.", **_STR)},
                 "required": ["seconds", "text"]},
    "timers": {"description": "List or cancel all running timers and reminders.",
               "properties": {"action": {"type": "string", "enum": ["list", "cancel"]}}, "required": ["action"]},
    "weather": {"description": "Get the live weather now and today's forecast.",
                "properties": {"city": _s("City name. Leave out for the user's location.", **_STR)}, "required": [], "info": True},
    "news": {"description": "Read the top news headlines, optionally about a topic.",
             "properties": {"topic": _STR}, "required": [], "info": True},
    "system_info": {"description": "Battery, CPU, memory or disk status of this laptop.",
                    "properties": {"what": {"type": "string", "enum": ["battery", "cpu", "memory", "disk", "all"]}},
                    "required": ["what"], "info": True},
    "media": {"description": "Media keys for whatever is playing (Spotify, YouTube, etc.).",
              "properties": {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop"]}},
              "required": ["action"]},
    "play": {"description": "Play a song, artist, video or podcast (opens YouTube results).",
             "properties": {"query": _STR}, "required": ["query"]},
    "window": {"description": "Control the active window or desktop.",
               "properties": {"action": {"type": "string", "enum": ["minimize", "maximize", "restore", "close", "switch",
                                                                     "show_desktop", "snap_left", "snap_right", "task_view"]}},
               "required": ["action"]},
    "open_folder": {"description": "Open a folder: downloads, documents, desktop, pictures, music, videos, home, or a full path.",
                    "properties": {"name": _STR}, "required": ["name"]},
    "open_file": {"description": "Find a file by name in the user's folders and open it.",
                  "properties": {"name": _s("Part of the file name.", **_STR)}, "required": ["name"]},
    "add_note": {"description": "Save a short note for the user.", "properties": {"text": _STR}, "required": ["text"]},
    "read_notes": {"description": "Read the user's latest saved notes.", "properties": {}, "required": [], "info": True},
    "email": {"description": "Open a new email draft in the mail app (never sends). 'to' can be an address or a saved contact name.",
              "properties": {"to": _STR, "subject": _STR, "body": _STR}, "required": []},
    "wifi": {"description": "Turn Wi-Fi on or off, or open Wi-Fi settings if no state. Off asks to confirm.",
             "properties": {"state": _ONOFF}, "required": []},
    "bluetooth": {"description": "Turn Bluetooth on or off, or open Bluetooth settings if no state.",
                  "properties": {"state": _ONOFF}, "required": []},
    "calculate": {"description": "Exact maths. Python expression with + - * / ** % ( ) and sqrt().",
                  "properties": {"expression": _STR}, "required": ["expression"], "info": True},
    "read_clipboard": {"description": "Get the text on the clipboard (to read, summarize, translate or explain it).",
                       "properties": {"full": {"type": "boolean"}}, "required": [], "info": True},
    "get_selected_text": {"description": "Get the text the user has selected/highlighted in the active window.",
                          "properties": {}, "required": [], "info": True},
    "look_at_screen": {"description": "See a screenshot of the user's screen now. Use for 'what's on my screen', 'read this', 'help me with this error'.",
                       "properties": {}, "required": [], "info": True},
    "copy_text": {"description": "Put text on the clipboard (e.g. a translation or a reply the user asked for).",
                  "properties": {"text": _STR}, "required": ["text"]},
    "whatsapp": {"description": "Send a WhatsApp message to a saved contact name or phone number.",
                 "properties": {"to": _STR, "text": _STR}, "required": ["to", "text"]},
    "remember": {"description": "Save a lasting fact about the user (name, preferences, people, plans) for future conversations.",
                 "properties": {"fact": _s("The fact, written in third person, e.g. 'User's sister is Priya'.", **_STR)},
                 "required": ["fact"]},
    "recall": {"description": "List what you remember about the user.", "properties": {}, "required": [], "info": True},
    "forget_memory": {"description": "Delete everything remembered about the user (Jarvis asks to confirm).",
                      "properties": {}, "required": []},
    "routine": {"description": "Run one of the user's saved routines by name (listed in the system prompt).",
                "properties": {"name": _STR}, "required": ["name"]},
}
