"""Voice commands for pill themes — Phase 6.

Parsing is separated from execution, like the other packs. The
executor only persists the choice (in aura_settings.json); main.py
applies it to the pill in the same turn, so this module never
touches tkinter and stays unit-testable anywhere.
"""

import re

from aura.theme import (
    load_theme_name,
    resolve_theme,
    save_theme_name,
    theme_names_text,
)


def parse_theme_command(text: str):
    """Match spoken text to a theme request. None if no match."""
    t = text.strip().lower()
    if t in (
        "list themes",
        "what themes are there",
        "what themes can i use",
        "show themes",
    ):
        return {"kind": "list"}
    if (
        re.search(r"what( is|'s) (my|the) (current )?theme", t)
        or t == "current theme"
    ):
        return {"kind": "current"}
    if t in ("reset theme", "reset the theme", "default theme"):
        return {"kind": "set", "theme": "violet"}
    if "theme" in t or "pill" in t:
        # "change theme to emerald" / "set the theme to rose"
        m = re.search(r"\btheme to ([a-z]+)", t)
        if m:
            return {"kind": "set", "word": m.group(1)}
        # "use the emerald theme" / "switch to rose theme"
        m = re.search(r"\b([a-z]+) theme\b", t)
        if m and m.group(1) not in ("change", "set", "switch", "the"):
            return {"kind": "set", "word": m.group(1)}
        # "make the pill green"
        m = re.search(r"\bmake the pill ([a-z]+)", t)
        if m:
            return {"kind": "set", "word": m.group(1)}
        # A theme request with no colour named: ask which one.
        if re.search(r"\b(change|set|switch|use)\b", t):
            return {"kind": "ask"}
    return None


def execute_theme_command(cmd: dict) -> str:
    """Carry out a parsed theme command and reply in one sentence."""
    kind = cmd["kind"]
    if kind == "list":
        return (
            f"I have {len(theme_names_text().split(', '))} themes: "
            f"{theme_names_text()}. Say 'change theme to' and a name."
        )
    if kind == "current":
        return f"You're on the {load_theme_name()} theme."
    if kind == "ask":
        return (
            "Which theme? I have: "
            f"{theme_names_text()}. Say 'change theme to' and a name."
        )
    if kind == "set":
        name = cmd.get("theme") or resolve_theme(cmd.get("word", ""))
        if name is None:
            return (
                f"I don't know a '{cmd.get('word')}' theme. I have: "
                f"{theme_names_text()}."
            )
        if load_theme_name() == name:
            return f"Already on the {name} theme."
        save_theme_name(name)
        return f"Theme changed to {name}."
    return "Sorry, I didn't catch that theme request."
