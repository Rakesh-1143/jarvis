"""Full system control: one place that lists the new intents, so wiring them in is small.

Wiring (in actions/__init__.py):
    from . import control
    _HANDLERS.update(control.HANDLERS)
    CATALOG.update(control.CATALOG)
    _risky_text:  q = control.risky_question(intent, args); if q: return q
    _do_risky:    if intent in control.RISKY: return control.do_risky(intent, args)
In main.py, after set_notifier:  actions.control.set_io(io.say, io.listen)
In nlu.parse, after volume/brightness and before _device_rules:
    hit = nlu_control.parse_control(t)  ->  (intent, args) or None
"""
from __future__ import annotations

from . import fileops, inputs, processes, winsettings

RISKY = {"delete_file", "kill_process", "computer_use"}


def set_io(say_fn, listen_fn) -> None:
    """Screen control speaks questions and listens for answers mid-task."""
    from jarvis import agent

    agent.say, agent.listen = say_fn, listen_fn


def computer_use(args: dict) -> str:
    task = str(args.get("task") or "").strip()
    if not task:
        return "What should I do on the screen?"
    if args.get("confirm") is not True:
        return "Say yes to let me take control of the screen."
    from jarvis import agent

    return agent.run_task(task)


def risky_question(intent: str, args: dict) -> str | None:
    """Words for 'Are you sure you want to ...?', or None if this needs no yes (or there is nothing to act on)."""
    if intent == "delete_file":
        return fileops.delete_question(args)
    if intent == "kill_process":
        return processes.kill_question(args)
    if intent == "computer_use" and str(args.get("task") or "").strip():
        task = str(args["task"]).strip().rstrip(".?!")
        return f"let me take control of the mouse and keyboard to {task}"
    return None


def do_risky(intent: str, args: dict) -> str:
    """Called with args['confirm'] = True after the user said yes."""
    return HANDLERS[intent]({**args, "confirm": True})


# intent -> fn(args) -> reply. Risky ones only act when args has confirm=True.
HANDLERS = {
    "open_settings": winsettings.open_settings,
    "dark_mode": winsettings.dark_mode,
    "power_plan": winsettings.power_plan,
    "screen_off": winsettings.screen_off,
    "processes": processes.processes,
    "kill_process": processes.kill_process,
    "create_item": fileops.create_item,
    "copy_file": fileops.copy_file,
    "move_file": fileops.move_file,
    "rename_file": fileops.rename_file,
    "delete_file": fileops.delete_file,
    "press_keys": inputs.press_keys,
    "mouse": inputs.mouse,
    "click_text": inputs.click_text,
    "computer_use": computer_use,
}

_STR = {"type": "string"}
_FOLDER = "A folder: desktop, documents, downloads, pictures, music, videos, a folder name, or a full path."

# Same shape as actions/catalog.py. "info": True = the reply is data the AI may want to read.
CATALOG: dict[str, dict] = {
    "open_settings": {"description": "Open a Windows Settings page, e.g. display, sound, night light, bluetooth, battery, "
                                     "notifications, focus, apps, startup apps, storage, windows update, privacy, mouse, "
                                     "keyboard, background, themes, date and time, language, printers, accessibility, "
                                     "security, control panel, device manager.",
                      "properties": {"page": _STR}, "required": ["page"]},
    "dark_mode": {"description": "Turn Windows dark mode on, or off (= light mode).",
                  "properties": {"state": {"type": "string", "enum": ["on", "off"]}}, "required": ["state"]},
    "power_plan": {"description": "Switch the Windows power plan.",
                   "properties": {"plan": {"type": "string", "enum": ["balanced", "power_saver", "high_performance"]}},
                   "required": ["plan"]},
    "screen_off": {"description": "Turn the screen off now (moving the mouse turns it on).", "properties": {}, "required": []},
    "processes": {"description": "Say which programs use the most memory or CPU right now.",
                  "properties": {"sort": {"type": "string", "enum": ["memory", "cpu"]}}, "required": [], "info": True},
    "kill_process": {"description": "Force close (end task) a running program or process by name. Jarvis asks the user "
                                    "to confirm. Windows system processes are never closed.",
                     "properties": {"name": {"type": "string", "description": "Program or process name, e.g. chrome, teams."}},
                     "required": ["name"]},
    "create_item": {"description": "Create a new empty file or folder in the user's folders (never overwrites).",
                    "properties": {"kind": {"type": "string", "enum": ["file", "folder"]},
                                   "name": {"type": "string", "description": "New name. Files without a type get .txt."},
                                   "where": {"type": "string", "description": _FOLDER + " Default desktop."}},
                    "required": ["kind", "name"]},
    "copy_file": {"description": "Copy a file or folder (found by name in the user's folders) into another folder.",
                  "properties": {"name": _STR, "to": {"type": "string", "description": _FOLDER}}, "required": ["name", "to"]},
    "move_file": {"description": "Move a file or folder (found by name in the user's folders) into another folder.",
                  "properties": {"name": _STR, "to": {"type": "string", "description": _FOLDER}}, "required": ["name", "to"]},
    "rename_file": {"description": "Rename a file or folder found by name. The file type is kept if the new name has none.",
                    "properties": {"name": _STR, "new_name": _STR}, "required": ["name", "new_name"]},
    "delete_file": {"description": "Delete a file or folder found by name (goes to the Recycle Bin). Jarvis asks the user "
                                   "to confirm.", "properties": {"name": _STR}, "required": ["name"]},
    "press_keys": {"description": "Press a key or keyboard shortcut in the active window, e.g. 'ctrl+c', 'alt+f4', "
                                  "'enter', 'win+d', 'ctrl+shift+t'.",
                   "properties": {"keys": {"type": "string", "description": "Keys joined with +."},
                                  "times": {"type": "integer", "description": "How many times, default 1."}},
                   "required": ["keys"]},
    "mouse": {"description": "Simple mouse control at the current mouse position.",
              "properties": {"action": {"type": "string", "enum": ["click", "double_click", "right_click", "middle_click",
                                                                    "scroll", "move", "center"]},
                             "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                             "amount": {"type": "string", "description": "'a little', 'a lot', or a number "
                                                                         "(scroll clicks or pixels)."}},
              "required": ["action"]},
    "click_text": {"description": "Click a button, link, menu item or tab in the active window by its visible name.",
                   "properties": {"text": _STR, "button": {"type": "string", "enum": ["left", "right", "double"]}},
                   "required": ["text"]},
    "computer_use": {"description": "LAST RESORT for multi-step tasks on the screen that no other tool can do (e.g. change "
                                    "a setting inside an app, fill a form, find something in an app). Claude then looks at "
                                    "the screen and uses mouse and keyboard. Slow. Jarvis asks the user to confirm first.",
                     "properties": {"task": {"type": "string", "description": "The full task in plain words."}},
                     "required": ["task"]},
}
