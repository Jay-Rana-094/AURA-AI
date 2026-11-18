"""Personality mode voice commands — Phase 10.1.

* "switch to Aura mode" / "switch to professional/minimal/friendly/
  silent mode"
* "what personality mode are you in" / "what mode are you in"
* "turn on silent mode" / "turn off silent mode"

Switching a mode changes only tone, verbosity and voice rate — never
permissions, and never the confirmation rules. The brain records a
``personality_refresh`` gui action (the chat_refresh pattern) so an open
Control Center follows the change.
"""

import re

from aura.personality import PRESETS, describe_mode, load_mode, save_mode

_SWITCH = re.compile(
    r"^(?:switch|change|set)(?: to| my)? (?:the )?(\w+) (?:personality )?mode$",
    re.IGNORECASE,
)
_TURN_ON_SILENT = re.compile(
    r"^(?:turn on|enable) silent mode$",
    re.IGNORECASE,
)
_TURN_OFF_SILENT = re.compile(
    r"^(?:turn off|disable) silent mode$",
    re.IGNORECASE,
)
_ASK_MODE = re.compile(
    r"^what (?:personality )?mode (?:are you in|am i in|is this)\??$",
    re.IGNORECASE,
)


def parse_personality_command(text):
    """Return a dict describing the personality command, or None."""
    if not text:
        return None
    t = text.strip()
    m = _SWITCH.match(t)
    if m:
        mode = m.group(1).lower()
        if mode in PRESETS:
            return {"action": "switch", "mode": mode}
        return {"action": "unknown_mode", "mode": mode}
    if _TURN_ON_SILENT.match(t):
        return {"action": "switch", "mode": "silent"}
    if _TURN_OFF_SILENT.match(t):
        return {"action": "switch", "mode": "friendly"}
    if _ASK_MODE.match(t):
        return {"action": "ask"}
    return None


def execute_personality_command(cmd, _memory=None):
    """Run a parsed personality command. Returns the reply.

    ``_memory`` is accepted for the shared command signature and unused.
    """
    action = cmd["action"]
    if action == "switch":
        if save_mode(cmd["mode"]):
            return describe_mode(cmd["mode"])
        return "I couldn't switch modes — something went wrong saving it."
    if action == "unknown_mode":
        names = ", ".join(sorted(PRESETS))
        return (
            f"I don't have a {cmd['mode']} mode. The modes are: {names}."
        )
    if action == "ask":
        return describe_mode(load_mode())
    return "I don't know how to do that yet."
