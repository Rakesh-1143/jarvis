# Wiring notes: piece BG (radio.py)

Merge: `from .radio import CATALOG as CBG, HANDLERS as HBG`, then update catalog CATALOG and _HANDLERS.
One intent: `radio {action: play|next|stop|save|favourite|list, query?, country?}` (`list` is info).
No risky actions. No new packages (urllib + json + subprocess).
Not the same as `radios.py` (Wi-Fi/Bluetooth on/off) — different module, different intents.

brain.py: add `radio` to UNTRUSTED_INFO (station names come from the internet) and to GUARDED_ACTIONS
(it starts a player with a URL from the internet).

main.py (optional, recommended): call `radio.stop_all()` on exit / atexit, so VLC stops when Jarvis quits.

Optional config (works without it):
```yaml
vlc_path: "C:/Program Files/VideoLAN/VLC/vlc.exe"   # else PATH, else the usual VLC install folders
radio_file: ~/.jarvis/radio.json                     # favourites + last station
```

## NLU phrases -> args
| Say | Args |
|---|---|
| "play Radio Mirchi", "play radio mirchi radio" | {action: play, query: "radio mirchi"} |
| "play some jazz radio", "play jazz radio station" | {action: play, query: "some jazz radio"} (module strips filler words itself) |
| "play radio from India", "play hindi radio from India" | {action: play, query?: "hindi", country: "India"} |
| "next station", "change the station", "another station" | {action: next} |
| "stop the radio", "turn off the radio" | {action: stop} |
| "save this station", "add this station to favourites" | {action: save} |
| "play my favourite station", "play my favourite station Radio Mirchi" | {action: favourite, query?: "radio mirchi"} |
| "list my stations", "what are my favourite stations" | {action: list} |

Notes:
- Only match "play X" as radio when the phrase has the word radio/station/fm. Otherwise "play X" stays with
  spotify/media/youtube. "play Radio Mirchi" contains "radio", so it matches.
- "next station" must NOT steal "next song/track/episode". Only match the word "station".
- "stop the radio" must NOT match Wi-Fi/Bluetooth "radio" words in nlu (those say wifi/bluetooth).
- Plays in VLC (Jarvis keeps the process, so "stop" works). Without VLC: os.startfile(stream URL) opens
  the default player; then "stop" says to say pause. Playing a new station stops the old VLC.
- Search order: name = full query, then tag = query without filler, then name = query without filler.
  radio-browser mirrors are tried in order (de1, de2, fi1, all).
- "next" walks the last search results; with no search this session, it walks the favourites.
- Live radio-browser API and real VLC not tested (no internet / Windows in sandbox). Test on Windows.
