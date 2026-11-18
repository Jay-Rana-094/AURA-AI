"""Tests for Phase 10.1 — Focus Mode.

Sessions run on a monotonic clock (immune to the system clock
changing mid-session). The FocusManager takes an injectable
clock, so the tests fake time with a one-element list — no
real waiting is needed.

    python test_focus.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.focus_cmds import (
    execute_focus_command,
    parse_focus_command,
)
from aura.focus import PRESETS, PROFILES, FocusManager
from aura.memory import Memory


def _manager():
    """A FocusManager plus its fake clock.

    Returns (manager, clock) where clock is a one-element list
    holding "now" — advance it to move time forward.
    """
    clock = [1000.0]
    return FocusManager(clock=lambda: clock[0]), clock


def main():
    mem = Memory(":memory:")

    # Presets and profiles are data, not branches.
    assert set(PRESETS) == {"pomodoro", "fifty"}
    assert PRESETS["pomodoro"] == {
        "work_minutes": 25, "break_minutes": 5, "label": "Pomodoro"}
    assert PRESETS["fifty"]["work_minutes"] == 50
    assert PROFILES["coding"] == "fifty"
    assert PROFILES["study"] == "fifty"
    assert PROFILES["reading"] == "pomodoro"
    assert PROFILES["meeting"] == "pomodoro"

    # A session starts, reports its remaining time.
    focus, clock = _manager()
    session = focus.start(25)
    assert focus.active is True
    assert focus.status() == "focus"
    assert session["work_seconds"] == 25 * 60
    assert focus.remaining_seconds() == 25 * 60
    assert focus.status_line() == "Focus: 25:00 left"

    # Time passes: the remaining time falls.
    clock[0] += 600
    assert focus.remaining_seconds() == 15 * 60
    assert focus.elapsed_seconds() == 600
    assert focus.poll(mem) is None  # not done yet

    # Pause freezes the clock; resume picks up where it left.
    assert focus.pause() is True
    assert focus.status() == "paused"
    assert focus.status_line() == "Focus paused — 15:00 left"
    clock[0] += 1800
    assert focus.remaining_seconds() == 15 * 60
    assert focus.pause() is False  # already paused
    assert focus.resume() is True
    assert focus.status() == "focus"
    clock[0] += 840
    assert focus.remaining_seconds() == 60
    assert focus.poll(mem) is None

    # The session ends at zero — and a 5-minute break starts
    # (the default break for a 25-minute session).
    clock[0] += 120
    assert focus.poll(mem) == "session_done"
    assert focus.on_break is True
    assert focus.status() == "break"
    assert focus.status_line() == "Break: 05:00 left"
    assert focus.poll(mem) is None
    clock[0] += 300
    assert focus.poll(mem) == "break_done"
    assert focus.active is False
    assert focus.status() == "idle"
    assert focus.status_line() == ""

    # The finished session is in history, completed.
    sessions = mem.list_focus_sessions()
    assert len(sessions) == 1, sessions
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["duration_seconds"] >= 25 * 60

    # Ending early records the session as ended_early.
    focus.start(45, task="report")
    clock[0] += 300
    ended = focus.end(mem)
    assert ended is not None
    assert focus.active is False
    sessions = mem.list_focus_sessions()
    assert len(sessions) == 2
    assert sessions[0]["status"] == "ended_early"
    assert sessions[0]["task"] == "report"
    assert focus.end(mem) is None  # nothing running

    # A zero/negative length is refused (a bad voice parse must
    # never start a session).
    try:
        focus.start(0)
    except ValueError:
        pass
    else:
        raise AssertionError("start(0) was accepted")
    assert focus.active is False

    # Presets: pomodoro is 25/5, a coding task picks fifty (50/10).
    focus.start_preset("pomodoro")
    assert focus.remaining_seconds() == 25 * 60
    focus.end(mem)
    focus.start_for_task("coding")
    assert focus.remaining_seconds() == 50 * 60
    focus.end(mem)
    focus.start_for_task("reading")
    assert focus.remaining_seconds() == 25 * 60
    focus.end(mem)

    # Notifications are held during a session and flushed when
    # it ends — they are never lost, just delayed.
    focus.start(25)
    focus.hold_notification("Reminder: call Papa")
    focus.hold_notification("Morning briefing spoken.")
    assert focus.held_notifications == [
        "Reminder: call Papa", "Morning briefing spoken."]
    focus.end(mem)
    held = focus.flush_held_notifications(mem)
    assert held == ["Reminder: call Papa", "Morning briefing spoken."]
    assert focus.held_notifications == []
    assert mem.unread_notification_count() == 2

    # Polling with no memory store never crashes (a missing DB
    # must not freeze AURA mid-session).
    focus.start(1)
    clock[0] += 120
    assert focus.poll(None) == "session_done"
    assert focus.on_break is True

    # --- parser shapes -------------------------------------------
    assert parse_focus_command("start a 25-minute coding session") == {
        "action": "start", "minutes": 25, "task": "coding", "for": ""}
    assert parse_focus_command("start a focus session for 25 minutes") == {
        "action": "start", "minutes": 25, "task": ""}
    assert parse_focus_command("start Pomodoro") == {
        "action": "start_preset", "preset": "pomodoro", "task": ""}
    assert parse_focus_command("start a 50/10 session") == {
        "action": "start_preset", "preset": "fifty", "task": ""}
    assert parse_focus_command("start a coding session") == {
        "action": "start_task", "task": "coding", "for": ""}
    assert parse_focus_command("pause my focus session") == {
        "action": "pause"}
    assert parse_focus_command("resume focus") == {"action": "resume"}
    assert parse_focus_command(
        "how much time is left in my focus session?") == {
        "action": "remaining"}
    assert parse_focus_command("how long is my focus session") == {
        "action": "remaining"}
    assert parse_focus_command("how long have i been focusing?") == {
        "action": "elapsed"}
    assert parse_focus_command("end focus mode") == {"action": "end"}
    assert parse_focus_command("start a break for 10 minutes") == {
        "action": "break", "minutes": 10}
    assert parse_focus_command("focus history") == {"action": "history"}
    assert parse_focus_command("what is the time") is None

    # --- executor: guards + todo linking --------------------------
    focus2, _clock2 = _manager()
    mem2 = Memory(":memory:")
    mem2.add_todo("finish report for Friday")
    reply = execute_focus_command(
        parse_focus_command("start a 30-minute session for report"),
        focus2, mem2)
    assert "30 minutes" in reply and "finish report" in reply, reply
    assert focus2.current()["task"] == "finish report for Friday"
    # A second start while one is running is refused.
    reply = execute_focus_command(
        parse_focus_command("start a 10-minute session"), focus2, mem2)
    assert "already in a focus session" in reply, reply
    # An unmatchable todo link is honest, not a silent start.
    focus2.end(mem2)
    reply = execute_focus_command(
        parse_focus_command("start a 30-minute session for nope"),
        focus2, mem2)
    assert "couldn't find a todo" in reply, reply
    assert focus2.active is False
    # History with no finished sessions says so honestly — and
    # a deliberately ended session IS in history (it was recorded
    # as ended_early, so the list shows it).
    reply = execute_focus_command({"action": "history"}, focus2, mem2)
    assert "ended_early" in reply and "finish report" in reply, reply
    reply = execute_focus_command(
        {"action": "history"}, focus2, Memory(":memory:"))
    assert "haven't finished" in reply, reply

    # --- brain routing (step 4o) ----------------------------------
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))
    reply, _ = handle("start a focus session for 25 minutes")
    assert "Focus started" in reply and "25 minutes" in reply, reply
    reply, _ = handle("how long is my focus session")
    assert "Focus:" in reply, reply
    reply, _ = handle("pause focus")
    assert "paused" in reply.lower(), reply
    reply, _ = handle("resume focus")
    assert "resumed" in reply.lower(), reply
    reply, _ = handle("end focus")
    assert "ended" in reply.lower(), reply
    reply, _ = handle("focus history")
    assert "haven't finished" in reply or "recent focus" in reply, reply

    print("test_focus: OK")


if __name__ == "__main__":
    main()
