# Wiring notes: piece AK (pchealth.py)

Merge: `from .pchealth import CATALOG as CAK, HANDLERS as HAK`, then update catalog CATALOG and _HANDLERS.
One intent: `pc_health {what?: all|battery|startup|updates|antivirus}` (default all). `info: True`.
Read only. No risky actions. No main.py hooks. No config. No new packages.

brain.py: add `pc_health` to UNTRUSTED_INFO (startup app names come from the registry / Startup folder,
any installed program can set them).

## NLU phrases -> args
| Say | Args |
|---|---|
| "check my PC health", "PC health check", "how healthy is my laptop" | {what: all} |
| "battery health", "how worn is my battery", "battery cycle count" | {what: battery} |
| "what starts with Windows", "startup apps", "what runs at startup" | {what: startup} |
| "any Windows updates", "is Windows up to date", "check for updates" | {what: updates} |
| "is antivirus on", "is Defender on", "virus protection status" | {what: antivirus} |

Notes:
- "battery health" must NOT go to `system_info {what: battery}` (that is charge %). Plain "battery" / "battery level" stays system_info. Match "health|wear|worn|cycle" first.
- "check for updates" only lists; it never installs. Don't steal "update <app>" (software piece V).
- The update count search can take 30-60 s on Windows. Optional: say "Checking, this can take a minute" before the
  call for `all`/`updates`.
- Windows only; other systems reply "PC health check works only on Windows."
- Not tested on real Windows (Linux, all OS calls faked). Test on PC: powercfg XML tags, StartupApproved byte
  (odd first byte = turned off in Task Manager), Get-MpComputerStatus without admin, SecurityCenter2 fallback
  for third-party antivirus.
