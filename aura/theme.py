"""Pill themes — Phase 6.

Pure data + settings persistence (no tkinter), so this stays
unit-testable anywhere. The pill reads the saved theme at startup
and main.py re-applies it after every voice turn, so a theme
command takes effect in the same turn it was spoken.

A theme recolours the glow, the pill outline, the orb, the mic
ring, the label and the waveform bars. The *meaning* colours never
change: listening stays green, thinking amber, error red — those
are states, not decoration. The default "violet" theme reproduces
the original glow pill exactly, so existing installs look
unchanged until a new theme is chosen.
"""

import json
import os

DEFAULT_THEME = "violet"

# Each theme: glow layers (outer -> inner), pill outline, top
# highlight line, orb fills, control fills (mic/wake/engine menu),
# accent (mic outline, label, speaking ring), idle orb ring, label,
# and the two alternating waveform-bar colours.
THEMES = {
    "violet": {
        "glow": ["#12083a", "#1b0f4d", "#241a66"],
        "pill_outline": "#5b8cff",
        "highlight": "#6ea8ff",
        "orb_fill": "#12082b",
        "orb_inner": "#2b1666",
        "control": "#141438",
        "accent": "#35a0ff",
        "ring_idle": "#8b5cf6",
        "label": "#7ec8ff",
        "bars": ["#67e8f9", "#a78bfa"],
    },
    "emerald": {
        "glow": ["#06281c", "#0a3524", "#0e4530"],
        "pill_outline": "#34d399",
        "highlight": "#6ee7b7",
        "orb_fill": "#06281c",
        "orb_inner": "#0e4530",
        "control": "#0f2e22",
        "accent": "#34d399",
        "ring_idle": "#10b981",
        "label": "#6ee7b7",
        "bars": ["#a7f3d0", "#34d399"],
    },
    "amber": {
        "glow": ["#2b1a05", "#3a2408", "#4a2e0b"],
        "pill_outline": "#f59e0b",
        "highlight": "#fcd34d",
        "orb_fill": "#2b1a05",
        "orb_inner": "#4a2e0b",
        "control": "#2e2210",
        "accent": "#f59e0b",
        "ring_idle": "#d97706",
        "label": "#fcd34d",
        "bars": ["#fde68a", "#f59e0b"],
    },
    "rose": {
        "glow": ["#2b0a1e", "#3a0f28", "#4a1434"],
        "pill_outline": "#f472b6",
        "highlight": "#fda4af",
        "orb_fill": "#2b0a1e",
        "orb_inner": "#4a1434",
        "control": "#2e1020",
        "accent": "#f472b6",
        "ring_idle": "#ec4899",
        "label": "#fda4af",
        "bars": ["#fecdd3", "#f472b6"],
    },
    "ocean": {
        "glow": ["#06202e", "#0a2e40", "#0e3d54"],
        "pill_outline": "#22d3ee",
        "highlight": "#a5f3fc",
        "orb_fill": "#06202e",
        "orb_inner": "#0e3d54",
        "control": "#0f2430",
        "accent": "#22d3ee",
        "ring_idle": "#06b6d4",
        "label": "#a5f3fc",
        "bars": ["#a5f3fc", "#22d3ee"],
    },
}

# Everyday colour words that map onto a theme name.
_THEME_ALIASES = {
    "purple": "violet",
    "green": "emerald",
    "orange": "amber",
    "gold": "amber",
    "pink": "rose",
    "blue": "ocean",
    "teal": "ocean",
    "cyan": "ocean",
}

_REQUIRED_KEYS = {
    "glow", "pill_outline", "highlight", "orb_fill", "orb_inner",
    "control", "accent", "ring_idle", "label", "bars",
}

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def resolve_theme(word: str):
    """Map a spoken word to a theme name, or None if unknown."""
    word = word.strip().lower()
    if word in THEMES:
        return word
    return _THEME_ALIASES.get(word)


def validate_theme(name: str):
    """Return None if ``name`` is a known theme, else a reason."""
    if name in THEMES:
        return None
    return f"Unknown theme '{name}'."


def load_theme_name() -> str:
    """The saved theme, or "violet" if none was ever set."""
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        name = str(data.get("theme", "")).strip().lower()
        if name and validate_theme(name) is None:
            return name
    except (OSError, ValueError):
        pass
    return DEFAULT_THEME


def save_theme_name(name: str) -> None:
    """Persist ``name`` (already validated by the caller)."""
    data = {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data["theme"] = name.strip().lower()
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def theme_names_text() -> str:
    """Speech-friendly list: "violet, emerald, amber, rose, ocean"."""
    names = list(THEMES)
    return ", ".join(names)
