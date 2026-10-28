"""AURA's local memory — Phase 3.

One SQLite file next to main.py (``aura_memory.db``). Nothing leaves
the PC, and deleting that file wipes everything AURA remembers.

Tables:
  notes     — free-form things to remember ("remember that ...").
  todos     — action items; listing shows pending ones only, high
              priority first (Phase 5: high/medium/low).
  reminders — text + a due time; the app speaks them when due and
              marks them notified so they never repeat — unless the
              reminder repeats (Phase 5): daily/weekly reminders are
              advanced to their next occurrence instead of finishing.
  turns     — conversation history (Phase 5): each user turn and
              AURA's reply, newest first; pruned to the last 200.
  notifications — AURA's own notification log (Phase 6): reminders
              that fired, newest first, unread until listed; pruned
              to the last 50. This is AURA's record, not Windows'
              toast notifications (those need extra app setup).

All access goes through one lock: the voice thread and the reminder
thread share this object.
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta

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
                    priority TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0,
                    recurrence TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    reply_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Migration for databases created before Phase 5: add the
            # recurrence column if it is not there yet.
            cols = [
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(reminders)"
                )
            ]
            if "recurrence" not in cols:
                self._conn.execute(
                    "ALTER TABLE reminders ADD COLUMN recurrence TEXT"
                )
            todo_cols = [
                row[1]
                for row in self._conn.execute("PRAGMA table_info(todos)")
            ]
            if "priority" not in todo_cols:
                self._conn.execute(
                    "ALTER TABLE todos ADD COLUMN priority TEXT"
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
    # Priority order: high first, then medium (and unset, which counts
    # as medium), then low; same priority keeps insertion order.
    _PRIORITY_ORDER = (
        "CASE priority WHEN 'high' THEN 0 WHEN 'low' THEN 2 ELSE 1 END"
    )

    def add_todo(self, text: str, priority: str = "medium") -> None:
        self._write(
            "INSERT INTO todos (text, priority, created_at)"
            " VALUES (?, ?, ?)",
            (
                text,
                priority,
                datetime.now().strftime(_TIME_FORMAT),
            ),
        )

    def list_todos(self, priority: str | None = None):
        if priority is None:
            return self._rows(
                "SELECT * FROM todos WHERE done = 0"
                f" ORDER BY {self._PRIORITY_ORDER}, id"
            )
        return self._rows(
            "SELECT * FROM todos WHERE done = 0 AND priority = ?"
            f" ORDER BY {self._PRIORITY_ORDER}, id",
            (priority,),
        )

    def complete_todo(self, n: int):
        row = self._nth(self.list_todos(), n)
        if row is None:
            return None
        self._write("UPDATE todos SET done = 1 WHERE id = ?", (row["id"],))
        return row["text"]

    def set_todo_priority(self, n: int, priority: str):
        row = self._nth(self.list_todos(), n)
        if row is None:
            return None
        self._write(
            "UPDATE todos SET priority = ? WHERE id = ?",
            (priority, row["id"]),
        )
        return row["text"]

    # -- reminders ---------------------------------------------------------------
    def add_reminder(
        self, text: str, remind_at: datetime, recurrence=None
    ) -> None:
        """Add a reminder. ``recurrence`` is None (one-shot), "daily"
        or "weekly" (Phase 5)."""
        self._write(
            "INSERT INTO reminders (text, remind_at, recurrence, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                text,
                remind_at.strftime(_TIME_FORMAT),
                recurrence,
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
        """Finish a one-shot reminder — or advance a repeating one.

        A daily reminder moves to the next future day at the same
        time, a weekly one to the same weekday next week. Stepping
        in a loop (not a single step) skips any occurrences missed
        while the PC was off, so it never fires a burst of catch-ups.
        """
        rows = self._rows(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        )
        if not rows:
            return
        row = rows[0]
        recurrence = None
        try:
            recurrence = row["recurrence"]
        except (IndexError, KeyError):
            recurrence = None
        step = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}.get(
            recurrence
        )
        if step is None:
            self._write(
                "UPDATE reminders SET notified = 1 WHERE id = ?",
                (reminder_id,),
            )
            return
        when = datetime.strptime(row["remind_at"], _TIME_FORMAT)
        now = datetime.now()
        while when <= now:
            when += step
        self._write(
            "UPDATE reminders SET remind_at = ? WHERE id = ?",
            (when.strftime(_TIME_FORMAT), reminder_id),
        )

    def list_recurring(self):
        """Repeating reminders only (daily/weekly), soonest first."""
        return self._rows(
            "SELECT * FROM reminders"
            " WHERE notified = 0 AND recurrence IS NOT NULL"
            " ORDER BY remind_at, id"
        )

    def cancel_recurring(self, n: int):
        row = self._nth(self.list_recurring(), n)
        if row is None:
            return None
        self._write("DELETE FROM reminders WHERE id = ?", (row["id"],))
        return row["text"]

    def cancel_reminder(self, n: int):
        row = self._nth(self.list_reminders(), n)
        if row is None:
            return None
        self._write("DELETE FROM reminders WHERE id = ?", (row["id"],))
        return row["text"]

    # -- conversation history (Phase 5) --------------------------------------
    # Turns are recorded by the app after every handle() call. Only
    # the last 200 are kept, so the database never grows unbounded.
    _TURN_LIMIT = 200

    def add_turn(self, user_text: str, reply_text: str) -> None:
        self._write(
            "INSERT INTO turns (user_text, reply_text, created_at)"
            " VALUES (?, ?, ?)",
            (
                user_text,
                reply_text,
                datetime.now().strftime(_TIME_FORMAT),
            ),
        )
        self._write(
            "DELETE FROM turns WHERE id NOT IN"
            " (SELECT id FROM turns ORDER BY id DESC LIMIT ?)",
            (self._TURN_LIMIT,),
        )

    def recent_turns(self, limit: int = 5):
        """Newest turns first."""
        return self._rows(
            "SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        )

    def search_turns(self, query: str, limit: int = 5):
        """Turns whose user text or reply mentions ``query``."""
        like = f"%{query}%"
        return self._rows(
            "SELECT * FROM turns"
            " WHERE user_text LIKE ? OR reply_text LIKE ?"
            " ORDER BY id DESC LIMIT ?",
            (like, like, limit),
        )

    def clear_turns(self) -> None:
        self._write("DELETE FROM turns")

    # -- notifications (Phase 6) ---------------------------------------
    # AURA's own notification log: anything the app wants Jay to
    # catch up on later (today: reminders that fired). Listing them
    # marks them read, like opening a notification shade.
    _NOTIFICATION_LIMIT = 50

    def add_notification(self, text: str) -> None:
        self._write(
            "INSERT INTO notifications (text, read, created_at)"
            " VALUES (?, 0, ?)",
            (text, datetime.now().strftime(_TIME_FORMAT)),
        )
        self._write(
            "DELETE FROM notifications WHERE id NOT IN"
            " (SELECT id FROM notifications ORDER BY id DESC LIMIT ?)",
            (self._NOTIFICATION_LIMIT,),
        )

    def unread_notifications(self, limit: int = 5):
        """Unread notifications, newest first."""
        return self._rows(
            "SELECT * FROM notifications WHERE read = 0"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def unread_notification_count(self) -> int:
        rows = self._rows(
            "SELECT COUNT(*) AS n FROM notifications WHERE read = 0"
        )
        return rows[0]["n"]

    def mark_notifications_read(self) -> None:
        self._write("UPDATE notifications SET read = 1 WHERE read = 0")

    def clear_notifications(self) -> None:
        self._write("DELETE FROM notifications")
