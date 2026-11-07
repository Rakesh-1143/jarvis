# Wiring notes: piece BE (recipes.py)

Files: `jarvis/actions/recipes.py`, `tests/test_recipes.py` (83 tests, network faked).
Merge: `from .recipes import CATALOG as CBE, HANDLERS as HBE`, then update catalog CATALOG and _HANDLERS.
No new packages (urllib, json, re, difflib). Nothing Windows-specific. No config needed.
Data: TheMealDB free API (`https://www.themealdb.com/api/json/v1/1/`: search.php, filter.php, lookup.php, random.php).
Not tested live (sandbox has no net). Mostly western/international dishes; many Indian dishes are missing,
so "cook paneer butter masala" may fall back to the closest name ("I couldn't find X exactly. The closest is Y").
Duplicate check: no recipe/cook code anywhere in jarvis/ or main.py; intent names `recipe`/`cook` are unused.

## Intents
| Intent | Args | Kind |
|---|---|---|
| recipe | {action: find\|random\|by_ingredients, query?} | info |
| cook | {action: start\|next\|previous\|repeat\|ingredients\|stop\|timer\|status\|goto, name?, step?} | action |

- `cook start` with no name (or "it"/"this") uses the last recipe found by `recipe`.
- `cook timer` calls `timers.timer({"seconds", "label": "step N"})` for the current step's time.
  Ranges use the lower number ("5-7 minutes" -> 5 min) so the user checks early.

## Risky
None.

## Brain
- `UNTRUSTED_INFO += recipe, cook` (both read back web text from TheMealDB: names, ingredients, steps).
  If UNTRUSTED_INFO is info-only, at least add `recipe`.
- No GUARDED_ACTIONS needed; the AI may start cook mode.

## main.py hook (cook mode in loop)
In `handle()`, after the quiz block and before routines/shortcuts (needs `skip_modes` like quiz):
```python
recipes = None if skip_modes else getattr(actions, "recipes", None)
if recipes is not None and recipes.is_active():
    hit = recipes.match_cook(text)          # ("cook", {...}) or None
    if hit is not None:
        return _run_one(Command(*hit), io, cfg, actions, nlu, brain, depth)
    # anything else ("what time is it", "set a timer for 5 minutes") runs normally; cook mode stays on
```
(`Command` from jarvis.nlu, or `type(nlu.parse(text))(*hit)` like the quiz block.)
- `match_cook` only catches exact short phrases: next / next step / continue / done, go back / previous,
  repeat / say that again, ingredients / what do I need, start a timer, which step am I on,
  go to step 3 / step five, stop cooking. "yes" means "start the timer" only right after a step that
  offered one. "next song", "stop", "set a timer for 5 minutes" are NOT caught.
- Optional: on exit nothing to clean (no threads, no files).
- Optional nice-to-have: if the wake word is needed between steps, cook mode works best with
  continuous listening; no change made here.

## NLU
Use `recipes.parse(text) -> (intent, args) | None` in nlu_features (outside cook mode).
| Say | Intent | Args |
|---|---|---|
| "cook paneer butter masala", "let's cook chicken curry", "bake a chocolate cake", "walk me through making biryani", "cook mode for pasta" | cook | {action: start, name} |
| "start cook mode", "cook it", "let's cook this" | cook | {action: start} |
| "recipe for butter chicken", "find me a recipe for dal", "show me the lasagne recipe", "how do I cook rice" | recipe | {action: find, query} |
| "random recipe", "suggest something to cook", "what should I cook tonight" | recipe | {action: random} |
| "what can I make with eggs and tomatoes", "recipes with chicken" | recipe | {action: by_ingredients, query} |

Notes:
- Returns None for "cook", "cook something", "open recipe", "delete the recipe", "how do I make a folder".
- "how do I make X" is only caught with the word "recipe" at the end (avoids "make a folder").
- Place after dictation/teach/corrections checks. Searched nlu.py, nlu_control.py, nlu_features.py:
  no rule uses "cook", "bake" or "recipe".
