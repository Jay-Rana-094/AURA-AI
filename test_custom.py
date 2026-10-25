"""Tests for Phase 4 custom commands.

Uses a temp JSON file — nothing touches the real custom_commands.json:
    python test_custom.py
The mapped command in the brain round-trip is "what is the time",
a builtin, so no app is ever actually opened by these tests.
"""

import os
import tempfile

from aura.brain import handle, set_custom_store
from aura.commands.custom import CustomStore, parse_custom_management


def main():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # store must start empty, not from a blank file
    store = CustomStore(path)
    set_custom_store(store)

    # --- Parsing ---
    cmd = parse_custom_management("teach aura study time means open vs code")
    assert cmd == {
        "kind": "custom_teach",
        "phrase": "study time",
        "command": "open vs code",
    }, cmd
    assert parse_custom_management("list my custom commands")["kind"] == (
        "custom_list"
    )
    assert parse_custom_management("forget custom command study time") == {
        "kind": "custom_forget",
        "phrase": "study time",
    }
    assert parse_custom_management("open notepad") is None

    # --- Store round-trip ---
    store.add("study time", "what is the time")
    assert store.match("study time") == "what is the time"
    assert store.match("Study Time") == "what is the time"  # case-insensitive
    assert store.match("study") is None  # exact phrase only
    assert store.remove("study time") is True
    assert store.remove("study time") is False
    assert store.match("study time") is None
    # Persistence: a fresh store on the same file sees the data.
    store.add("focus mode", "what is the time")
    assert CustomStore(path).match("focus mode") == "what is the time"

    # --- Brain round-trip ---
    # (Phrase deliberately avoids builtin words like "time", which the
    # builtin time reply would match on its own after forgetting.)
    reply, quit_ = handle("teach aura chill mode means what is the time")
    assert "When you say 'chill mode'" in reply and not quit_, reply
    reply, _ = handle("chill mode")
    assert reply.startswith("It's "), reply  # mapped command ran
    reply, _ = handle("list my custom commands")
    assert "chill mode" in reply and "focus mode" in reply, reply
    reply, _ = handle("forget custom command chill mode")
    assert reply == "Forgot 'chill mode'.", reply
    reply, _ = handle("chill mode")
    assert "don't know how to do that" in reply, reply

    # --- Recursion guard: a custom phrase mapping to itself must not loop.
    store.add("loop test", "loop test")
    reply, _ = handle("loop test")
    assert "don't know how to do that" in reply, reply

    # --- Help ---
    reply, _ = handle("what can you do")
    assert "custom" in reply.lower(), reply

    os.unlink(path)
    print("All Phase 4 custom-command tests passed.")


if __name__ == "__main__":
    main()
