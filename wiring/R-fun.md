# Piece R: fun.py — wiring notes

Files: `jarvis/actions/fun.py`, `tests/test_fun.py` (41 tests pass). No new requirements. No config keys.

## actions/__init__.py + catalog.py
- Merge `fun.CATALOG` and `fun.HANDLERS` (intents `random_pick`, `quiz`).
- Nothing is risky. Neither intent is "info" (replies are spoken directly).

## nlu.py
- Call `fun.parse(text)` with the other early feature rules. It returns `(intent, args)` or `None`.
  Wrap: `r = fun.parse(text); if r: return Command(*r)`.
- Put it AFTER the timer/volume rules (it only matches fun phrases, but keep core rules first).

Phrases it handles:
- "flip a coin", "heads or tails", "toss three coins"
- "roll a dice", "roll", "roll two dice", "roll a 20 sided die", "roll a d12", "roll 3d8"
- "random number between 5 and 50", "pick a number up to 10", "random number"
- "pick one: pizza or pasta", "help me decide between tea, coffee and juice", "should I watch a movie or read a book"
- "rock paper scissors", "I choose paper"
- "quiz me", "ask me a question", "start a maths quiz", "gk quiz", "trivia"
- "stop the quiz", "what's my score"; during a quiz also "skip", "pass", "I don't know"

## main.py (quiz answers)
- After a quiz reply, the user's next words are the answer. In the loop: if `fun.quiz_pending()` and
  nlu gave `unknown` (or anything other than `quiz`), run `Command("quiz", {"action": "answer", "answer": text})` instead.
- Turn on follow-up listening after a quiz reply so the user need not say "Jarvis" again.
- A question times out after 120 s (`fun.QUIZ_TIMEOUT`); then `quiz_pending()` is False.
