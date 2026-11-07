# Wiring notes: piece AO (scores.py)

Merge: `from .scores import CATALOG as CAO, HANDLERS as HAO`, then update catalog CATALOG and _HANDLERS.
Info intent: `scores`. Not risky. No main.py hooks. No new packages (urllib, json, xml.etree only).

## brain.py
- Add `scores` to `UNTRUSTED_INFO`: team names and score lines come from web feeds (outside text).
  The module already cleans them (safe characters only, max 80 chars per line, tags removed).

## Config (optional, defaults work)
```yaml
scores:
  teams: ["India"]                     # favourite teams, used when no team is said
  football_leagues: ["eng.1", "uefa.champions", "esp.1", "ind.1"]   # ESPN league codes
  cricket_url: "https://static.cricinfo.com/rss/livescores.xml"
```
Add `"scores": {}` to `config.DEFAULTS`.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "India score", "what's the India score", "score of India match" | scores | {team: "India"} |
| "live cricket scores", "cricket score", "IPL score" | scores | {sport: "cricket"} (or {team: "IPL"}: means any cricket) |
| "Premier League scores", "Champions League scores", "La Liga results" | scores | {sport: "football", league: "premier league"} |
| "Arsenal score", "how is Arsenal doing" | scores | {team: "Arsenal"} (sport guessed) |
| "football scores", "soccer scores" | scores | {sport: "football"} |
| "live scores", "sports scores" | scores | {} (uses favourite teams, else cricket) |

Notes:
- Handler accepts messy text: `team` may hold "what's the India score" or "premier league"; it strips filler
  and moves league names to `league` itself. Sport is guessed from team/league words when not given.
  Unknown team with no sport -> cricket.
- Rule must need the word "score(s)" / "result(s)" so "India" alone or "score a goal" chat is not caught.
- On any network/feed error the reply is "I couldn't get live <sport> scores right now. Try asking me to
  search the web." The AI brain (web_search) can still answer when it has a key.
- Live feeds were NOT tested (sandbox blocks internet). Formats coded from the known feed shapes. Cricinfo
  RSS URL is old and may be dead; if so, set `scores.cricket_url` to the new one. Test on Windows.
