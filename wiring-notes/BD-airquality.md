# Wiring notes: piece BD (airquality.py)

Merge: `from .airquality import CATALOG as CBD, HANDLERS as HBD`, then update catalog CATALOG and _HANDLERS.
Intents: `air_quality`, `sun_times`, `rain_soon`, `uv` - all info, all args optional `{city?}`.
Not risky (no confirm). No main.py hooks. No config changes (reads existing `weather.city`).
No new packages (urllib, json only).

## brain.py
- Add all four (`air_quality`, `sun_times`, `rain_soon`, `uv`) to `UNTRUSTED_INFO`: the place name comes
  from Open-Meteo geocoding / ipinfo.io (outside text). The module cleans it (tags removed, safe
  characters only, max 60 chars). Numbers come from the API.

## Location
- `city` arg (handler strips "in/for/at ..." and "today/now" itself) -> config `weather.city`
  (falls back to `info.WEATHER_CITY`) -> rough IP location from `https://ipinfo.io/json`.
- "here" / "my area" / "outside" count as no city.
- "Hyderabad, India" works: searches "Hyderabad", prefers the result whose country matches.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "what's the air quality", "how is the air today", "AQI in Delhi", "pollution level in Delhi" | air_quality | {city: "Delhi"} |
| "is it safe to go running", "can I go for a run outside", "is the air ok for a walk" | air_quality | {} |
| "when is sunset", "what time is sunrise", "sunrise and sunset in Goa" | sun_times | {city: "Goa"} |
| "will it rain in the next hour", "is it going to rain soon", "do I need an umbrella" | rain_soon | {} |
| "UV index today", "what's the UV in Chennai", "do I need sunscreen" | uv | {city: "Chennai"} |

Notes for nlu_features.py:
- Put these rules BEFORE the general `weather` rule, or "will it rain" / "air" will go to `weather`.
  Keep plain "what's the weather" / "will it rain tomorrow" on `weather` (rain_soon is next hour only;
  only send to rain_soon when the phrase has "next hour", "soon", "right now", or "umbrella").
- City: take text after a final "in <city>" / "for <city>"; leave it out otherwise.
- "running" phrases need an outdoor/air word or "safe to" so "is Chrome running" stays on processes.

## Behaviour
- AQI = US AQI from Open-Meteo (CAMS data), bands: good, moderate, unhealthy for sensitive groups,
  unhealthy, very unhealthy, hazardous; each band adds one line of running/outdoor advice.
  Also says PM2.5 and PM10 (micrograms per cubic metre).
- sun_times: before sunrise says both; in the day says sunset (and when sunrise was); after sunset
  says tomorrow's sunrise. Times are local time of the place (API `timezone=auto`).
- rain_soon: this hour + next hour. Yes if chance >= 50% or >= 0.5 mm; "maybe" at 25-49%; else no,
  and mentions if rain is likely in the next ~5 hours.
- uv: today's max + right now, with WHO band (low/moderate/high/very high/extreme) and advice.
- Offline/error: "I couldn't reach the weather service. Check the internet connection."
- Live services NOT tested (sandbox blocks internet; 48 tests use fakes).
  Test on Windows: "what's the air quality", "when is sunset", "will it rain in the next hour", "UV index today".
