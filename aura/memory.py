"""AURA's local memory — Phase 3.

One SQLite file next to main.py (``aura_memory.db``). Nothing leaves
the PC, and deleting that file wipes everything AURA remembers.

Tables:
  notes     — free-form things to remember ("remember that ...").
  todos     — action items; listing shows pending ones only.
  reminders — text + a due time; the app speaks them when due and
              marks them notified so they never repeat.

All access goes through one lock: the voice thread and the reminder
thread share this object.
"""

import os
import sqlite3
import threading
from datetime import datetime

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_memory.db",
)

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Memory:
    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_DB
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # -- helpers -----------------------------------------------------------
    def _rows(self, sql: str, args=()):
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _write(self, sql: str, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.lastrowid

    @staticmethod
    def _nth(rows, n: int):
        """Map a spoken number (1-based, in listed order) to a row."""
        if 1 <= n <= len(rows):
            return rows[n - 1]
        return None

    # -- notes ---------------------------------------------------------------
    def add_note(self, text: str) -> None:
        self._write(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)",
            (text, datetime.now().strftime(_TIME_FORMAT)),
        )

    def list_notes(self):
        return self._rows("SELECT * FROM notes ORDER BY id")

    def delete_note(self, n: int):
        row = self._nth(self.list_notes(), n)
        if row is None:
            return None
        self._write("DELETE FROM notes WHERE id = ?", (row["id"],))
        return row["text"]

    # -- todos -----------------------------------------------------------------
    def add_todo(self, text: str) -> None:
        self._write(
            "INSERT INTO todos (text, created_at) VALUES (?, ?)",
            (text, datetime.now().strftime(_TIME_FORMAT)),
        )

    def list_todos(self):
        return self._rows(
            "SELECT * FROM todos WHERE done = 0 ORDER BY id"
        )

    def complete_todo(self, n: int):
        row = self._nth(self.list_todos(), n)
        if row is None:
            return None
        self._write("UPDATE todos SET done = 1 WHERE id = ?", (row["id"],))
        return row["text"]

    # -- reminders ---------------------------------------------------------------
    def add_reminder(self, text: str, remind_at: datetime) -> None:
        self._write(
            "INSERT INTO reminders (text, remind_at, created_at)"
            " VALUES (?, ?, ?)",
            (
                text,
                remind_at.strftime(_TIME_FORMAT),
                datetime.now().strftime(_TIME_FORMAT),
            ),
        )

    def list_reminders(self):
        return self._rows(
            "SELECT * FROM reminders WHERE notified = 0"
            " ORDER BY remind_at, id"
        )

    def due_reminders(self):
        now = datetime.now().strftime(_TIME_FORMAT)
        return self._rows(
            "SELECT * FROM reminders WHERE notified = 0 AND remind_at <= ?"
            " ORDER BY remind_at, id",
            (now,),
        )

    def mark_notified(self, reminder_id: int) -> None:
        self._write(
            "UPDATE reminders SET notified = 1 WHERE id = ?", (reminder_id,)
        )

    def cancel_reminder(self, n: int):
        row = self._nth(self.list_reminders(), n)
        if row is None:
            return None
        self._write("DELETE FROM reminders WHERE id = ?", (row["id"],))
        return row["text"]
