"""Tests for actions/fuzzy.py (name matching). Each test runs with difflib and, if installed, rapidfuzz."""
import pytest

from jarvis.actions import apps, fuzzy

_BACKENDS = ["difflib"] + (["rapidfuzz"] if fuzzy._rf is not None else [])


@pytest.fixture(autouse=True, params=_BACKENDS)
def backend(request, monkeypatch):
    if request.param == "difflib":
        monkeypatch.setattr(fuzzy, "_rf", None)
    return request.param


CONTACTS = {"mom": {"phone": "+911"}, "dad": {}, "Rahul": {}, "rohit": {}, "priya sharma": {}, "Tom": {}}


def test_has_no_intents():
    assert not hasattr(fuzzy, "CATALOG") and not hasattr(fuzzy, "HANDLERS")


@pytest.mark.parametrize("text,want", [
    ("The Note-Pad app", "note pad"),
    ("  my   Chrome please ", "chrome"),
    ("what's app", "whats"),  # "app" is a filler word
    ("", ""),
    (None, ""),
])
def test_normalize(text, want):
    assert fuzzy.normalize(text) == want


@pytest.mark.parametrize("text,want", [
    ("open note pad", "open notepad"),
    ("play spotty fly", "play spotify"),
    ("Open Crome now", "open chrome now"),
    ("open chrome", "open chrome"),  # "chrom" must not match inside "chrome"
    ("open file explorer", "open file explorer"),  # "file explore" must not grow an extra r
    ("open down loads folder", "open downloads folder"),
])
def test_fix_slips(text, want):
    assert fuzzy.fix_slips(text) == want


@pytest.mark.parametrize("heard,want", [
    ("crome", "chrome"),
    ("note pad", "notepad"),
    ("spotty fly", "spotify"),
    ("calculater", "calculator"),
    ("fire fox", "firefox"),
    ("power point", "powerpoint"),
    ("exel", "excel"),
    ("gogle chrome", "google chrome"),
    ("Task Manger", "task manager"),
    ("you tube", "youtube"),
    ("NOTEPAD", "notepad"),
])
def test_app_matches_misheard_names(heard, want):
    assert fuzzy.app(heard) == want


@pytest.mark.parametrize("heard", ["blender", "word pad", "visual studio", "notepad plus", "zoom", "", "ab"])
def test_app_does_not_guess(heard):
    assert fuzzy.app(heard) is None


def test_app_custom_dict_and_returns_original_key():
    my_apps = {"OBS Studio": "obs64.exe", "Steam": "steam.exe"}
    assert fuzzy.app("obs studoi", my_apps) == "OBS Studio"
    assert fuzzy.app("stem", my_apps) == "Steam"
    assert my_apps[fuzzy.app("steem", my_apps)] == "steam.exe"


def test_app_same_value_is_not_a_tie():
    # both keys open the same program, so a near tie between them is fine
    assert fuzzy.best("vscode", {"vs code": "code", "vscode": "code"}) in ("vs code", "vscode")
    assert apps.APP_PATHS[fuzzy.app("vs cold")] == "code"


def test_tie_between_different_things_returns_none():
    assert fuzzy.best("cat", ["bat", "hat"], cutoff=0) is None  # too short, never fuzzy
    assert fuzzy.best("marta", {"marti": 1, "marto": 2}, cutoff=50) is None


@pytest.mark.parametrize("heard,want", [
    ("my mom", "mom"),
    ("Mom", "mom"),
    ("rahul", "Rahul"),
    ("raul", "Rahul"),
    ("rohith", "rohit"),
    ("sharma priya", "priya sharma"),
])
def test_contact_matches(heard, want):
    assert fuzzy.contact(heard, CONTACTS) == want
    assert CONTACTS[fuzzy.contact(heard, CONTACTS)] is not None


@pytest.mark.parametrize("heard", ["tom cruise", "rahool k", "priya", "mum", "bob", ""])
def test_contact_does_not_guess(heard):
    assert fuzzy.contact(heard, CONTACTS) is None


def test_contact_short_names_need_exact_match():
    assert fuzzy.contact("tom", CONTACTS) == "Tom"
    assert fuzzy.contact("dan", CONTACTS) is None  # not "dad"


def test_contact_empty_or_list():
    assert fuzzy.contact("mom", None) is None
    assert fuzzy.contact("mom", {}) is None
    assert fuzzy.contact("rohith", ["rohit", "rahul"]) == "rohit"


@pytest.mark.parametrize("heard,want", [
    ("down loads", "downloads"),
    ("documents folder", "documents"),
    ("my docs", "docs"),
    ("dekstop", "desktop"),
    ("desk top", "desktop"),
    ("pitures", "pictures"),
    ("vidoes", "videos"),
    ("the music folder", "music"),
])
def test_folder_matches(heard, want):
    assert fuzzy.folder(heard) == want


@pytest.mark.parametrize("heard", ["projects", "system32", "windows", ""])
def test_folder_does_not_guess(heard):
    assert fuzzy.folder(heard) is None


def test_folder_custom_names():
    assert fuzzy.folder("colege notes", ["college notes", "work"]) == "college notes"


def test_matches_sorted_and_limited():
    out = fuzzy.matches("chrom", {"chrome": 1, "google chrome": 1, "chromium": 2}, cutoff=50)
    assert out[0][0] == "chrome" and out[0][1] == 100
    assert [s for _, s in out] == sorted((s for _, s in out), reverse=True)
    assert len(fuzzy.matches("a", ["a"] * 10, cutoff=0, limit=2)) == 2


def test_score_range_and_symmetry_basics():
    assert fuzzy.score("notepad", "notepad") == 100
    assert fuzzy.score("note pad", "notepad") == 100
    assert fuzzy.score("", "notepad") == 0
    assert 0 <= fuzzy.score("excel", "outlook") < fuzzy.DEFAULT_CUTOFF
    assert fuzzy.score("visual studio", "visual studio code") < fuzzy.DEFAULT_CUTOFF


def test_default_app_list_includes_websites():
    assert fuzzy.app("gmial") == "gmail"
    assert "gmail" in apps.WEBSITES


def test_does_not_change_shared_tables():
    before = (dict(apps.APP_PATHS), dict(apps.WEBSITES))
    fuzzy.app("crome")
    assert (apps.APP_PATHS, apps.WEBSITES) == before
