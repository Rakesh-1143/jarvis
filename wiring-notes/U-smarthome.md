# Wiring notes: piece U (smarthome.py, Home Assistant)

Files: `jarvis/actions/smarthome.py`, `tests/test_smarthome.py` (26 tests pass, all HTTP faked).
No new packages (urllib + json). No main.py hooks.

## actions/__init__.py + catalog
- Merge: `from . import smarthome` then `CATALOG.update(smarthome.CATALOG)`, `_HANDLERS.update(smarthome.HANDLERS)`.
  Intents: `device {name, action: on|off|toggle|set|status|lock|unlock|open|close, value?}`, `scene {name}`.
- Risky: in `_risky_text` add `if intent == "device": return smarthome.risky_text(args)` (None when safe).
  Risky = unlock a lock (or "off" on a lock), open a lock latch, open/set a garage/gate/door cover,
  `name: everything` + `off`. The handler never does these without `confirm=True`. "Lock" and "close" are not risky.
- `device` with action status is spoken directly (not an `info` tool). Neither intent is `info`.

## Config (add to config.yaml / config.py DEFAULTS as `"home_assistant": {}`)
```yaml
home_assistant:
  url: ""              # e.g. "http://homeassistant.local:8123"
  token: ""            # leave empty; set env var HASS_TOKEN instead (long-lived token from HA profile page)
  verify_ssl: true     # false only for a self-signed https cert on your home network
  aliases: {}          # spoken name -> entity_id, e.g. {ac: climate.living_room, "big light": light.hall}
  all_off_domains: [light, fan, media_player]   # what "turn off everything" turns off (lock/cover never)
```
Env vars: `HASS_TOKEN` (wins over config), `HASS_URL` (used if config url is empty).

## NLU phrases -> intent + args
Put these AFTER the laptop rules for wifi, bluetooth, volume, brightness, screen, apps (`_device_rules`),
so "turn on wifi" / "turn off bluetooth" / "turn off the screen" keep working.
Best: only use a generic "turn on/off X" smart-home rule when `home_assistant.url` is set.

| Say | Intent | Args |
|---|---|---|
| "turn on the bedroom light", "switch off kitchen lights", "turn on the fan" | device | {name, action: on/off} |
| "toggle the TV plug" | device | {name, action: toggle} |
| "set fan to 50 percent", "dim bedroom light to 30" | device | {name, action: set, value: 50} |
| "set AC to 24", "set the thermostat to 21 degrees" | device | {name: "AC", action: set, value: 24} |
| "is the front door locked", "is the garage open", "what's the outside temperature", "is the bedroom light on" | device | {name, action: status} |
| "lock the front door" | device | {name, action: lock} |
| "unlock the front door" (risky) | device | {name, action: unlock} |
| "open the garage" (risky), "close the garage", "open the blinds" | device | {name, action: open/close} |
| "turn off everything", "turn off all devices", "everything off" (risky) | device | {name: "everything", action: off} |
| "turn off all the lights", "lights off" | device | {name: "all lights", action: off} |
| "activate movie night", "set movie night scene", "start bedtime scene" | scene | {name: "movie night"} |

Notes:
- `name` is matched fuzzily against Home Assistant friendly names (words like light/fan/AC/lock/garage help pick
  the right kind). If two devices match equally, Jarvis asks for the full name and does nothing.
- "turn on everything" is refused on purpose.
- Not tested against a real Home Assistant (sandbox has none). API format from HA REST docs. Test on Windows.
