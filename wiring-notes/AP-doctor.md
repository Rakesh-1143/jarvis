# Wiring notes: piece AP (doctor.py, self-check)

Merge: `from .doctor import CATALOG as CAP, HANDLERS as HAP`, then update catalog CATALOG and _HANDLERS.
Info intent: `self_check {full?: bool}`. Not risky. No new packages, no new config keys.

## main.py
- Add `parser.add_argument("--doctor", action="store_true", help="check mic, model, voice, packages, config and exit")`
  and `parser.add_argument("--full", action="store_true", help="with --doctor: also test the AI key with one tiny call")`.
- Right after `args = parser.parse_args(argv)` (before VoiceIO / stt start, so a broken mic or model cannot crash it):
  ```python
  if args.doctor:
      from jarvis.actions import doctor
      return doctor.run_cli(["--full"] if args.full else [])
  ```
  `run_cli` prints the report, saves `doctor-report.txt` in the project folder, returns 1 if any problem, else 0.
- Optional: in packaging, add `doctor.bat` = `python main.py --doctor` + `pause` (packaging is shared; wiring thread decides).

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "check yourself", "run a self check", "self test", "diagnose yourself", "are you working properly", "check your setup", "run diagnostics" | self_check | {} |
| "full check", "full self check", "check yourself fully", "full diagnostics" | self_check | {full: true} |

## Notes
- Takes ~2-5 s: 1 s mic recording, TTS voice list, internet ping. Reply is a short summary, e.g.
  "8 OK, 1 problem: no microphone sound. Optional, not set up: ffmpeg missing. Details and fixes are in doctor-report.txt."
- Optional things (no AI key, KDE Connect, winget, ffmpeg, Outlook) are listed apart and are not "problems".
- The API key is only tested (one 1-token call) when `full` is true.
- Never creates files or folders except doctor-report.txt; never starts Outlook (registry check only).
- Mic test opens a second input stream; on Windows shared mode this works while Vosk listens. Test on real Windows.
- Tests: tests/test_doctor.py (21 tests, all fakes). Full suite: 1291 passed, 3 skipped on Linux.
- Suggest for the tray piece (AR): menu "Run self-check" can call `doctor.self_check({})` and show/speak the result.
