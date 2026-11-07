# Wiring notes: piece F (convert.py) and piece J (network.py)

Merge: `from .convert import CATALOG as C1, HANDLERS as H1` / `from .network import CATALOG as C2, HANDLERS as H2`,
then update catalog CATALOG and _HANDLERS. All 4 intents are info (no risky ones). No main.py hooks.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "convert 5 miles to km", "5 miles in km", "how many cm in 6 feet" | convert | {amount: 5, from: "miles", to: "km"} (for "how many X in N Y": amount N, from Y, to X) |
| "100 F in C", "what is 30 degrees celsius in fahrenheit" | convert | {amount: 100, from: "F", to: "C"} |
| "10 dollars in rupees", "convert 50 euros to INR" | convert | {amount: 10, from: "dollars", to: "rupees"} |
| "what time is it in Tokyo", "time in London" | world_time | {city: "tokyo"} |
| "how many days until 25 December", "days until christmas", "how many weeks until new year" | date_calc | {question: <full text>} |
| "what day is 15 August", "what day was 15/08/1947" | date_calc | {question: <full text>} |
| "what is the date in 45 days", "date in 3 weeks", "what was the date 10 days ago" | date_calc | {question: <full text>} |
| "how many days since 1 January" | date_calc | {question: <full text>} |
| "am I online", "is the internet working", "check internet" | network | {what: "online"} |
| "what's my IP", "what is my IP address" | network | {what: "ip"} |
| "what Wi-Fi am I on", "which wifi am I connected to" | network | {what: "wifi"} |
| "internet speed", "run a speed test", "how fast is my internet" | network | {what: "speed"} |
| "ping google", "ping my router" | network | {what: "ping", host: "google"} |

Notes:
- `amount` may be a number or words ("twenty five"); convert.py parses it.
- "what time is it in X" must be checked before the plain `time` intent.
- "pound(s)" alone = weight. Money needs "British pounds", "pounds sterling" or "GBP".
- Speed test takes up to 15 s; main may say "Testing, one moment" first.
- requirements.txt: added `tzdata` (Windows only) for world time.
