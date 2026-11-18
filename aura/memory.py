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
  facts       — long-term memory (Phase 10.1): structured
              project facts the user EXPLICITLY asked AURA to
              remember ("remember that Nexture's stack is MERN").
              A fact is (project, key, value); re-saving the same
              fact updates it — the newer explicit correction wins.
              Never auto-saved from ordinary speech, and secrets
              (passwords, tokens, keys) are refused, never stored.
  preferences — long-term memory: simple key/value preferences
              ("my preferred editor is VS Code"), same rules as
              facts.
  focus_sessions — Focus Mode history (Phase 10.1): one row
              per finished session (task, profile, duration,
              status). The LIVE session (running/paused, remaining
              time) is runtime state in aura/focus.py, not a row
              here — only finished sessions are recorded, so an
              interrupted session is never claimed as completed.

All access goes through one lock: the voice thread and the reminder
thread share this object.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_memory.db",
)

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_SECRET_RE = re.compile(
    r"\b(password|passwd|pwd|passcode|token|secret|passkey|credential|"
    r"private\s+key|api\s+key|access\s+key|client\s+secret)\b",
    re.IGNORECASE,
)


def _looks_like_secret(text):
    """True when text mentions a password/token/key — never store those."""
    return bool(text) and bool(_SECRET_RE.search(text))


def _now():
    return datetime.now().strftime(_TIME_FORMAT)


class Memory:
    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_DB
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT '',
                    project TEXT NOT NULL DEFAULT '',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'voice',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project, key)
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL DEFAULT '',
                    profile TEXT NOT NULL DEFAULT 'custom',
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'completed'
                );
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

    # -- facts (long-term memory, Phase 10.1) ---------------------------
    # Every write here is explicit: the user said "remember that..." (or
    # an update/forget command). AURA never auto-saves facts from
    # conversation. Secrets are refused at this layer too, so no caller
    # can store a password/token/key by accident.

    def save_fact(self, project, key, value, category="", source="voice"):
        """Upsert a fact. A newer explicit correction wins (same project+key).

        Returns the row id. Raises ValueError for secrets.
        """
        if _looks_like_secret(key) or _looks_like_secret(value):
            raise ValueError("I can't store passwords, tokens, or secret keys.")
        now = _now()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id FROM facts WHERE project = ? AND key = ?",
                (project, key),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE facts SET value = ?, category = ?, source = ?,"
                    " updated_at = ? WHERE id = ?",
                    (value, category, source, now, row[0]),
                )
                fact_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO facts (category, project, key, value, source,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (category, project, key, value, source, now, now),
                )
                fact_id = cur.lastrowid
            self._conn.commit()
            return fact_id

    def get_fact(self, project, key):
        """The fact row (dict) for a project+key, or None."""
        rows = self._rows(
            "SELECT * FROM facts WHERE project = ? AND key = ?",
            (project, key),
        )
        return dict(rows[0]) if rows else None

    def find_facts(self, project):
        """All facts for a project (every fact when project is ''), newest first."""
        if project:
            rows = self._rows(
                "SELECT * FROM facts WHERE project = ?"
                " ORDER BY updated_at DESC",
                (project,),
            )
        else:
            rows = self._rows("SELECT * FROM facts ORDER BY updated_at DESC")
        return [dict(r) for r in rows]

    def list_facts(self):
        """All facts, newest first."""
        return self.find_facts("")

    def list_projects(self):
        """Distinct non-empty project names that have facts, sorted."""
        rows = self._rows(
            "SELECT DISTINCT project FROM facts WHERE project != ''"
            " ORDER BY project"
        )
        return [r[0] for r in rows]

    def delete_fact(self, project, key):
        """Delete one fact. Returns True when a row was removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE project = ? AND key = ?",
                (project, key),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_fact_number(self, number):
        """Delete the Nth entry in list order (1-based) — the same
        numbering the "list what you remember" reply shows: facts
        newest first, then preferences. A deleted preference comes
        back as a fact-shaped dict (project ""), so the caller can
        describe it the same way. Returns None when out of range.
        """
        facts = self.list_facts()
        prefs = self.list_preferences()
        if number < 1 or number > len(facts) + len(prefs):
            return None
        if number <= len(facts):
            fact = facts[number - 1]
            self.delete_fact(fact["project"], fact["key"])
            return fact
        pref = prefs[number - len(facts) - 1]
        self.delete_preference(pref["key"])
        return {"project": "", "key": pref["key"],
                "value": pref["value"]}

    # -- preferences (Phase 10.1) -----------------------------------------
    # Simple key/value store for user preferences ("my preferred editor
    # is VS Code"). Same explicit-save rule as facts; secrets refused.

    def save_preference(self, key, value):
        if _looks_like_secret(key) or _looks_like_secret(value):
            raise ValueError("I can't store passwords, tokens, or secret keys.")
        self._write(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at",
            (key, value, _now()),
        )

    def get_preference(self, key):
        rows = self._rows(
            "SELECT * FROM preferences WHERE key = ?", (key,)
        )
        return dict(rows[0]) if rows else None

    def list_preferences(self):
        rows = self._rows("SELECT * FROM preferences ORDER BY key")
        return [dict(r) for r in rows]

    def delete_preference(self, key):
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM preferences WHERE key = ?", (key,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    # -- focus sessions (Phase 10.1) --------------------------------------
    # History of finished/ended focus sessions. A session is only recorded
    # when it finishes or is ended deliberately — closing AURA mid-session
    # writes nothing, so a row never claims a session completed when it didn't.

    def record_focus_session(self, task, profile, duration_seconds,
                             started_at, ended_at, status):
        return self._write(
            "INSERT INTO focus_sessions (task, profile, duration_seconds,"
            " started_at, ended_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (task, profile, int(duration_seconds), started_at, ended_at,
             status),
        )

    def list_focus_sessions(self, limit=20):
        # Newest first; id breaks ties when two sessions share a
        # started_at second (started_at has 1-second resolution).
        rows = self._rows(
            "SELECT * FROM focus_sessions ORDER BY started_at DESC,"
            " id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
