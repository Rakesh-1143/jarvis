"""Hidden launcher used by auto-start and install.bat (runs with pythonw.exe, no window).

Starts Jarvis in voice mode. If it crashes (for example the mic is not ready yet
right after login), it writes the error to jarvis-crash.log and tries again.
"""
import datetime
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_TRIES = 5
WAIT_SECONDS = 15

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def log_crash() -> None:
    with open(ROOT / "jarvis-crash.log", "a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
        f.write(traceback.format_exc())


def start() -> None:
    for attempt in range(MAX_TRIES):
        try:
            import main  # inside try: a broken install (missing package) is written to the crash log too

            main.main([])
            return  # user said "goodbye"
        except Exception:
            log_crash()
            if attempt < MAX_TRIES - 1:
                time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    start()
