# Jarvis — a free personal AI assistant

Talk to your computer like Tony Stark. Jarvis listens for **"Hey Jarvis"**, understands your voice,
runs commands, and answers with a free AI model that runs **on your own computer**.
No paid API keys are needed.

Built after studying popular open-source Jarvis projects on GitHub
(isair/jarvis, Priler/jarvis, sukeesh/Jarvis, kishanrajput23/Jarvis-Desktop-Voice-Assistant,
AlexandreSajus/JARVIS) and keeping their best ideas while using only free tools.

## Free stack

| Part | Tool | Cost |
|---|---|---|
| Wake word ("Hey Jarvis") | [openWakeWord](https://github.com/dscripka/openWakeWord) (fallback: Whisper hears "Jarvis") | Free, offline |
| Speech to text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Free, offline |
| Text to speech | pyttsx3 / your OS voice (SAPI, `say`, espeak) | Free, offline |
| AI brain | [Ollama](https://ollama.com) (e.g. Llama 3.2) or any OpenAI-compatible server (Groq free tier, LM Studio) | Free |
| Weather | Open-Meteo | Free, no key |
| Knowledge / search / news | Wikipedia, DuckDuckGo, Google News RSS | Free, no key |
| Memory | SQLite file on your computer | Free, offline |

## Features

- **Voice mode** with wake word, auto stop when you stop talking, and spoken replies.
- **Text mode** in the terminal, and a **web chat page** (with browser mic and voice).
- **AI chat** with memory of the conversation. The AI can **use Jarvis skills as tools**
  (for example "Should I take an umbrella in Paris?" makes it check the weather).
- **Skills** (work even without AI):
  - Time, date, greetings, jokes, coin flip / dice, calculator ("what is 15 percent of 300")
  - Weather ("weather in London"), Wikipedia ("tell me about Nikola Tesla"), web search, news headlines
  - Open apps ("open notepad") and websites ("open youtube"), Google search in browser
  - Play songs on YouTube ("play Believer")
  - System info (CPU, RAM, disk, battery), screenshots, volume control
  - Lock, sleep, restart, shutdown (restart/shutdown ask for confirmation)
  - Notes, to-do list, timers, reminders ("remind me to call mom in 10 minutes", "at 5 pm")
  - Personal memory ("remember that my birthday is May 5", "what do you know about me", "forget birthday")
- Works on **Windows, macOS and Linux**.

## Setup (about 10 minutes)

1. Install **Python 3.10 or 3.11** (3.11 recommended; the wake-word model does not support newer Python on Linux).
2. Install **Ollama** from <https://ollama.com>, then download a model:
   ```bash
   ollama pull llama3.2
   ```
   (Small PC? Use `llama3.2:1b`. Strong PC? Try `qwen2.5:7b`.)
3. Get Jarvis and install it:
   ```bash
   git clone https://github.com/<you>/jarvis.git
   cd jarvis
   python -m venv .venv
   # Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
   pip install -e ".[all,wakeword]"
   ```
   On Linux also install audio tools: `sudo apt install libportaudio2 espeak-ng`.
   If `wakeword` fails to install, just use `pip install -e ".[all]"`; Jarvis then listens for the word "Jarvis" instead.
4. (Optional) Copy `config.example.toml` to `config.toml` and change your name, city, AI model, etc.

## Run

```bash
jarvis            # voice mode: say "Hey Jarvis", then your command
jarvis --text     # type in the terminal
jarvis --web      # open http://127.0.0.1:5050 in your browser
jarvis --once "what's the weather"
```

The first voice run downloads the speech model (about 150 MB). After that, everything works offline
except internet skills (weather, news, search).

### No strong PC? Use a free cloud AI

In `config.toml`:

```toml
[llm]
provider = "openai"
base_url = "https://api.groq.com/openai/v1"
model = "llama-3.1-8b-instant"
api_key_env = "GROQ_API_KEY"
```

Get a free key at <https://console.groq.com> and set the `GROQ_API_KEY` environment variable.
Set `provider = "none"` to use only built-in skills.

## Add your own skill

Create a file in `jarvis/skills/`, for example `jarvis/skills/my_skills.py`:

```python
from . import skill

@skill("greet_friend", "Say hello to a friend by name.",
       patterns=[r"say hi to (?P<name>.+)"],
       params={"name": "Friend's name"}, required=["name"])
def greet_friend(ctx, name):
    return f"Hello {name}, nice to meet you!"
```

It is loaded automatically. The regex makes it work instantly, and the description lets the AI call it too.

## Project layout

```
jarvis/
  __main__.py     command line: voice, text, web modes
  assistant.py    routes text -> skill or AI
  brain.py        Ollama / OpenAI-compatible client with tool calling
  memory.py       SQLite: facts, chat history, notes, to-dos, reminders
  skills/         basic, web, system, productivity skills
  speech/         microphone, wake word, speech-to-text, text-to-speech
  web/            browser chat page
tests/            pytest tests (no internet or microphone needed)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Privacy

Voice, AI (with Ollama) and memory stay on your computer. Only internet skills send your query to
the free service they use (Open-Meteo, Wikipedia, DuckDuckGo, Google News, YouTube).

## License

MIT
