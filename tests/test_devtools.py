"""Developer tools (piece BN). Uses a real temp git repo and tiny Python commands as 'tests' / 'dev server'."""
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import devtools as dv  # noqa: E402

PY = sys.executable
HAS_GIT = shutil.which("git") is not None


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    proj = tmp_path / "jarvis"
    proj.mkdir()
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setattr(dv, "PROJECTS", {
        "jarvis": {"path": str(proj), "test": [PY, "-c", "print('== 5 passed in 0.1s ==')"],
                   "run": [PY, "-c", "import time; time.sleep(60)"]},
        "My Site": {"path": str(site), "test": [PY, "-c", "import sys; print('1 failed, 4 passed'); sys.exit(1)"]},
    })
    monkeypatch.setattr(dv, "LOG_FILE", str(tmp_path / "logs" / "devtools.log"))
    monkeypatch.setattr(dv, "_cfg", lambda: {})
    monkeypatch.setitem(dv._last_project, "name", "")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    yield {"jarvis": proj, "site": site, "tmp": tmp_path}
    dv.stop_all()


@pytest.fixture
def repo(setup):
    if not HAS_GIT:
        pytest.skip("git not installed")
    p = setup["jarvis"]
    git(p, "init", "-q", "-b", "main")
    (p / "a.txt").write_text("one\n")
    git(p, "add", ".")
    git(p, "commit", "-q", "-m", "first commit")
    return p


# ---------- config + project names ----------
def test_projects_skip_bad_entries(monkeypatch):
    monkeypatch.setattr(dv, "PROJECTS", {"ok": "C:/x", "bad": {"test": "pytest"}, "num": 5,
                                         "both": {"path": "/p", "test": "pytest -q", "run": ""}})
    p = dv.projects()
    assert set(p) == {"ok", "both"}
    assert p["ok"] == {"path": "C:/x"}
    assert p["both"] == {"path": "/p", "test": "pytest -q"}


def test_projects_from_config(monkeypatch):
    monkeypatch.setattr(dv, "PROJECTS", None)
    monkeypatch.setattr(dv, "_cfg", lambda: {"devtools": {"projects": {"A": {"path": "/a"}}}})
    assert dv.projects() == {"a": {"path": "/a"}}
    monkeypatch.setattr(dv, "_cfg", lambda: {"projects": {"b": "/b"}})
    assert dv.projects() == {"b": {"path": "/b"}}


def test_no_projects_says_how(monkeypatch):
    monkeypatch.setattr(dv, "PROJECTS", {})
    assert "config.yaml" in dv.dev({"action": "git_status"})


@pytest.mark.parametrize("said,want", [
    ("jarvis", "jarvis"), ("Jarvis project", "jarvis"), ("the jarvis repo", "jarvis"), ("jarvs", "jarvis"),
    ("my site", "my site"), ("mysite", "my site"), ("site", "my site"),
])
def test_resolve(said, want):
    assert dv.resolve(said) == (want, "")


def test_resolve_unknown_and_ambiguous():
    name, why = dv.resolve("banana")
    assert name is None and "banana" in why and "jarvis" in why
    name, why = dv.resolve(None)
    assert name is None and why.startswith("Which project")


def test_resolve_only_project(monkeypatch, setup):
    monkeypatch.setattr(dv, "PROJECTS", {"jarvis": {"path": str(setup["jarvis"])}})
    assert dv.resolve("") == ("jarvis", "")


def test_last_project_remembered(setup):
    dv.dev({"action": "test", "project": "jarvis"})
    assert dv.resolve(None) == ("jarvis", "")


def test_missing_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(dv, "PROJECTS", {"gone": {"path": str(tmp_path / "nope")}})
    assert "doesn't exist" in dv.dev({"action": "git_status"})


def test_bad_action():
    assert "I can open" in dv.dev({"action": "rm -rf"})
    assert "I can open" in dv.dev({})


# ---------- tests command ----------
def test_run_tests_pass(setup):
    r = dv.dev({"action": "test", "project": "jarvis"})
    assert r == "jarvis: Tests passed: 5 passed."
    log = (setup["tmp"] / "logs" / "devtools.log").read_text()
    assert "jarvis: tests" in log and "5 passed" in log


def test_run_tests_fail(setup):
    assert dv.dev({"action": "test", "project": "my site"}) == "my site: Tests failed: 1 failed, 4 passed."


def test_no_test_command(monkeypatch, setup):
    monkeypatch.setattr(dv, "PROJECTS", {"x": {"path": str(setup["jarvis"])}})
    assert "no test command" in dv.dev({"action": "test"})


def test_test_command_missing_program(monkeypatch, setup):
    monkeypatch.setattr(dv, "PROJECTS", {"x": {"path": str(setup["jarvis"]), "test": "no-such-prog-xyz -q"}})
    assert "didn't run" in dv.dev({"action": "test"})


def test_test_timeout(monkeypatch, setup):
    monkeypatch.setattr(dv, "PROJECTS", {"x": {"path": str(setup["jarvis"]),
                                               "test": [PY, "-c", "import time; time.sleep(5)"]}})
    monkeypatch.setattr(dv, "_timeout", lambda: 1)
    assert "timed out" in dv.dev({"action": "test"})


def test_string_command_split_no_shell(monkeypatch, setup):
    marker = setup["tmp"] / "pwned"
    cmd = f'"{PY}" -c "print(1)" ; touch {marker}' if os.name != "nt" else f'"{PY}" -c "print(1)" & echo x > {marker}'
    monkeypatch.setattr(dv, "PROJECTS", {"x": {"path": str(setup["jarvis"]), "test": cmd}})
    dv.dev({"action": "test"})
    assert not marker.exists()  # ';' / '&' went to python as plain arguments, no shell ran


@pytest.mark.parametrize("out,code,want", [
    ("....\n===== 12 passed, 1 skipped in 2.0s =====", 0, "Tests passed: 12 passed, 1 skipped."),
    ("F.\n== 1 failed, 1 passed in 0.2s ==", 1, "Tests failed: 1 failed, 1 passed."),
    ("Tests:       2 failed, 8 passed, 10 total", 1, "Tests failed: 2 failed, 8 passed."),
    ("  5 passing (20ms)\n  1 failing", 1, "Tests failed: 1 failed, 5 passed."),
    ("Ran 4 tests in 0.01s\n\nOK", 0, "Tests passed: 4 ran."),
    ("Ran 4 tests in 0.01s\n\nFAILED (failures=1)", 1, "Tests failed: 4 ran, failures 1."),
    ("ok  \tpkg\t0.1s", 0, "Tests passed."),
    ("boom\nsomething broke", 2, "Tests failed (exit code 2). Last line: something broke"),
])
def test_summary(out, code, want):
    assert dv.test_summary(out, code) == want


# ---------- git ----------
def test_git_status_clean(repo):
    assert dv.dev({"action": "git_status", "project": "jarvis"}) == "jarvis: On main, nothing to commit."


def test_git_status_changes(repo):
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("new\n")
    (repo / "c.txt").write_text("new\n")
    assert dv.dev({"action": "git_status", "project": "jarvis"}) == "jarvis: On main, 1 changed file, 2 new files."


def test_say_status_ahead_behind():
    out = "## main...origin/main [ahead 2, behind 1]\n M x.py\nUU y.py\n"
    assert dv._say_status(out) == "On main, 1 changed file, 1 with conflicts, 2 commits ahead, 1 behind."


def test_git_log_and_branch(repo):
    r = dv.dev({"action": "git_log", "project": "jarvis"})
    assert r.startswith("Last commits in jarvis: first commit (")
    assert dv.dev({"action": "git_branch", "project": "jarvis"}) == "jarvis is on branch main."


def test_git_diff(repo):
    assert dv.dev({"action": "git_diff", "project": "jarvis"}) == "No unstaged changes in jarvis."
    (repo / "a.txt").write_text("two\nthree\n")
    r = dv.dev({"action": "git_diff", "project": "jarvis"})
    assert "1 file changed" in r


def test_not_a_git_folder(setup):
    if not HAS_GIT:
        pytest.skip("git not installed")
    assert dv.dev({"action": "git_status", "project": "my site"}) == "my site is not a git folder."


def test_commit_needs_confirm(repo):
    (repo / "a.txt").write_text("changed\n")
    r = dv.dev({"action": "git_commit", "project": "jarvis", "message": "fix bug"})
    assert r == 'Are you sure you want to commit all changes in jarvis with the message "fix bug"? Say yes to confirm.'
    assert git(repo, "log", "--oneline").count("\n") == 1  # nothing committed


def test_commit_with_confirm(repo):
    (repo / "a.txt").write_text("changed\n")
    r = dv.dev({"action": "git_commit", "project": "jarvis", "message": "fix; rm -rf / && echo hi", "confirm": True})
    assert r == "Committed jarvis: 1 file."
    assert git(repo, "log", "-1", "--pretty=%s").strip() == "fix; rm -rf / && echo hi"  # message is one argument


def test_commit_dash_message_is_text(repo):
    (repo / "a.txt").write_text("changed\n")
    dv.dev({"action": "git_commit", "project": "jarvis", "message": "--amend", "confirm": True})
    assert git(repo, "log", "--oneline").count("\n") == 2
    assert git(repo, "log", "-1", "--pretty=%s").strip() == "--amend"


def test_commit_nothing(repo):
    assert dv.dev({"action": "git_commit", "project": "jarvis", "message": "x", "confirm": True}) \
        == "Nothing to commit in jarvis."


def test_commit_without_message(repo):
    r = dv.dev({"action": "git_commit", "project": "jarvis", "confirm": True})
    assert r.startswith("What should the commit message be")


def test_push_needs_confirm_and_reports_no_remote(repo):
    assert dv.dev({"action": "git_push", "project": "jarvis"}).startswith("Are you sure you want to push branch main of jarvis to the remote")
    r = dv.dev({"action": "git_push", "project": "jarvis", "confirm": True})
    assert "failed" in r or "remote" in r


def test_pull_and_push_with_local_remote(repo, setup):
    remote = setup["tmp"] / "remote.git"
    git(setup["tmp"], "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    assert dv.dev({"action": "git_pull", "project": "jarvis"}) == "jarvis is already up to date."
    (repo / "a.txt").write_text("changed\n")
    dv.dev({"action": "git_commit", "project": "jarvis", "message": "two", "confirm": True})
    assert dv.dev({"action": "git_status", "project": "jarvis"}) == "jarvis: On main, nothing to commit, 1 commit ahead."
    assert dv.dev({"action": "git_push", "project": "jarvis", "confirm": True}) == "Pushed jarvis."


def test_git_missing(monkeypatch, setup):
    monkeypatch.setattr(dv.shutil, "which", lambda name: None)
    monkeypatch.setattr(dv, "_GIT", {**dv._GIT, "git_status": ["no-such-git-xyz", "status"]})
    assert dv.dev({"action": "git_status", "project": "jarvis"}) == "Git is not installed, or not on PATH."


def test_risky_helpers():
    assert dv.needs_confirm({"action": "git_commit"}) and dv.needs_confirm({"action": "git_push"})
    assert not dv.needs_confirm({"action": "git_status"}) and not dv.needs_confirm({})
    assert dv.risky_text({"action": "git_status"}) is None
    assert dv.risky_text({"action": "git_push", "project": "jarvis"}) == "push jarvis to the remote"
    assert dv.risky_text({"action": "git_commit"}) == "commit all changes"


def test_output_action(setup):
    assert dv.dev({"action": "output"}).startswith(("There is no output", "Output of"))
    dv.dev({"action": "test", "project": "my site"})
    r = dv.dev({"action": "output"})
    assert r.startswith("Output of my site: tests") and "1 failed, 4 passed" in r


# ---------- VS Code ----------
def test_open_in_vscode(monkeypatch, setup):
    calls = []
    monkeypatch.setattr(dv.shutil, "which", lambda name: "/bin/code" if name == "code" else None)
    monkeypatch.setattr(dv.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    assert dv.dev({"action": "open", "project": "jarvis"}) == "Opening jarvis in VS Code."
    assert calls[0][0] == ["/bin/code", str(setup["jarvis"])]
    assert "shell" not in calls[0][1]


def test_open_without_vscode(monkeypatch):
    monkeypatch.setattr(dv.shutil, "which", lambda name: None)
    monkeypatch.setattr(dv, "IS_WINDOWS", False)
    assert dv.dev({"action": "open", "project": "jarvis"}).startswith("I can't find VS Code")


# ---------- dev server ----------
def test_dev_server_start_stop(setup):
    assert dv.dev({"action": "run", "project": "jarvis"}).startswith("Starting the jarvis dev server")
    p = dv._servers["jarvis"]
    assert p.poll() is None
    assert "already running" in dv.dev({"action": "run", "project": "jarvis"})
    assert dv.dev({"action": "stop"}) == "Stopped the jarvis dev server."
    assert p.poll() is not None
    assert dv.dev({"action": "stop"}) == "No dev server is running."


def test_stop_named_not_running(setup):
    dv.dev({"action": "run", "project": "jarvis"})
    assert "not running" in dv.dev({"action": "stop", "project": "my site"})
    assert dv.dev({"action": "stop", "project": "jarvis"}) == "Stopped the jarvis dev server."


def test_no_run_command():
    assert "no run command" in dv.dev({"action": "run", "project": "my site"})


def test_stop_all(setup):
    dv.dev({"action": "run", "project": "jarvis"})
    p = dv._servers["jarvis"]
    dv.stop_all()
    assert p.poll() is not None and not dv._servers


# ---------- phrases ----------
@pytest.mark.parametrize("said,args", [
    ("open jarvis project in VS Code", {"action": "open", "project": "jarvis"}),
    ("open my project in vs code", {"action": "open"}),
    ("Jarvis, open the website repo in visual studio code", {"action": "open", "project": "website"}),
    ("git status", {"action": "git_status"}),
    ("git status of jarvis", {"action": "git_status", "project": "jarvis"}),
    ("what's the git status for my site", {"action": "git_status", "project": "site"}),
    ("pull latest", {"action": "git_pull"}),
    ("pull the latest changes for jarvis", {"action": "git_pull", "project": "jarvis"}),
    ("git pull", {"action": "git_pull"}),
    ("show the last commits", {"action": "git_log"}),
    ("git log of jarvis", {"action": "git_log", "project": "jarvis"}),
    ("show me the diff", {"action": "git_diff"}),
    ("which branch am i on", {"action": "git_branch"}),
    ("commit with message fix login bug", {"action": "git_commit", "message": "fix login bug"}),
    ("commit all my changes in jarvis with the message add tests",
     {"action": "git_commit", "project": "jarvis", "message": "add tests"}),
    ("git commit saying update readme", {"action": "git_commit", "message": "update readme"}),
    ("push my changes", {"action": "git_push"}),
    ("push my code to github", {"action": "git_push"}),
    ("git push", {"action": "git_push"}),
    ("run the tests", {"action": "test"}),
    ("run my tests for jarvis", {"action": "test", "project": "jarvis"}),
    ("run tests", {"action": "test"}),
    ("start the dev server", {"action": "run"}),
    ("start the development server for my site", {"action": "run", "project": "site"}),
    ("stop the dev server", {"action": "stop"}),
    ("show the test output", {"action": "output"}),
    ("which tests failed", {"action": "output"}),
])
def test_parse(said, args):
    assert dv.parse(said) == ("dev", args)


@pytest.mark.parametrize("said", [
    "open vs code", "open chrome", "commit", "push", "stop", "stop the music", "run notepad", "start the timer",
    "what's the status", "pull up my notes", "show me the weather", "start tracking jarvis",
])
def test_parse_ignores(said):
    assert dv.parse(said) is None


def test_catalog():
    assert set(dv.CATALOG) == set(dv.HANDLERS) == {"dev"}
    assert set(dv.CATALOG["dev"]["properties"]["action"]["enum"]) == set(dv.ACTIONS)
