"""Shared test setup: no state may leak from one test file into another."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _no_open_quiz():
    """A quiz question left open by one test would send the next test's words to the quiz."""
    yield
    from jarvis.actions import fun

    fun._QUIZ_STATE["question"] = None


@pytest.fixture(autouse=True)
def _history_in_tmp(tmp_path, monkeypatch):
    """main.handle logs every command to history: keep test commands out of the real history file."""
    from jarvis.actions import history

    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "history.jsonl"))


@pytest.fixture(autouse=True)
def _user_files_in_tmp(tmp_path, monkeypatch):
    """Setup answers (user.json) and word fixes must not come from, or go to, the real files."""
    from jarvis.actions import corrections, onboarding

    monkeypatch.setattr(onboarding, "USER_FILE", tmp_path / "user.json")
    monkeypatch.setattr(corrections, "_path", lambda: tmp_path / "corrections.json")
    monkeypatch.setattr(corrections, "_misheard_path", lambda: tmp_path / "misheard.jsonl")


@pytest.fixture(autouse=True)
def _round7_files_in_tmp(tmp_path, monkeypatch):
    """Contacts, habits and flashcards saved by one test must not reach the real files or another test."""
    from jarvis.actions import contacts, documents, flashcards, habits

    monkeypatch.setattr(contacts, "CONTACTS_FILE", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(contacts, "_config_contacts", lambda: {})
    monkeypatch.setattr(habits, "HABITS_FILE", str(tmp_path / "habits.json"))
    monkeypatch.setattr(flashcards, "FLASHCARDS_FILE", str(tmp_path / "flashcards.json"))
    documents.reset()
    yield
    documents.reset()
    try:
        flashcards.stop()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _round8_files_in_tmp(tmp_path, monkeypatch):
    """Time tracking and birthdays saved by one test must not reach the real files; cook mode must not leak."""
    from jarvis.actions import birthdays, recipes, timetrack

    monkeypatch.setattr(timetrack, "TRACK_FILE", str(tmp_path / "timetrack.json"))
    monkeypatch.setattr(birthdays, "_path", lambda: str(tmp_path / "birthdays.json"))
    yield
    try:
        recipes.stop()
    except Exception:
        pass
