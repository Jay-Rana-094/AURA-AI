"""Tests for the Phase 6 notification center (no microphone needed).

    python test_notifications.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.notify_cmds import (
    execute_notification_command,
    parse_notification_command,
)
from aura.memory import Memory


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)

    # --- Memory: newest first, read marking, clearing, pruning. ---
    mem.add_notification("Reminder: take medicine")
    mem.add_notification("Reminder: team call")
    mem.add_notification("Reminder: drink water")
    assert mem.unread_notification_count() == 3
    rows = mem.unread_notifications(5)
    assert rows[0]["text"] == "Reminder: drink water", rows[0]["text"]
    assert rows[-1]["text"] == "Reminder: take medicine"
    mem.mark_notifications_read()
    assert mem.unread_notification_count() == 0
    assert mem.unread_notifications(5) == []
    mem.add_notification("Reminder: call mom")
    mem.clear_notifications()
    assert mem.unread_notification_count() == 0

    mem2 = Memory(":memory:")
    for i in range(55):
        mem2.add_notification(f"note {i}")
    assert len(mem2.unread_notifications(100)) == 50
    assert mem2.unread_notifications(100)[0]["text"] == "note 54"

    # --- Parser: every phrasing, and no false friends. ---
    assert parse_notification_command(
        "what notifications do i have")["kind"] == "list"
    assert parse_notification_command(
        "show my notifications")["kind"] == "list"
    assert parse_notification_command("any notifications")["kind"] == "list"
    assert parse_notification_command(
        "do i have notifications")["kind"] == "list"
    assert parse_notification_command("notifications")["kind"] == "list"
    assert parse_notification_command(
        "how many notifications")["kind"] == "count"
    assert parse_notification_command(
        "clear my notifications")["kind"] == "clear"
    assert parse_notification_command(
        "dismiss notifications")["kind"] == "clear"
    assert parse_notification_command("open notepad") is None
    assert parse_notification_command("what is the time") is None
    assert parse_notification_command("remind me to call mom") is None

    # --- Executor: list marks read, count, clear. ---
    mem.add_notification("Reminder: take medicine")
    mem.add_notification("Reminder: team call")
    reply = execute_notification_command({"kind": "count"}, mem)
    assert "2 new notifications" in reply, reply
    reply = execute_notification_command({"kind": "list"}, mem)
    assert "2 new notifications" in reply, reply
    assert "take medicine" in reply and "team call" in reply, reply
    reply = execute_notification_command({"kind": "list"}, mem)
    assert "No new notifications" in reply, reply
    mem.add_notification("Reminder: call mom")
    reply = execute_notification_command({"kind": "clear"}, mem)
    assert "cleared" in reply and mem.unread_notification_count() == 0, reply

    # --- Voice end to end through handle(). ---
    mem.add_notification("Reminder: water plants")
    reply, _ = handle("what notifications do i have")
    assert "water plants" in reply, reply
    reply, _ = handle("how many notifications")
    assert "No new notifications" in reply, reply

    print("All notification tests passed.")


if __name__ == "__main__":
    main()
