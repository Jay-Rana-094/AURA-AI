"""Tests for Phase 5 task priorities (no microphone needed).

    python test_priorities.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.memory_cmds import parse_memory_command
from aura.memory import Memory


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)

    # --- Storage: priority order high -> medium -> low, id tiebreak. ---
    mem.add_todo("low one", "low")
    mem.add_todo("plain one")  # default medium
    mem.add_todo("high one", "high")
    mem.add_todo("low two", "low")
    order = [r["text"] for r in mem.list_todos()]
    assert order == ["high one", "plain one", "low one", "low two"], order
    assert [r["text"] for r in mem.list_todos("high")] == ["high one"]
    assert [r["text"] for r in mem.list_todos("low")] == [
        "low one",
        "low two",
    ]
    # Numbering follows the same order: completing #1 removes "high one".
    assert mem.complete_todo(1) == "high one"
    # Re-prioritizing moves the item in the list.
    assert mem.set_todo_priority(3, "high") == "low two"
    assert [r["text"] for r in mem.list_todos()][:1] == ["low two"]
    assert mem.set_todo_priority(9, "high") is None

    # --- Parser: priority in every phrasing. ---
    cmd = parse_memory_command("add call mom to my todo list with high priority")
    assert cmd["kind"] == "todo_add" and cmd["priority"] == "high"
    assert cmd["text"] == "call mom", cmd
    cmd = parse_memory_command("add buy milk to my todo list high priority")
    assert cmd["priority"] == "high" and cmd["text"] == "buy milk", cmd
    cmd = parse_memory_command("add high priority task buy milk")
    assert cmd["priority"] == "high" and cmd["text"] == "buy milk", cmd
    cmd = parse_memory_command(
        "add high priority task buy milk to my todo list"
    )
    assert cmd["priority"] == "high" and cmd["text"] == "buy milk", cmd
    cmd = parse_memory_command("add buy milk to my todo list")
    assert cmd["priority"] == "medium" and cmd["text"] == "buy milk", cmd
    cmd = parse_memory_command("set todo 2 to high priority")
    assert cmd["kind"] == "todo_set_priority" and cmd["number"] == 2
    assert cmd["priority"] == "high", cmd
    cmd = parse_memory_command("mark todo 1 as low priority")
    assert cmd["kind"] == "todo_set_priority" and cmd["priority"] == "low"
    cmd = parse_memory_command("list my high priority todos")
    assert cmd["kind"] == "todo_list_priority" and cmd["priority"] == "high"

    # --- Voice end to end through handle(). ---
    mem2 = Memory(":memory:")
    set_memory(mem2)
    reply, _ = handle("add finish report to my todo list with high priority")
    assert "high priority" in reply and "finish report" in reply, reply
    reply, _ = handle("add buy milk to my todo list")
    assert "Added to your todo list: buy milk" in reply, reply
    reply, _ = handle("list my todos")
    assert reply.index("finish report") < reply.index("buy milk"), reply
    assert "[high]" in reply, reply
    reply, _ = handle("set todo 2 to high priority")
    assert "set to high priority" in reply, reply
    reply, _ = handle("list my high priority todos")
    assert "finish report" in reply and "buy milk" in reply, reply
    reply, _ = handle("complete todo 1")
    assert reply.startswith("Done:"), reply

    print("All task-priority tests passed.")


if __name__ == "__main__":
    main()
