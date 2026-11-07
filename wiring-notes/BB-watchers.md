# Wiring notes: piece BB (watchers.py)

Merge: `from .watchers import CATALOG as CBB, HANDLERS as HBB`, then update catalog CATALOG and _HANDLERS.
Intents: `watch`, `watches`. Nothing risky. No new packages (psutil, urllib only). No config.

## main.py
- `watchers.set_notifier(io.say)` once at start (next to monitor.start / focus notifier).
- Optional on exit: `watchers.stop()` (thread is a daemon, so not required).
- The thread starts by itself on the first watch.

## brain.py
- `watches` with action list is info (it only reads). Add `watches` to info intents if the brain needs the list.
- `watch` with what=website makes a web request to a site the user (or AI) names: add `watch` to
  GUARDED_ACTIONS if AI-started web requests should be guarded. Only http/https is allowed, host is checked.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "tell me when my download finishes", "let me know when the download is done" | watch | {what: "download"} |
| "tell me when google.com is back", "tell me when google dot com is up" | watch | {what: "website", target: "google.com"} |
| "tell me when battery is 80 percent", "tell me when the battery reaches 80%" | watch | {what: "battery", value: 80} |
| "tell me when Zoom closes", "let me know when Zoom is closed" | watch | {what: "app_closed", target: "zoom"} |
| "tell me when the CPU is idle", "tell me when my render is done" | watch | {what: "cpu_idle"} |
| "what are you watching", "list my watches" | watches | {action: "list"} |
| "stop watching", "cancel all watches" | watches | {action: "cancel"} |
| "stop watching Zoom", "stop watching my download" | watches | {action: "cancel", target: "zoom"} |

Notes:
- Rule must start with "tell me when" / "let me know when" / "notify me when" so normal "when is ..." questions
  are not caught. Do not clash with timers/reminders ("remind me ..."), or triggers.py ("when X do Y" is config only).
- Handler is lenient: `what` also accepts download(s), site, url, app, cpu, idle, render; battery value can be in
  `target` as "80%"; website target can be "google dot com" or "google" (adds .com).
- Download done = no partial files (.crdownload/.part/.partial/.opdownload) left in Downloads
  (`recent.folder_path("downloads")`, so config `downloads_folder` works). Says the newest new file name.
- Website up = HTTP 2xx/3xx; checks every 60 s, gives up after 6 h. If already up, says so and does not watch.
- Battery / app / CPU give up after 12 h. Max 10 watches. Same watch twice -> "I'm already waiting for ...".
- Tested on Linux with fakes only (32 tests). Not tested on real Windows or with a real download.
