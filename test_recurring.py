"""Tests for Phase 5 recurring reminders (no microphone needed).

    python test_recurring.py
"""

import os
import tempfile
from datetime import datetime, timedelta

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.memory_cmds import parse_memory_command
from aura.memory import Memory


def _fmt(when):
    return when.strftime("%Y-%m-%d %H:%M:%S")


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)
    now = datetime.now()

    # --- Storage: daily advances to tomorrow, weekly by 7 days. ---
    mem.add_reminder("vitamins", now - timedelta(days=1), "daily")
    mem.add_reminder("call mom", now - timedelta(days=8), "weekly")
    mem.add_reminder("one-shot", now - timedelta(hours=1), None)
    due = mem.due_reminders()
    assert len(due) == 3, [r["text"] for r in due]

    mem.mark_notified(due[0]["id"])  # daily
    mem.mark_notified(due[1]["id"])  # weekly
    mem.mark_notified(due[2]["id"])  # one-shot
    assert [r["text"] for r in mem.due_reminders()] == []
    rows = {r["text"]: r for r in mem.list_reminders()}
    assert "one-shot" not in rows  # finished
    daily_next = datetime.strptime(rows["vitamins"]["remind_at"], "%Y-%m-%d %H:%M:%S")
    assert daily_next > now and daily_next <= now + timedelta(days=1), daily_next
    weekly_next = datetime.strptime(rows["call mom"]["remind_at"], "%Y-%m-%d %H:%M:%S")
    assert weekly_next > now and weekly_next <= now + timedelta(days=7), weekly_next
    assert weekly_next.weekday() == (now - timedelta(days=8)).weekday()
    assert len(mem.list_recurring()) == 2

    # --- Parser: repeat phrases in both word orders. ---
    cmd = parse_memory_command("remind me to take medicine every day at 9 am")
    assert cmd["kind"] == "reminder_add" and cmd["recurrence"] == "daily"
    assert cmd["text"] == "take medicine", cmd
    cmd = parse_memory_command("remind me to call mom every monday at 8 am")
    assert cmd["kind"] == "reminder_add" and cmd["recurrence"] == "weekly"
    assert cmd["text"] == "call mom", cmd
    assert cmd["when"].weekday() == 0  # Monday
    cmd = parse_memory_command("remind me every day at 9 am to drink water")
    assert cmd["kind"] == "reminder_add" and cmd["recurrence"] == "daily"
    assert cmd["text"] == "drink water", cmd
    cmd = parse_memory_command("remind me to stretch every day")
    assert cmd["kind"] == "reminder_recurring_no_time", cmd
    cmd = parse_memory_command("remind me to call mom at 5 pm")
    assert cmd["kind"] == "reminder_add" and cmd["recurrence"] is None, cmd
    cmd = parse_memory_command("list my recurring reminders")
    assert cmd["kind"] == "reminder_recurring_list", cmd
    cmd = parse_memory_command("cancel recurring reminder 2")
    assert cmd["kind"] == "reminder_recurring_cancel" and cmd["number"] == 2

    # --- Voice end to end through handle(). ---
    reply, _ = handle("remind me to water plants every day at 7 am")
    assert "Repeating every day" in reply and "water plants" in reply, reply
    reply, _ = handle("list my recurring reminders")
    assert "water plants" in reply and "every day" in reply, reply
    reply, _ = handle("remind me to stretch every day")
    assert "need a time" in reply, reply
    pos = [r["text"] for r in mem.list_recurring()].index("water plants") + 1
    reply, _ = handle(f"cancel recurring reminder {pos}")
    assert "Cancelled repeating reminder: water plants" in reply, reply

    print("All recurring-reminder tests passed.")


if __name__ == "__main__":
    main()
