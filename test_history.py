"""Tests for Phase 5 conversation history (no microphone needed).

    python test_history.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.history_cmds import parse_history_command
from aura.memory import Memory


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)

    # --- Storage: newest first, search both sides, prune at 200. ---
    mem.add_turn("open notepad", "Opening notepad.")
    mem.add_turn("what is the time", "It's 10:30 AM.")
    mem.add_turn("remind me to call mom at 5 pm", "Reminder set.")
    recent = [r["user_text"] for r in mem.recent_turns(2)]
    assert recent == [
        "remind me to call mom at 5 pm",
        "what is the time",
    ], recent
    found = [r["user_text"] for r in mem.search_turns("notepad")]
    assert found == ["open notepad"], found
    found = [r["user_text"] for r in mem.search_turns("10:30")]
    assert found == ["what is the time"], found  # match in the reply
    assert mem.search_turns("zebra") == []
    for i in range(205):
        mem.add_turn(f"turn {i}", "reply")
    assert len(mem.recent_turns(500)) == 200
    mem.clear_turns()
    assert mem.recent_turns() == []

    # --- Parser: recent vs topic vs last vs clear. ---
    cmd = parse_history_command("what did we talk about")
    assert cmd["kind"] == "history_recent", cmd
    cmd = parse_history_command("show our conversation")
    assert cmd["kind"] == "history_recent", cmd
    cmd = parse_history_command("what did we talk about notepad")
    assert cmd["kind"] == "history_search" and cmd["topic"] == "notepad", cmd
    cmd = parse_history_command("what did you say about reminders")
    assert cmd["kind"] == "history_search" and cmd["topic"] == "reminders"
    cmd = parse_history_command("what did you just say")
    assert cmd["kind"] == "history_last", cmd
    cmd = parse_history_command("clear conversation history")
    assert cmd["kind"] == "history_clear", cmd
    assert parse_history_command("open notepad") is None

    # --- Voice end to end through handle(). ---
    mem.add_turn("open notepad", "Opening notepad.")
    mem.add_turn("what is the time", "It's 10:30 AM.")
    reply, _ = handle("what did we talk about")
    assert "open notepad" in reply and "10:30" in reply, reply
    reply, _ = handle("what did you say about notepad")
    assert "open notepad" in reply and "10:30" not in reply, reply
    reply, _ = handle("what did you just say")
    assert "10:30" in reply, reply
    reply, _ = handle("what did you say about zebra")
    assert "don't have anything about zebra" in reply, reply
    reply, _ = handle("clear conversation history")
    assert "cleared" in reply, reply
    reply, _ = handle("what did we talk about")
    assert "haven't talked" in reply, reply

    print("All conversation-history tests passed.")


if __name__ == "__main__":
    main()
