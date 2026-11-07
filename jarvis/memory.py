"""Long-term memory stored in a local SQLite file."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, text TEXT NOT NULL, due REAL NOT NULL, fired INTEGER NOT NULL DEFAULT 0);
"""


class Memory:
    def __init__(self, path: str | Path = ":memory:"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.fetchall()

    # facts ("remember that ...")
    def add_fact(self, text: str) -> None:
        self._exec("INSERT INTO facts (text, created) VALUES (?, ?)", (text, time.time()))

    def facts(self) -> list[str]:
        return [r[0] for r in self._exec("SELECT text FROM facts ORDER BY id")]

    def forget(self, keyword: str) -> int:
        rows = self._exec("SELECT id FROM facts WHERE text LIKE ?", (f"%{keyword}%",))
        self._exec("DELETE FROM facts WHERE text LIKE ?", (f"%{keyword}%",))
        return len(rows)

    # chat history
    def add_message(self, role: str, content: str) -> None:
        self._exec("INSERT INTO history (role, content, created) VALUES (?, ?, ?)", (role, content, time.time()))

    def recent_messages(self, limit: int) -> list[dict]:
        rows = self._exec("SELECT role, content FROM history ORDER BY id DESC LIMIT ?", (limit,))
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def clear_history(self) -> None:
        self._exec("DELETE FROM history")

    # notes
    def add_note(self, text: str) -> None:
        self._exec("INSERT INTO notes (text, created) VALUES (?, ?)", (text, time.time()))

    def notes(self) -> list[str]:
        return [r[0] for r in self._exec("SELECT text FROM notes ORDER BY id")]

    def clear_notes(self) -> None:
        self._exec("DELETE FROM notes")

    # to-do list
    def add_todo(self, text: str) -> None:
        self._exec("INSERT INTO todos (text, created) VALUES (?, ?)", (text, time.time()))

    def todos(self) -> list[tuple[int, str]]:
        return self._exec("SELECT id, text FROM todos WHERE done = 0 ORDER BY id")

    def finish_todo(self, keyword: str) -> int:
        rows = self._exec("SELECT id FROM todos WHERE done = 0 AND text LIKE ?", (f"%{keyword}%",))
        self._exec("UPDATE todos SET done = 1 WHERE done = 0 AND text LIKE ?", (f"%{keyword}%",))
        return len(rows)

    # reminders
    def add_reminder(self, text: str, due: float) -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO reminders (text, due) VALUES (?, ?)", (text, due))
            self.db.commit()
            return cur.lastrowid

    def pending_reminders(self) -> list[tuple[int, str, float]]:
        return self._exec("SELECT id, text, due FROM reminders WHERE fired = 0 ORDER BY due")

    def mark_fired(self, rid: int) -> None:
        self._exec("UPDATE reminders SET fired = 1 WHERE id = ?", (rid,))
