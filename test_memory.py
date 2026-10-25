"""Tests for Phase 3 memory (notes, todos, reminders).

Uses an in-memory SQLite DB — nothing is written to disk:
    python test_memory.py
"""

from datetime import datetime, timedelta

from aura.brain import handle, set_memory
from aura.commands.memory_cmds import _parse_time, parse_memory_command
from aura.memory import Memory


def main():
    mem = Memory(":memory:")
    set_memory(mem)

    # --- Time parsing ---
    when, rest = _parse_time("call mom in 30 minutes")
    assert when is not None and rest == "call mom"
    assert timedelta(minutes=29) < when - datetime.now() < timedelta(
        minutes=31
    )
    when, rest = _parse_time("go for a walk in 2 hours")
    assert rest == "go for a walk" and when.hour == (
        datetime.now() + timedelta(hours=2)
    ).hour
    when, _ = _parse_time("meeting at 5 pm")
    assert when.hour == 17
    when, _ = _parse_time("meeting at 5:30 pm")
    assert (when.hour, when.minute) == (17, 30)
    when, _ = _parse_time("meeting at 17:30")
    assert (when.hour, when.minute) == (17, 30)
    when, _ = _parse_time("call tomorrow at 9 am")
    assert when.date() == (datetime.now() + timedelta(days=1)).date()
    assert when.hour == 9
    when, _ = _parse_time("no time here")
    assert when is None
    # Spoken number words (the Phase 3.0 reminder bug)
    when, rest = _parse_time("stretch in one minute")
    assert when is not None and rest == "stretch"
    when, rest = _parse_time("stretch in a minute")
    assert when is not None and rest == "stretch"
    when, rest = _parse_time("walk in half an hour")
    assert when is not None and rest == "walk"
    when, _ = _parse_time("meeting at five pm")
    assert when.hour == 17
    when, _ = _parse_time("call tomorrow at nine am")
    assert when.hour == 9
    assert parse_memory_command("remind me to stretch in one minute")[
        "kind"
    ] == "reminder_add"

    # --- Command parsing ---
    assert parse_memory_command("remember that my keys are on the desk")[
        "kind"
    ] == "note_add"
    assert parse_memory_command("remind me to call mom in 10 minutes")[
        "kind"
    ] == "reminder_add"
    assert parse_memory_command("remind me to call mom")["kind"] == "todo_add"
    assert parse_memory_command("add buy milk to my todo list")["kind"] == (
        "todo_add"
    )
    assert parse_memory_command("what are my todos")["kind"] == "todo_list"
    assert parse_memory_command("complete todo 2")["kind"] == "todo_complete"
    assert parse_memory_command("cancel reminder 1")["kind"] == (
        "reminder_cancel"
    )
    assert parse_memory_command("open notepad") is None  # Phase 2, not memory

    # --- Brain round-trip: notes ---
    reply, quit_ = handle("remember that my keys are on the desk")
    assert reply == "Noted." and not quit_, reply
    reply, _ = handle("what are my notes")
    assert "keys are on the desk" in reply, reply
    reply, _ = handle("delete note 1")
    assert reply.startswith("Deleted note"), reply
    reply, _ = handle("what are my notes")
    assert "don't have any notes" in reply, reply

    # --- Brain round-trip: todos ---
    handle("add buy milk to my todo list")
    reply, _ = handle("remind me to call mom")  # no time -> todo
    assert "instead of setting a reminder" in reply, reply
    reply, _ = handle("what are my todos")
    assert "buy milk" in reply and "call mom" in reply, reply
    reply, _ = handle("complete todo 1")
    assert reply == "Done: buy milk.", reply
    reply, _ = handle("what are my todos")
    assert "buy milk" not in reply and "call mom" in reply, reply

    # --- Brain round-trip: reminders + due logic ---
    handle("remind me to stretch in 1 minutes")
    assert len(mem.list_reminders()) == 1
    assert mem.due_reminders() == []  # not due yet
    mem.add_reminder("past item", datetime.now() - timedelta(minutes=1))
    due = mem.due_reminders()
    assert len(due) == 1 and due[0]["text"] == "past item"
    mem.mark_notified(due[0]["id"])
    assert mem.due_reminders() == []
    reply, _ = handle("cancel reminder 1")
    assert reply.startswith("Cancelled reminder"), reply

    print("All Phase 3 memory tests passed.")


if __name__ == "__main__":
    main()
