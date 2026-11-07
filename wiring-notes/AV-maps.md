# Wiring notes: piece AV (maps.py)

Merge: `from .maps import CATALOG as CAV, HANDLERS as HAV`, then update catalog CATALOG and _HANDLERS.
Intents: `travel_time` (info), `directions`. Not risky (no confirm). No main.py hooks.
No new packages (urllib, json, webbrowser only).

## brain.py
- Add `travel_time` to `UNTRUSTED_INFO`: the place name in the reply comes from OpenStreetMap
  (anyone can edit it). The module cleans it (tags removed, safe characters only, max 60 chars).
- Add `directions` to `GUARDED_ACTIONS`: it opens the browser. URL is always
  `https://www.google.com/maps/dir/?api=1&...` with encoded params, but after reading outside text the
  AI should not open pages on its own (same as `browser`).

## Config (optional, defaults work)
```yaml
maps:
  home: ""        # start point when no "from" is said; empty = weather city (voice setup)
  units: ""       # km | miles; empty = miles if weather.units is imperial, else km
```
Add `"maps": {}` to `config.DEFAULTS`.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "how long to drive to Hyderabad", "how long will it take to reach Vizag" | travel_time | {to: "Hyderabad"} |
| "how far is the airport", "distance to Pune" | travel_time | {to: "the airport"} |
| "how long from Vizag to Hyderabad", "how far is Hyderabad from Vizag" | travel_time | {to: "Hyderabad", from: "Vizag"} |
| "how long to walk to the park" | travel_time | {to: "the park", mode: "walking"} |
| "directions to the airport", "navigate to Charminar", "take me to X" | directions | {to: "the airport"} |
| "directions to X by bus / by train", "walking directions to X" | directions | {to: X, mode: "transit" / "walking"} |
| "directions from home to X" | directions | {to: X, from: "home"} |

Notes:
- Handler accepts messy text: `to` may hold the whole phrase ("how long to drive to Vizag" or
  "Hyderabad from Vizag"); it strips filler and splits "from" itself. So a simple rule is enough:
  `^(how (long|far)|distance to|travel time to)\b.*` -> travel_time {to: <text>};
  `^((walking |driving )?directions? to|navigate to|take me to)\b.*` -> directions {to: <text>}.
- Mode can also come from words in `to` ("walk", "on foot", "bus", "train", "metro").
- "how far" must not catch "how far along is my download"/timers: require "to" or "is <place>",
  and keep the rule after timer/download rules.
- "home" as destination or start = config `maps.home` (or weather city).
- travel_time for bus/train says it can't, and suggests directions (Google Maps).
- Times are OSRM car times (no live traffic; reply says so). Walking = road distance at 5 km/h.
- Offline/error: "I couldn't reach the map service..." If only routing fails, gives straight-line distance.
- Nominatim rules kept: User-Agent "JarvisVoiceAssistant/1.0", max 1 request per second (lock + sleep),
  results cached in memory. Destination search is biased to ~150 km around the start ("the airport").
- Live services NOT tested (sandbox blocks internet). Test on Windows: "how long to drive to <city>".
