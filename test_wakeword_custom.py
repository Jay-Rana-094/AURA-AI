"""Tests for the Phase 5 custom wake word (no microphone needed).

    python test_wakeword_custom.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.memory import Memory
from aura.wake_settings import (
    DEFAULT_WAKE_WORD,
    display_wake_word,
    load_wake_word,
    save_wake_word,
    set_settings_path,
    validate_wake_word,
)
from aura.wakeword import contains_wake_word


def main():
    tmp = tempfile.mkdtemp()
    set_settings_path(os.path.join(tmp, "aura_settings.json"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # Storage: default, save/load round-trip, reset.
    assert load_wake_word() == DEFAULT_WAKE_WORD == "aura"
    save_wake_word("jarvis")
    assert load_wake_word() == "jarvis"
    save_wake_word("hey jarvis")
    assert load_wake_word() == "hey jarvis"
    save_wake_word(DEFAULT_WAKE_WORD)
    assert load_wake_word() == "aura"

    # Validation.
    assert validate_wake_word("jarvis") is None
    assert validate_wake_word("hey jarvis") is None
    assert validate_wake_word("") is not None
    assert validate_wake_word("one two three") is not None
    assert validate_wake_word("jarvis123") is not None
    assert validate_wake_word("goodbye") is not None
    assert validate_wake_word("x" * 21) is not None

    # Display form.
    assert display_wake_word("jarvis") == "Jarvis"
    assert display_wake_word("hey jarvis") == "Hey Jarvis"

    # The matcher already took a word parameter — it just works.
    assert contains_wake_word("hey jarvis open notepad", "jarvis")
    assert not contains_wake_word("hey aura open notepad", "jarvis")

    # Voice commands, end to end through handle().
    reply, quit_ = handle("change my wake word to jarvis")
    assert "Jarvis" in reply and not quit_, reply
    assert load_wake_word() == "jarvis"
    reply, _ = handle("what is my wake word")
    assert "Jarvis" in reply, reply
    reply, _ = handle("set wake word to hey jarvis")
    assert "Hey Jarvis" in reply and load_wake_word() == "hey jarvis"
    reply, _ = handle("change wake word to goodbye")
    assert "close me" in reply and load_wake_word() == "hey jarvis"
    reply, _ = handle("reset wake word")
    assert "Aura" in reply and load_wake_word() == "aura"

    print("All custom wake-word tests passed.")


if __name__ == "__main__":
    main()
