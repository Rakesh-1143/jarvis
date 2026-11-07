"""Full system control: settings, files, processes, mouse/keys, screen-control agent. OS calls are faked."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis import agent  # noqa: E402
from jarvis.actions import control, fileops, inputs, processes, winsettings  # noqa: E402
from jarvis.nlu_control import parse_control, parse_early  # noqa: E402

NLU = [
    ("turn on dark mode", "dark_mode", {"state": "on"}),
    ("turn off dark mode", "dark_mode", {"state": "off"}),
    ("switch to light mode", "dark_mode", {"state": "off"}),
    ("turn on battery saver", "power_plan", {"plan": "power_saver"}),
    ("turn off battery saver", "power_plan", {"plan": "balanced"}),
    ("high performance mode", "power_plan", {"plan": "high_performance"}),
    ("turn off the screen", "screen_off", {}),
    ("open display settings", "open_settings", {"page": "display"}),
    ("open sound settings", "open_settings", {"page": "sound"}),
    ("turn on night light", "open_settings", {"page": "night light"}),
    ("open do not disturb settings", "open_settings", {"page": "notifications"}),
    ("open focus settings", "open_settings", {"page": "notifications"}),
    ("open device manager", "open_settings", {"page": "device manager"}),
    ("what's using my memory", "processes", {"sort": "memory"}),
    ("what is using the cpu", "processes", {"sort": "cpu"}),
    ("what apps are running", "processes", {"sort": "memory"}),
    ("end task chrome", "kill_process", {"name": "chrome"}),
    ("kill process teams", "kill_process", {"name": "teams"}),
    ("create a folder called projects on the desktop", "create_item", {"kind": "folder", "name": "projects", "where": "desktop"}),
    ("make a new file notes", "create_item", {"kind": "file", "name": "notes"}),
    ("copy the file budget to documents", "copy_file", {"name": "budget", "to": "documents"}),
    ("move file report into the downloads folder", "move_file", {"name": "report", "to": "downloads"}),
    ("rename the file report to final report", "rename_file", {"name": "report", "new_name": "final report"}),
    ("delete the file old notes", "delete_file", {"name": "old notes"}),
    ("press control c", "press_keys", {"keys": "control c"}),
    ("press enter", "press_keys", {"keys": "enter"}),
    ("press tab three times", "press_keys", {"keys": "tab", "times": 3}),
    ("press alt f4", "press_keys", {"keys": "alt f4"}),
    ("copy that", "press_keys", {"keys": "ctrl+c"}),
    ("paste", "press_keys", {"keys": "ctrl+v"}),
    ("undo", "press_keys", {"keys": "ctrl+z"}),
    ("select all", "press_keys", {"keys": "ctrl+a"}),
    ("save", "press_keys", {"keys": "ctrl+s"}),
    ("new tab", "press_keys", {"keys": "ctrl+t"}),
    ("close this tab", "press_keys", {"keys": "ctrl+w"}),
    ("refresh the page", "press_keys", {"keys": "f5"}),
    ("zoom in", "press_keys", {"keys": "ctrl+="}),
    ("go back", "press_keys", {"keys": "alt+left"}),
    ("scroll to the bottom", "press_keys", {"keys": "ctrl+end"}),
    ("click", "mouse", {"action": "click"}),
    ("right click", "mouse", {"action": "right_click"}),
    ("double click", "mouse", {"action": "double_click"}),
    ("click on the save button", "click_text", {"text": "save"}),
    ("double click on budget", "click_text", {"text": "budget", "button": "double"}),
    ("scroll down", "mouse", {"action": "scroll", "direction": "down"}),
    ("scroll up a lot", "mouse", {"action": "scroll", "direction": "up", "amount": "a lot"}),
    ("move the mouse left", "mouse", {"action": "move", "direction": "left"}),
    ("move the mouse to the center", "mouse", {"action": "center"}),
    ("take control and change my wallpaper to the beach photo", "computer_use",
     {"task": "change my wallpaper to the beach photo"}),
    ("take control of my computer and restart spotify", "computer_use", {"task": "restart spotify"}),
]


@pytest.mark.parametrize("text,intent,args", NLU)
def test_nlu_control(text, intent, args):
    assert parse_control(text) == (intent, args)


@pytest.mark.parametrize("text", ["open wifi settings", "open bluetooth settings", "open chrome", "what time is it",
                                  "play some music", "show desktop", "lock the screen", "find cats"])
def test_nlu_control_leaves_other_commands(text):
    assert parse_control(text) is None


def test_parse_early_only_takes_screen_control():
    assert parse_early("take control and restart chrome") == ("computer_use", {"task": "restart chrome"})
    assert parse_early("restart") is None


@pytest.mark.parametrize("text,keys", [
    ("control c", ["ctrl", "c"]), ("ctrl+shift+t", ["ctrl", "shift", "t"]), ("Return", ["enter"]),
    ("alt+Tab", ["alt", "tab"]), ("f five", ["f5"]), ("alt f4", ["alt", "f4"]), ("windows d", ["win", "d"]),
    ("page down", ["pagedown"]), ("Page_Down", ["pagedown"]), ("control see", ["ctrl", "c"]), ("super", ["win"]),
    ("control plus z", ["ctrl", "z"]), ("ctrl+=", ["ctrl", "="]), ("ctrl+-", ["ctrl", "-"]),
])
def test_parse_keys(text, keys):
    assert inputs.parse_keys(text) == keys


def test_parse_keys_unknown():
    assert inputs.parse_keys("banana") is None


def test_catalog_matches_handlers():
    assert set(control.CATALOG) == set(control.HANDLERS)
    for spec in control.CATALOG.values():
        assert set(spec["required"]) <= set(spec["properties"])


# ---------- fake pyautogui ----------
class FakePG:
    FAILSAFE = True

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a, k))

    def size(self):
        return (1920, 1080)

    def position(self):
        return (960, 540)

    def screenshot(self):
        from PIL import Image

        return Image.new("RGB", (1920, 1080), "white")


@pytest.fixture
def pg(monkeypatch):
    fake = FakePG()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


def test_press_keys_and_mouse(pg):
    assert inputs.press_keys({"keys": "control c"}) == "Done."
    assert inputs.press_keys({"keys": "enter", "times": 2}) == "Done."
    assert inputs.mouse({"action": "scroll", "direction": "down", "amount": "a lot"}) == "Scrolled down."
    assert inputs.mouse({"action": "right_click"}) == "Right clicked."
    names = [(c[0], c[1]) for c in pg.calls]
    assert ("hotkey", ("ctrl", "c")) in names
    assert names.count(("press", ("enter",))) == 2
    assert ("scroll", (-15 * inputs.NOTCH,)) in names
    assert inputs.press_keys({"keys": "banana"}) == "I don't know the key banana."


def test_find_element_prefers_exact_clickable():
    a, b, c = object(), object(), object()
    els = [("Save as", "MenuItem", a), ("Save", "Text", b), ("Save", "Button", c), ("Open", "Button", object())]
    assert inputs.find_element("save", els) is c
    assert inputs.find_element("nothing", els) is None


def test_click_text(monkeypatch):
    clicked = []
    el = NS(click_input=lambda **k: clicked.append(k))
    monkeypatch.setattr(inputs, "_foreground_elements", lambda: [("OK", "Button", el)])
    assert inputs.click_text({"text": "ok"}) == "Clicked ok."
    assert clicked == [{"button": "left"}]
    assert inputs.click_text({"text": "cancel"}) == "I couldn't find cancel on the screen."


# ---------- settings ----------
def test_find_page():
    assert winsettings.find_page("display")[1] == "ms-settings:display"
    assert winsettings.find_page("the bluetooth settings")[1] == "ms-settings:bluetooth"
    assert winsettings.find_page("change my wallpaper")[1] == "ms-settings:personalization-background"
    assert winsettings.find_page("zzz") == ("", "ms-settings:")


def test_open_settings_and_power_plan(monkeypatch):
    opened = []
    monkeypatch.setattr(winsettings, "_start", opened.append)
    assert winsettings.open_settings({"page": "sound"}) == "Opening sound settings."
    runs = []
    monkeypatch.setattr(winsettings.subprocess, "run", lambda cmd, **k: runs.append(cmd) or NS(returncode=0))
    assert winsettings.power_plan({"plan": "power_saver"}) == "Power plan set to power saver."
    assert runs[-1] == ["powercfg", "/setactive", "SCHEME_MAX"]
    monkeypatch.setattr(winsettings.subprocess, "run", lambda cmd, **k: NS(returncode=1))
    assert "opened the power settings" in winsettings.power_plan({"plan": "high_performance"})
    assert opened == ["ms-settings:sound", "ms-settings:powersleep"]


def test_dark_mode_falls_back_to_settings(monkeypatch):
    opened = []
    monkeypatch.setattr(winsettings, "_start", opened.append)
    monkeypatch.setattr(winsettings, "_set_dark", lambda on: (_ for _ in ()).throw(OSError("no registry")))
    assert "opened the colors settings" in winsettings.dark_mode({"state": "on"})
    monkeypatch.setattr(winsettings, "_set_dark", lambda on: None)
    assert winsettings.dark_mode({"state": "off"}) == "Light mode is on."


# ---------- files ----------
@pytest.fixture
def home(tmp_path, monkeypatch):
    for d in ("Desktop", "Documents", "Downloads"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(fileops, "home", lambda: tmp_path)
    fileops._cache.clear()
    return tmp_path


def test_create_copy_move_rename(home):
    assert fileops.create_item({"kind": "folder", "name": "projects"}) == "Created the folder projects in Desktop."
    assert (home / "Desktop" / "projects").is_dir()
    assert fileops.create_item({"kind": "file", "name": "todo", "where": "documents"}) == "Created the file todo.txt in Documents."
    assert fileops.create_item({"kind": "file", "name": "todo", "where": "documents"}) == "todo.txt already exists in Documents."
    assert fileops.copy_file({"name": "todo", "to": "downloads"}) == "Copied todo.txt to Downloads."
    assert (home / "Downloads" / "todo.txt").exists() and (home / "Documents" / "todo.txt").exists()
    assert fileops.move_file({"name": "projects", "to": "documents"}) == "Moved projects to Documents."
    assert (home / "Documents" / "projects").is_dir()
    (home / "Desktop" / "report.docx").write_text("x")
    assert fileops.rename_file({"name": "report", "new_name": "final"}) == "Renamed report.docx to final.docx."
    assert (home / "Desktop" / "final.docx").exists()


def test_file_safety(home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "sys.dll").write_text("x")
    assert fileops.move_file({"name": str(outside / "sys.dll"), "to": "desktop"}) == "I can only work inside your user folders."
    assert fileops.move_file({"name": "documents", "to": "desktop"}) == "I won't move your Documents folder."
    assert fileops.delete_question({"name": "documents"}) is None
    assert fileops.create_item({"kind": "file", "name": "a/b"}) == "What should I call it?"


def test_delete_needs_confirm_and_uses_recycle_bin(home, monkeypatch):
    (home / "Downloads" / "old notes.txt").write_text("x")
    trashed = []
    monkeypatch.setattr(fileops, "_trash", trashed.append)
    q = control.risky_question("delete_file", {"name": "old notes"})
    assert q == "move old notes.txt from Downloads to the recycle bin"
    assert control.HANDLERS["delete_file"]({"name": "old notes"}) == "Say yes to move old notes.txt to the recycle bin."
    assert trashed == []
    assert control.do_risky("delete_file", {"name": "old notes"}) == "Moved old notes.txt to the recycle bin."
    assert trashed == [home / "Downloads" / "old notes.txt"]
    assert control.risky_question("delete_file", {"name": "missing thing"}) is None
    assert control.HANDLERS["delete_file"]({"name": "missing thing"}) == "I couldn't find missing thing."


# ---------- processes ----------
class FakeProc:
    def __init__(self, pid, name, mem):
        self.info = {"pid": pid, "name": name, "memory_info": NS(rss=mem)}
        self.pid = pid

    def cpu_percent(self, _):
        return 10.0


def fake_psutil(procs, killed):
    return NS(process_iter=lambda attrs=None: procs, cpu_count=lambda: 2,
              Process=lambda pid: NS(kill=lambda: killed.append(pid)))


def test_processes_and_kill(monkeypatch):
    killed = []
    procs = [FakeProc(1, "chrome.exe", 500e6), FakeProc(2, "chrome.exe", 900e6), FakeProc(3, "Code.exe", 300e6),
             FakeProc(4, "svchost.exe", 2e9), FakeProc(5, "explorer.exe", 1e8)]
    with mock.patch.dict(sys.modules, {"psutil": fake_psutil(procs, killed)}):
        out = processes.processes({"sort": "memory"})
        assert out.startswith("Using the most memory: Svchost 2.0 gigabytes, Chrome 1.4 gigabytes")
        assert processes.kill_question({"name": "chrome"}) == "force close Chrome (unsaved work will be lost)"
        assert processes.kill_question({"name": "svchost"}) is None
        assert processes.kill_process({"name": "svchost"}) == "I won't close svchost. Windows needs it."
        assert processes.kill_process({"name": "chrome"}) == "Say yes to force close Chrome."
        assert killed == []
        assert control.do_risky("kill_process", {"name": "chrome"}) == "Closed Chrome."
        assert killed == [1, 2]


# ---------- screen-control agent ----------
def block(type_, **kw):
    return NS(type=type_, **kw)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


def test_agent_runs_actions_and_scales(pg):
    client = FakeClient(
        NS(stop_reason="tool_use", content=[
            block("tool_use", id="t1", name="left_click", input={"coordinate": [683, 384]}, toolset_name="computer"),
            block("tool_use", id="t2", name="type", input={"text": "hello"}, toolset_name="computer"),
            block("tool_use", id="t3", name="key", input={"text": "Return"}, toolset_name="computer"),
            block("tool_use", id="t4", name="screenshot", input={}, toolset_name="computer"),
        ]),
        NS(stop_reason="end_turn", content=[block("text", text="Done, I searched for hello.")]),
    )
    a = agent.Agent({"ai": {"model": "claude-opus-5-5"}}, client=client, pg=pg)
    assert a.run("search for hello") == "Done, I searched for hello."
    req = client.requests[0]
    assert req["tools"] == [{"type": "computer_toolset_20260801"}]
    assert req["model"] == "claude-opus-5-5"
    # 1920 wide screen shrunk to 1366: (683, 384) -> (960, 540)
    assert ("click", (960, 540), {"clicks": 1, "interval": 0.08, "button": "left"}) in pg.calls
    assert ("typewrite", ("hello",), {"interval": 0.02}) in pg.calls
    assert ("hotkey", ("enter",), {}) in pg.calls
    results = client.requests[1]["messages"][2]["content"]  # [task, assistant, results, ...]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2", "t3", "t4"]
    assert all(r["toolset_name"] == "computer" for r in results)
    assert results[3]["content"][0]["type"] == "image"


def test_agent_stops_batch_after_failure(pg):
    client = FakeClient(
        NS(stop_reason="tool_use", content=[
            block("tool_use", id="t1", name="key", input={"text": "nonsensekey"}, toolset_name="computer"),
            block("tool_use", id="t2", name="left_click", input={"coordinate": [1, 1]}, toolset_name="computer"),
        ]),
        NS(stop_reason="end_turn", content=[block("text", text="I couldn't do it.")]),
    )
    agent.Agent({}, client=client, pg=pg).run("x")
    r1, r2 = client.requests[1]["messages"][2]["content"]
    assert r1["is_error"] and r2["is_error"]
    assert r2["content"] == "Not executed: an earlier computer action in this turn failed."
    assert not any(c[0] == "click" for c in pg.calls)


def test_agent_asks_user_before_risky_step(pg, monkeypatch):
    spoken, answers = [], ["yes send it"]
    monkeypatch.setattr(agent, "say", spoken.append)
    monkeypatch.setattr(agent, "listen", lambda: answers.pop(0) if answers else None)
    client = FakeClient(
        NS(stop_reason="end_turn", content=[block("text", text="Should I send the email to Sam?")]),
        NS(stop_reason="end_turn", content=[block("text", text="Sent.")]),
    )
    assert agent.Agent({}, client=client, pg=pg).run("email sam") == "Sent."
    assert spoken == ["Should I send the email to Sam?"]
    assert client.requests[1]["messages"][2] == {"role": "user", "content": "yes send it"}


def test_agent_no_key_and_failsafe(pg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "API key" in agent.Agent({"ai": {"api_key": ""}}).run("x")

    class FailSafeException(Exception):
        pass

    class Boom(FakeClient):
        def create(self, **kw):
            raise FailSafeException()

    assert agent.Agent({}, client=Boom(), pg=pg).run("x") == "Stopped. You moved the mouse to a corner."


def test_computer_use_is_risky_and_confirms(monkeypatch):
    ran = []
    monkeypatch.setattr(agent, "run_task", lambda task, cfg=None: ran.append(task) or "Done.")
    q = control.risky_question("computer_use", {"task": "open spotify."})
    assert q == "let me take control of the mouse and keyboard to open spotify"
    assert control.HANDLERS["computer_use"]({"task": "open spotify"}).startswith("Say yes")
    assert ran == []
    assert control.do_risky("computer_use", {"task": "open spotify"}) == "Done."
    assert ran == ["open spotify"]
