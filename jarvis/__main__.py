"""Run Jarvis.

  python -m jarvis            # voice mode (falls back to text if voice packages are missing)
  python -m jarvis --text     # type to Jarvis in the terminal
  python -m jarvis --web      # browser chat page at http://127.0.0.1:5050
  python -m jarvis --once "what time is it"
"""

from __future__ import annotations

import argparse
import sys

from .assistant import Assistant
from .config import load_config


def run_text(assistant: Assistant) -> None:
    name = assistant.name
    assistant.ctx.notify = lambda m: print(f"\n{name}: {m}\nYou: ", end="", flush=True)
    assistant.start_background()
    print(f"{name} is online. Type 'help' for commands, 'exit' to quit.")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if assistant.is_exit(text):
            print(f"{name}: Goodbye.")
            break
        print(f"{name}: {assistant.handle(text)}")
    assistant.stop()


def run_voice(assistant: Assistant) -> None:
    from .speech.audio import Microphone
    from .speech.stt import Transcriber
    from .speech.tts import Speaker
    from .speech.wakeword import OpenWakeWord, TextWakeWord

    v = assistant.config["voice"]
    name = assistant.name
    speaker = Speaker(v["tts_engine"], v["tts_rate"], on_print=lambda t: print(f"{name}: {t}"))
    print("Loading speech model (first run downloads it)...")
    stt = Transcriber(v["stt_model"], v["language"])
    mic = Microphone()

    wake = None
    if v["wake_engine"] == "openwakeword":
        try:
            wake = OpenWakeWord(v["wake_threshold"])
            hint = 'Say "Hey Jarvis".'
        except Exception as e:
            print(f"openWakeWord not available ({e}); using text wake word instead.")
    if wake is None:
        wake = TextWakeWord(stt, v["wake_word"])
        hint = f'Say "{v["wake_word"].title()}" followed by your command.'

    def notify(msg: str) -> None:
        speaker.say(msg, wait=False)

    assistant.ctx.notify = notify
    assistant.start_background()
    speaker.say(f"{name} online. {hint}")
    mic.flush()

    try:
        while True:
            print("(waiting for wake word...)")
            text = wake.wait(mic)
            if not text:
                speaker.say("Yes?")
                mic.flush()
                print("(listening...)")
                audio = mic.record_command(v["silence_seconds"])
                if audio is None:
                    continue
                text = stt.transcribe(audio)
            if not text:
                continue
            print(f"You: {text}")
            if assistant.is_exit(text):
                speaker.say("Goodbye.")
                break
            speaker.say(assistant.handle(text))
            mic.flush()  # don't hear ourselves
    except KeyboardInterrupt:
        print()
    finally:
        assistant.stop()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jarvis", description="Free personal AI assistant.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--text", action="store_true", help="type instead of talk")
    g.add_argument("--web", action="store_true", help="start the browser chat page")
    g.add_argument("--once", metavar="TEXT", help="answer one command and exit")
    p.add_argument("--config", help="path to config.toml")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    assistant = Assistant(cfg)

    if args.once:
        print(assistant.handle(args.once))
    elif args.web:
        from .web.server import serve
        serve(assistant, cfg["web"]["host"], int(cfg["web"]["port"]))
    elif args.text:
        run_text(assistant)
    else:
        try:
            run_voice(assistant)
        except (ImportError, OSError) as e:
            print(f"Voice packages or microphone missing ({e}).\n"
                  "Install them with: pip install -e .[voice]\nStarting text mode.\n", file=sys.stderr)
            run_text(assistant)
        except Exception as e:  # e.g. the speech model could not be downloaded
            print(f"Voice mode failed to start: {e}\nStarting text mode.\n", file=sys.stderr)
            run_text(assistant)


if __name__ == "__main__":
    main()
