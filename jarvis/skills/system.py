"""Skills that control the computer: apps, websites, volume, screenshots, power."""

from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import subprocess
import urllib.parse
import webbrowser

from . import skill

OS = platform.system()  # "Windows", "Darwin" (macOS) or "Linux"

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "twitter": "https://x.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "whatsapp": "https://web.whatsapp.com", "netflix": "https://www.netflix.com", "amazon": "https://www.amazon.com",
    "reddit": "https://www.reddit.com", "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
    "chatgpt": "https://chatgpt.com", "maps": "https://maps.google.com", "spotify": "https://open.spotify.com",
    "wikipedia": "https://www.wikipedia.org", "calendar": "https://calendar.google.com",
}

APPS = {
    "Windows": {"notepad": "notepad", "calculator": "calc", "paint": "mspaint", "file explorer": "explorer",
                "explorer": "explorer", "command prompt": "cmd", "terminal": "wt", "task manager": "taskmgr",
                "settings": "start ms-settings:", "chrome": "start chrome", "edge": "start msedge",
                "word": "start winword", "excel": "start excel", "vs code": "code", "vscode": "code"},
    "Darwin": {"calculator": "Calculator", "notes": "Notes", "terminal": "Terminal", "finder": "Finder",
               "safari": "Safari", "chrome": "Google Chrome", "music": "Music", "settings": "System Settings",
               "vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "calendar": "Calendar", "mail": "Mail"},
    "Linux": {"calculator": "gnome-calculator", "terminal": "x-terminal-emulator", "files": "nautilus",
              "file manager": "nautilus", "text editor": "gedit", "chrome": "google-chrome", "firefox": "firefox",
              "vs code": "code", "vscode": "code", "settings": "gnome-control-center"},
}


def _launch(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@skill("open_website", "Open a website in the web browser by name or URL.",
       patterns=[r"open (the )?(website )?(?P<site>[\w.-]+\.(com|org|net|io|in|dev|ai|co)(/\S*)?)",
                 r"open (?P<site>youtube|google|gmail|github|facebook|instagram|twitter|linkedin|whatsapp|netflix|amazon|reddit|stack ?overflow|chatgpt|maps|spotify|wikipedia|calendar)"],
       params={"site": "Website name (e.g. 'youtube') or URL"}, required=["site"])
def open_website(ctx, site: str):
    key = site.lower().strip()
    url = SITES.get(key) or SITES.get(key.replace(" ", ""))
    if not url:
        url = key if key.startswith("http") else "https://" + key
    webbrowser.open(url)
    return f"Opening {site}."


@skill("open_app", "Open an application on the computer, e.g. 'notepad' or 'calculator'.",
       patterns=[r"(open|launch|start|run) (the )?(app |application )?(?P<app>.+?)( app)?"],
       params={"app": "Application name"}, required=["app"])
def open_app(ctx, app: str):
    name = app.lower().strip()
    if name in SITES:
        return open_website(ctx, name)
    known = APPS.get(OS, {}).get(name)
    if OS == "Windows":
        _launch(known or f"start {name}")
    elif OS == "Darwin":
        _launch(f'open -a "{known or app}"')
    else:
        exe = known or name.replace(" ", "-")
        if not shutil.which(exe.split()[0]):
            return f"I couldn't find an app called {app}."
        _launch(exe)
    return f"Opening {app}."


@skill("search_browser", "Open a Google search for something in the browser.",
       patterns=[r"(google|search google for|search in browser for) (?P<query>.+) in (the )?browser"],
       params={"query": "Search words"}, required=["query"])
def search_browser(ctx, query: str):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searching Google for {query}."


@skill("play_youtube", "Play a song or video on YouTube.",
       patterns=[r"play (?P<query>.+?)( on youtube)?"],
       params={"query": "Song or video name"}, required=["query"])
def play_youtube(ctx, query: str):
    import re
    from .. import net

    page = net.get("https://www.youtube.com/results", {"search_query": query}).decode("utf-8", "ignore")
    ids = re.findall(r'"videoId":"([\w-]{11})"', page)
    url = f"https://www.youtube.com/watch?v={ids[0]}" if ids else \
        "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    webbrowser.open(url)
    return f"Playing {query} on YouTube."


@skill("system_info", "Report CPU, memory, disk and battery status.",
       patterns=[r"(system|computer|pc) (info|status|stats|report)", r"(check |what('s| is) (the |my )?)?(battery|cpu|ram|memory) (status|level|usage)?"])
def system_info(ctx):
    parts = [f"You are on {platform.system()} {platform.release()}."]
    try:
        import psutil
    except ImportError:
        total, used, _ = shutil.disk_usage(os.path.expanduser("~"))
        parts.append(f"Disk is {used * 100 // total} percent full. Install psutil for CPU and memory details.")
        return " ".join(parts)
    parts.append(f"CPU usage is {psutil.cpu_percent(interval=0.5)} percent.")
    vm = psutil.virtual_memory()
    parts.append(f"Memory usage is {vm.percent} percent of {round(vm.total / 2**30)} gigabytes.")
    parts.append(f"Disk is {psutil.disk_usage(os.path.expanduser('~')).percent} percent full.")
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat:
        parts.append(f"Battery is at {round(bat.percent)} percent{', charging' if bat.power_plugged else ''}.")
    return " ".join(parts)


@skill("screenshot", "Take a screenshot and save it to the Pictures folder.",
       patterns=[r"(take|capture) (a )?screen ?shot", r"screen ?shot"])
def screenshot(ctx):
    folder = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, dt.datetime.now().strftime("jarvis_%Y%m%d_%H%M%S.png"))
    try:
        import mss
        with mss.mss() as s:
            s.shot(output=path)
    except ImportError:
        if OS == "Darwin":
            subprocess.run(["screencapture", "-x", path], check=True)
        elif shutil.which("gnome-screenshot"):
            subprocess.run(["gnome-screenshot", "-f", path], check=True)
        else:
            return "Install the 'mss' package to take screenshots."
    return f"Screenshot saved to {path}."


def _win_key(vk: int, times: int = 1) -> None:
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


@skill("volume", "Change the speaker volume: 'up', 'down', 'mute', or a number 0-100.",
       patterns=[r"(turn |set )?(the )?volume (?P<level>up|down|\d{1,3})( percent)?",
                 r"(?P<level>mute|unmute)( the)?( volume| sound| audio)?",
                 r"turn (?P<level>up|down) the volume", r"(be )?(?P<level>louder|quieter)"],
       params={"level": "'up', 'down', 'mute', 'unmute' or a number 0-100"}, required=["level"])
def volume(ctx, level: str):
    level = {"louder": "up", "quieter": "down"}.get(level.lower(), level.lower())
    if OS == "Windows":
        vk = {"up": 0xAF, "down": 0xAE, "mute": 0xAD, "unmute": 0xAD}
        if level in vk:
            _win_key(vk[level], 5 if level in ("up", "down") else 1)
        else:
            _win_key(0xAE, 50)
            _win_key(0xAF, int(level) // 2)
    elif OS == "Darwin":
        script = {"up": "set volume output volume ((output volume of (get volume settings)) + 10)",
                  "down": "set volume output volume ((output volume of (get volume settings)) - 10)",
                  "mute": "set volume with output muted", "unmute": "set volume without output muted"}
        subprocess.run(["osascript", "-e", script.get(level, f"set volume output volume {level}")])
    else:
        arg = {"up": "5%+", "down": "5%-", "mute": "mute", "unmute": "unmute"}.get(level, f"{level}%")
        if shutil.which("amixer"):
            subprocess.run(["amixer", "-q", "set", "Master", arg])
        elif shutil.which("pactl"):
            pa = {"up": "+5%", "down": "-5%"}.get(level)
            if level in ("mute", "unmute"):
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if level == "mute" else "0"])
            else:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pa or f"{level}%"])
        else:
            return "I can't find a volume control tool (amixer or pactl)."
    return "Volume " + (f"set to {level} percent." if level.isdigit() else f"{level}.")


POWER = {
    "shutdown": {"Windows": "shutdown /s /t 5", "Darwin": "osascript -e 'tell app \"System Events\" to shut down'", "Linux": "systemctl poweroff"},
    "restart": {"Windows": "shutdown /r /t 5", "Darwin": "osascript -e 'tell app \"System Events\" to restart'", "Linux": "systemctl reboot"},
    "sleep": {"Windows": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0", "Darwin": "pmset sleepnow", "Linux": "systemctl suspend"},
    "lock": {"Windows": "rundll32.exe user32.dll,LockWorkStation", "Darwin": "pmset displaysleepnow", "Linux": "loginctl lock-session"},
}


@skill("power", "Lock, sleep, restart or shut down the computer. Shutdown and restart need confirmation.",
       patterns=[r"(?P<action>lock)( the| my)?( computer| pc| system| screen)?( now)?",
                 r"(put )?(the |my )?(computer|pc|system) to (?P<action>sleep)( now)?",
                 r"(?P<action>sleep|restart|shutdown|shut down|reboot) (the |my )?(computer|pc|system)( now)?",
                 r"(?P<action>shutdown|shut down|restart|reboot)( now)?",
                 r"(?P<confirm>confirm) (?P<action>shutdown|shut down|restart|reboot)"],
       params={"action": "lock, sleep, restart or shutdown", "confirm": "Say 'confirm' to really shut down or restart"},
       required=["action"])
def power(ctx, action: str, confirm: str = ""):
    action = {"shut down": "shutdown", "reboot": "restart"}.get(action.lower(), action.lower())
    if action in ("shutdown", "restart") and confirm.lower() != "confirm":
        return f"Are you sure? Say 'confirm {action}' to {action} the computer."
    _launch(POWER[action][OS])
    return f"Okay, {action}."
