# Wiring notes: piece N (lookup.py)

Merge: `from .lookup import CATALOG as CN, HANDLERS as HN`, then update catalog CATALOG and _HANDLERS.
Info intents: define, wikipedia, synonyms. `spell` is spoken directly. No risky intents. No main.py hooks.
No new packages (urllib + json only). Optional config: `lookup: {wiki_lang: "en", sentences: 2}` (defaults work without it).

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "define serendipity", "what does serendipity mean", "meaning of serendipity", "what is the meaning of X" | define | {word: "serendipity"} |
| "wikipedia Albert Einstein", "search wikipedia for Paris", "tell me about Paris from wikipedia", "look up X on wikipedia" | wikipedia | {topic: "Albert Einstein"} |
| "how do you spell necessary", "spell necessary", "spelling of necessary" | spell | {word: "necessary"} |
| "synonyms for happy", "another word for happy", "what's a synonym of happy" | synonyms | {word: "happy"} |
| "opposite of happy", "antonyms of happy", "antonym for happy" | synonyms | {word: "happy", kind: "antonyms"} |

Notes:
- Do NOT route plain "who is X" / "what is X" to wikipedia in rules: leave those to the AI brain (it can call the
  `wikipedia` tool). With no Claude key, main may fall back to `wikipedia {topic: X}` for "who is X".
- "what does X mean" must be matched before any generic "what is" rule.
- `define`/`spell`/`synonyms` clean the word themselves ("the word 'hello'" -> hello).
- Live APIs were NOT tested (sandbox blocks them); response formats coded from the public API docs. Test on Windows.
