# Piece P: expenses (wiring notes)

Files: `jarvis/actions/expenses.py`, `tests/test_expenses.py` (12 pass).

## actions/__init__.py + catalog.py
- `from . import expenses`; merge `expenses.HANDLERS` into `_HANDLERS` and `expenses.CATALOG` into `CATALOG`.
- Nothing risky. `expense_report` is `"info": True`.
- main.py: no hooks.

## Intents and args
- `expense_add {amount, category?, note?}`: amount can be a number or text ("250", "2.5k", "two hundred and fifty"). If no category, it is guessed from the note (food, travel, shopping, bills, other). A category word like "lunch" maps to food and becomes the note.
- `expense_report {period?, category?}`: period = today | yesterday | week | last week | month | last month | year | all (default month; "this week" also ok).
- `expense_undo {}`: deletes the last added row.

## NLU phrases (suggested regex, run before generic "add"/"how much" rules)
- `^(?:i\s+)?(?:spent|paid)\s+(?P<amount>.+?)\s+(?:on|for)\s+(?P<note>.+)$` -> expense_add {amount, note}
- `^(?:add|log|record)\s+(?:an?\s+)?expense(?:\s+of)?\s+(?P<amount>.+?)(?:\s+(?:on|for)\s+(?P<note>.+))?$` -> expense_add
- `^how much (?:did i|have i) (?:spend|spent)(?:\s+on\s+(?P<category>\w+))?\s*(?P<period>today|yesterday|this week|last week|this month|last month|this year)?$` -> expense_report
- `^how much on (?P<category>\w+)\s*(?P<period>today|this week|this month|...)?$` -> expense_report
- `^(?:delete|remove|undo) (?:the\s+)?last expense$` -> expense_undo

Note: amount text from STT ("two hundred fifty") is fine; the module parses it.

## config.yaml
```yaml
expenses_file: "~/Documents/Jarvis expenses.csv"
currency: "₹"
```
