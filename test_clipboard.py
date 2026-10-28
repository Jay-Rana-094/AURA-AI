"""Tests for Phase 6 clipboard control (no Windows box needed —
the PowerShell accessors are stubbed; parsing and routing are real).

    python test_clipboard.py
"""

import os
import tempfile

import aura.commands.clipboard_cmds as cc
from aura.brain import handle, set_custom_store, set_memory
from aura.commands.clipboard_cmds import (
    execute_clipboard_command,
    parse_clipboard_command,
)
from aura.commands.custom import CustomStore
from aura.memory import Memory


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)

    # --- Parser: every phrasing, and no false friends. ---
    assert parse_clipboard_command("what's on my clipboard")["kind"] == "read"
    assert parse_clipboard_command("read my clipboard")["kind"] == "read"
    assert parse_clipboard_command("show clipboard")["kind"] == "read"
    assert parse_clipboard_command("check the clipboard")["kind"] == "read"
    assert parse_clipboard_command("what did i copy")["kind"] == "read"
    assert parse_clipboard_command("copy that")["kind"] == "copy_last"
    assert parse_clipboard_command("copy that to clipboard")["kind"] == (
        "copy_last"
    )
    assert parse_clipboard_command("copy your last reply")["kind"] == (
        "copy_last"
    )
    cmd = parse_clipboard_command("copy hello world to clipboard")
    assert cmd["kind"] == "copy_text" and cmd["text"] == "hello world", cmd
    assert parse_clipboard_command("clear my clipboard")["kind"] == "clear"
    assert parse_clipboard_command("empty the clipboard")["kind"] == "clear"
    assert parse_clipboard_command("open notepad") is None
    assert parse_clipboard_command("what is the time") is None
    assert parse_clipboard_command("remind me to call mom") is None

    # --- Executor with stubbed clipboard. ---
    written = []
    cleared = []
    cc._read_clipboard = lambda: "buy milk tomorrow"
    cc._write_clipboard = lambda text: written.append(text) or True
    cc._clear_clipboard = lambda: cleared.append(True) or True

    reply = execute_clipboard_command({"kind": "read"}, mem)
    assert "buy milk tomorrow" in reply, reply

    cc._read_clipboard = lambda: ""
    reply = execute_clipboard_command({"kind": "read"}, mem)
    assert "empty" in reply, reply

    cc._read_clipboard = lambda: None
    reply = execute_clipboard_command({"kind": "read"}, mem)
    assert "couldn't read" in reply, reply

    reply = execute_clipboard_command(
        {"kind": "copy_text", "text": "hello world"}, mem
    )
    assert "hello world" in reply and written[-1] == "hello world", reply

    reply = execute_clipboard_command({"kind": "copy_last"}, mem)
    assert "haven't said anything" in reply, reply
    mem.add_turn("what is the time", "It is 8 PM.")
    reply = execute_clipboard_command({"kind": "copy_last"}, mem)
    assert "last reply" in reply and written[-1] == "It is 8 PM.", reply

    reply = execute_clipboard_command({"kind": "clear"}, mem)
    assert "cleared" in reply and cleared, reply

    # Long clipboard text is trimmed for speech, mid-word cuts avoided.
    cc._read_clipboard = lambda: "word " * 100
    reply = execute_clipboard_command({"kind": "read"}, mem)
    assert reply.endswith("…") and len(reply) < 400, reply

    # --- Voice end to end through handle(). ---
    cc._read_clipboard = lambda: "meeting at 5 pm"
    reply, _ = handle("what's on my clipboard")
    assert "meeting at 5 pm" in reply, reply
    reply, _ = handle("copy that")
    assert "last reply" in reply and written[-1] == "It is 8 PM.", reply

    print("All clipboard tests passed.")


if __name__ == "__main__":
    main()
