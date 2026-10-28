"""Tests for Phase 6 theme customization (no window needed — the
GUI recoloring itself needs a real PC, but parsing, persistence
and brain routing are all testable here).

    python test_theme.py
"""

import os
import tempfile

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.theme_cmds import (
    execute_theme_command,
    parse_theme_command,
)
from aura.memory import Memory
from aura.theme import (
    THEMES,
    load_theme_name,
    resolve_theme,
    save_theme_name,
    set_settings_path,
    theme_names_text,
    validate_theme,
)


def main():
    tmp = tempfile.mkdtemp()
    set_settings_path(os.path.join(tmp, "settings.json"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Theme data: every theme complete, violet = original pill. ---
    required = {
        "glow", "pill_outline", "highlight", "orb_fill", "orb_inner",
        "control", "accent", "ring_idle", "label", "bars",
    }
    for name, theme in THEMES.items():
        assert set(theme) == required, name
        assert len(theme["glow"]) == 3 and len(theme["bars"]) == 2, name
    violet = THEMES["violet"]
    assert violet["glow"] == ["#12083a", "#1b0f4d", "#241a66"], violet
    assert violet["pill_outline"] == "#5b8cff"
    assert violet["accent"] == "#35a0ff"

    # --- Persistence: default, round-trip, bad value falls back. ---
    assert load_theme_name() == "violet"
    save_theme_name("emerald")
    assert load_theme_name() == "emerald"
    with open(os.path.join(tmp, "settings.json"), "w") as fh:
        fh.write('{"theme": "not-a-theme"}')
    assert load_theme_name() == "violet"

    # --- Aliases resolve; unknown words do not. ---
    assert resolve_theme("green") == "emerald"
    assert resolve_theme("purple") == "violet"
    assert resolve_theme("pink") == "rose"
    assert resolve_theme("blue") == "ocean"
    assert resolve_theme("ultraviolet") is None
    assert validate_theme("amber") is None
    assert validate_theme("nope") is not None
    assert "emerald" in theme_names_text()

    # --- Parser: every phrasing, and no false friends. ---
    assert parse_theme_command("change theme to emerald")["word"] == "emerald"
    assert parse_theme_command("set the theme to rose")["word"] == "rose"
    assert parse_theme_command("use the amber theme")["word"] == "amber"
    assert parse_theme_command("switch to ocean theme")["word"] == "ocean"
    assert parse_theme_command("make the pill green")["word"] == "green"
    assert parse_theme_command("change theme")["kind"] == "ask"
    assert parse_theme_command("list themes")["kind"] == "list"
    assert parse_theme_command("what is my theme")["kind"] == "current"
    assert parse_theme_command("reset theme")["theme"] == "violet"
    assert parse_theme_command("change theme to ultraviolet")["word"] == (
        "ultraviolet"
    )
    assert parse_theme_command("open notepad") is None
    assert parse_theme_command("what is the time") is None

    # --- Executor: set / already / unknown / list / current. ---
    save_theme_name("violet")
    reply = execute_theme_command({"kind": "set", "word": "emerald"})
    assert "emerald" in reply and load_theme_name() == "emerald", reply
    reply = execute_theme_command({"kind": "set", "word": "emerald"})
    assert "Already" in reply, reply
    reply = execute_theme_command({"kind": "set", "word": "ultraviolet"})
    assert "don't know" in reply and "violet" in reply, reply
    reply = execute_theme_command({"kind": "list"})
    assert "violet" in reply and "ocean" in reply, reply
    reply = execute_theme_command({"kind": "current"})
    assert "emerald" in reply, reply
    reply = execute_theme_command({"kind": "set", "theme": "violet"})
    assert load_theme_name() == "violet", reply

    # --- Voice end to end through handle(). ---
    reply, _ = handle("change theme to rose")
    assert "rose" in reply and load_theme_name() == "rose", reply
    reply, _ = handle("what is my theme")
    assert "rose" in reply, reply

    print("All theme tests passed.")


if __name__ == "__main__":
    main()
