# Wiring notes: piece BQ (hotspot.py)

Files: `jarvis/actions/hotspot.py`, `tests/test_hotspot.py` (38 tests).
Merge: `from .hotspot import CATALOG as CBQ, HANDLERS as HBQ`, then update catalog CATALOG and _HANDLERS.
Duplicate check: winsettings.py only opens `ms-settings:network-mobilehotspot`. No on/off, status or password anywhere.

## New packages (requirements.txt, Windows only, optional)
```
winrt-Windows.Networking.NetworkOperators>=2.0; sys_platform == "win32"  # hotspot: mobile hotspot on/off
winrt-Windows.Networking.Connectivity>=2.0; sys_platform == "win32"     # hotspot: internet profile
```
Checked against the real wheels (4!10.0.28000.2957): `NetworkOperatorTetheringManager.create_from_connection_profile`,
`get_tethering_capability_from_connection_profile`, `tethering_operational_state` (enum ON/OFF/IN_TRANSITION),
`start_tethering_async`/`stop_tethering_async` -> result `.status` (TetheringOperationStatus, e.g. WI_FI_DEVICE_OFF),
`get_current_access_point_configuration().ssid/.passphrase`, `client_count`, `max_client_count`, `get_tethering_clients()`.
Without the packages, or with no internet, it opens the hotspot Settings page and says why.

## Intents
| Intent | Args | Kind |
|---|---|---|
| hotspot | {action: on\|off\|status\|password} | status = info; on/off/password = action |

- The password is **never in the reply** (so never spoken, logged in history, or sent to the AI): it goes to the
  clipboard and to an always-on-top message box (own thread, does not block).
- Not risky.

## Brain
- `GUARDED_ACTIONS += hotspot` only for `password` if guards are per action; otherwise leave the AI free to use it
  (the password still never comes back to the AI). Simplest: no change.

## main.py hook
None.

## NLU
Use `hotspot.parse(text) -> (intent, args) | None` in nlu_features, BEFORE the winsettings rule.
It returns None for anything with "settings" in it, so "open hotspot settings" stays with winsettings.

| Say | Args |
|---|---|
| "turn on hotspot", "turn on my mobile hotspot", "switch the hotspot on", "start hotspot" | {action: on} |
| "turn off hotspot", "stop the hot spot", "switch hotspot off" | {action: off} |
| "what's my hotspot password", "show me the hotspot password", "what is the password for my hotspot" | {action: password} |
| "is my hotspot on", "how many devices are connected to my hotspot", "who is on my hotspot", "hotspot status", "what's my hotspot name" | {action: status} |

## Hand test on Windows
With Wi-Fi or Ethernet connected: "turn on hotspot", join from a phone, "how many devices are on my hotspot",
"what's my hotspot password" (check it is not spoken), "turn off hotspot". Then turn Wi-Fi off and try again
(should say Wi-Fi is off and open Settings).
