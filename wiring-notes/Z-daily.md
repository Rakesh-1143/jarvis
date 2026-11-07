# Wiring notes: piece Z (daily.py)

Files: `jarvis/actions/daily.py`, `jarvis/actions/daily_data.py` (434 words, 100 quotes), `tests/test_daily.py` (20 tests).
Merge: `from .daily import CATALOG as CZ, HANDLERS as HZ`, then update catalog CATALOG and _HANDLERS.
Intent `daily` is info. Nothing risky. No main.py hooks. No new packages (urllib + json only).
Optional config: `daily: {events: 2}` (1-5 "on this day" items). Add `"daily": {}` to config.py DEFAULTS if you like; not required.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "word of the day", "what's today's word", "today's word", "teach me a word" | daily | {what: "word"} |
| "give me a new word", "another word", "random word" | daily | {what: "word", random: true} |
| "quote of the day", "today's quote", "thought of the day", "give me a quote" | daily | {what: "quote"} |
| "another quote", "random quote", "inspire me", "motivate me" | daily | {what: "quote", random: true} |
| "what happened on this day", "on this day in history", "today in history", "this day in history" | daily | {what: "on_this_day"} |
| "daily briefing", "daily facts" | daily | {what: "all"} |

Notes:
- "another word for X" belongs to `synonyms` (piece N). Match `another word for` BEFORE the bare "another word" rule.
- Routines: add `daily {what: all}` (or word/quote) to the "good morning" routine. When offline, `all` silently skips the history part.
- Word and quote change once a day (fixed order, same on every PC); no word repeats within 365 days.
- Live Wikimedia API not tested (sandbox has no internet); format from the public API docs. Falls back to the en.wikipedia.org REST feed. Test on Windows.
