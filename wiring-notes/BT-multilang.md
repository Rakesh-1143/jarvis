# Wiring notes: piece BT (multilang.py) - commands in Hindi and Telugu

Files: `jarvis/actions/multilang.py`, `tests/test_multilang.py` (50 tests, Linux fakes).
Merge: `from .multilang import CATALOG as CBT, HANDLERS as HBT` (or `from . import multilang`), then update catalog CATALOG and _HANDLERS.

## Packages
- None required. Hindi uses Vosk (already installed) + a second model `vosk-model-small-hi-0.22` (~42 MB), downloaded once with `stt._download_model` into `models/`.
- Optional, add to requirements.txt as commented lines:
  - `# faster-whisper>=1.0  # multilang.py: Telugu commands (model "small", ~500 MB, CPU)`
  - `deep-translator` is already optional for interpreter.py; multilang reuses `interpreter._google_translate`.

## Config (config.yaml, all optional)
```yaml
stt:
  languages: [en]          # default languages at first start, e.g. [en, hi]. Voice choice is saved to multilang.file
multilang:
  file: ~/.jarvis/multilang.json
  hindi_model_path: models/vosk-model-small-hi-0.22
  whisper_model: small     # faster-whisper size for Telugu
  min_confidence: 0.6      # English below this -> also try Hindi/Telugu models
```

## Intent
| Intent | Args | Kind |
|---|---|---|
| `language` | `{action: on\|off\|status\|reply, lang?: english\|hindi\|telugu}` | normal (own text only; not in UNTRUSTED_INFO, not risky) |

## NLU
Call `multilang.parse(t)` in nlu_features **before** `_interpreter` and before the generic "switch to ..." rules.
It returns `("language", args)` or None. It only matches English/Hindi/Telugu, so "switch to Spanish" (interpreter in-mode switch) and "switch to ollama/next tab" are untouched.

| Say | Args |
|---|---|
| "understand Hindi", "commands in Hindi too", "switch to Hindi", "I will speak Telugu", "hindi mein suno" | `{action: on, lang}` |
| "turn off Hindi", "stop Telugu" | `{action: off, lang}` |
| "English only", "only English" | `{action: off}` |
| "reply in Hindi", "speak in Hindi too", "answer in English" | `{action: reply, lang}` |
| "which languages do you understand", "language status" | `{action: status}` |

Note: while translate mode (interpreter.py) is on, main sends every phrase to `interpreter.process` first, so these phrases only work when translate mode is off. That is fine.

## main.py / stt hooks (do NOT change stt.py itself)
1. Listening - in `VoiceIO.listen` (main.py ~line 89):
   ```python
   def listen(self, timeout=None):
       _tray_state("listening")
       t = timeout or self.cfg["listen_timeout"]
       from jarvis.actions import multilang
       if multilang.is_active():
           return multilang.listen(timeout=t)   # records, picks the language, returns English text
       return self.stt.listen(timeout=t)
   ```
   This covers the main command, follow-ups and yes/no answers ("haan" -> "yes", "nahi" -> "no").
   The wake word stays English Vosk ("Jarvis" is the same in all three languages).
   PIN entry (`security.verify(io.listen())`): Hindi digits may come back as words; if that is a problem, call `self.stt.listen` directly for the PIN.
2. Replies - in `VoiceIO.say` (only voice mode, not TextIO), before the normal tts call:
   ```python
   from jarvis.actions import multilang
   if multilang.reply_language() != "en" and multilang.say_reply(text):
       return   # already spoken in Hindi/Telugu (text still recorded by _record above)
   ```
   `say_reply` returns False (speak English as normal) when no Windows voice for that language exists or translation fails.
3. `--text` mode (TextIO): optional. Typed Hinglish can be passed through `multilang.to_english(text, "hi")` when `multilang.is_active()` and the text is not ASCII-English; not needed for the first version.
4. Doctor (optional): if `"hi" in multilang.languages()` check `multilang._hindi_model_path().exists()`; if `"te"` check `multilang.has_whisper()`.

## How it works
- `record()` uses the English Vosk recognizer only to find the end of the phrase, and keeps the raw audio.
- `recognize(audio)`: English first; if empty or mean word confidence < 0.6, the Hindi Vosk model and/or Telugu faster-whisper run on the same audio; the most confident text wins.
- `to_english(text, lang)`: offline phrasebook first (common commands in Devanagari, Telugu script and Hinglish: kholo/खोलो/తెరువు = open, band karo = close, badhao = up, kam karo = down, bajao/chalao = play, batao = what is, le lo = take ...), then Claude (if key), then Google free endpoint. Names/numbers kept. If all fail, the original text goes to nlu (which then says it did not understand).
- Telugu when faster-whisper is missing: "Telugu needs faster-whisper. Install it with: pip install faster-whisper."

## Not tested on real Windows
Sandbox has no mic, models or network. Hand test: "understand Hindi" (wait for the 42 MB download) -> "Jarvis" -> "क्रोम खोलो" / "Chrome kholo" -> Chrome opens; "awaaz badhao" -> volume up; "English only".
Hindi Vosk small model quality is modest; tune `multilang.min_confidence` if English commands are wrongly sent to Hindi (lower it) or Hindi is missed (raise it).
