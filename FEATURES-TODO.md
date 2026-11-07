# Jarvis: missing features (ranked)

Made 2026-11-07. Ranked by daily value and how practical it is on Windows.
Left out on purpose (owned by the "Give Jarvis full system control" thread):
Windows settings, file create/move/delete, processes, mouse and keyboard control, AI screen agent.
Also left out: things the AI brain already does well (jokes, translation, sports scores, facts, stock prices).

## What people use voice assistants for (research)

- NN/g study of 211 daily users: info lookup 40%, weather 29%, calls/texts/email 29%,
  music 22%, directions 19%, timers/alarms 16%, reminders 11%, smart home 9%, news 7%,
  calendar 5%, lists 5%. 86% of uses are single-step commands.
- Windows 11 Voice Access: "what can I say", "voice access sleep / wake up", dictation with
  "new paragraph", "delete that", "caps ...", "switch to app".
- Google Assistant / Alexa: shopping lists, "good morning" briefing, calendar, conversions,
  time in other cities, "what song is this", find my phone, broadcasts, routines.
- Home Assistant community poll: timers, lists, calendar events, local-only processing,
  "pause" that knows what is playing, multiple wake words.
- Desktop tools (Braina, open-source Jarvis repos, VoiceAttack-style tools): dictation,
  custom voice commands mapped to hotkeys or programs, text snippets.

Jarvis already has: apps, web search, websites, volume, brightness, screenshot, typing, time,
power, timers, reminders, alarms, weather, news, system info, media keys, YouTube play,
window control, folders, file search, notes, email draft, WhatsApp, Wi-Fi, Bluetooth,
calculator, clipboard, selected text, screen look, memory, routines, AI brain.

## Ranked list

| # | Feature | Why | Effort |
|---|---------|-----|--------|
| 1 | To-do and shopping lists | Top daily use; notes are not lists | Easy |
| 2 | Assistant control: "what can I say", "stop listening for 10 minutes", "repeat that", "speak slower" | Voice Access has it; needed every day | Easy |
| 3 | Custom voice shortcuts and text snippets from config | Most-requested desktop feature (VoiceAttack style) | Easy |
| 4 | Calendar: today's agenda, next meeting, meeting alerts, morning briefing | Daily planning | Medium |
| 5 | Dictation mode + read aloud | Hands-free writing; Voice Access core feature | Medium |
| 6 | Conversions, world time, date maths | Common quick questions, works offline | Easy |
| 7 | Audio: what's playing, mic mute, per-app volume, switch speakers/headphones | Daily on laptops with calls | Medium |
| 8 | Focus / Pomodoro + Do Not Disturb | Productivity | Easy |
| 9 | Health alerts: low battery, full charge, CPU hot, disk low | Proactive help | Easy |
| 10 | Network: am I online, IP, Wi-Fi name, speed test | Quick fixes | Easy |
| 11 | Check email: unread count, read subjects | Communication (29%) but needs setup | Medium |

## Build pieces

Rules for every piece:
- New module in `jarvis/actions/<name>.py` and new test file `tests/test_<name>.py`. Do not edit shared files.
- Handlers have the same shape as the others: `def handler(args: dict) -> str` (returns the reply).
- Read settings with `jarvis.config.load_config()`. Use fakes in tests (tests run on Linux).
- Put a `CATALOG` dict in the module (same format as `actions/catalog.py`) and a `HANDLERS` dict
  (intent -> function), so the wiring thread can merge them in one line.
- Add packages to `requirements.txt` only if really needed (mark Windows-only with `; sys_platform == "win32"`).
- At the end, write in your reply the exact NLU phrases you want, so the wiring thread can add them.

### Piece A: `lists.py` (rank 1)
- Saved in a JSON file (config `lists_file`, default `lists.json`). Any list name; default "to-do" and "shopping".
- Says: "add milk to my shopping list", "remove milk from shopping list", "what's on my to-do list",
  "clear my shopping list" (risky: ask yes), "what lists do I have".
- Intents to wire: `list_add {list, item}`, `list_remove {list, item}`, `list_read {list}` (info),
  `list_clear {list}` (risky), `lists {}` (info).

### Piece B: `assistant.py` (rank 2)
- "what can I say" / "help": short spoken list built from the catalog; "help with timers" gives examples.
- "stop listening for 10 minutes" / "go quiet": returns a reply and sets a flag `paused_until`; core must skip wake word until then. "start listening" ends it.
- "repeat that": says the last reply (core stores last reply; module keeps `set_last_reply(text)`).
- "speak slower / faster / louder / quieter": changes `tts.configure` values for this session.
- Intents to wire: `help {topic?}` (info), `pause_listening {minutes?}`, `resume_listening`,
  `repeat`, `voice {change: slower|faster|louder|quieter}`.
- main.py wiring: check `assistant.is_paused()` in the loop; call `assistant.set_last_reply(reply)` after each reply.

### Piece C: `shortcuts.py` (rank 3)
- Config `shortcuts:` phrase -> one of `{open: path_or_url}`, `{keys: "ctrl+shift+m"}`, `{run: "command"}`.
  `run` always asks "are you sure?" the first time (risky) and only runs commands written in config.
- Config `snippets:` name -> text. "type my address" types the saved text (use `pyautogui.write` or clipboard paste).
- Intents to wire: `shortcut {name}` (risky only when it is a `run`), `snippet {name}`.
- main.py wiring: match shortcut phrases before nlu, like routines. config.yaml: add empty `shortcuts:` and `snippets:` with examples in comments.

### Piece D: `agenda.py` (rank 4)
- Reads calendars from ICS links in config `calendars:` (Google Calendar "secret address in iCal format", Outlook "publish calendar" link). Optional Outlook desktop via `win32com` if installed.
- "what's on my calendar today / tomorrow", "when is my next meeting", "am I free at 3 pm".
- Meeting alert: speaks "Meeting X starts in 5 minutes" (uses `actions.set_notifier` style callback; module gives `start_alerts(notify)`).
- "good morning briefing": time, weather (`info.weather`), today's events, reminders count.
- Packages: `icalendar`, `recurring-ical-events`.
- Intents to wire: `agenda {day: today|tomorrow|date}` (info), `next_event {}` (info), `free_at {time}` (info), `briefing {}` (info).
- main.py wiring: call `agenda.start_alerts(io.say)` at start.

### Piece E: `dictation.py` (rank 5)
- "start dictation": every phrase after is typed into the active window until "stop dictation".
- Spoken commands inside dictation: "comma", "full stop / period", "question mark", "new line", "new paragraph",
  "delete that" (removes last phrase), "caps <word>", "undo". Auto capital letter after a full stop.
- "read this aloud": reads selected text (or clipboard if nothing selected) with tts; "stop reading".
- Module gives `process(text) -> str` (what to type) and `is_active()`.
- Intents to wire: `dictation {state: on|off}`, `read_aloud {source?: selection|clipboard}`.
- main.py wiring: when `dictation.is_active()`, skip nlu and send each phrase to `dictation.process`; follow-up listening must stay on.

### Piece F: `convert.py` (rank 6)
- Units offline (length, weight, temperature, volume, speed, data size, time): "5 miles in km", "100 F in C".
- Currency: frankfurter.app (free, no key), cached 12 h; offline says "no internet".
- World time: "time in Tokyo" using `zoneinfo` (+ `tzdata` package on Windows), city -> zone table.
- Date maths: "how many days until 25 December", "what day is 15 August", "date in 45 days".
- Intents to wire: `convert {amount, from, to}` (info), `world_time {city}` (info), `date_calc {question}` or `{target_date}` (info).

### Piece G: `audio.py` (rank 7)
- "what's playing": title/artist from Windows media session (WinRT `GlobalSystemMediaTransportControlsSessionManager`, package `winrt-Windows.Media.Control`).
- "mute my mic" / "unmute mic": default input device mute via `pycaw`.
- "set spotify volume to 30": per-app volume via `pycaw` audio sessions.
- "switch to headphones" / "list audio devices": set default output (IPolicyConfig via `comtypes`; fall back to opening Sound settings).
- Intents to wire: `now_playing {}` (info), `mic {state: on|off}`, `app_volume {app, level}`, `audio_output {name?}`.

### Piece H: `focus.py` (rank 8)
- Pomodoro: "start focus for 25 minutes" -> work/break cycles, spoken at each change; "stop focus", "how long left".
- Do Not Disturb on/off (Windows 11 registry/WNF best effort; fall back to opening notification settings).
- Optional: start focus runs routine `focus` from config if it exists (only return the name; main runs it).
- Intents to wire: `focus {action: start|stop|status, minutes?}`, `dnd {state: on|off}`.

### Piece I: `monitor.py` (rank 9)
- Background thread (every 60 s, psutil): battery under 20% and not charging, battery 100% while charging,
  CPU over 90% for 2 minutes, disk under 5 GB. Speaks once per event (no spam). Thresholds in config `alerts:`.
- "turn off battery alerts" / "turn on alerts".
- Intents to wire: `alerts {state: on|off}`.
- main.py wiring: call `monitor.start(io.say)` at start.

### Piece J: `network.py` (rank 10)
- "am I online" (quick HTTP check), "what's my IP" (local + public via api.ipify.org),
  "what Wi-Fi am I on" (`netsh wlan show interfaces`), "internet speed" (download a test file, report Mbps; no extra package),
  "ping google".
- Intents to wire: `network {what: online|ip|wifi|speed|ping}` (info).

### Piece K: `inbox.py` (rank 11)
- Check email with IMAP (Gmail/Outlook app password in config `email_account:` or env `JARVIS_IMAP_PASSWORD`),
  or Outlook desktop via `win32com` if present. Read only, never sends or deletes.
- "do I have new emails", "read my latest emails" (sender + subject), "any email from mom".
- Intents to wire: `check_email {from?, count?}` (info).

## Wiring summary (for the one wiring thread)

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| A lists | list_add, list_remove, list_read, list_clear, lists | list_clear | - |
| B assistant | help, pause_listening, resume_listening, repeat, voice | - | pause check, set_last_reply |
| C shortcuts | shortcut, snippet | shortcut (run) | match phrases before nlu |
| D agenda | agenda, next_event, free_at, briefing | - | start_alerts(io.say) |
| E dictation | dictation, read_aloud | - | dictation mode in loop |
| F convert | convert, world_time, date_calc | - | - |
| G audio | now_playing, mic, app_volume, audio_output | - | - |
| H focus | focus, dnd | - | - |
| I monitor | alerts | - | monitor.start(io.say) |
| J network | network | - | - |
| K inbox | check_email | - | - |

Sources: nngroup.com/articles/intelligent-assistants-poor-usability-high-adoption,
tomsguide.com (Windows 11 Voice Access guide), community.home-assistant.io (voice assistant poll),
bgr.com/2107621/essential-voice-assistant-commands, fossbytes.com/useful-google-assistant-voice-commands,
windowsreport.com/talking-pc-software, github.com/kishanrajput23/Jarvis-Desktop-Voice-Assistant.

---

## Round 2 (2026-11-07)

Same rules as above (new module + new test, `CATALOG` + `HANDLERS` dicts, no shared-file edits).
Research: OpenVoiceOS / Mycroft skill lists (wikipedia, dictionary, alarms, jokes, common queries),
PC voice-command tool guides (repeating reminders, browser control, voice memos), Windows Game Bar.
Sources: ovos-user-manual.openvoiceos.org/080-ht_skills, andlo.gitbook.io/mycroft-skills-list,
inairspace.com (best voice command software for PC 2025 guide).

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 12 | L `recurring.py` | Repeating reminders: "remind me to drink water every hour", "every weekday at 9 take medicine" | Timers only fire once today | Easy |
| 13 | M `browser.py` | Browser control + "summarize this page" | Browser is where most PC time goes | Medium |
| 14 | N `lookup.py` | Define a word, Wikipedia summary, spell a word, synonyms (works with no Claude key) | Top Mycroft/OVOS skills; free APIs | Easy |
| 15 | O `recent.py` | "open my last download", "what did I download today", "open recent file" | Very common need | Easy |
| 16 | P `expenses.py` | "I spent 200 on food", "how much did I spend this week" | Daily habit tracking | Easy |
| 17 | Q `memos.py` | Voice memos: record, list, play last memo | Hands-free notes with your own voice | Medium |
| 18 | R `fun.py` | Flip a coin, roll dice, random number, pick one of a list, quick quiz | Popular, offline, tiny | Easy |
| 19 | S `recorder.py` | "start screen recording" / "stop recording" | Handy for sharing bugs and tutorials | Medium |

### Piece L: `recurring.py`
- Repeating reminders saved to JSON (config `recurring_file`). Patterns: every N minutes/hours, daily at time, weekdays at time, on a weekday ("every Monday at 10").
- Own wall-clock thread like `timers.py` (fires after sleep/wake; skip missed ones older than 1 hour). `start(notify)`.
- "list repeating reminders", "stop the water reminder", "stop all repeating reminders" (risky).
- Intents: `repeat_reminder {text, every_minutes?, at?, days?}`, `repeat_reminders {action: list|cancel, text?}` (cancel all = risky).
- main.py: `recurring.start(io.say)` at start.

### Piece M: `browser.py`
- Hotkey commands for the active browser: new tab, close tab, reopen closed tab, next/previous tab, go back/forward, refresh, zoom in/out, bookmark, find on page, incognito window.
- "summarize this page" / "what's this page about": copy URL (ctrl+L, ctrl+C, Esc), fetch page text (`urllib` + simple HTML-to-text), return text as info for the AI. "read this page" returns first part for tts.
- Note: use `pyautogui.hotkey` directly; do not depend on `inputs.py` (other thread).
- Intents: `browser {action}`, `page_text {}` (info).

### Piece N: `lookup.py`
- Define: dictionaryapi.dev (free, no key). Wikipedia: REST summary API `https://en.wikipedia.org/api/rest_v1/page/summary/<title>` (2 sentences). Spell: letters spaced out. Synonyms: datamuse API.
- Works without Claude key; AI can also use them as info tools.
- Intents: `define {word}` (info), `wikipedia {topic}` (info), `spell {word}`, `synonyms {word}` (info).

### Piece O: `recent.py`
- Newest files in Downloads (and Desktop/Documents) by modified time. Windows Recent folder (`%APPDATA%\Microsoft\Windows\Recent` .lnk) for "recent files".
- "open my last download", "what did I download today", "open the last PDF", "show recent files".
- Read and open only (no move/delete).
- Intents: `recent_files {folder?: downloads|recent, kind?: pdf|image|video|doc, action: list|open}` (list = info).

### Piece P: `expenses.py`
- Saved CSV (config `expenses_file`). Currency symbol from config (default ₹).
- "I spent 250 on lunch" (category guess from a small word table: food, travel, shopping, bills, other), "how much did I spend today / this week / this month", "how much on food this month", "delete last expense".
- Intents: `expense_add {amount, category?, note?}`, `expense_report {period: today|week|month, category?}` (info), `expense_undo {}`.

### Piece Q: `memos.py`
- Record from mic with `sounddevice` + `soundfile` (already used by stt? reuse if present) to `memos/` folder; stop on "stop recording" or after silence/max 2 minutes. Must release the mic so stt can listen again.
- "record a voice memo", "play my last memo", "list my memos", "delete last memo" (risky).
- Intents: `memo {action: record|play|list|delete, which?}`.
- main.py: while recording, core must not listen (module exposes `is_recording()`).

### Piece R: `fun.py`
- Coin, dice (any sides, any count), random number in range, "pick one: pizza or pasta", rock-paper-scissors, simple offline maths/GK quiz from a built-in list.
- Intents: `random_pick {kind: coin|dice|number|choice, sides?, count?, low?, high?, options?}`, `quiz {}`.

### Piece S: `recorder.py`
- Screen recording with `ffmpeg` (gdigrab) if found in PATH or config `ffmpeg_path`, to `Videos/Jarvis`. Fallback: Xbox Game Bar hotkey Win+Alt+R (records the active app).
- "start screen recording", "stop recording", "where are my recordings" (opens folder).
- Intents: `screen_record {action: start|stop|open}`.

### Round 2 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| L recurring | repeat_reminder, repeat_reminders | cancel all | recurring.start(io.say) |
| M browser | browser, page_text | - | - |
| N lookup | define, wikipedia, spell, synonyms | - | - |
| O recent | recent_files | - | - |
| P expenses | expense_add, expense_report, expense_undo | - | - |
| Q memos | memo | delete | pause listening while recording |
| R fun | random_pick, quiz | - | - |
| S recorder | screen_record | - | - |

## Wiring status (2026-11-07)
All pieces A-K are wired: actions/__init__.py, catalog, nlu.py + nlu_features.py (new phrase rules), nlu_control.py,
main.py hooks, config.py DEFAULTS, config.yaml, README. Tests: tests/test_wiring.py. Not yet run on real Windows.
Round 2 (L-S) also wired on 2026-11-07, plus REVIEW.md R4. 722 tests pass.

---

## Round 3 (2026-11-07)

Same rules (new module + new test, `CATALOG` + `HANDLERS` dicts, no shared-file edits).
Sources: kdeconnect-cli docs (thegeekdiary.com/kdeconnect-cli-command-examples, KDE Connect on winget),
Home Assistant REST API (homeassistantapi.readthedocs.io), Windows OCR (pypi.org/project/winrt-windows-media-ocr, pypi.org/project/winocr),
NN/g usage data (smart home 9%, communication 29%).

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 20 | T `phone.py` | Phone link via KDE Connect: ring my phone, send SMS, phone battery, send file/link to phone | "Find my phone" + texting are top asks | Medium |
| 21 | U `smarthome.py` | Lights, plugs, fans, AC through Home Assistant | Smart home 9% of use | Medium |
| 22 | V `software.py` | Install, update, uninstall apps with winget | Real PC chore, no other piece does it | Medium |
| 23 | W `ocr.py` | Read/copy text from screen or image, offline (Windows OCR) | Works with no Claude key; copy text from images | Medium |
| 24 | X `cliphistory.py` | Clipboard history: "paste the second last thing I copied" | Saves time daily | Easy |
| 25 | Y `spotify.py` | Play a song/playlist in the Spotify app (not YouTube), like current song | Many users use Spotify | Medium |
| 26 | Z `daily.py` | Word of the day, quote of the day, "what happened on this day" | Morning routine add-ons | Easy |
| 27 | AA `generate.py` | Strong password (copied), QR code of a link/text shown on screen | Quick tools; QR moves links to phone | Easy |

### Piece T: `phone.py`
- Uses `kdeconnect-cli` (KDE Connect for Windows, from winget/Microsoft Store). Path in config `phone.kdeconnect_path`; device from config `phone.device` or the first paired one (`kdeconnect-cli -a --id-only`).
- "ring my phone" (`--ring`), "text mom saying I'm late" (`--send-sms TEXT --destination NUMBER`, number from `contacts`; risky: ask yes), "phone battery", "send this link to my phone" (`--share URL`, clipboard), "send my last download to phone".
- Not installed -> reply how to install. Tests: fake subprocess.
- Intents: `phone {action: ring|sms|battery|share, to?, text?, what?}` (sms risky; battery info).

### Piece U: `smarthome.py`
- Home Assistant REST: config `home_assistant: {url, token}` (or env `HASS_TOKEN`). `GET /api/states` to match spoken names to entities (friendly_name, fuzzy). `POST /api/services/<domain>/<service>`.
- "turn on bedroom light", "set fan to 50 percent", "set AC to 24", "is the door locked", "turn off everything" (risky).
- Locks/garage: unlock and open are risky (ask yes).
- Intents: `device {name, action: on|off|toggle|set|status, value?}`, `scene {name}`.

### Piece V: `software.py`
- `winget`: "install VLC" (search, pick top match, say name, ask yes, then `winget install --id X -e --accept-source-agreements --accept-package-agreements`), "update all my apps" (risky), "what apps need updates" (`winget upgrade` list, info), "uninstall Zoom" (risky).
- Runs in background thread; speaks when done (`start(notify)` or notifier arg). Timeout 15 min.
- Intents: `software {action: install|uninstall|update_all|check_updates, name?}` (install/uninstall/update_all risky; check_updates info).

### Piece W: `ocr.py`
- Windows OCR via `winrt-Windows.Media.Ocr` (+ `winrt-Windows.Graphics.Imaging`, `winrt-Windows.Storage`), offline, any installed Windows language.
- "copy the text on my screen" (full screenshot -> text -> clipboard), "read the text in this window" (active window), "read the text in my last screenshot / this image" (latest image in Pictures/Screenshots or clipboard image).
- Intents: `ocr {source: screen|window|clipboard_image|last_screenshot, action: read|copy}` (read = info).

### Piece X: `cliphistory.py`
- Background thread polls clipboard text every 1 s (`pyperclip`), keeps last 25 in memory (not saved to disk by default; config `clipboard_history.save: false`). Skips text that looks like a password (no spaces, mixed chars, 8-64 long) when `skip_secrets: true`.
- "what did I copy before", "paste the second last thing", "copy item 3 again", "clear clipboard history".
- Paste = set clipboard + ctrl+v via `pyautogui.hotkey`.
- Intents: `clip_history {action: list|paste|copy|clear, index?}` (list info).
- main.py: `cliphistory.start()` at start.

### Piece Y: `spotify.py`
- If config `spotify: {client_id, client_secret}` is set: Spotify Web API (`spotipy`, OAuth once, token cached) to play track/playlist/artist on the user's device, "like this song", "add to my playlist", "what's playing on Spotify", shuffle, repeat.
- No keys: open `spotify:search:<query>` URI then press Enter/play via media key (best effort), say "opened search in Spotify".
- Intents: `spotify {action: play|like|add_to_playlist|shuffle|repeat|now_playing, query?, playlist?}`.

### Piece Z: `daily.py`
- Word of the day (built-in list of ~365 useful English words with meaning, picked by date, offline), quote of the day (built-in list), "on this day" from Wikipedia API `https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/MM/DD` (2 items).
- Intents: `daily {what: word|quote|on_this_day}` (info). Routines can use them in "good morning".

### Piece AA: `generate.py`
- Password: `secrets`, length 16 default, copies to clipboard, does NOT speak it aloud (only "copied a 16-character password").
- QR: `qrcode` package -> PNG in temp, open it (or small tkinter window) from given text, a link, or clipboard. "make a QR code of this link".
- Also: random UUID / PIN.
- Intents: `generate {kind: password|qr|pin|uuid, text?, length?}`.

### Round 3 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| T phone | phone | sms | - |
| U smarthome | device, scene | unlock/open, "everything off" | - |
| V software | software | install, uninstall, update_all | software.set_notifier(io.say) |
| W ocr | ocr | - | - |
| X cliphistory | clip_history | clear | cliphistory.start() |
| Y spotify | spotify | - | - |
| Z daily | daily | - | - |
| AA generate | generate | - | - |
Round 3 (T-AA) wired on 2026-11-07. 1003 tests pass.

---

## Round 4 (2026-11-07)

Same rules (new module + new test, `CATALOG` + `HANDLERS` dicts, no shared-file edits).
Sources: Power Automate / Task Scheduler app-open triggers (learn.microsoft.com answers 956070, techadvisor.com how-to-automate-tasks-windows,
bgr.com/2213366 Windows morning automation), Automation Anywhere window triggers. Others are gaps found by comparing with Google Assistant/Alexa.
Note: ideas are getting thinner. Round 4 is mostly automation and safety, not new daily commands.

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 28 | AB `triggers.py` | "When X happens, do Y": app opens/closes, Wi-Fi network joins, charger plugged/unplugged, time of day | Tasker/Power Automate style; makes Jarvis proactive | Medium |
| 29 | AC `meetings.py` | "join my next meeting" (opens Zoom/Teams/Meet link from calendar), "leave meeting", "am I in a meeting" | Daily for students/workers | Easy |
| 30 | AD `screentime.py` | "how long did I use Chrome today", daily usage report, app limits ("warn me after 1 hour of YouTube") | Digital wellbeing; Windows has no voice for it | Medium |
| 31 | AE `security.py` | Voice PIN for risky actions, "lock Jarvis", guest mode (only safe intents) | Anyone near the laptop can talk to Jarvis | Easy |
| 32 | AF `history.py` | "what did I ask you yesterday", "do that again", search past commands | Repeat and recall | Easy |
| 33 | AG `localai.py` | Offline AI answers with Ollama when there is no Claude key or no internet | Works free and offline | Medium |
| 34 | AH `layouts.py` | Save and restore window layouts: "save this layout as coding", "restore coding layout" | Fast workspace setup | Medium |
| 35 | AI `podcasts.py` | "play the latest episode of <podcast>", "next episode", subscriptions from RSS | Music/podcast is 22% of use | Easy |

### Piece AB: `triggers.py`
- Config `triggers:` list of `{when: {app_opens|app_closes: name} | {wifi: SSID} | {charger: plugged|unplugged} | {time: "09:00", days?}, do: [phrases]}`.
- Background thread every 3 s (psutil process list, `netsh wlan show interfaces`, psutil battery). Fires once per event change.
- Steps are phrases (like routines); module calls a `runner(phrase)` callback given by main, so it reuses nlu + actions + confirm.
- Voice: "list my triggers", "pause triggers", "resume triggers".
- Intents: `triggers {action: list|pause|resume}` (list info).
- main.py: `triggers.start(runner=lambda p: <run phrase like a routine step>, notify=io.say)`.

### Piece AC: `meetings.py`
- Uses `agenda` module (`agenda.next_event()` or its data function; read agenda.py first) and finds a Zoom/Teams/Meet/Webex link in location/description.
- "join my next meeting" opens it (Zoom: convert to `zoommtg://` if Zoom installed). "join the 3 pm meeting".
- "leave meeting": hotkey per app (Zoom alt+q, Teams ctrl+shift+h, Meet ctrl+w). "mute in meeting": Zoom alt+a, Teams ctrl+shift+m, Meet ctrl+d.
- "am I in a meeting": process/window title check.
- Intents: `meeting {action: join|leave|mute|status, when?}` (status info).

### Piece AD: `screentime.py`
- Background thread every 5 s: active window process name (`win32gui`/`psutil`) -> seconds per app per day in SQLite or JSON (config `screentime_file`). Idle (no input 2 min, `GetLastInputInfo`) is not counted.
- "how long did I use Chrome today", "my screen time today / this week", "top apps today".
- Limits: config `app_limits: {youtube: 60}` (minutes, matched on window title or process) -> speaks warning once.
- Intents: `screen_time {app?, period: today|week}` (info), `app_limit {app, minutes}`.
- main.py: `screentime.start(io.say)`.

### Piece AE: `security.py`
- Config `security: {pin: "1234" (store hash), protect: [shutdown, restart, software, phone, device, fileops intents...], guest_mode_intents: [time, weather, ...]}`.
- `check(intent) -> str | None`: returns "Say your PIN" when needed; `verify(spoken)` matches digits ("one two three four"). 3 wrong tries -> lock 5 min.
- "lock Jarvis" (only wake + PIN works), "unlock Jarvis <pin>", "guest mode on/off".
- Never speak or log the PIN.
- Intents: `jarvis_lock {state: on|off, pin?}`, `guest_mode {state: on|off}`.
- main.py: before running any intent, call `security.check(intent)`; on PIN prompt, listen and `security.verify`.

### Piece AF: `history.py`
- Append each command (time, heard text, intent, reply) to JSON lines file (config `history_file`, keep 30 days, `history.enabled: true`).
- "what did I ask you yesterday", "what did I ask about weather", "do that again" (returns last non-history command for main to rerun), "clear history" (risky).
- Intents: `history {action: list|search|repeat_last|clear, day?, query?}` (list/search info; clear risky).
- main.py: `history.log(text, cmd, reply)` after each command; for `repeat_last`, re-run returned Command.

### Piece AG: `localai.py`
- Ollama HTTP API (`http://localhost:11434/api/chat`, model from config `local_ai.model`, default `llama3.2:3b`). Streams sentences like brain (`on_sentence`).
- `available() -> bool`, `ask(text, on_sentence=None) -> str`. Short system prompt (spoken answers, 2-3 sentences). No tools.
- "use local AI" / "use cloud AI" switch; "is local AI ready".
- Intents: `ai_mode {mode: local|cloud|auto}`, `local_ai_status {}` (info).
- main.py / brain wiring: if no Claude key, or Claude call fails offline, and `localai.available()`, answer with `localai.ask`.

### Piece AH: `layouts.py`
- Save: enumerate visible top-level windows (`win32gui.EnumWindows`), store process exe + title + rect + state to JSON by name.
- Restore: start missing apps (exe path), wait up to 10 s, move/resize matching windows (`SetWindowPos`/`MoveWindow`), restore maximized state.
- "save this layout as coding", "restore coding layout", "list layouts", "delete layout coding".
- Intents: `layout {action: save|restore|list|delete, name?}`.

### Piece AI: `podcasts.py`
- Config `podcasts: {name: rss_url}` and "subscribe to <name>" via iTunes search API (`https://itunes.apple.com/search?media=podcast&term=`) to find the feed.
- "play the latest episode of X" -> open episode mp3 URL in default player (or browser); remember last played per show; "next episode", "what's new in my podcasts" (info).
- Intents: `podcast {action: play_latest|next|subscribe|unsubscribe|whats_new|list, name?}`.

### Round 4 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| AB triggers | triggers | - | triggers.start(runner, io.say) |
| AC meetings | meeting | - | - |
| AD screentime | screen_time, app_limit | - | screentime.start(io.say) |
| AE security | jarvis_lock, guest_mode | - | security.check before every intent + PIN listen |
| AF history | history | clear | history.log after each command; repeat_last re-run |
| AG localai | ai_mode, local_ai_status | - | brain fallback to localai.ask |
| AH layouts | layout | delete | - |
| AI podcasts | podcast | - | - |

---

## Round 5 (2026-11-07) - last round recommended

Same rules (new module + new test, `CATALOG` + `HANDLERS` dicts, no shared-file edits).
Sources: Microsoft UserNotificationListener docs (github.com/MicrosoftDocs/winrt-api, usernotificationlistener.md), pypi winrt-Windows.UI.Notifications,
ESPNcricinfo RSS feeds page (espncricinfo.com/story/rss-feeds-209025), Google Assistant interpreter mode, Windows `powercfg /batteryreport`.
After this round, most remaining ideas are niche or already covered by the AI brain. Recommend stopping research and testing on the real PC.

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 36 | AJ `notifications.py` | "read my notifications", announce new WhatsApp/Gmail toasts | Hands-free messages | Medium (Windows permission; may not work unpackaged) |
| 37 | AK `pchealth.py` | Battery health, startup apps, Windows Update and Defender status, "PC health check" | Laptop care | Easy |
| 38 | AL `teach.py` | Teach by voice: "when I say 'study time', open notes and start focus", "forget that command" | Users add shortcuts without editing config | Easy |
| 39 | AM `calendar_add.py` | Add events: "add dentist tomorrow at 4 pm" (Outlook desktop or Google Calendar API) | agenda.py is read-only | Medium |
| 40 | AN `interpreter.py` | Interpreter mode: "translate mode Hindi" - each phrase is spoken back translated, until "stop translating" | Google Assistant interpreter mode | Medium |
| 41 | AO `scores.py` | Live cricket/football scores: "what's the India score", "IPL score" | Common ask; quicker than AI web search | Easy |

### Piece AJ: `notifications.py`
- WinRT `Windows.UI.Notifications.Management.UserNotificationListener` (`winrt-Windows.UI.Notifications.Management`). Request access once; if denied or not supported for an unpackaged app, reply "not available on this PC" and suggest Settings > Notifications. Builder must test this first on Windows and report.
- "read my notifications" (app + title + text, newest 5), "clear notifications" (risky), optional announce mode: background poll every 5 s, speak new ones from apps in config `notifications.announce_apps: [WhatsApp, Gmail]`.
- Intents: `notifications {action: read|clear|announce_on|announce_off}` (read info; clear risky).
- main.py: `notifications.start(io.say)` if announce on.

### Piece AK: `pchealth.py`
- Battery health: `powercfg /batteryreport /xml /output <temp>` -> design vs full charge capacity, cycle count.
- Startup apps: HKCU/HKLM Run keys + Startup folder (list only). Windows Update: last install date via `Get-HotFix` (PowerShell) or WU COM `Microsoft.Update.Session` pending count. Defender: `Get-MpComputerStatus` (AV enabled, last scan, signature age).
- "check my PC health" gives one short summary; "battery health", "what starts with Windows", "any Windows updates", "is antivirus on". Read only.
- Intents: `pc_health {what: all|battery|startup|updates|antivirus}` (info).

### Piece AL: `teach.py`
- "when I say X, do Y" -> saves phrase -> list of step phrases in `taught.json` (not config.yaml, so no shared edits). "when I say X, say Y" saves a fixed answer.
- "what have you learned", "forget the command X" (risky).
- `match(text) -> list[str] | None` for main to run like routines.
- Intents: `teach {phrase, steps?, answer?}`, `taught {action: list|forget, phrase?}` (list info; forget risky).
- main.py: check `teach.match(text)` before nlu (after routines/shortcuts).

### Piece AM: `calendar_add.py`
- Outlook desktop via `win32com` (`Outlook.Application` CreateItem(1)) if installed; else Google Calendar API (`google-api-python-client`, OAuth desktop flow, token cached; config `google_calendar.credentials_file`); else open Google Calendar "create event" URL (`https://calendar.google.com/calendar/render?action=TEMPLATE&text=..&dates=..`) prefilled in browser.
- "add dentist tomorrow at 4 pm for 1 hour", "add meeting with Ravi on Friday at 10". AI gives ISO start + minutes.
- Says event back and asks yes before saving (risky).
- Intents: `calendar_add {title, start, minutes?, location?}` (risky).

### Piece AN: `interpreter.py`
- "translate mode Hindi/Telugu/Spanish...": mode flag; each phrase heard is translated (Claude brain if key; else `deep-translator` Google free endpoint) and spoken; "stop translating" ends.
- tts voice: pick installed SAPI voice for that language if present, else speak with default voice and also show text in log.
- `is_active()`, `process(text) -> str`.
- Intents: `interpreter {state: on|off, language?}`.
- main.py: when active, skip nlu and send each phrase to `interpreter.process` (like dictation).

### Piece AO: `scores.py`
- ESPNcricinfo live scores RSS (check current URL from espncricinfo.com/story/rss-feeds-209025; old one: `static.cricinfo.com/rss/livescores.xml`) -> match titles like "India 245/3 v Australia". Football: ESPN public scoreboard JSON (`site.api.espn.com/apis/site/v2/sports/soccer/<league>/scoreboard`). Feeds may change: fail softly and let the AI web search answer.
- "India score", "live cricket scores", "Premier League scores", favourite teams in config `scores.teams`.
- Intents: `scores {sport: cricket|football, team?}` (info).

### Round 5 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| AJ notifications | notifications | clear | notifications.start(io.say) |
| AK pchealth | pc_health | - | - |
| AL teach | teach, taught | forget | teach.match(text) before nlu |
| AM calendar_add | calendar_add | yes (always) | - |
| AN interpreter | interpreter | - | interpreter mode in loop |
| AO scores | scores | - | - |

---

## Round 6 (2026-11-07) - reliability and polish

Same rules (new module + new test, `CATALOG` + `HANDLERS` where it has intents, no shared-file edits).
Focus: make the first real Windows run work, fewer false wakes, easier use. Does not repeat REVIEW.md fixes.
Sources: openWakeWord (pypi.org/project/openwakeword, github.com/dscripka/openWakeWord forks), pystray docs, rapidfuzz docs.

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 42 | AP `doctor.py` | Self-check: "Jarvis, check yourself" and `main.py --doctor` | First Windows run will hit setup problems; this finds them fast | Easy |
| 43 | AQ `wakeword.py` | openWakeWord engine option + sensitivity | Fewer false wakes and misses than Vosk grammar | Medium |
| 44 | AR `tray.py` | System tray icon: status, mute Jarvis, open config/log, restart, quit | Jarvis runs with no window; user needs to see and control it | Easy |
| 45 | AS `corrections.py` | "That was wrong" log + "when you hear X I mean Y" fixes applied before NLU | Accuracy gets better with use | Easy |
| 46 | AT `fuzzy.py` | Fuzzy name matching for apps, contacts, folders, devices (rapidfuzz) | Speech mishears names ("note pad", "spotty fly") | Easy |
| 47 | AU `onboarding.py` | First-run voice setup: name, city, mic level test, wake word test, API key check | Easier install for a beginner | Medium |

### Piece AP: `doctor.py`
- Checks, each pass/fail with a fix hint: Python version, every package in requirements.txt importable, Vosk model folder, default mic exists and gets sound (`sounddevice` 1 s level), TTS voices (`pyttsx3`), config.yaml loads and known keys have the right types, API key present (and one tiny call only if user says "full check"), internet, writable log/notes/data files, Windows-only features (pycaw, winrt, kdeconnect-cli, winget, ffmpeg, Outlook) present or not.
- Writes `doctor-report.txt`; speaks a short summary ("12 OK, 2 problems: no microphone sound, ffmpeg missing").
- Intents: `self_check {full?: bool}` (info). Also `run_cli()` for `python main.py --doctor`.

### Piece AQ: `wakeword.py`
- `wait(word, sensitivity)` using `openwakeword` (pre-trained "hey_jarvis" model; ONNX runtime on Windows) with the same mic settings as stt. Falls back to `stt.wait_for_wake_word` if the package or model is missing.
- Config `stt.wake_engine: vosk|openwakeword`, `stt.wake_sensitivity: 0.5`. Voice: "make wake word more / less sensitive" (saves to a small `wake.json`, not config.yaml).
- Intents: `wake_sensitivity {change: up|down, value?}`.
- main.py: choose engine at start.

### Piece AR: `tray.py`
- `pystray` + `Pillow` icon in its own thread. Icon colour shows state: idle / listening / speaking / paused (main calls `tray.set_state(...)`).
- Menu: Pause/Resume listening (uses assistant pause), Open config, Open log, Run self-check (doctor), Restart Jarvis, Quit.
- `start(on_quit, on_pause)` with callbacks from main. No intents.
- main.py: `tray.start(...)` when not `--text`, and `set_state` at each loop step.

### Piece AS: `corrections.py`
- "that was wrong" / "you misheard": saves last heard text + intent + reply to `misheard.jsonl` (for later tuning).
- "when you hear 'note pad' I mean 'notepad'" / "when I say 'chrome' I mean 'google chrome'": saves text replacements to `corrections.json`. `apply(text) -> text` (whole-word, case-insensitive).
- "list corrections", "remove correction X".
- Intents: `misheard {}`, `correction {heard, meant}`, `corrections {action: list|remove, heard?}` (list info).
- main.py: `text = corrections.apply(text)` right after listen; `corrections.set_last(text, cmd, reply)` after each command.

### Piece AT: `fuzzy.py`
- `best(name, choices, cutoff=80) -> str | None` with `rapidfuzz` (fallback `difflib`). Also joins split words ("note pad" -> "notepad") and common STT slips table.
- Helpers: `app(name, apps_dict)`, `contact(name, contacts)`, `folder(name)`, `device(name, entities)`.
- No intents. Wiring thread: use it inside apps/contacts/smarthome/folder lookups when exact match fails (small edits in those modules, done by the wiring thread).

### Piece AU: `onboarding.py`
- Runs when `user.json` is missing (or "Jarvis, set me up again"): asks name, city (for weather), news country, preferred voice speed; plays a mic level test and asks the user to say the wake word 3 times (reports hits); checks API key; saves to `user.json` and to memory (`actions.memories` remember).
- Config values from `user.json` override config.yaml (wiring: small change in `jarvis/config.py` `load_config`).
- Uses `io.say` / `io.listen` passed in: `run(io) -> None`.
- Intents: `setup {}`.
- main.py: at start, `if onboarding.needed(): onboarding.run(io)`.

### Round 6 duplicate check (2026-11-07)
Checked all modules in jarvis/actions/, README.md, REVIEW.md and rounds 1-5.
- AP doctor: already built (doctor.py) from this round's spec. Do not build again.
- AQ wakeword, AR tray, AU onboarding: nothing like them exists. OK to build.
- AS corrections: no correction feature exists. But do not make a new command log: use `history.py` (AF) for "the last command"; only add `corrections.json` text fixes. Different from `teach.py` (teach = phrase -> actions; corrections = misheard word -> right word).
- AT fuzzy: `smarthome.py` already has its own difflib matching. Leave smarthome alone; use fuzzy only for apps, contacts and folders.

### Round 6 wiring

| Piece | Intents | Risky | main.py / shared hooks |
|---|---|---|---|
| AP doctor | self_check | - | `--doctor` flag |
| AQ wakeword | wake_sensitivity | - | pick wake engine at start |
| AR tray | - | - | tray.start + set_state |
| AS corrections | misheard, correction, corrections | - | apply() after listen, set_last() after reply |
| AT fuzzy | - | - | use in apps/contacts/smarthome/folders lookups |
| AU onboarding | setup | - | run on first start; config.py reads user.json |

---

## Round 7 (2026-11-07)

Same rules (new module + new test, `CATALOG` + `HANDLERS`, no shared-file edits).
Duplicate check done first: all 60 modules in jarvis/actions/, README.md, REVIEW.md and rounds 1-6 (A-AU, all built).
Code search found no existing maps, document reading, contacts editing, habits, flashcards, birthdays, download watching or file conversion.
Research basis: NN/g usage data (directions 19%, communication 29%), Google Assistant/Alexa features (birthdays, contacts, directions), study and habit apps.

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 48 | AV `maps.py` | Directions and travel time: "how long to drive to Hyderabad", "directions to the airport" | Directions = 19% of assistant use; not built | Easy |
| 49 | AW `documents.py` | Read or summarize a PDF/Word/text file: "summarize my last download", "read page 2 of this PDF" | Opening files exists, reading them does not | Medium |
| 50 | AX `contacts.py` | Manage contacts by voice: "add Ravi's number 98...", "what is Ravi's number", "Ravi's birthday is 5 May" | Contacts today only live in config.yaml | Easy |
| 51 | AY `habits.py` | Habit tracker: "I did my workout", "my reading streak", "habits this week" | Daily motivation; nothing like it built | Easy |
| 52 | AZ `flashcards.py` | Your own flashcards with spaced repetition: "add flashcard", "quiz me on Spanish" | Study use; fun.py quiz is fixed GK only | Easy |
| 53 | BA `birthdays.py` | Birthdays/anniversaries: "when is mom's birthday", "birthdays this month", alert the day before | Common Alexa/Google ask | Easy |
| 54 | BB `watchers.py` | "Tell me when my download finishes", "tell me when this website is back up", "when the battery reaches 80%" | One-off watch-and-tell (triggers.py runs fixed rules from config) | Easy |
| 55 | BC `fileconvert.py` | Convert files: images to PDF, Word to PDF, resize/compress image, merge PDFs | Real chore; fileops only copies/moves/deletes | Medium |

### Piece AV: `maps.py`
- Geocode with Nominatim (OpenStreetMap, free, needs a User-Agent "JarvisVoiceAssistant", max 1 request/s), route time and distance with OSRM public server (`router.project-osrm.org`, driving). Home city/address from config `home` or the weather city.
- "how far is X", "how long to drive to X", "directions to X" (opens Google Maps directions URL `https://www.google.com/maps/dir/?api=1&destination=...`).
- No live traffic (say so). Fail softly offline.
- Intents: `travel_time {to, from?}` (info), `directions {to, from?, mode?: driving|walking|transit}`.

### Piece AW: `documents.py`
- Text from PDF (`pypdf`), DOCX (`python-docx`), TXT/MD/CSV. File from a name, a path, or `recent.py` helpers ("my last download", "the last PDF").
- "read this PDF" (first ~800 chars to tts, "continue" reads next part), "read page 3", "summarize my last download" (info tool: returns text up to 15k chars to the AI), "how many pages".
- Read only.
- Intents: `document {action: read|continue|page|info, name?, page?}` (info for AI summaries).

### Piece AX: `contacts.py`
- `contacts.json` (merged with config `contacts` for reading; config ones are read-only). Fields: name, phone, email, birthday, notes.
- "add contact Ravi phone 98...", "Ravi's email is ...", "what's Ravi's number", "delete contact Ravi" (risky), "list my contacts".
- Exposes `lookup(name) -> dict | None` (uses `fuzzy.py`) so whatsapp/email/phone can use it (wiring thread connects).
- Intents: `contact_add {name, phone?, email?, birthday?}`, `contact_get {name, field?}` (info), `contact_delete {name}` (risky), `contacts_list {}` (info).

### Piece AY: `habits.py`
- `habits.json`: habit name -> list of done dates. "I did my workout" / "mark reading done", "did I meditate today", "my workout streak", "habits this week", "remove habit X" (risky).
- Optional evening nudge: config `habits.remind_at: "21:00"` speaks habits not done today (`start(notify)`).
- Intents: `habit_done {name}`, `habit_status {name?, period?: today|week}` (info), `habit_remove {name}` (risky).
- main.py: `habits.start(io.say)`.

### Piece AZ: `flashcards.py`
- Decks in `flashcards.json`; Leitner boxes (simple spaced repetition: right -> next box, wrong -> box 1; box n due every 2^(n-1) days).
- "add flashcard to Spanish: hello means hola", "quiz me on Spanish" (asks question, waits for answer via follow-up listening, says right/wrong with fuzzy match), "how many cards are due", "delete deck X" (risky).
- Quiz is a mode like dictation: `is_active()`, `process(text) -> str`.
- Intents: `flashcard_add {deck, front, back}`, `flashcard_quiz {deck?}`, `flashcard_status {}` (info), `deck_delete {deck}` (risky).
- main.py: when quiz active, send each phrase to `flashcards.process`.

### Piece BA: `birthdays.py`
- Reads birthdays from `contacts.py` (AX) plus its own `birthdays.json` for non-contacts and anniversaries.
- "mom's birthday is 12 March", "when is mom's birthday", "how old is Priya turning" (if year known), "birthdays this month", alert at 9:00 on the day and the day before (`start(notify)`).
- Intents: `birthday_add {name, date, kind?: birthday|anniversary}`, `birthday_get {name?, period?: month|week}` (info).
- main.py: `birthdays.start(io.say)`. Build after AX (or read contacts.json directly if AX is not ready).

### Piece BB: `watchers.py`
- One-off watches in a background thread, spoken once then removed: download finished (newest `.crdownload`/`.part` in Downloads disappears and a final file appears), website up (HTTP 200 every 60 s, max 6 h), battery reaches N% (psutil), app closed (process gone), CPU idle (under 10% for 2 min, e.g. for a render).
- "tell me when my download finishes", "tell me when google.com is back", "tell me when battery is 80 percent", "tell me when Zoom closes", "what are you watching", "stop watching".
- Different from `triggers.py` (fixed rules from config that run actions) and `monitor.py` (fixed alerts).
- Intents: `watch {what: download|website|battery|app_closed|cpu_idle, target?, value?}`, `watches {action: list|cancel}`.
- main.py: `watchers.set_notifier(io.say)`.

### Piece BC: `fileconvert.py`
- Images -> PDF (`Pillow`), merge PDFs (`pypdf`), Word/PowerPoint -> PDF (Office COM via `win32com` if installed; else say "needs Microsoft Office"), resize/compress image (Pillow, keep original, save as `name-small.jpg`), convert image format (PNG/JPG/WebP).
- Input: "this file" (selected file in Explorer via Shell COM `Shell.Application` windows `.Document.SelectedItems()`), last download, or a name via `recent.py`. Output next to the source; never overwrite (add -1, -2).
- Intents: `convert_file {action: to_pdf|merge_pdfs|resize|compress|to_format, name?, format?, size?}`.

### Round 7 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| AV maps | travel_time, directions | - | - |
| AW documents | document | - | - |
| AX contacts | contact_add, contact_get, contact_delete, contacts_list | contact_delete | whatsapp/email/phone use contacts.lookup |
| AY habits | habit_done, habit_status, habit_remove | habit_remove | habits.start(io.say) |
| AZ flashcards | flashcard_add, flashcard_quiz, flashcard_status, deck_delete | deck_delete | quiz mode in loop |
| BA birthdays | birthday_add, birthday_get | - | birthdays.start(io.say) |
| BB watchers | watch, watches | - | watchers.set_notifier(io.say) |
| BC fileconvert | convert_file | - | - |

---

## Round 8 (2026-11-07)

Same rules (new module + new test, `CATALOG` + `HANDLERS`, no shared-file edits).
Duplicate check: all 72 files in jarvis/actions/, README.md, REVIEW.md, rounds 1-7 (A-BC). Code search found no air quality/sunrise,
recipes, accessibility tools, internet radio, local music library, or project time tracking.
Dropped as duplicates: wallpaper (in winsettings.py), journal (notes + dictation), stock/crypto prices (AI web search), countdowns (date_calc).
Sources: Open-Meteo air-quality and forecast APIs (open-meteo.com, free, no key), TheMealDB API (themealdb.com/api.php, free test key "1"),
radio-browser.info API (api.radio-browser.info), Windows accessibility shortcuts (Win+Plus magnifier, Ctrl+Win+Enter Narrator, Win+Ctrl+L live captions, Win+Ctrl+C colour filters).

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 56 | BD `airquality.py` | Air quality (AQI), UV, sunrise/sunset, "will it rain in the next hour" | Weather is 29% of use; AQI matters a lot in Indian cities | Easy |
| 57 | BE `recipes.py` | Find a recipe and cook hands-free: "next step", "start a timer for this step" | Classic kitchen voice use; hands are dirty | Medium |
| 58 | BF `accessibility.py` | Magnifier on/zoom, Narrator, live captions, colour filters, bigger cursor/text | Voice Access users; helps anyone with eye strain | Easy |
| 59 | BG `radio.py` | Internet radio: "play Radio Mirchi", "play jazz radio", "next station" | Music 22% of use; play/spotify are YouTube/Spotify only | Easy |
| 60 | BH `localmusic.py` | Play songs from your own Music folder: by song, artist, album, shuffle | Offline music; YouTube needs internet | Medium |
| 61 | BI `timetrack.py` | Project time tracking: "start tracking college project", "stop", "time on project this week" | screentime.py tracks apps, not tasks | Easy |

### Piece BD: `airquality.py`
- Open-Meteo: geocode city (`geocoding-api.open-meteo.com/v1/search`), air quality (`air-quality-api.open-meteo.com/v1/air-quality`, `us_aqi`, `pm2_5`, `pm10`), forecast (`api.open-meteo.com/v1/forecast`: `uv_index`, `sunrise`, `sunset`, `precipitation_probability` hourly). City from args or config weather city.
- "what's the air quality", "is it safe to go running" (AQI + simple advice band), "when is sunset", "UV index today", "will it rain in the next hour".
- Intents: `air_quality {city?}` (info), `sun_times {city?}` (info), `rain_soon {city?}` (info), `uv {city?}` (info).

### Piece BE: `recipes.py`
- TheMealDB search (`/api/json/v1/1/search.php?s=`), random meal, by ingredient (`filter.php?i=`). Split instructions into steps.
- Cook mode (like dictation): "cook paneer butter masala" -> reads ingredients, then each "next step" / "repeat step" / "previous step" / "stop cooking". If a step has "for N minutes", offer "start a timer" (returns a `timer` Command or calls `timers.timer`).
- "what can I make with eggs and tomatoes".
- Intents: `recipe {action: find|random|by_ingredients, query?}` (info), `cook {action: start|next|previous|repeat|stop|ingredients, name?}`.
- main.py: when cook mode is active, short phrases ("next", "repeat") go to `recipes.process`.

### Piece BF: `accessibility.py`
- Magnifier: start/zoom in (Win+Plus), zoom out (Win+Minus), close (Win+Esc). Narrator toggle (Ctrl+Win+Enter). Live captions (Win+Ctrl+L, Windows 11 22H2+). Colour filters toggle (Win+Ctrl+C, must be enabled once in settings; say so). Text size / cursor size: open `ms-settings:easeofaccess-display` and `ms-settings:easeofaccess-mousepointer` pages.
- Uses `pyautogui.hotkey` directly (not inputs.py).
- Intents: `accessibility {feature: magnifier|narrator|captions|color_filter|text_size|cursor, action: on|off|toggle|zoom_in|zoom_out}`.

### Piece BG: `radio.py`
- radio-browser.info: search stations by name/tag/country (`/json/stations/search?name=..&limit=5&hidebroken=true&order=clickcount`), play stream URL in VLC if found (config `vlc_path` or default locations) else default player/browser. Favourites in `radio.json`.
- "play Radio Mirchi", "play some jazz radio", "next station", "stop the radio", "save this station", "play my favourite station".
- Intents: `radio {action: play|next|stop|save|favourite, query?}`.

### Piece BH: `localmusic.py`
- Scans Music folder (+ config `music_folders`) for mp3/m4a/flac/wav/ogg; reads tags with `mutagen` (title, artist, album); caches index in `music_index.json` (rescan on "update my music library" or if older than 1 day).
- "play Arijit Singh from my music", "play the album X", "shuffle my music", "what songs do I have by X". Builds an .m3u playlist in temp and opens it with VLC or the default player. Pause/next use existing media keys.
- Intents: `local_music {action: play|shuffle|list|rescan, artist?, album?, song?}` (list info).

### Piece BI: `timetrack.py`
- `timetrack.json`: sessions {project, start, end}. One running at a time; starting another stops the first.
- "start tracking college project", "stop tracking", "what am I tracking", "how long did I work on X today / this week", "time report this week" (top projects), "delete last session" (risky). Optional CSV export to Documents.
- Intents: `track {action: start|stop|status, project?}`, `track_report {project?, period: today|week|month}` (info), `track_undo {}` (risky).

### Round 8 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| BD airquality | air_quality, sun_times, rain_soon, uv | - | - |
| BE recipes | recipe, cook | - | cook mode in loop |
| BF accessibility | accessibility | - | - |
| BG radio | radio | - | - |
| BH localmusic | local_music | - | - |
| BI timetrack | track, track_report, track_undo | track_undo | - |

---

## Round 9 (2026-11-07)

Same rules (new module + new test, `CATALOG` + `HANDLERS`, no shared-file edits).
Duplicate check: all 79 files in jarvis/actions/, README.md, REVIEW.md, rounds 1-8 (A-BI). Code search found: printers only as a Settings page
(winsettings.py), VS Code only as an app to open (apps.py), file search by name only (files.py `os.walk`). No virtual desktops, sleep timer,
file-content search, git/dev helpers, or end-of-day recap.
Sources: Windows Search SQL over OLE DB (`Provider=Search.CollatorDSO`, `SYSTEMINDEX`, Microsoft Learn "Querying the Index with Windows Search SQL Syntax"),
`pyvda` (pypi, Windows virtual desktops), `win32print` / `ShellExecute "print"` (pywin32), Windows virtual-desktop hotkeys (Win+Ctrl+D/Left/Right/F4).

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 62 | BJ `printer.py` | "print this document", "print my last download", "what's in the print queue", "cancel printing", "default printer" | Printing by voice not built (only Settings page) | Easy |
| 63 | BK `vdesktops.py` | Virtual desktops: "new desktop", "go to desktop 2", "move this window to desktop 3", "close this desktop" | Workspace switching; window control has no desktops | Easy |
| 64 | BL `sleeptimer.py` | Bedtime: "stop the music in 30 minutes" (fades volume), "sleep the laptop in 1 hour" | Common phone/speaker feature; timers only speak | Easy |
| 65 | BM `filesearch.py` | Find files by what is inside: "find the document that mentions invoice 2024", "files I edited yesterday" | files.py searches names only | Medium |
| 66 | BN `devtools.py` | For coding: "open my project in VS Code", "git status", "git pull", "commit with message ..." (asks yes), "run my tests" (fixed per project in config) | User is a developer; fixed commands only, no free shell | Medium |
| 67 | BO `recap.py` | Evening recap: "how was my day" - screen time, tracked projects, habits done, money spent, reminders missed, tomorrow's first meeting | Ties many built pieces into one daily summary | Easy |

### Piece BJ: `printer.py`
- File from a name, "my last download" or "this file" (reuse `recent.py` / `fileconvert.py` helpers where public). Print with `win32api.ShellExecute(0, "print", path, None, ".", 0)`; PDFs need a default PDF app that supports print (say so if it fails).
- Queue: `win32print.EnumJobs` on default printer; cancel all jobs (risky) with `SetJob(..., JOB_CONTROL_DELETE)`. "what's my default printer", "is the printer online" (printer status flags).
- Intents: `print_file {name?}` (asks yes: "Print report.pdf on HP LaserJet?"), `print_queue {action: list|cancel}` (list info; cancel risky), `printer_info {}` (info).

### Piece BK: `vdesktops.py`
- `pyvda` if installed (go to desktop N, move active window to N, count, current name); fallback to hotkeys Win+Ctrl+D (new), Win+Ctrl+Left/Right (switch), Win+Ctrl+F4 (close).
- "new desktop", "next desktop", "go to desktop 2", "move this window to desktop 3", "which desktop am I on", "close this desktop" (windows move to the next one; no confirm needed).
- Intents: `vdesktop {action: new|next|previous|go|move_window|close|which, number?}`.

### Piece BL: `sleeptimer.py`
- "stop the music in 30 minutes": after N minutes, fade master volume down over 30 s (pycaw, via `audio.py` helpers if public, else own), send media pause, restore the old volume level.
- "sleep the laptop in 1 hour" / "shut down in 2 hours": schedules; asks yes now (risky) and speaks a 1-minute warning ("say cancel to stop").
- "cancel sleep timer", "how long is left on the sleep timer".
- Intents: `sleep_timer {minutes, action: stop_media|sleep|shutdown}` (sleep/shutdown risky), `sleep_timer_cancel {}`, `sleep_timer_status {}` (info).

### Piece BM: `filesearch.py`
- Windows Search index via OLE DB (`adodbapi` or `win32com.client.Dispatch("ADODB.Connection")`, `Provider=Search.CollatorDSO;Extended Properties='Application=Windows';`). Query `SELECT TOP 10 System.ItemPathDisplay, System.DateModified FROM SYSTEMINDEX WHERE CONTAINS('"invoice 2024"') AND SCOPE='file:C:/Users/<you>'`. Escape quotes in user text.
- "find the file that mentions X", "files I edited yesterday / this week", "find PDFs about tax", "open the first one" (remembers last results). If index is off, say how to turn it on (Settings > Searching Windows).
- Read and open only.
- Intents: `find_files {text?, kind?, modified?: today|yesterday|week}` (info), `open_result {number}`.

### Piece BN: `devtools.py`
- Config `projects: {name: {path, test: "pytest -q", run: "npm run dev"}}`. Only the commands written in config run (like shortcuts). Git commands are a fixed list: status, pull, log -5, diff --stat, branch, commit -am "<msg>" (risky), push (risky). Run with `subprocess.run([...], cwd=path, timeout=120)`, no `shell=True`.
- "open jarvis project in VS Code" (`code <path>`), "git status of jarvis", "pull latest", "run the tests" (speaks pass/fail count from the last line), "start the dev server" (background, `stop` kills it).
- Output summary is spoken short; full output saved to `devtools.log` and can be sent to the AI as info.
- Intents: `dev {action: open|git_status|git_pull|git_log|git_diff|git_commit|git_push|test|run|stop, project?, message?}` (commit/push risky; status/log/diff/test info).

### Piece BO: `recap.py`
- Builds one short spoken summary from built modules, each optional (skip if module missing or empty): `screentime` top 3 apps, `timetrack` today, `habits` done/missed, `expenses` today total, `lists` open to-dos count, missed reminders (timers), `agenda` first event tomorrow, `birthdays` tomorrow.
- "how was my day", "evening recap", "what's tomorrow look like" (agenda + reminders + birthdays for tomorrow). Optional daily time in config `recap.at: "21:30"` (`start(notify)`).
- Read only. Reads module data through their public functions; do not edit those modules.
- Intents: `recap {day?: today|tomorrow}` (info).
- main.py: `recap.start(io.say)` if `recap.at` is set.

### Round 9 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| BJ printer | print_file, print_queue, printer_info | print_file, cancel | - |
| BK vdesktops | vdesktop | - | - |
| BL sleeptimer | sleep_timer, sleep_timer_cancel, sleep_timer_status | sleep/shutdown | sleeptimer.set_notifier(io.say) |
| BM filesearch | find_files, open_result | - | - |
| BN devtools | dev | git_commit, git_push | - |
| BO recap | recap | - | recap.start(io.say) if recap.at |

---

## Round 10 (2026-11-07) - small round, ideas nearly used up

Same rules (new module + new test, `CATALOG` + `HANDLERS`, no shared-file edits).
Duplicate check: all files in jarvis/actions/, README.md, REVIEW.md, rounds 1-9 (A-BO). Code search: hotspot only as a Settings page
(winsettings.py), camera only as "open the Camera app" (apps.py). No drive eject, display projection modes, or webcam photo.
Sources: Microsoft Learn `NetworkOperatorTetheringManager` (WinRT, mobile hotspot on/off), `DisplaySwitch.exe /extend|/clone|/internal|/external`,
Shell `Eject` verb on removable drives (`Shell.Application` Namespace(17)), OpenCV `VideoCapture`.

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 68 | BP `drives.py` | "what drives are connected", "how much space on D drive", "eject my pen drive" | Daily USB use; disk info today is C: only | Easy |
| 69 | BQ `hotspot.py` | Turn mobile hotspot on/off, say its name and password, how many devices connected | Only the Settings page exists now | Medium |
| 70 | BR `display.py` | "extend my screen", "duplicate screen", "second screen only", "laptop screen only", "what's my resolution" | Projector/second monitor in meetings and class | Easy |
| 71 | BS `webcam.py` | "take a photo", "take a photo in 3 seconds", "is my camera on" | Camera app opens today, but no hands-free photo | Easy |

### Piece BP: `drives.py`
- psutil `disk_partitions()` + `disk_usage()`; drive type via `win32file.GetDriveType` (removable, fixed, network, CD); volume label via `win32api.GetVolumeInformation`.
- "what drives are connected", "how much space on D drive", "is my pen drive connected", "open my pen drive" (Explorer), "eject my pen drive" (Shell `Eject` verb on the removable drive; if busy, say "a file is still open on it").
- Read only, except eject.
- Intents: `drives {action: list|space|open|eject, drive?}` (list/space info).

### Piece BQ: `hotspot.py`
- WinRT `Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager.CreateFromConnectionProfile(NetworkInformation.GetInternetConnectionProfile())` (`winrt-Windows.Networking.NetworkOperators`, `winrt-Windows.Networking.Connectivity`). `StartTetheringAsync`/`StopTetheringAsync`, `GetCurrentAccessPointConfiguration()` for SSID/passphrase, `ClientCount`.
- "turn on hotspot", "turn off hotspot", "what's my hotspot password" (shows on screen / copies to clipboard instead of speaking it aloud), "how many devices are on my hotspot".
- Fallback: open `ms-settings:network-mobilehotspot` if the API fails or no internet profile.
- Intents: `hotspot {action: on|off|status|password}` (status info).

### Piece BR: `display.py`
- `DisplaySwitch.exe /extend | /clone | /internal | /external` (Windows 10/11). Resolution and monitor count via `win32api.EnumDisplayMonitors` / `EnumDisplaySettings`.
- "extend my screen", "duplicate screen", "second screen only", "laptop screen only", "how many monitors", "what's my resolution", "open projection menu" (Win+P).
- Intents: `display {action: extend|duplicate|external_only|internal_only|info|menu}` (info is info).

### Piece BS: `webcam.py`
- OpenCV (`opencv-python`) `VideoCapture(0)`, warm up 10 frames, save JPG to `Pictures/Jarvis` with time name; optional countdown with beeps; open the photo after. Release camera at once.
- "is my camera on / in use": registry `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam\...\LastUsedTimeStop == 0` means in use now (list app names).
- Says clearly when a photo is taken (privacy). No video recording, no background capture.
- Intents: `webcam {action: photo|status, delay?}` (status info).

### Round 10 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| BP drives | drives | - | - |
| BQ hotspot | hotspot | - | - |
| BR display | display | - | - |
| BS webcam | webcam | - | - |

---

## Round 11 (2026-11-07) - final round: no more new useful ideas after this

Duplicate check: all modules in jarvis/actions/, README.md, REVIEW.md, rounds 1-10 (A-BS). Code search: no speaker identification,
and commands are understood in English only (interpreter.py translates speech out, not commands in).
Sources: Home Assistant voice poll (users asked for voice ID), Vosk model list (alphacephei.com/vosk/models: small Hindi model `vosk-model-small-hi-0.22`),
`resemblyzer` (pypi, speaker embeddings, CPU).

| # | Piece | Feature | Why | Effort |
|---|-------|---------|-----|--------|
| 72 | BT `multilang.py` | Give commands in Hindi (and Telugu via faster-whisper if installed): "Jarvis, Chrome kholo" | Many Indian users mix languages; today only English works | Medium |
| 73 | BU `voiceid.py` | Know who is speaking: only the owner's voice can run risky actions; "who am I" | Safer than PIN alone; asked for in voice-assistant polls | Medium |

### Piece BT: `multilang.py`
- Config `stt.languages: [en, hi]`. Hindi: second Vosk model (`vosk-model-small-hi-0.22`, ~42 MB, download like the English one). Telugu: only if `faster-whisper` is installed (model `small`, language="te"); otherwise say "Telugu needs faster-whisper".
- `recognize(audio_bytes) -> (text, lang)`: run English first; if confidence low or text empty, try the other models. `to_english(text, lang)`: Claude brain if key, else `deep-translator`; keep names/numbers.
- "switch to Hindi", "speak in Hindi too" (tts reply language if a Hindi SAPI voice exists).
- Intents: `language {action: set|status, lang?}`.
- main.py / stt wiring: after listen, if `multilang` active, use `multilang.recognize` and pass `to_english(text)` to nlu.

### Piece BU: `voiceid.py`
- `resemblyzer` VoiceEncoder (CPU). Enrol: "learn my voice" asks the user to say 5 short sentences, saves the mean embedding to `voiceid.npy` (never uploaded).
- `verify(audio) -> (is_owner, score)`; threshold in config `voiceid.threshold: 0.75`. Works with `security.py`: when on, risky intents need owner voice (PIN still works as backup).
- "learn my voice", "who am I", "forget my voice" (risky), "voice lock on/off".
- Intents: `voice_id {action: enrol|check|forget|on|off}` (forget risky).
- main.py: keep the last command's audio; pass to `voiceid.verify` before risky intents when voice lock is on.

### Round 11 wiring

| Piece | Intents | Risky | main.py hooks |
|---|---|---|---|
| BT multilang | language | - | recognize + to_english after listen |
| BU voiceid | voice_id | forget | verify audio before risky intents |

### Research stopped here
73 features across 11 rounds. Everything else found is already built, a small variation of a built feature, or handled by the AI brain.
Best next step: run Jarvis on the real Windows PC (`python main.py --doctor`, then `--text`, then voice) and fix real errors.
