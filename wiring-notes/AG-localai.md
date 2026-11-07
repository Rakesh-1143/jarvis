# Wiring notes: piece AG (localai.py)

Merge: `from .localai import CATALOG as CAG, HANDLERS as HAG`, then update catalog CATALOG and _HANDLERS.
Intents:
- `ai_mode {mode: local|cloud|auto}` - not info, not risky.
- `local_ai_status {}` - info.
No new packages (stdlib urllib). User must install Ollama (ollama.com) and run `ollama pull llama3.2:3b` once.

Optional config (defaults work without it). Add `"local_ai": {}` to config.py DEFAULTS and this to config.yaml:
```yaml
local_ai:
  url: http://localhost:11434
  model: llama3.2:3b     # any pulled Ollama model; "llama3.2" matches "llama3.2:latest"
  mode: auto             # auto = Claude first, local when Claude has no key or is offline; local; cloud
  timeout: 60            # seconds per answer
  history_turns: 4       # follow-up memory (kept in RAM only)
```

## Module API
- `localai.available() -> bool` - server up AND model pulled. Cached 10 s (cheap to call per question).
- `localai.ask(text, on_sentence=None) -> str` - never raises. With `on_sentence`, it ALWAYS speaks
  something (sentences, or one short error line), so the answer Command should get `spoken: True`.
- `localai.use_local(claude_ready: bool) -> bool` - the one decision helper:
  mode cloud -> False; mode auto -> `not claude_ready and available()`; mode local -> `available()`.
- `get_mode()`, `set_mode(mode)`, `status(force=False)`, `clear_history()`.

## brain.py hooks (shared file, wiring thread only)
1. Top of `Brain.ask`, before `if not self.available:`
   ```python
   from jarvis.actions import localai
   if localai.use_local(self.available):
       ans = localai.ask(text, on_sentence=on_sentence if self.ai["stream"] else None)
       return [Command("answer", {"text": ans, "spoken": bool(on_sentence and self.ai["stream"])})]
   ```
   This covers "no key" and "user said use local AI".
2. In the `except Exception as e:` of `Brain.ask`: if `e` is `anthropic.APIConnectionError` / `APITimeoutError`
   (offline), `not (speaker and speaker.spoke)` (nothing said yet), and `localai.use_local(False)`,
   return the same local answer as in step 1 instead of "I can't reach the internet right now."
   Skip this when mode is `cloud` (use_local handles that).
3. Local answers have no tools: they never return action Commands, so no guard changes are needed.
   Do NOT add `local_ai_status` to UNTRUSTED_INFO (Jarvis writes its text).

## main.py hooks
- Line ~302: questions only go to the brain when `brain.available`. With no key, change those checks to
  `ai_ready = brain.available or localai.use_local(brain.available)` so "what is ..." questions reach the local AI.
  (`unknown` already goes to `brain.ask`, so step 1 above catches it.)
- Startup log: if `not brain.available and localai.available()`, log "Claude is off, using local AI".
  Do not ping Ollama in a tight loop; `available()` is cached.

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "use local AI", "use offline AI", "switch to local AI", "use ollama" | ai_mode | {mode: "local"} |
| "use cloud AI", "use Claude", "switch to online AI" | ai_mode | {mode: "cloud"} |
| "auto AI mode", "use automatic AI", "AI mode auto" | ai_mode | {mode: "auto"} |
| "is local AI ready", "local AI status", "is ollama running", "is offline AI working" | local_ai_status | {} |

Notes:
- The handler also accepts mode words offline/ollama -> local, claude/online -> cloud, automatic -> auto, so rules can pass them raw.
- Mode set by voice lasts until Jarvis restarts (then config `mode` is used). Not saved to disk on purpose.
- Put these rules before generic "use ..." / "switch to ..." rules (e.g. "switch to chrome").
