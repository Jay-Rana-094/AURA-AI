"""Tests for Phase 6 daily briefing (no microphone needed).

    python test_briefing.py
"""

import os
import tempfile
from datetime import datetime, timedelta

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.briefing import build_briefing, parse_briefing_command
from aura.commands.custom import CustomStore
from aura.memory import Memory


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)
    now = datetime(2026, 10, 28, 8, 5)  # a Wednesday morning

    # --- Empty day: nothing due, nothing pending. ---
    reply = build_briefing(mem, now)
    assert "Good morning" in reply and "October 28" in reply, reply
    assert "No reminders due today" in reply, reply
    assert "todo list is clear" in reply, reply

    # --- A full day: overdue + today + tomorrow (excluded). ---
    mem.add_reminder("call mom", now - timedelta(hours=1))
    mem.add_reminder("take medicine", now.replace(hour=9, minute=0), "daily")
    mem.add_reminder("team call", now.replace(hour=17, minute=0))
    mem.add_reminder("dentist", now + timedelta(days=1))
    mem.add_todo("finish report", "high")
    mem.add_todo("buy milk")
    mem.add_todo("water plants", "low")
    reply = build_briefing(mem, now)
    assert "Overdue reminders: call mom" in reply, reply
    assert "take medicine at 9:00 AM (every day)" in reply, reply
    assert "team call at 5:00 PM" in reply, reply
    assert "dentist" not in reply, reply  # tomorrow, not today
    assert "Pending todos (3)" in reply, reply
    assert reply.index("finish report") < reply.index("buy milk"), reply
    assert reply.index("buy milk") < reply.index("water plants"), reply
    assert "(high priority)" in reply and "(low priority)" in reply, reply

    # --- Parser: every phrasing, and no false friends. ---
    for phrase in (
        "daily briefing",
        "morning briefing",
        "brief me",
        "good morning",
        "what's my day look like",
        "what's on today",
        "what do i have today",
    ):
        assert parse_briefing_command(phrase) is not None, phrase
    assert parse_briefing_command("open notepad") is None
    assert parse_briefing_command("what is the time") is None

    # --- Voice end to end through handle(). ---
    # handle() uses the real clock, so seed one reminder for today
    # in real terms (the Oct-28 seeds above are "tomorrow" now).
    mem.add_reminder("take medicine", datetime.now() + timedelta(hours=1))
    reply, _ = handle("daily briefing")
    assert "finish report" in reply and "take medicine" in reply, reply
    reply, _ = handle("what do i have today")
    assert "Reminders today" in reply, reply

    print("All daily-briefing tests passed.")


if __name__ == "__main__":
    main()
