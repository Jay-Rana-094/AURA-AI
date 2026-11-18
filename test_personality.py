"""Tests for Phase 10.1 — Personality Modes.

Presets are data in aura_settings.json, not code branches:
tone, verbosity, voice rate and whether speech is on. The
"Jarvis" preset was renamed to "Aura" at Jay's word
(2026-11-17) — "Alfred" was never the name, and no preset is
called Jarvis any more.

    python test_personality.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.memory import Memory
from aura.personality import (
    DEFAULT_MODE,
    PRESETS,
    describe_mode,
    format_reply,
    is_silent,
    load_mode,
    personality_status,
    save_mode,
    voice_rate,
)
from aura.personality import set_settings_path


def main():
    tmp = tempfile.mkdtemp()
    set_settings_path(os.path.join(tmp, "settings.json"))

    # The five presets, exactly as designed.
    assert tuple(PRESETS) == (
        "aura", "professional", "minimal", "friendly", "silent",
    ), tuple(PRESETS)
    assert "jarvis" not in PRESETS
    assert "alfred" not in PRESETS
    for code, preset in PRESETS.items():
        assert preset["label"], code
        assert preset["style"], code
        assert preset["verbosity"] in ("medium", "short", "minimal"), code
        assert isinstance(preset["speech"], bool), code
        assert 100 <= preset["voice_rate"] <= 220, code

    # Default is friendly; an unknown saved name falls back to it.
    assert load_mode() == DEFAULT_MODE == "friendly"
    assert save_mode("aura") is True
    assert load_mode() == "aura"
    assert save_mode("not-a-mode") is False
    assert load_mode() == "aura"

    # Voice rates come from the data, per mode.
    save_mode("aura")
    assert voice_rate() == 175
    save_mode("professional")
    assert voice_rate() == 165
    save_mode("minimal")
    assert voice_rate() == 180
    save_mode("friendly")
    assert voice_rate() == 175
    save_mode("silent")
    assert voice_rate() == 175

    # Only Silent turns speech off.
    save_mode("friendly")
    assert is_silent() is False
    save_mode("silent")
    assert is_silent() is True
    save_mode("aura")
    assert is_silent() is False

    # Friendly leaves a reply untouched.
    save_mode("friendly")
    reply = "The time is 10:00 AM."
    assert format_reply(reply) == reply

    # Aura and Professional rephrase the canned lines (tone),
    # and leave anything else untouched.
    save_mode("aura")
    assert format_reply(
        "Hey Jay... how can I help you today?"
    ) == "Good to see you, Jay. How may I assist?"
    assert format_reply("Goodbye, Jay.") == "Very well, sir. Powering down."
    assert format_reply("Okay.") == "Consider it done."
    assert format_reply("The time is 10:00 AM.") == "The time is 10:00 AM."
    save_mode("professional")
    assert format_reply(
        "Hey Jay... how can I help you today?"
    ) == "Hello. How can I help?"
    assert format_reply("Goodbye, Jay.") == "Goodbye."
    assert format_reply("Okay.") == "Done."
    save_mode("minimal")
    assert format_reply(
        "Hey Jay... how can I help you today?"
    ) == "Ready."
    assert format_reply("Goodbye, Jay.") == "Bye."
    # Minimal is terse: a long reply is cut to its first sentence.
    long = "The time is 10:00 AM. Your next reminder is at noon."
    assert format_reply(long) == "The time is 10:00 AM."
    # Questions and failure replies are never trimmed, in any
    # mode — cutting those would hide what AURA needs or what
    # went wrong.
    save_mode("minimal")
    assert format_reply(
        "I don't know how to do that yet."
    ) == "I don't know how to do that yet."
    assert format_reply(
        "Are you sure you want to shut down?"
    ) == "Are you sure you want to shut down?"
    # Silent formats like minimal — silence is a speaking
    # decision in main.py, not a text change.
    save_mode("silent")
    assert format_reply(reply) == reply

    # describe_mode + the Control Center status dict.
    save_mode("aura")
    line = describe_mode()
    assert "Aura" in line and "polished" in line, line
    assert "medium replies" in line
    status = personality_status()
    assert status["mode"] == "aura"
    assert status["label"] == "Aura"
    assert status["description"] == line
    save_mode("silent")
    assert "no spoken replies" in describe_mode()

    # --- brain routing (step 4d2) --------------------------------
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))
    save_mode("friendly")
    reply, _ = handle("switch to Aura mode")
    assert "Aura" in reply and load_mode() == "aura", reply
    reply, _ = handle("what mode are you in")
    assert "Aura" in reply, reply
    reply, _ = handle("switch to jarvis mode")
    assert "don't have a jarvis mode" in reply.lower(), reply
    assert "aura" in reply.lower() and "silent" in reply.lower(), reply
    reply, _ = handle("turn on silent mode")
    assert load_mode() == "silent"
    assert "no spoken replies" in reply, reply
    reply, _ = handle("turn off silent mode")
    assert load_mode() == "friendly"
    save_mode("friendly")

    print("test_personality: OK")


if __name__ == "__main__":
    main()
