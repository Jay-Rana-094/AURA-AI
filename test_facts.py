"""Tests for Phase 10.1 — Long-Term Memory (facts + preferences).

Facts are stored ONLY when Jay tells AURA to remember
something ("remember that ...") — never silently harvested.
Secrets are refused. The brain routes these at step 4a, ahead
of notes and the built-in packs, so a fact must never steal a
status question ("what is my gpu usage", "what is my theme").

    python test_facts.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.facts_cmds import (
    execute_facts_command,
    parse_facts_command,
)
from aura.memory import Memory, _looks_like_secret


def main():
    mem = Memory(":memory:")

    # Secrets are refused, whatever the phrasing.
    assert _looks_like_secret("my password is hunter2") is True
    assert _looks_like_secret("the api key is abc123") is True
    assert _looks_like_secret("my token is xyz") is True
    assert _looks_like_secret("the capital of france is paris") is False
    assert _looks_like_secret("my favourite editor is vs code") is False

    # Parser: project facts, preferences, asks, updates, forgets.
    assert parse_facts_command(
        "remember that Nexture's stack is MERN"
    ) == {"action": "save", "project": "Nexture",
          "key": "stack", "value": "MERN"}
    assert parse_facts_command(
        "remember that Nexture is my MERN stack e-commerce project"
    ) == {"action": "save", "project": "Nexture",
          "key": "stack", "value": "MERN stack e-commerce project"}
    assert parse_facts_command(
        "remember my preferred editor is VS Code"
    ) == {"action": "save_preference", "key": "editor",
          "value": "VS Code"}
    assert parse_facts_command(
        "remember my API server uses port 6500"
    ) == {"action": "save", "project": "",
          "key": "api server port", "value": "6500"}
    assert parse_facts_command("what stack does Nexture use?") == {
        "action": "ask", "project": "Nexture", "key": "stack"}
    assert parse_facts_command("what is Nexture's stack?") == {
        "action": "ask", "project": "Nexture", "key": "stack"}
    assert parse_facts_command(
        "what do you remember about Nexture?"
    ) == {"action": "about", "project": "Nexture"}
    assert parse_facts_command("what is my preferred editor?") == {
        "action": "ask_preference", "key": "editor"}
    assert parse_facts_command("update Nexture's port to 7000") == {
        "action": "update", "project": "Nexture",
        "key": "port", "value": "7000"}
    assert parse_facts_command("forget Nexture's port") == {
        "action": "forget", "project": "Nexture", "key": "port"}
    assert parse_facts_command("forget fact number 2") == {
        "action": "forget_number", "number": 2}
    assert parse_facts_command("list what you remember") == {
        "action": "list"}
    # Status questions fall through to their real handlers.
    assert parse_facts_command("what is my gpu usage") is None
    assert parse_facts_command("what is my hotkey") is None
    assert parse_facts_command("what is my morning briefing") is None
    assert parse_facts_command("what is my wake word") is None
    assert parse_facts_command("what is my theme") is None
    # Unrelated phrases don't parse.
    assert parse_facts_command("what is the time") is None
    assert parse_facts_command("remind me to call papa") is None
    # The note guard: a plain "remember that my keys are on the
    # desk" has no fact shape, so it still lands as a note.
    assert parse_facts_command(
        "remember that my keys are on the desk") is None

    # Save a project fact and ask it back, both ways.
    reply = execute_facts_command(
        parse_facts_command("remember that Nexture's stack is MERN"),
        mem)
    assert "remember that Nexture's stack is MERN" in reply, reply
    reply = execute_facts_command(
        parse_facts_command("what stack does Nexture use?"), mem)
    assert "MERN" in reply, reply
    reply = execute_facts_command(
        parse_facts_command("what is Nexture's stack?"), mem)
    assert "MERN" in reply, reply

    # Save a preference and ask it back.
    reply = execute_facts_command(
        parse_facts_command("remember my preferred editor is VS Code"),
        mem)
    assert "Your editor is VS Code" in reply, reply
    reply = execute_facts_command(
        parse_facts_command("what is my preferred editor?"), mem)
    assert "VS Code" in reply, reply

    # "What do you remember about X" lists the project's facts.
    reply = execute_facts_command(
        parse_facts_command("what do you remember about Nexture?"),
        mem)
    assert "MERN" in reply, reply

    # A secret save is refused and stores nothing.
    reply = execute_facts_command(
        parse_facts_command("remember that Nexture's password is hunter2"),
        mem)
    assert "can't store" in reply.lower(), reply
    assert mem.get_fact("Nexture", "password") is None

    # The "that" form of "remember my ..." must reach the same refusal:
    # without it the phrase fell through to the notes pack and was
    # stored as a plain note ("Noted.") instead of being refused.
    cmd = parse_facts_command("remember that my password is hunter2")
    assert cmd is not None and cmd["action"] == "save", cmd
    assert cmd["key"] == "password" and cmd["value"] == "hunter2", cmd
    reply = execute_facts_command(cmd, mem)
    assert "can't store" in reply.lower(), reply
    assert mem.get_fact("", "password") is None

    # Update a fact, then forget it; the other facts survive.
    execute_facts_command(
        parse_facts_command("remember that Nexture's port is 6500"), mem)
    reply = execute_facts_command(
        parse_facts_command("update Nexture's port to 7000"), mem)
    assert "7000" in reply, reply
    assert mem.get_fact("Nexture", "port")["value"] == "7000"
    reply = execute_facts_command(
        parse_facts_command("forget Nexture's port"), mem)
    assert "Forgotten" in reply, reply
    assert mem.get_fact("Nexture", "port") is None
    assert mem.get_fact("Nexture", "stack") is not None

    # "List what you remember" numbers everything; "forget fact
    # number 2" removes one by number.
    reply = execute_facts_command(
        parse_facts_command("list what you remember"), mem)
    assert "1." in reply and "stack" in reply and "editor" in reply, reply
    reply = execute_facts_command(
        parse_facts_command("forget fact number 2"), mem)
    assert "Forgotten" in reply, reply
    assert len(mem.list_facts()) + len(mem.list_preferences()) == 1

    # Asking about nothing stored says so honestly.
    reply = execute_facts_command(
        parse_facts_command("what do you remember about PulseTrade?"),
        mem)
    assert "don't remember anything" in reply, reply
    reply = execute_facts_command(
        parse_facts_command("what is my favourite colour?"), mem)
    assert "haven't told me" in reply, reply

    # --- brain routing (step 4a) --------------------------------
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))
    reply, _ = handle("remember that Nexture's stack is MERN")
    # The brain lowercases all input first, so a voice-saved fact
    # lands lowercase — the reply echoes what was stored.
    assert "remember that nexture's stack is mern" in reply, reply
    reply, _ = handle("what stack does Nexture use?")
    assert "mern" in reply, reply
    # Status questions must NOT be answered as preferences —
    # the reserved-keys guard lets them fall through to the
    # real handlers (GPU / theme / hotkey / morning briefing).
    reply, _ = handle("what is my gpu usage")
    assert "GPU" in reply, reply
    reply, _ = handle("what is my theme")
    assert "theme" in reply.lower(), reply
    reply, _ = handle("what is my hotkey")
    assert "hotkey" in reply.lower(), reply
    # "What is my morning briefing" has no voice handler of its
    # own (the status phrases are "is morning briefing on" /
    # "when is my morning briefing") — the reserved key keeps it
    # falling through to the old honest fallback instead of being
    # answered as a preference.
    reply, _ = handle("what is my morning briefing")
    assert "don't know how to do that yet" in reply, reply
    reply, _ = handle("when is my morning briefing")
    assert "morning" in reply.lower(), reply
    # And the note guard still works end to end.
    reply, _ = handle("remember that my keys are on the desk")
    assert "note" in reply.lower() or "noted" in reply.lower(), reply

    print("test_facts: OK")


if __name__ == "__main__":
    main()
