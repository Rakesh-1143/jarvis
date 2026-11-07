# Wiring notes: piece AZ (flashcards.py)

Merge: `from .flashcards import CATALOG as CAZ, HANDLERS as HAZ`, then update catalog CATALOG and _HANDLERS.
Also `from . import flashcards` in actions/__init__.py so main can do `getattr(actions, "flashcards", None)`.

Intents:
- `flashcard_add {deck?, front, back}` - not risky. Same front in the same deck updates the answer.
- `flashcard_quiz {deck?}` - starts quiz mode with the due cards (max 20, hardest first). No deck = all decks.
- `flashcard_status {deck?}` - info (`"info": True` in CATALOG). Add to brain UNTRUSTED_INFO (deck names and card text are user-typed).
- `deck_delete {deck}` - RISKY. In `_risky_text`: `if intent == "deck_delete": return flashcards.risky_text(args)`.
  The handler never deletes without `confirm=True` (returns "Are you sure ...?").

No new packages. No config needed. Optional config: `flashcards_file` (default `~/.jarvis/flashcards.json`).

## Spaced repetition
Leitner boxes 1-5. New card: box 1, due today. Right -> box+1 (max 5). Wrong / "I don't know" -> box 1.
Next due = today + 2^(box-1) days. "skip" shows the answer and does not move the card.

## Module API
- `flashcards.is_active() -> bool` - quiz running (ends by itself after 10 min with no answer).
- `flashcards.takes(text, intent) -> bool` - should this phrase go to the quiz? True for quiz words
  (stop/skip/repeat/I don't know/score), for the expected answer itself, and when `intent` is
  unknown / web_search / calculate / answer / quiz / cancel / confirm. False for clear commands (W1).
- `flashcards.process(text) -> str` - grade one answer, return what to say (next card or the final score). Never raises.
- `flashcards.stop() -> str` - end the quiz ("" if none). Call on exit is not needed (saved after each answer).
- `flashcards.parse(text) -> (intent, args) | None` - phrase rules (below), for nlu_features.

## main.py hook (shared file, wiring thread only)
In `handle()`, after the interpreter check and BEFORE the fun quiz block (same `skip_modes` rule):
```python
flashcards = None if skip_modes else getattr(actions, "flashcards", None)
if flashcards is not None and flashcards.is_active():
    fcmd = nlu.parse(text)
    if flashcards.takes(text, fcmd.intent):
        return flashcards.process(text)
    # any other clear command ("open chrome", "what time is it") runs normally; the quiz keeps waiting
```
Follow-up listening: main's normal follow-up mode (`follow_up_seconds`) already hears the answer without
the wake word. Optional: in `_next_phrase`, wait longer while `flashcards.is_active()` (people think before answering).
Optional: add `flashcards.is_active()` to the security check like dictation (locked = no quiz answers); not needed, answers do nothing risky.

## NLU phrases -> intent + args (call `flashcards.parse` BEFORE `fun.parse`)
| Say | Intent | Args |
|---|---|---|
| "add flashcard to Spanish hello means hola", "add a flashcard to Spanish deck: good night means buenas noches" | flashcard_add | {deck: "spanish", front, back} |
| "add flashcard the capital of France is Paris" (no deck) | flashcard_add | {deck: "general", ...} |
| "new card in biology: X answer Y" | flashcard_add | {deck: "biology", front: X, back: Y} |
| "quiz me on Spanish" (only if a Spanish deck exists), "quiz me on my Spanish flashcards", "study my flashcards", "practice Spanish flashcards", "study Spanish" (known deck) | flashcard_quiz | {deck?} |
| "how many flashcards are due", "how many cards are due in Spanish", "what decks do I have" | flashcard_status | {deck?} |
| "delete the Spanish deck", "delete my Spanish flashcards" | deck_delete | {deck: "spanish"} |

Notes:
- "quiz me", "quiz me on maths / gk / trivia" return None from `flashcards.parse`, so fun.py's quiz still gets them.
- Separators for add: "means", "answer (is)", "equals", "=", "translates to", else the LAST " is ".
- The deck after "to/in" is one word unless it is a known deck name with more words ("world capitals") or followed by "deck"/"flashcards".
- STT gives no colons; "to Spanish hello means hola" works without them.
- A card answer may hold choices with "/" or ";" ("hola / ola"); answer check ignores case, accents, "it's ..." and small slips (80% match, words of 4+ letters).
