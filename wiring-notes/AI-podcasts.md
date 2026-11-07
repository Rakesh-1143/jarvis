# Wiring notes: piece AI (podcasts.py)

Merge: `from .podcasts import CATALOG as CAI, HANDLERS as HAI`, then update catalog CATALOG and _HANDLERS.
One intent: `podcast {action: play_latest|next|subscribe|unsubscribe|whats_new|list, name?}`.
No risky actions. No main.py hooks. No new packages (urllib + xml.etree + json).

brain.py: add `podcast` to UNTRUSTED_INFO (episode titles come from the internet) and to GUARDED_ACTIONS
(it opens URLs / changes saved subscriptions).

Optional config (works without it):
```yaml
podcasts:            # shows from config (cannot be unsubscribed by voice)
  the daily: https://feeds.simplecast.com/54nAGcIl
podcasts_file: ~/.jarvis/podcasts.json   # voice subscriptions, last played, last seen
```

## NLU phrases -> args
| Say | Args |
|---|---|
| "play the latest episode of the daily", "play the daily podcast", "play podcast hard fork" | {action: play_latest, name: "the daily"} |
| "next episode", "play the next episode (of X)" | {action: next, name?: X} |
| "subscribe to hard fork (podcast)" | {action: subscribe, name: "hard fork"} |
| "unsubscribe from hard fork" | {action: unsubscribe, name: "hard fork"} |
| "what's new in my podcasts", "any new podcast episodes" | {action: whats_new} |
| "list my podcasts", "what podcasts do I follow" | {action: list} |

Notes:
- "next episode" must NOT steal "next song/track" (media keys). Only match the word "episode".
- "play X podcast" must be matched before the generic "play X" (spotify/media) rule.
- play_latest with an unknown name searches iTunes and plays it without subscribing. "next" never searches.
- Episode opens with os.startfile(mp3 url) -> default player or browser.
- Live iTunes / RSS not tested (no internet in sandbox). Test on Windows.
