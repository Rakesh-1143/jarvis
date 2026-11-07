"""Developer tools by voice (piece BN): VS Code, a fixed set of git commands, project tests and dev server.

Says: "open jarvis project in VS Code", "git status of jarvis", "pull latest", "show the last commits",
"git diff", "which branch am I on", "commit with message fix login bug" (asks yes),
"push my changes" (asks yes), "run the tests", "start the dev server", "stop the dev server",
"show the test output".

config.yaml:
    devtools:
      projects:                       # name -> folder + optional commands written by YOU
        jarvis: {path: "C:/code/jarvis", test: "pytest -q", run: "python main.py --text"}
        website: {path: "~/code/site", test: "npm test", run: "npm run dev"}
      log_file: "~/.jarvis/devtools.log"   # full output of every command
      timeout: 120                         # seconds for git / test commands
(A top-level `projects:` block is read too, if `devtools.projects` is missing.)

Safety:
- No free shell. Git runs only the fixed argument lists in _GIT. The commit message is one argument, never parsed.
- Only `test` / `run` commands the user wrote in config.yaml run (like shortcuts), split into a list, no shell=True.
- commit and push are risky: they only run with args["confirm"] is True (actions/__init__ asks yes first).
- pull is `git pull --ff-only` (never makes a merge commit). GIT_TERMINAL_PROMPT=0 so git never waits on a password.

Public:
    parse(text) -> (intent, args) | None    optional phrase helper for nlu_features
    needs_confirm(args) / risky_text(args)  for actions/__init__._risky_text
    last_output() -> str                    full text of the last command (also action "output")
    stop_all()                              kills dev servers (also registered with atexit)
    CATALOG, HANDLERS                       merged by actions/__init__.py
"""
from __future__ import annotations

import atexit
import datetime as dt
import difflib
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading

from ..winutil import IS_WINDOWS, NO_WINDOW

log = logging.getLogger("jarvis.devtools")

DEFAULT_LOG = "~/.jarvis/devtools.log"
DEFAULT_TIMEOUT = 120
MAX_LOG_BYTES = 1_000_000       # devtools.log is renamed to .old above this
MAX_KEEP = 20_000               # characters of the last output kept for "show the output"
MAX_MESSAGE = 200               # commit message length

PROJECTS: dict | None = None    # tests set this; None = read config each time
LOG_FILE = ""                   # empty = config or DEFAULT_LOG

ACTIONS = ("open", "git_status", "git_pull", "git_log", "git_diff", "git_branch", "git_commit", "git_push",
           "test", "run", "stop", "output")
RISKY = ("git_commit", "git_push")

# The only git commands Jarvis ever runs. {message} is filled as ONE argument for commit.
_GIT = {
    "git_status": ["git", "status", "--porcelain=v1", "--branch"],
    "git_pull": ["git", "pull", "--ff-only"],
    "git_log": ["git", "log", "-5", "--pretty=format:%s (%cr)"],
    "git_diff": ["git", "diff", "--stat"],
    "git_branch": ["git", "branch", "--show-current"],
    "git_commit": ["git", "commit", "-a", "-m", "{message}"],
    "git_push": ["git", "push"],
}

_lock = threading.Lock()
_servers: dict[str, subprocess.Popen] = {}   # project name -> running dev server
_last = {"title": "", "text": ""}
_last_project = {"name": ""}


# ---------- config ----------
def _cfg() -> dict:
    try:
        from ..config import load_config

        c = load_config() or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _norm(name) -> str:
    t = re.sub(r"[^\w\s.-]", " ", str(name or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def projects() -> dict[str, dict]:
    """{name: {"path", "test"?, "run"?}} from config; bad entries are skipped. A plain string is a path."""
    raw = PROJECTS
    if raw is None:
        c = _cfg()
        dev = c.get("devtools") if isinstance(c.get("devtools"), dict) else {}
        raw = dev.get("projects") or c.get("projects") or {}
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in raw.items():
        if isinstance(value, str):
            value = {"path": value}
        if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not value["path"].strip():
            continue
        entry = {"path": value["path"].strip()}
        for key in ("test", "run"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                entry[key] = v.strip()
            elif isinstance(v, list) and v and all(isinstance(x, (str, int, float)) for x in v):
                entry[key] = [str(x) for x in v]
        if _norm(name):
            out[_norm(name)] = entry
    return out


def _timeout() -> int:
    dev = _cfg().get("devtools")
    try:
        t = int((dev or {}).get("timeout") or DEFAULT_TIMEOUT)
        return max(5, min(t, 3600))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_TIMEOUT


def _log_path() -> str:
    path = LOG_FILE
    if not path:
        dev = _cfg().get("devtools")
        path = (dev.get("log_file") if isinstance(dev, dict) else "") or DEFAULT_LOG
    return os.path.expanduser(os.path.expandvars(path))


def _names(projs: dict) -> str:
    return ", ".join(sorted(projs)) if projs else "none yet"


_NO_PROJECTS = ("You have no projects set up. Add them in config.yaml under devtools: projects:, "
                "for example  jarvis: {path: \"C:/code/jarvis\", test: \"pytest -q\"}.")


def resolve(name=None) -> tuple[str | None, str]:
    """(project name, "") or (None, reason to speak). No name: the only project, else the last one used."""
    projs = projects()
    if not projs:
        return None, _NO_PROJECTS
    said = _norm(name)
    said = re.sub(r"^(?:the|my)\s+", "", said)
    said = re.sub(r"\s+(?:project|repo|repository|folder|code)$", "", said).strip()
    if said in ("", "my", "this", "it", "project", "the project", "current"):
        if len(projs) == 1:
            return next(iter(projs)), ""
        if _last_project["name"] in projs:
            return _last_project["name"], ""
        return None, f"Which project? You have: {_names(projs)}."
    if said in projs:
        return said, ""
    squash = {k.replace(" ", "").replace("-", "").replace("_", ""): k for k in projs}
    key = said.replace(" ", "").replace("-", "").replace("_", "")
    if key in squash:
        return squash[key], ""
    close = difflib.get_close_matches(said, list(projs), n=1, cutoff=0.75)
    if close:
        return close[0], ""
    inside = [k for k in projs if said in k or k in said]
    if len(inside) == 1:
        return inside[0], ""
    return None, f"I don't know a project called {said}. Your projects: {_names(projs)}."


def _folder(name: str) -> tuple[str | None, str]:
    path = os.path.expanduser(os.path.expandvars(projects()[name]["path"]))
    if not os.path.isdir(path):
        return None, f"The folder for {name} doesn't exist: {path}."
    return path, ""


# ---------- running ----------
def _argv(command) -> list[str]:
    """Config command -> argument list (no shell). Windows paths keep their backslashes."""
    if isinstance(command, list):
        parts = list(command)
    else:
        parts = shlex.split(command, posix=not IS_WINDOWS)
        if IS_WINDOWS:
            parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    if parts:
        # npm / code / yarn are .cmd files on Windows: CreateProcess only finds them with the full path
        parts[0] = shutil.which(parts[0]) or parts[0]
    return parts


def _env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"   # never hang waiting for a password
    env.setdefault("GIT_PAGER", "cat")
    return env


def _write_log(title: str, text: str) -> None:
    _last["title"], _last["text"] = title, text[-MAX_KEEP:]
    path = _log_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} {title} ===\n{text}\n")
    except OSError:
        log.warning("could not write %s", path)


def _run(argv: list[str], cwd: str, title: str, timeout: int | None = None) -> tuple[int | None, str]:
    """Run and wait. (exit code, output). Code None = could not start or timed out; output says why."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=timeout or _timeout(), env=_env(),
                           creationflags=NO_WINDOW)
    except FileNotFoundError:
        return None, f"not found: {os.path.basename(argv[0]) if argv else '?'}"
    except subprocess.TimeoutExpired:
        _write_log(title, "(timed out)")
        return None, f"timed out after {timeout or _timeout()} seconds"
    except OSError as exc:
        return None, str(exc)
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    _write_log(f"{title} (exit {p.returncode})", out.strip())
    return p.returncode, out


def _first_line(text: str, limit: int = 120) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith(("hint:", "To ")):
            return line[:limit]
    return ""


# ---------- summaries (short, for speaking) ----------
def _say_status(out: str) -> str:
    branch, extra, changed, new, conflicts = "", "", 0, 0, 0
    for line in out.splitlines():
        if line.startswith("## "):
            head = line[3:]
            branch = re.split(r"\.\.\.|\s", head, maxsplit=1)[0]
            if branch.startswith("No commits yet on "):
                branch = head.split()[-1]
            ahead = re.search(r"ahead (\d+)", head)
            behind = re.search(r"behind (\d+)", head)
            bits = []
            if ahead:
                bits.append(f"{ahead.group(1)} commit{'s' * (ahead.group(1) != '1')} ahead")
            if behind:
                bits.append(f"{behind.group(1)} behind")
            extra = ", ".join(bits)
        elif line.startswith("??"):
            new += 1
        elif line[:2] in ("UU", "AA", "DD", "AU", "UA", "DU", "UD"):
            conflicts += 1
        elif line.strip():
            changed += 1
    parts = [f"On {branch}" if branch and branch != "HEAD" else "Detached head"]
    if not (changed or new or conflicts):
        parts.append("nothing to commit")
    if changed:
        parts.append(f"{changed} changed file{'s' * (changed != 1)}")
    if new:
        parts.append(f"{new} new file{'s' * (new != 1)}")
    if conflicts:
        parts.append(f"{conflicts} with conflicts")
    if extra:
        parts.append(extra)
    return ", ".join(parts) + "."


_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|passing|failing|pending|todo)\b", re.I)


def test_summary(out: str, code: int | None) -> str:
    """Pass/fail words from the last lines (pytest, unittest, jest, mocha, go...)."""
    lines = [l.strip(" =") for l in (out or "").splitlines() if l.strip(" =")]
    counts: dict[str, str] = {}
    for line in lines[-15:]:
        for num, word in _COUNT.findall(line):
            w = word.lower()
            w = {"passing": "passed", "failing": "failed", "error": "errors"}.get(w, w)
            counts[w] = num
    ran = next((m for m in (re.match(r"Ran (\d+) tests?", l) for l in lines[-15:]) if m), None)
    unit_fail = next((m for m in (re.match(r"FAILED \((.+)\)", l) for l in lines[-5:]) if m), None)
    ok = code == 0
    if counts:
        order = [k for k in ("failed", "errors", "passed", "skipped", "pending", "todo") if k in counts]
        text = ", ".join(f"{counts[k]} {k}" for k in order)
    elif ran:
        text = f"{ran.group(1)} ran" + (f", {unit_fail.group(1).replace('=', ' ')}" if unit_fail else "")
    else:
        text = ""
    if ok:
        return f"Tests passed: {text}." if text else "Tests passed."
    last = lines[-1][:120] if lines else ""
    return f"Tests failed: {text}." if text else f"Tests failed (exit code {code}). Last line: {last}"


# ---------- actions ----------
def needs_confirm(args: dict) -> bool:
    return str((args or {}).get("action") or "").lower().strip() in RISKY


def _message(args: dict) -> str:
    msg = re.sub(r"\s+", " ", str((args or {}).get("message") or "")).strip().strip("\"'")
    return msg[:MAX_MESSAGE]


def risky_text(args: dict) -> str | None:
    """Words for 'Are you sure you want to ...?' (commit/push only), else None."""
    if not needs_confirm(args):
        return None
    name, _ = resolve((args or {}).get("project"))
    where = f" in {name}" if name else ""
    if args.get("action") == "git_commit":
        msg = _message(args)
        return f"commit all changes{where} with the message \"{msg}\"" if msg else f"commit all changes{where}"
    if not name:
        return "push to the remote"
    branch = _branch_of(name)
    return f"push branch {branch} of {name} to the remote" if branch else f"push {name} to the remote"


def _branch_of(name: str) -> str:
    """Current branch name for the push question, "" if unknown. Read-only git call."""
    try:
        path = projects()[name]["path"]
        code, out = _run(_argv(_GIT["git_branch"]), path, f"{name}: git branch", timeout=10)
        return out.strip().splitlines()[0][:60] if code == 0 and out.strip() else ""
    except Exception:
        return ""


def _open(name: str, path: str) -> str:
    exe = shutil.which("code")
    if not exe and IS_WINDOWS:
        guess = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
        exe = guess if os.path.exists(guess) else None
    if not exe:
        return "I can't find VS Code. Install it, or in VS Code run 'Shell Command: Install code command in PATH'."
    try:
        subprocess.Popen([exe, path], cwd=path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError as exc:
        return f"Sorry, VS Code didn't open: {exc}"
    return f"Opening {name} in VS Code."


def _git(action: str, name: str, path: str, args: dict) -> str:
    argv = [a.replace("{message}", _message(args)) if a == "{message}" else a for a in _GIT[action]]
    code, out = _run(_argv(argv), path, f"{name}: {' '.join(_GIT[action][:2])}")
    if code is None:
        if out.startswith("not found"):
            return "Git is not installed, or not on PATH."
        return f"Git {action[4:]} failed: {out}."
    if code != 0:
        low = out.lower()
        if "not a git repository" in low:
            return f"{name} is not a git folder."
        if action == "git_commit" and ("nothing to commit" in low or "no changes added" in low):
            return f"Nothing to commit in {name}."
        if action == "git_pull" and ("not possible to fast-forward" in low or "diverg" in low):
            return f"Can't pull {name} cleanly: your branch and the remote both have new commits. Sort it out in VS Code."
        if "could not read username" in low or "authentication" in low or "permission denied" in low:
            return f"Git needs you to sign in for {name}. Run the command once in a terminal."
        if "no upstream" in low or "has no upstream branch" in low:
            return f"This branch in {name} has no remote branch yet. Push it once from a terminal."
        return f"Git {action[4:]} failed in {name}: {_first_line(out)}"
    if action == "git_status":
        return f"{name}: {_say_status(out)}"
    if action == "git_pull":
        if "already up to date" in out.lower():
            return f"{name} is already up to date."
        m = re.search(r"(\d+) files? changed", out)
        return f"Pulled the latest {name}" + (f": {m.group(1)} file{'s' * (m.group(1) != '1')} changed." if m else ".")
    if action == "git_log":
        subjects = [l.strip() for l in out.splitlines() if l.strip()][:5]
        if not subjects:
            return f"{name} has no commits yet."
        return f"Last commits in {name}: " + "; ".join(s[:80] for s in subjects) + "."
    if action == "git_diff":
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return f"{name}: {lines[-1]}." if lines else f"No unstaged changes in {name}."
    if action == "git_branch":
        b = out.strip()
        return f"{name} is on branch {b}." if b else f"{name} is not on a branch (detached head)."
    if action == "git_commit":
        m = re.search(r"(\d+) files? changed", out)
        return f"Committed {name}" + (f": {m.group(1)} file{'s' * (m.group(1) != '1')}." if m else ".")
    if action == "git_push":
        return f"Pushed {name}." if "up-to-date" not in out.lower() else f"{name} was already pushed."
    return "Done."


def _test(name: str, path: str) -> str:
    cmd = projects()[name].get("test")
    if not cmd:
        return f"{name} has no test command. Add  test: \"pytest -q\"  to it in config.yaml."
    argv = _argv(cmd)
    if not argv:
        return f"The test command for {name} is empty."
    code, out = _run(argv, path, f"{name}: tests")
    if code is None:
        return f"The tests for {name} didn't run: {out}."
    return f"{name}: {test_summary(out, code)}"


def _start(name: str, path: str) -> str:
    cmd = projects()[name].get("run")
    if not cmd:
        return f"{name} has no run command. Add  run: \"npm run dev\"  to it in config.yaml."
    with _lock:
        old = _servers.get(name)
        if old is not None and old.poll() is None:
            return f"The {name} server is already running. Say stop the dev server to stop it."
        log_path = _log_path()
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            out = open(log_path, "a", encoding="utf-8", errors="replace")
            out.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} {name}: dev server ===\n")
            out.flush()
        except OSError:
            out = subprocess.DEVNULL
        extra = {} if IS_WINDOWS else {"start_new_session": True}
        try:
            p = subprocess.Popen(_argv(cmd), cwd=path, stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=subprocess.STDOUT, env=_env(), creationflags=NO_WINDOW, **extra)
        except OSError as exc:
            return f"The {name} server didn't start: {exc}"
        finally:
            if out is not subprocess.DEVNULL:
                out.close()  # the child has its own copy of the handle
        _servers[name] = p
    return f"Starting the {name} dev server. Its output goes to the devtools log."


def _kill(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        if IS_WINDOWS:  # npm starts node as a child: end the whole tree
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                           creationflags=NO_WINDOW, timeout=15)
        else:
            import signal

            os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=10)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _stop(name: str | None) -> str:
    with _lock:
        running = {k: p for k, p in _servers.items() if p.poll() is None}
        for k in [k for k in _servers if k not in running]:
            del _servers[k]
    if not running:
        return "No dev server is running."
    targets = [name] if name in running else list(running) if name is None else []
    if not targets:
        return f"The {name} server is not running. Running: {_names(running)}."
    for k in targets:
        _kill(running[k])
        with _lock:
            _servers.pop(k, None)
    return f"Stopped the {' and '.join(targets)} dev server{'s' * (len(targets) > 1)}."


def stop_all() -> None:
    with _lock:
        procs = list(_servers.values())
        _servers.clear()
    for p in procs:
        _kill(p)


atexit.register(stop_all)


def last_output() -> str:
    if not _last["text"]:
        return "There is no output yet."
    text = _last["text"][-1500:]
    return f"Output of {_last['title']}:\n{text}"


def dev(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or "").lower().strip()
    if action not in ACTIONS:
        return "I can open a project in VS Code, do git status, pull, log, diff, commit, push, run tests, " \
               "or start and stop the dev server."
    if action == "output":
        return last_output()
    if action == "stop":
        name = None
        if args.get("project"):
            name, why = resolve(args.get("project"))
            if not name:
                return why
        return _stop(name)
    if action in RISKY and args.get("confirm") is not True:  # never without a yes
        return f"Are you sure you want to {risky_text({**args, 'action': action})}? Say yes to confirm."
    if action == "git_commit" and not _message(args):
        return "What should the commit message be? Say: commit with message, then the message."
    name, why = resolve(args.get("project"))
    if not name:
        return why
    path, why = _folder(name)
    if not path:
        return why
    _last_project["name"] = name
    try:
        if action == "open":
            return _open(name, path)
        if action == "test":
            return _test(name, path)
        if action == "run":
            return _start(name, path)
        return _git(action, name, path, args)
    except Exception as exc:  # never crash the main loop
        log.exception("dev %s failed", action)
        return f"Sorry, that failed: {str(exc)[:120]}"


# ---------- phrases (optional helper for nlu_features) ----------
_P = r"(?:\s+(?:of|for|in|on)\s+(?P<project>[\w .-]+?))?"
_GIT_WORD = r"(?:git|the git|my git)"
_RULES: list[tuple[re.Pattern, str]] = [(re.compile(rx + r"$"), action) for rx, action in [
    (r"^open\s+(?P<project>[\w .-]+?)\s+(?:in|with)\s+(?:vs ?code|visual studio code)", "open"),
    (r"^(?:git\s+status|(?:show|check)\s+(?:me\s+)?(?:the\s+)?git\s+status|what(?:'s| is)\s+the\s+git\s+status)" + _P,
     "git_status"),
    (r"^(?:git\s+pull|pull\s+(?:the\s+)?(?:latest|new)(?:\s+(?:changes|code))?|pull\s+(?:the\s+)?(?:latest\s+)?code)" + _P,
     "git_pull"),
    (r"^(?:git\s+log|show\s+(?:me\s+)?(?:the\s+)?(?:git\s+log|(?:last|recent)\s+(?:few\s+)?commits)|"
     r"what\s+are\s+the\s+(?:last|recent)\s+commits)" + _P, "git_log"),
    (r"^(?:git\s+diff|show\s+(?:me\s+)?(?:the\s+)?(?:git\s+)?diff)" + _P, "git_diff"),
    (r"^(?:git\s+branch|which\s+(?:git\s+)?branch\s+am\s+i\s+on|what\s+(?:git\s+)?branch\s+am\s+i\s+on)" + _P,
     "git_branch"),
    (r"^(?:git\s+)?commit(?:\s+(?:all\s+)?(?:my\s+|the\s+)?(?:changes|code|everything|work))?" + _P +
     r"\s+(?:with\s+(?:the\s+)?message|saying)\s+(?P<message>.+)", "git_commit"),
    (r"^(?:git\s+push|push\s+(?:my\s+|the\s+)?(?:changes|code|commits?))" + _P +
     r"(?:\s+to\s+(?:github|gitlab|the\s+remote|origin|remote))?", "git_push"),
    (r"^(?:run|start)\s+(?:the\s+|my\s+|all\s+(?:the\s+)?)?(?:unit\s+)?tests" + _P, "test"),
    (r"^(?:start|run|launch)\s+(?:the\s+|my\s+)?(?:dev(?:elopment)?|local)\s+server" + _P, "run"),
    (r"^(?:stop|kill|close)\s+(?:the\s+|my\s+)?(?:dev(?:elopment)?|local)\s+servers?" + _P, "stop"),
    (r"^(?:show|read|tell)\s+(?:me\s+)?(?:the\s+)?(?:full\s+)?(?:test|git|dev|last)\s+(?:output|errors?|log)", "output"),
    (r"^(?:which|what)\s+tests\s+failed", "output"),
]]


def parse(text: str) -> tuple[str, dict] | None:
    """'git status of jarvis' -> ('dev', {'action': 'git_status', 'project': 'jarvis'}); else None."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip().strip(" .!?"))
    t = re.sub(r"^(?:hey\s+|ok\s+)?jarvis[, ]+", "", t)
    t = re.sub(r"^please\s+|\s+please$", "", t)
    for rx, action in _RULES:
        m = rx.match(t)
        if not m:
            continue
        args: dict = {"action": action}
        gd = m.groupdict()
        proj = re.sub(r"^(?:the|my)\s+", "", (gd.get("project") or "").strip())
        proj = re.sub(r"\s+(?:project|repo|repository|folder|code)$", "", proj).strip()
        if action == "open" and proj in ("", "my", "project", "code", "my project"):
            proj = ""
        if proj and proj not in ("my", "project", "this", "it", "code"):
            args["project"] = proj
        if gd.get("message"):
            args["message"] = gd["message"].strip()
        return "dev", args
    return None


# ---------- for the AI brain and actions/__init__.py ----------
CATALOG: dict[str, dict] = {
    "dev": {
        "description": "Developer tools for the user's coding projects listed in config.yaml: open a project in "
                       "VS Code, git status/pull/log/diff/branch, git commit -a with a message and git push (both "
                       "ask the user to confirm), run the project's test command, start/stop its dev server, or "
                       "read the full output of the last command. No other commands can run.",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "project": {"type": "string", "description": "Project name from config; empty = the only/last one."},
            "message": {"type": "string", "description": "Commit message (git_commit only)."},
        },
        "required": ["action"],
    },
}

HANDLERS = {"dev": dev}
