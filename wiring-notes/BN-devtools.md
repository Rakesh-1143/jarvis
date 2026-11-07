# Wiring notes: piece BN (devtools.py)

Files: `jarvis/actions/devtools.py`, `tests/test_devtools.py` (91 tests; uses a real temp git repo, skips git tests if git is missing).
Merge: add `devtools` to the module loop in `actions/__init__.py` (CATALOG + HANDLERS).
No new packages (subprocess, shlex, shutil, difflib only). Uses `winutil.NO_WINDOW` / `IS_WINDOWS`.
Duplicate check: apps.py only opens VS Code as an app; shortcuts.py `run:` runs one shell command after a yes.
No git, test runner or dev-server control anywhere.

## Intent
| Intent | Args | Kind |
|---|---|---|
| dev | {action: open\|git_status\|git_pull\|git_log\|git_diff\|git_branch\|git_commit\|git_push\|test\|run\|stop\|output, project?, message?} | git_commit / git_push **risky**; status/log/diff/branch/test/output are info |

- `project` is optional: the only project, else the last one used, else "Which project?". Spoken names are matched loosely (case, spaces, "project/repo" word, close spelling).
- Git runs only the fixed lists in `devtools._GIT` (no shell). Commit message is one argv item (tested with `; rm -rf /` and `--amend`).
- pull = `git pull --ff-only`. `GIT_TERMINAL_PROMPT=0`: git never waits for a password (says "sign in once in a terminal").
- `test` / `run` run only the commands the user wrote in config, split into a list (no `shell=True`). `npm`, `code` are found via `shutil.which` (handles .cmd on Windows).
- `run` starts a background dev server (output appended to the devtools log). `stop` kills it (Windows: `taskkill /T /F` for the whole tree). `atexit` stops all servers when Jarvis exits, so no main.py hook is needed.
- Full output of every command goes to `~/.jarvis/devtools.log`; "show the test output" / action `output` returns the last 1500 chars.
- The handler itself also refuses commit/push without `confirm: True` (same as shortcuts.py), so it is safe even if `_risky_text` is missed.

## Risky (actions/__init__.py)
```python
# _risky_text
if intent == "dev" and devtools.needs_confirm(args):
    return devtools.risky_text(args)  # 'commit all changes in jarvis with the message "fix bug"' / 'push jarvis to the remote'
# _do_risky: add "dev" to the tuple that calls _HANDLERS[intent](args)
```

## Brain
- `UNTRUSTED_INFO += dev` (git log, test output and commit subjects are text Jarvis doesn't control).
- `GUARDED_ACTIONS += dev` (AI must not commit / push / start servers after reading that text; the user can still say it).

## main.py hook
None (atexit inside the module stops dev servers).

## Config (optional; without it every command says how to add a project)
```yaml
devtools:
  projects:
    jarvis: {path: "C:/code/jarvis", test: "pytest -q", run: "python main.py --text"}
    website: {path: "~/code/site", test: "npm test", run: "npm run dev"}
  log_file: "~/.jarvis/devtools.log"
  timeout: 120          # seconds for git and test commands (5-3600)
```
A top-level `projects:` block is also read if `devtools.projects` is missing. A project can be a plain path string.
Add `"devtools": {"projects": {}, "log_file": "~/.jarvis/devtools.log", "timeout": 120}` to `config.DEFAULTS`
and a commented example to config.yaml.

## NLU
Use `devtools.parse(text) -> ("dev", args) | None` in nlu_features (tested: 27 phrases + 12 non-matches).
**Order matters:** call it BEFORE the open_app / close_app / press_keys rules. Today the old rules turn
"open jarvis project in vs code" into open_app, "run the tests" / "start the dev server" into open_app,
"stop the dev server" into close_app, and "push my changes" into press_keys (checked with nlu.parse).

| Say | args |
|---|---|
| "open jarvis project in VS Code", "open my project in vs code" | {action: open, project?} |
| "git status (of/for X)", "what's the git status" | git_status |
| "pull latest", "pull the latest changes for X", "git pull" | git_pull |
| "show the last commits", "git log" | git_log |
| "git diff", "show me the diff" | git_diff |
| "which branch am I on", "git branch" | git_branch |
| "commit with message X", "commit all my changes in Y with the message X", "git commit saying X" | git_commit {message} |
| "push my changes (to github)", "git push" | git_push |
| "run the tests (for X)", "run tests" | test |
| "start the dev server (for X)" | run |
| "stop the dev server" | stop |
| "show the test output", "which tests failed" | output |

Plain "commit", "push", "stop", "open vs code", "pull up my notes" do NOT match (left to other rules).
Commit messages come from speech, so they are lower case.
