# Jarvis

A voice assistant for your Windows laptop. Say **"Jarvis"**, then a command.
Works offline (speech model runs on your PC).

## Install (one time)

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/
   - On the first screen, tick **"Add python.exe to PATH"**.
2. Copy the whole `jarvis` folder to your PC, for example `C:\jarvis`.
   Don't put it on the Desktop or in OneDrive: OneDrive would sync thousands of package files.
3. Open the folder `packaging` and **double-click `install.bat`**.
   It will:
   - make a private Python folder `.venv`
   - install the packages
   - download the speech model (~40 MB, one time)
   - ask if Jarvis should start when you log in
   - ask if you want to start Jarvis now
4. Allow the microphone: **Settings > Privacy & security > Microphone**,
   turn on **"Let desktop apps access your microphone"**.

## Test it

Open a terminal in the `jarvis` folder (in Explorer, type `cmd` in the address bar), then:

| Test | Command |
|------|---------|
| Type commands (no mic) | `.venv\Scripts\python main.py --text` |
| Microphone + speech | `.venv\Scripts\python -m jarvis.stt` |
| Voice output | `.venv\Scripts\python -m jarvis.tts` |
| Full voice mode | `.venv\Scripts\python main.py` |
| All unit tests | `.venv\Scripts\python -m pytest tests` |

Try these in `--text` mode first:
`what time is it`, `open notepad`, `search for weather today`,
`volume up`, `set brightness to 50`, `take a screenshot`, `shut down` (then say `no`).

To quit: say or type **"goodbye"** (or "exit jarvis").
**"Stop listening"** does not quit any more: it pauses Jarvis. Say **"Jarvis, start listening"** to wake it up.

## Ask anything (AI brain)

Built-in commands work offline. For anything else (questions, chat, maths,
"open Spotify and set volume to 30", live facts), Jarvis asks Claude.

1. Get an API key at https://console.anthropic.com (API Keys). It is paid per use.
2. Set it as a Windows environment variable (safest): open a terminal and run
   `setx ANTHROPIC_API_KEY "your-key"`, then restart Jarvis.
   Or paste it in `config.yaml` under `ai:` -> `api_key:`.
3. Without a key, Jarvis still does all built-in commands.

Change model, speed and web search under `ai:` in `config.yaml`.

## What you can say

| Feature | Examples |
|---|---|
| Apps | `open chrome`, `close notepad` |
| Timers, reminders | `set a timer for five minutes`, `remind me to call mom in 10 minutes`, `remind me at 5 pm to go to the gym`, `what timers do I have`, `cancel all timers` |
| Weather, news | `what's the weather`, `weather in London`, `latest news`, `cricket news` |
| Music, media | `play lofi beats`, `pause`, `next song`, `previous track`, `stop the music` |
| Files, folders | `open downloads`, `open file budget report` |
| Notes | `take a note buy milk`, `read my notes` |
| Email | `send an email to mom about dinner` (opens a draft, never sends) |
| System info | `how much battery`, `cpu usage`, `how much ram`, `disk space`, `system status` |
| Wi-Fi, Bluetooth | `turn off wifi`, `bluetooth on`, `open wifi settings` |
| Windows | `minimize this window`, `maximize`, `close this window`, `switch window`, `snap window left`, `show desktop` |
| Screen, sound | `volume up`, `mute`, `set brightness to 50`, `take a screenshot`, `type hello` |
| Power | `lock`, `go to sleep`, `restart`, `shut down`, `empty the recycle bin` |
| Alarms | `set an alarm for 7 am`, `wake me up in 20 minutes` |
| Calculator (offline) | `what is 15 percent of 2400`, `square root of 81`, `12 times 8` |
| Websites | `open youtube`, `go to gmail`, `open example.com` |
| WhatsApp | `whatsapp mom saying I'm on my way` (needs WhatsApp Desktop and the number under `contacts`) |
| Clipboard | `read my clipboard` |
| Memory | `remember that my sister is Priya`, `what do you remember about me`, `forget everything` |
| Routines | `good morning`, `start work mode`, `break time` (edit them under `routines:` in `config.yaml`) |
| Anything else (AI) | `tell me a joke`, `who won the match yesterday`, `translate hello to Hindi` |
| Lists | `add milk to my shopping list`, `remove milk from my shopping list`, `what's on my to-do list`, `clear my shopping list`, `what lists do I have` |
| Help, pause, voice | `what can I say`, `help with timers`, `stop listening for 10 minutes`, `go quiet`, `start listening`, `repeat that`, `speak slower`, `speak faster`, `speak louder`, `speak quieter`, `normal voice` |
| Calendar | `what's on my calendar today`, `what's my schedule for friday`, `when is my next meeting`, `am I free at 3 pm`, `good morning briefing` (also says "Meeting X starts in 5 minutes") |
| Dictation | `start dictation`, then just talk. Inside: `comma`, `full stop`, `question mark`, `new line`, `new paragraph`, `caps <word>`, `delete that`, `undo`, `stop dictation` |
| Read aloud | `read this aloud` (selected text, or the clipboard), `stop reading` |
| Conversions | `convert 5 miles to km`, `100 F in C`, `how many cm in 6 feet`, `10 dollars in rupees`, `convert 50 euros to INR` |
| World time, dates | `what time is it in Tokyo`, `how many days until 25 December`, `what day was 15/08/1947`, `date in 45 days`, `how many days since 1 January` |
| Internet | `am I online`, `what's my IP`, `what Wi-Fi am I on`, `internet speed`, `ping google` |
| Audio | `what's playing`, `mute my mic`, `unmute mic`, `set spotify volume to 30`, `spotify volume down`, `switch to headphones`, `list audio devices` |
| Focus | `start focus for 25 minutes`, `how long left`, `stop focus`, `turn on do not disturb`, `turn off do not disturb` |
| Health alerts | Jarvis warns on low battery, full charge, CPU hot, low disk. `turn off battery alerts`, `turn on alerts` |
| Email (read only) | `do I have new emails`, `read my latest emails`, `read my last 5 emails`, `any email from mom` |
| Repeating reminders | `remind me to drink water every hour`, `every weekday at 9 take medicine`, `remind me every day at 8 pm to call mom`, `list repeating reminders`, `stop the water reminder`, `stop all repeating reminders` (asks first) |
| Browser | `new tab`, `close this tab`, `reopen closed tab`, `next tab`, `refresh the page`, `bookmark this page`, `find price on this page`, `open incognito`, `show history`, `open downloads page` |
| Web page | `summarize this page`, `what's this page about` (needs the AI key), `read this page out loud` |
| Words, Wikipedia | `define serendipity`, `what does serendipity mean`, `how do you spell necessary`, `another word for happy`, `opposite of happy`, `wikipedia Albert Einstein` |
| Recent files | `open my last download`, `open the last pdf`, `open the second last download`, `what did I download today`, `show recent files`, `open the latest picture on my desktop` |
| Expenses | `I spent 250 on lunch`, `add expense of 500 for uber`, `how much did I spend this month`, `how much did I spend on food this week`, `delete the last expense` (saved as a CSV file you can open in Excel) |
| Voice memos | `record a voice memo` (stops by itself when you go quiet), `play my last memo`, `play memo 2`, `list my memos`, `delete my last memo` (asks first), `open my memos folder` |
| Fun | `flip a coin`, `roll two dice`, `random number between 5 and 50`, `pick one: pizza or pasta`, `rock paper scissors`, `quiz me` (then just say your answer), `what's my score`, `stop the quiz` |
| Screen recording | `record my screen`, `stop recording`, `where are my recordings` (best with ffmpeg installed; otherwise Xbox Game Bar) |
| Phone (KDE Connect) | `ring my phone`, `where is my phone`, `text mom saying I'm late` (asks first), `send this link to my phone`, `send my last download to my phone`, `phone battery` |
| Smart home (Home Assistant) | `turn on the bedroom light`, `set fan to 50 percent`, `set AC to 24`, `is the front door locked`, `lock the front door`, `unlock the front door` (asks first), `open the garage` (asks first), `turn off everything` (asks first), `activate movie night scene` |
| Install apps (winget) | `install VLC`, `uninstall Zoom`, `update all my apps` (all ask first), `what apps need updates` |
| Read text on screen (offline) | `copy the text on my screen`, `read the text in this window`, `read the text in my last screenshot`, `copy text from this image` |
| Clipboard history | `what did I copy before`, `paste the second last thing I copied`, `paste item 3`, `copy item 3 again`, `clear clipboard history` (asks first) |
| Spotify | `play shape of you on spotify`, `play my workout playlist on spotify`, `play my liked songs`, `like this song`, `add this song to my gym playlist`, `shuffle on`, `repeat this song`, `what's playing on spotify` |
| Daily | `word of the day`, `give me a new word`, `quote of the day`, `inspire me`, `what happened on this day` |
| Passwords, QR codes | `generate a password` (copied, never spoken), `make a 24 character password`, `give me a PIN`, `generate a uuid`, `make a QR code of this link`, `QR code for hello world` |
| Triggers | set them in `config.yaml` (`triggers:`), e.g. "when Zoom opens, set volume 20". Say `list my triggers`, `pause triggers`, `resume triggers` |
| Meetings | `join my next meeting`, `join the 3 pm meeting`, `mute me`, `unmute me`, `leave the call`, `am I in a meeting` |
| Screen time | `my screen time today`, `screen time this week`, `how long did I use chrome today`, `warn me after 1 hour of youtube`, `limit youtube to 30 minutes`, `remove the youtube limit`, `what are my app limits` |
| PIN lock, guest mode | `lock Jarvis`, `unlock Jarvis` (then say your PIN), `guest mode on`, `guest mode off` (PIN) |
| Command history | `what did I ask you yesterday`, `what did I ask about weather`, `do that again` (risky ones ask again), `clear my history` (asks first) |
| Offline AI (Ollama) | `use local AI`, `use Claude`, `auto AI mode`, `is local AI ready` |
| Window layouts | `save this layout as coding`, `restore my coding layout`, `list my layouts`, `delete the coding layout` (asks first) |
| Podcasts | `play the daily podcast`, `play the latest episode of hard fork`, `next episode`, `subscribe to hard fork`, `what's new in my podcasts`, `list my podcasts` |
| Notifications | `read my notifications`, `clear my notifications`, `announce my notifications`, `stop announcing notifications` |
| PC health | `check my pc health`, `how hot is my cpu`, `how is my disk`, `is my battery healthy` |
| Teach me | `when I say movie time, open netflix and dim the screen`, then just say `movie time`. `what have you learned`, `forget the command movie time` |
| Add to calendar | `add meeting with Ravi on Friday at 10`, `put gym in my calendar tomorrow at 7 am` (always asks first) |
| Interpreter | `start interpreter mode in spanish` (everything you say is translated and spoken), `stop translating` |
| Live scores | `what's the cricket score`, `India score`, `premier league results` |
| Self check | `run a self check`, or run `python main.py --doctor` (add `--full` to also test the AI key) |
| Wake word | `make the wake word more sensitive`, `you wake up too often`, `set wake word sensitivity to 6` (optional engine: install `openwakeword` and set `stt: wake_engine: openwakeword`; then the wake phrase is "hey Jarvis", not "Jarvis") |
| Fix misheard words | `when you hear note pad I mean notepad`, `you misheard, I said notepad`, `list corrections`, `remove correction note pad` |
| Setup | runs by itself the first time. Later: `run setup`, `change my name`, `change my city`, `test my mic`, `set up a PIN`, or `python main.py --setup` |
| Maps | `how long to drive to Hyderabad`, `how far is the airport`, `directions to Charminar` (opens Google Maps), `take me home` |
| Read documents | `read my last download`, `read this pdf`, `continue`, `read page 3`, `how many pages in this pdf`, `summarize my last download` (AI) |
| Contacts | `add contact Ravi phone 98765 43210`, `Ravi's email is ravi at gmail dot com`, `what's Ravi's number`, `list my contacts`, `delete contact Ravi` (asks first) |
| Habits | `I did my workout`, `did I meditate today`, `my workout streak`, `habits this week`, `remove habit reading` (asks first) |
| Flashcards | `add flashcard to Spanish hello means hola`, `quiz me on Spanish` (then say the answer, `skip`, or `stop`), `how many flashcards are due`, `delete the Spanish deck` (asks first) |
| Tell me when | `tell me when my download finishes`, `tell me when google dot com is back`, `tell me when battery is 80 percent`, `tell me when Zoom closes`, `what are you watching`, `stop watching` |
| Convert files | `convert this to pdf` (selected files in Explorer, else your last download), `merge these pdfs`, `resize this picture to 50 percent`, `compress this photo`, `convert this image to png` |
| Air, sun, rain | `what's the air quality`, `AQI in Delhi`, `is it safe to go running`, `when is sunset`, `will it rain in the next hour`, `do I need an umbrella`, `UV index today` |
| Recipes, cook mode | `recipe for butter chicken`, `what can I make with eggs and tomatoes`, `random recipe`, `cook pasta`, then `next`, `go back`, `repeat`, `ingredients`, `start a timer`, `stop cooking` |
| Accessibility | `turn on the magnifier`, `magnifier zoom in`, `close the magnifier`, `turn on narrator`, `turn on live captions`, `turn on grayscale`, `make the text bigger`, `bigger mouse pointer` |
| Internet radio | `play Radio Mirchi`, `play jazz radio`, `play hindi radio from India`, `next station`, `save this station`, `play my favourite station`, `stop the radio` (best with VLC) |
| My music (on this PC) | `play my music`, `shuffle my music`, `play Arijit Singh from my music`, `play the album Aashiqui 2 from my music`, `what songs do I have by X`, `rescan my music library` |
| Time tracking | `start tracking college project`, `stop tracking`, `what am I tracking`, `how long did I work on thesis this week`, `time report this week`, `export my time report`, `delete last session` (asks first) |
| Birthdays | `mom's birthday is 12 March`, `our anniversary is 10 June 2015`, `when is mom's birthday`, `how old is Priya turning`, `birthdays this month`, `any birthdays this week` |
| Printing | `print this document` (selected files), `print my last download`, `print report.pdf` (all ask first), `what's printing`, `cancel printing` (asks first), `is the printer online`. Plain `print this` still presses Ctrl+P |
| Virtual desktops | `new desktop`, `next desktop`, `previous desktop`, `go to desktop 2`, `move this window to desktop 3`, `which desktop am I on`, `close this desktop` |
| Sleep timer | `stop the music in 30 minutes`, `sleep the laptop in 1 hour`, `shut down in 2 hours` (sleep / shut down ask first), `sleep timer status`, `cancel sleep timer` |
| Search inside files | `find the file that mentions invoice`, `find pdfs about tax`, `files I edited today`, then `open the first one` |
| Code projects | `open jarvis project in VS Code`, `git status`, `pull latest`, `show the last commits`, `run the tests`, `start the dev server`, `commit with message fix bug` and `push my changes` (ask first) |
| Day recap | `how was my day`, `what does tomorrow look like` |
| Drives | `what drives are connected`, `how much space on D drive`, `open my pen drive`, `eject my pen drive` |
| Mobile hotspot | `turn on hotspot`, `turn off hotspot`, `how many devices are on my hotspot`, `what's my hotspot password` (shown and copied, never spoken) |
| Second screen | `extend my screen`, `duplicate screen`, `second screen only`, `laptop screen only`, `what's my resolution`, `open projection menu` |
| Webcam | `take a photo`, `take a photo in 3 seconds`, `is my camera on` (photos need `opencv-python`) |
| Hindi / Telugu | `understand Hindi`, `I will speak Telugu`, `reply in Hindi`, `English only`. Then e.g. "Chrome kholo", "awaaz badhao" |
| Voice lock | `learn my voice` (PIN first), `who am I`, `voice lock on`, `voice lock off`, `forget my voice` (asks first) |
| Your shortcuts | any phrase you add under `shortcuts:` in `config.yaml`, and `type my address` for `snippets:` |
| AI + your laptop | `what's on my screen`, `explain this error` (looks at the screen), `summarize the selected text`, `translate my clipboard to Hindi and copy it`, `should I charge my laptop` |

**Talking fast:** after the wake word you hear a short beep (no "Yes?"). After Jarvis answers,
keep talking for 6 seconds without saying "Jarvis" again (`follow_up_seconds`).
AI answers start speaking after the first sentence arrives.
Reminders and alarms are saved, so they still go off after a restart or after the laptop wakes up.

Jarvis asks **"Are you sure?"** before shut down, restart, sleep, emptying the recycle bin,
turning Wi-Fi off, forgetting memory, clearing a list, running a `run:` shortcut, stopping all repeating reminders, deleting a voice memo, sending an SMS, unlocking or opening doors, adding a calendar event, clearing notifications, forgetting a taught command, deleting a contact, a habit, a flashcard deck or a time tracking session, forgetting your voice print,
"turn off everything", installing / uninstalling / updating apps, clearing clipboard history, and (if you turn on `whatsapp: auto_send`) sending WhatsApp messages. Say **yes** to go ahead.

## Control the whole PC

| What | Examples |
|---|---|
| Windows settings | `turn on dark mode`, `light mode`, `battery saver on`, `high performance mode`, `turn off the screen`, `open display settings`, `open sound settings`, `night light`, `open notification settings`, `open device manager` |
| Files and folders | `create a folder called projects on the desktop`, `make a new file notes`, `copy the file budget to documents`, `move file report to downloads`, `rename the file report to final`, `delete the file old notes` |
| Running programs | `what apps are running`, `what's using my memory`, `what is using the cpu`, `end task chrome`, `force close teams` |
| Keyboard | `press enter`, `press control c`, `press alt f4`, `press tab three times`, `copy that`, `paste`, `undo`, `select all`, `save`, `new tab`, `close this tab`, `refresh`, `zoom in`, `go back` |
| Mouse | `click`, `right click`, `double click`, `scroll down`, `scroll up a lot`, `move the mouse left`, `move the mouse to the center` |
| Click by name | `click on the save button`, `click on downloads`, `double click on budget` (works in the window in front) |
| AI takes control | `take control and change my wallpaper to the beach photo`, `take control and turn on captions in YouTube` |

- **Delete** sends to the Recycle Bin and asks **"Are you sure?"** first. Files are only touched inside your
  user folder (Desktop, Documents, Downloads...), never system folders, and never overwritten.
- **End task** asks first, and never closes Windows system processes.
- **Take control** (needs the Claude API key) asks first, then Claude looks at the screen and uses the mouse
  and keyboard step by step. It stops to ask you before deleting, sending, buying, installing or changing
  passwords. **To stop it at once, push the mouse into any screen corner.** Settings: `computer_use:` in `config.yaml`.
- Night light opens the Settings page (Windows has no safe switch for it). Do not disturb tries to switch
  itself; if Windows blocks it, Jarvis opens the notification settings instead.
- Battery saver / high performance use Windows power plans. Many new laptops only have "Balanced";
  then Jarvis opens the power settings so you can change Power mode.

## Auto-start

Jarvis starts in the background (no window) when you log in.

- Turn on: `.venv\Scripts\python packaging\autostart.py install`
- Turn off: `.venv\Scripts\python packaging\autostart.py uninstall`
- Check: `.venv\Scripts\python packaging\autostart.py status`
- Stop it and turn off auto-start: double-click `packaging\uninstall.bat`

## Settings

Edit `config.yaml` (wake word, voice speed, app paths), then restart Jarvis.
Add your own apps under `apps:`, for example `spotify: "C:/Users/YOU/AppData/Roaming/Spotify/Spotify.exe"`.
Also there: weather city, news country, notes file, email `contacts`.

New feature settings (all in `config.yaml`, with comments):

- **Calendar:** paste your calendar's ICS link under `calendars:`. Google Calendar: Settings > your calendar >
  "Secret address in iCal format". Outlook.com: Settings > Calendar > Shared calendars > Publish > ICS link.
- **Email:** under `email_account:` put your address in `user:`. For Gmail make an app password
  (myaccount.google.com/apppasswords) and save it with `setx JARVIS_IMAP_PASSWORD "your-app-password"`.
  For Outlook.com / Microsoft 365 set `provider: outlook` (reads the Outlook desktop app). Jarvis never sends or deletes mail.
- **Shortcuts and snippets:** `shortcuts:` phrase -> `{open: ...}`, `{keys: ...}` or `{run: ...}`; `snippets:` name -> text.
- **Focus:** minutes per round under `focus:`. A routine called `focus` under `routines:` runs when a focus session starts.
- **Alerts:** thresholds under `alerts:` (battery %, CPU %, free disk GB). `enabled: false` turns them all off.
- **Expenses:** `expenses_file` (a CSV file) and `currency`.
- **Voice memos:** `memos:` folder and how long a quiet gap ends a memo. Jarvis does not listen to commands while a memo records.
- **Screen recording:** `recorder:` (ffmpeg path, folder, fps). Install ffmpeg from ffmpeg.org for full-screen recordings.
- **Dictionary / Wikipedia:** `lookup:` (Wikipedia language, how many sentences).
- If the AI (not you) wants to record your mic or screen, or open a recent file, Jarvis asks you "yes" first.
- **Phone:** install KDE Connect (`winget install KDE.KDEConnect`) on the PC and the phone, and pair them.
  Phone numbers come from `contacts:`. Settings under `phone:`.
- **Smart home:** under `home_assistant:` put your Home Assistant address in `url:`. Make a long-lived token
  (Home Assistant > your profile > Security) and save it with `setx HASS_TOKEN "your-token"`.
  Smart home phrases only work when this is set up, so "turn on wifi" etc. stay laptop commands.
- **Installing apps** uses winget (built into Windows 10/11). It runs in the background and tells you when it is done.
- **Reading text on screen** uses Windows' own offline OCR. If it says no OCR language, add a language in
  Settings > Time & language > Language.
- **Clipboard history** is kept in memory only (set `clipboard_history: save: true` to keep it). Text that looks like
  a password is not kept.
- **Spotify:** without keys Jarvis opens a search in the Spotify app. For full control make an app at
  developer.spotify.com/dashboard, add the redirect URI from `config.yaml`, and put the Client ID under `spotify:`
  (or `setx SPOTIPY_CLIENT_ID "..."`). The first time, a browser opens to log in. Playing needs Spotify Premium.
- **Passwords** are copied to the clipboard and cleared after 60 seconds (`generate:` settings).
- **PIN lock:** run `.venv\Scripts\python -m jarvis.actions.security set-pin` once. Then risky commands (shut down,
  delete, install, SMS, smart home...) ask for your PIN, "lock Jarvis" locks everything, and "guest mode on" only allows
  simple things (time, weather, timers, music...). The PIN is never written to the log or the history. Settings: `security:`.
- **Offline AI:** install Ollama (ollama.com) and run `ollama pull llama3.2:3b` once. With no Claude key, or with no
  internet, Jarvis answers with it. Settings: `local_ai:`.
- **Triggers** run like routine steps in the background. A risky step (shut down, delete...) is skipped, never done without you.
- **Screen time** is saved in `Documents\Jarvis screen time.json`. **History** is saved in `Documents\Jarvis history.jsonl` (30 days).
- **Notifications:** `notifications:` (which apps to announce). Reading Windows notifications needs the optional
  `winrt` packages in `requirements.txt` and permission in Settings > Privacy > Notifications.
- **Add to calendar:** `calendar: add_with:` auto (Outlook app if installed, else a Google Calendar link in the browser),
  `outlook`, `google` (needs `google_calendar: credentials_file`) or `link`. Jarvis always asks before adding.
- **Live scores:** your teams and leagues under `scores:`.
- **Taught commands** are saved in `taught_file` (`~/.jarvis/taught.json`). The AI can't teach or forget them for you.
- **Self check:** `python main.py --doctor` checks Python, packages, the mic, models, keys and settings, and writes a report.
- **Tray icon:** in voice mode a Jarvis icon shows near the clock (grey idle, green listening, amber thinking,
  blue speaking, red paused). Right-click: pause, open config, open log, self-check, restart, quit. Needs `pystray`.
- **Names that sound close:** if an app, contact or folder name is not found exactly, Jarvis picks a very close one
  ("crome" -> Chrome, "down loads" -> Downloads). It never guesses between two people, and never for file names.
- **Your setup answers** (name, city, units, greeting) are saved in `~/.jarvis/user.json` and win over `config.yaml`.
- **Contacts** you add by voice are saved in `contacts_file`. WhatsApp, email and SMS use them too.
- **Habits:** `habits: remind_at: "21:00"` gives an evening nudge for habits not done yet.
- **Documents and PDFs** need `pypdf` and `python-docx`. Word to PDF needs Microsoft Office.
- **Maps** use OpenStreetMap (free, no key). Times are driving times without live traffic. Set `maps: home:`.
- **Birthdays:** Jarvis reminds you once a day after `birthdays: remind_at` (09:00), and the day before.
- **Radio and my music** play in VLC if it is installed (`vlc_path`), else in your default player.
  Extra music folders: `music_folders:`. Song tags need `mutagen`.
- **Time tracking** is saved in `timetrack: file`; `export my time report` writes a CSV to Documents.
- **Air quality, sunrise, rain, UV** use Open-Meteo (free, no key) and your `weather: city`.
- **Code projects:** add them under `devtools: projects:` (path, test command, run command). Jarvis runs only the
  commands you write there, and git commit / push always ask first.
- **Evening recap:** set `recap: at: "21:30"` to hear it every evening.
- **Virtual desktops:** install `pyvda` for exact "go to desktop 3" and "move this window". Without it, Windows shortcuts are used.
- **Search inside files** uses Windows Search. If it says search is off: Settings > Privacy and security > Searching Windows.
- **Big optional packages:** install only what you want: `pip install opencv-python` (webcam photos),
  `pip install faster-whisper` (Telugu, ~500 MB), `pip install resemblyzer` (voice lock, ~800 MB).
- **Hindi** downloads a 42 MB speech model the first time you say "understand Hindi".
- **Voice lock** lets your own voice replace the PIN for risky commands. It is a convenience, not as strong as the PIN
  (a recording of your voice could pass). "lock Jarvis" and guest mode still need the PIN. If you set your own
  `security: protect:` list, add `voice_id:enrol`, `voice_id:off` and `voice_id:forget` to it.
- **Lists:** saved in `lists_file` (default `Documents\Jarvis lists.json`).

## If something goes wrong

- Look at `jarvis.log` and `jarvis-crash.log` in the `jarvis` folder. Note: `jarvis.log` keeps what you said (it is capped at about 4 MB).
- "Python was not found": reinstall Python and tick "Add python.exe to PATH".
- Jarvis does not hear you: check the mic setting above, and the default mic in Windows sound settings.
- Speech model download failed: run `install.bat` again (needs internet once).
- Brightness only works on laptop screens (and some monitors).
- "Jarvis is already running": only one Jarvis can run at a time. Use the tray icon (Quit), or `packaging\uninstall.bat` to stop the hidden one.
- "config.yaml has a mistake near line N": fix that line. Put Windows paths in single quotes, like `'C:\Users\me\Music'`, and use spaces, not tabs.
- One optional package failed to install: `install.bat` still finishes, and only that feature is off. Run `.venv\Scripts\python main.py --doctor` to see what is missing.
- "open WhatsApp" / "open Zoom": Jarvis also finds apps from the Start menu (Store apps too).
- "Add your Claude API key": see "Ask anything" above.
- Wi-Fi/Bluetooth can't switch: Jarvis opens the Settings page instead. Check
  **Settings > Privacy & security > Radios** allows desktop apps.
