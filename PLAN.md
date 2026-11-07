# Jarvis plan (shared by all threads)

- OS: Windows 10/11. Language: Python 3.11+.
- No GitHub repo yet. All code lives in `/mnt/project-files/jarvis/` (later push to a repo if the user makes one).
- Each thread owns only its own folder/file below. Keep the interfaces exactly as written so pieces fit.

## Layout
```
jarvis/
  main.py              # 1 core: loop, wake word, wiring
  config.yaml          # 1 core: settings (wake word, voice, app paths)
  requirements.txt     # each thread adds its own lines
  jarvis/
    stt.py             # 2 speech input
    nlu.py             # 3 command understanding
    actions/           # 4 laptop actions (one module per group)
    tts.py             # 5 voice replies
  packaging/           # 6 installer + auto-start
  tests/
```

## Interfaces
- `stt.listen(timeout: float = 5) -> str | None` : record mic, return text (offline, e.g. Vosk or faster-whisper).
- `stt.wait_for_wake_word(word: str = "jarvis") -> None` : blocks until the wake word is heard.
- `nlu.parse(text: str) -> Command` where `Command = dataclass(intent: str, args: dict)`; unknown -> `intent="unknown"`.
- `actions.run(cmd: Command) -> str` : does the action, returns a short reply sentence. Intents: `open_app, close_app, web_search, volume, brightness, screenshot, type_text, time, shutdown, restart, lock`. Dangerous ones (shutdown/restart) must ask "are you sure?" via returned reply + a `confirm` flag.
- `tts.say(text: str) -> None` : speak offline (pyttsx3 / Windows SAPI).

## Flow
wait_for_wake_word -> tts.say("Yes?") -> listen -> parse -> run -> say(reply) -> repeat.

## Core notes (piece 1, done)
- Settings: `from jarvis.config import load_config; cfg = load_config()` returns `config.yaml` as a dict (keys: `apps`, `search_url`, `screenshot_folder`, `voice`, `stt`, ...).
- Confirm rule: for `shutdown`/`restart`, `actions.run(cmd)` with no `cmd.args["confirm"]` must ONLY return the question (e.g. "Are you sure you want to shut down?"). Core then listens; on "yes" it calls `actions.run` again with `cmd.args["confirm"] = True`.
- `tts.configure(rate, volume, voice)` is called once at start if it exists.
- Run: `python main.py` (voice) or `python main.py --text` (type commands). Tests: `python -m pytest tests`.

## Actions notes (piece 4, done)
- Code: `jarvis/actions/` (`__init__.py` run + confirm logic, `apps.py`, `web.py`, `system.py`, `screen.py`, `keyboard.py`). Tests: `tests/test_actions.py`.
- Args: open_app/close_app `{name}`, web_search `{query}`, volume/brightness `{level}` or `{change: up|down|mute|unmute, step?}`, type_text `{text}`, shutdown/restart `{confirm?}`.
- Also handles intents `confirm` / `cancel` for a pending shutdown/restart (expires after 30 s).
- Reads `apps`, `search_url`, `screenshot_folder` from config via `jarvis.config.load_config` on import.

## Packaging notes (piece 6, done)
- `packaging/install.bat`: double-click. Finds Python 3.11+, makes `.venv`, installs requirements, downloads Vosk model, asks about auto-start, offers to start.
- `packaging/autostart.py install|uninstall|status`: HKCU Run key "Jarvis" -> `.venv\Scripts\pythonw.exe packaging\start_jarvis.pyw` (starts at user login, no admin, no window).
- `packaging/start_jarvis.pyw`: hidden launcher, retries 5x (15 s apart) on crash, writes `jarvis-crash.log`.
- `packaging/uninstall.bat`: turns off auto-start and stops a running Jarvis.
- How to install/test: `README.md`. Tests: `tests/test_packaging.py`.

## AI brain + extra features (done 2026-11-07)
- Flow now: parse -> if `unknown` (or a "what/who/how..." question) -> `brain.ask(text)` -> list of Commands -> run each (with confirm) -> say replies.
- `jarvis/brain.py`: `Brain(cfg, actions.CATALOG).ask(text) -> list[Command]`. Claude API (`anthropic` SDK, model from `ai.model`, default `claude-opus-5-5`, effort `low`, server web search, `fallbacks: "default"`). Plain answers are `Command("answer", {"text"})`. Key: `ai.api_key` or env `ANTHROPIC_API_KEY`; no key = rules only.
- `actions/catalog.py`: `CATALOG` intent -> description + JSON schema (the AI's tools). Must match `_HANDLERS` (tested).
- New intents: timer, reminder, timers, weather, news, system_info, media, play, window, open_folder, open_file, add_note, read_notes, email, wifi, bluetooth, sleep, empty_recycle_bin, answer. Args: see `nlu.py` docstring and `catalog.py`.
- Risky (ask yes first): shutdown, restart, sleep, empty_recycle_bin, wifi off. `actions.needs_confirm(cmd)`; core checks it plus `confirm_intents`.
- `actions.set_notifier(fn)`: core passes `io.say` so timers/reminders speak.
- New modules: `actions/timers.py`, `info.py` (wttr.in, Google News RSS, psutil), `desktop.py` (media keys, YouTube, windows), `files.py` (folders, file search, notes, mailto), `radios.py` (WinRT Radio API, falls back to Settings page).
- Tests: `tests/test_brain.py`, `tests/test_features.py`.

## Real-time round (done 2026-11-07)
- Speed: greeting is a beep (`greeting: beep`), follow-up listening (`follow_up_seconds`, VoiceIO only: `io.follow_up = True`, `io.listen(timeout)`), mic chunks 0.125 s, AI replies stream sentence by sentence (`brain.ask(text, on_sentence=io.say)`; answer Command gets `spoken: True`, actions returns "" and core skips empty replies).
- Brain "info" tools (`"info": True` in catalog): result goes back to Claude, which then answers. Includes `look_at_screen` (screenshot image, brain only), `read_clipboard`, `get_selected_text`, weather, news, system_info, time, read_notes, recall, calculate. Brain args: `Brain(cfg, CATALOG, runner=actions.run, look=actions.look_at_screen, memory=actions.memories)`.
- New intents: calculate (`jarvis/calc.py`, offline, safe AST), read_clipboard, copy_text, get_selected_text, whatsapp (deep link; `whatsapp.auto_send` makes it risky + presses Enter), remember / recall / forget_memory (risky), alarms = reminder with text "alarm", websites via open_app (`apps.WEBSITES`, config `websites`).
- Routines: config `routines: {name: [phrases]}`; core matches "good morning" / "start work mode" before nlu; intent `routine {name}` for the AI. Code: `main.run_routine`.
- Timers: one wall-clock thread (fires after sleep), reminders saved to `reminders_file` via `actions.start_reminders(path)` (called by core).
- Contacts can be `name: email` or `name: {email, phone}`.

## Full system control (done 2026-11-07)
- Hub: `jarvis/actions/control.py` (HANDLERS, CATALOG, RISKY, risky_question, do_risky, set_io). Wired into `actions/__init__.py` (_HANDLERS/CATALOG update, _risky_text, _do_risky), `nlu.py` (`nlu_control.parse_early` after _early_rules, `parse_control` before _device_rules), `main.py` (`actions.control.set_io(io.say, io.listen)`).
- Modules: `actions/winsettings.py` (open_settings, dark_mode, power_plan, screen_off), `actions/fileops.py` (create_item, copy_file, move_file, rename_file, delete_file; only inside user home, never overwrite, delete -> Recycle Bin via Send2Trash), `actions/processes.py` (processes [info], kill_process; protected system list), `actions/inputs.py` (press_keys, mouse, click_text via pywinauto UIA, `parse_keys`), `jarvis/agent.py` (computer_use: Claude `computer_toolset_20260801` loop, pyautogui, screenshots scaled to 1366 px, fail-safe corner, asks the user mid-task via say/listen).
- Risky (ask yes): delete_file, kill_process, computer_use. Their handlers never act without `confirm=True`.
- Config: `computer_use:` (enabled, model, effort, max_steps). Tests: `tests/test_control.py`.
