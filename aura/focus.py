"""AURA Focus Mode — Phase 10.1.

Timed focus sessions with a monotonic clock, so wall-clock changes
(daylight saving, a manual clock change) can never stretch or shrink a
session. A session is only written to the focus_sessions history table
when it finishes or is ended deliberately — closing AURA mid-session
records nothing, so history never claims a session completed when it
didn't.

Presets (work minutes / break minutes):

* pomodoro — 25 / 5
* fifty    — 50 / 10
* custom   — whatever minutes the user asked for

Honest scope on notifications: AURA cannot mute other apps' Windows
toasts. During a session it only holds AURA's OWN non-essential
notification-log entries (``held_notifications``) and writes them back
to the log when the session ends. Reminders that come due still speak —
they are alarms, not distractions.
"""

import time
from datetime import datetime

PRESETS = {
    "pomodoro": {"work_minutes": 25, "break_minutes": 5, "label": "Pomodoro"},
    "fifty": {"work_minutes": 50, "break_minutes": 10, "label": "50/10"},
}

# Profiles map a spoken task word to a preset. Anything unrecognised
# falls back to pomodoro — the safest default for an unknown task.
PROFILES = {
    "coding": "fifty",
    "study": "fifty",
    "studying": "fifty",
    "reading": "pomodoro",
    "meeting": "pomodoro",
    "writing": "pomodoro",
}

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now_iso():
    return datetime.now().strftime(_TIME_FORMAT)


def _format_clock(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class FocusManager:
    """One focus session at a time. ``clock`` is injectable for tests."""

    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._session = None  # dict while a session/break is active
        self.held_notifications = []

    # -- state ------------------------------------------------------------

    @property
    def active(self):
        return self._session is not None

    @property
    def on_break(self):
        return self.active and self._session["phase"] == "break"

    def status(self):
        """'idle', 'focus', 'break', or 'paused'."""
        if not self.active:
            return "idle"
        if self._session.get("paused"):
            return "paused"
        return self._session["phase"]

    def current(self):
        """The active session dict, or None. (A copy — read-only.)"""
        return dict(self._session) if self._session else None

    # -- lifecycle --------------------------------------------------------

    def start(self, work_minutes, task="", profile="custom",
              break_minutes=5):
        """Start a focus session. Returns the session dict.

        Raises ValueError for a non-positive duration.
        """
        if work_minutes <= 0:
            raise ValueError("A focus session needs a positive length.")
        now = self._clock()
        self._session = {
            "task": task,
            "profile": profile,
            "work_seconds": int(work_minutes * 60),
            "break_seconds": int(break_minutes * 60),
            "phase": "focus",
            "started_at": _now_iso(),
            "started_mono": now,
            "elapsed_before_pause": 0.0,
            "paused": False,
            "paused_at": None,
        }
        return self.current()

    def start_preset(self, name, task=""):
        """Start a named preset ('pomodoro' / 'fifty')."""
        preset = PRESETS[name]
        profile = PROFILES.get(task.lower(), name) if task else name
        return self.start(
            preset["work_minutes"], task=task, profile=profile,
            break_minutes=preset["break_minutes"],
        )

    def start_for_task(self, task, work_minutes=None, break_minutes=5):
        """Start a session for a task word, picking its profile preset.

        An explicit ``work_minutes`` overrides the preset length.
        """
        preset_name = PROFILES.get(task.lower(), "pomodoro")
        preset = PRESETS[preset_name]
        return self.start(
            work_minutes if work_minutes else preset["work_minutes"],
            task=task, profile=preset_name,
            break_minutes=break_minutes if work_minutes
            else preset["break_minutes"],
        )

    def pause(self):
        """Pause the clock. Returns True when something was paused."""
        if not self.active or self._session.get("paused"):
            return False
        # Bank the time elapsed in the segment that just ended.
        self._session["elapsed_before_pause"] += (
            self._clock() - self._session["started_mono"]
        )
        self._session["paused"] = True
        self._session["paused_at"] = self._clock()
        return True

    def resume(self):
        """Resume a paused session. Returns True when resumed."""
        if not self.active or not self._session.get("paused"):
            return False
        # A fresh segment starts now; the banked time stays banked.
        self._session["started_mono"] = self._clock()
        self._session["paused"] = False
        self._session["paused_at"] = None
        return True

    def _elapsed(self):
        if not self.active:
            return 0.0
        if self._session.get("paused"):
            return self._session["elapsed_before_pause"]
        return (
            self._session["elapsed_before_pause"]
            + self._clock() - self._session["started_mono"]
        )

    def elapsed_seconds(self):
        return int(self._elapsed())

    def remaining_seconds(self):
        """Seconds left in the current phase (focus or break)."""
        if not self.active:
            return 0
        total = (
            self._session["break_seconds"]
            if self._session["phase"] == "break"
            else self._session["work_seconds"]
        )
        return max(0, int(total - self._elapsed()))

    def status_line(self):
        """One line for the pill / Control Center, e.g. 'Focus: 24:31 left'."""
        if not self.active:
            return ""
        if self._session.get("paused"):
            return (
                f"Focus paused — {_format_clock(self.remaining_seconds())}"
                " left"
            )
        if self._session["phase"] == "break":
            return f"Break: {_format_clock(self.remaining_seconds())} left"
        task = self._session["task"]
        label = f" · {task}" if task else ""
        return f"Focus: {_format_clock(self.remaining_seconds())} left{label}"

    # -- finishing ----------------------------------------------------------

    def _finish(self, memory, status):
        """Record the finished phase to history and clear the session."""
        session = self._session
        if session is None:
            return None
        ended = _now_iso()
        if memory is not None and session["phase"] == "focus":
            memory.record_focus_session(
                task=session["task"],
                profile=session["profile"],
                duration_seconds=self._elapsed(),
                started_at=session["started_at"],
                ended_at=ended,
                status=status,
            )
        self._session = None
        return session

    def end(self, memory=None):
        """End the session early. Returns the session dict, or None.

        Held AURA notifications are returned to the caller for restoring
        (see ``flush_held_notifications``); the session is recorded with
        status 'ended_early'.
        """
        if not self.active:
            return None
        return self._finish(memory, "ended_early")

    def start_break(self, memory=None, break_minutes=None):
        """Move a finished focus phase into its break. Returns the break dict.

        The focus phase is recorded as 'completed' first. Returns None
        when no session is active.
        """
        if not self.active or self._session["phase"] != "focus":
            return None
        session = self._session
        if break_minutes is not None:
            session["break_seconds"] = int(break_minutes * 60)
        if memory is not None:
            memory.record_focus_session(
                task=session["task"],
                profile=session["profile"],
                duration_seconds=self._elapsed(),
                started_at=session["started_at"],
                ended_at=_now_iso(),
                status="completed",
            )
        session["phase"] = "break"
        session["started_mono"] = self._clock()
        session["elapsed_before_pause"] = 0.0
        session["paused"] = False
        session["paused_at"] = None
        return self.current()

    def poll(self, memory=None):
        """Check for a finished phase. Returns 'session_done', 'break_done',
        or None. Callers (main.py's reminder loop) speak the result.

        When a focus phase ends, the session moves into its break
        automatically and the break length is the preset's. When the break
        ends, the session clears.
        """
        if not self.active or self._session.get("paused"):
            return None
        if self.remaining_seconds() > 0:
            return None
        if self._session["phase"] == "focus":
            self.start_break(memory)
            return "session_done"
        self._session = None
        return "break_done"

    # -- held notifications -------------------------------------------------

    def hold_notification(self, text):
        """Hold one of AURA's own notification-log entries for later."""
        self.held_notifications.append(text)

    def flush_held_notifications(self, memory=None):
        """Write held notifications back to the log. Returns the list."""
        held = list(self.held_notifications)
        self.held_notifications = []
        if memory is not None:
            for text in held:
                memory.add_notification(text)
        return held
