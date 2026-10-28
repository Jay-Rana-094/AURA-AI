"""Spoken-language mode — Phase 7.

AURA speaks one language at a time: English ("en", the default)
or Hindi ("hi"). The mode lives in ``aura_settings.json`` next to
``main.py`` (same file as the wake word and theme), so the
listener, speaker and brain all read the same mode, and a voice
switch ("speak Hindi") takes effect on the very next turn.

Only the standard library is used here, so this stays
unit-testable anywhere.
"""

import json
import os

DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
}

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def validate_language(code: str):
    """Return None if ``code`` is a supported language, else a reason."""
    if code in LANGUAGES:
        return None
    return f"Unknown language '{code}'."


def load_language() -> str:
    """The saved language, or "en" if none was ever set."""
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        code = str(data.get("language", "")).strip().lower()
        if code and validate_language(code) is None:
            return code
    except (OSError, ValueError):
        pass
    return DEFAULT_LANGUAGE


def save_language(code: str) -> None:
    """Persist ``code`` (already validated by the caller)."""
    data = {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data["language"] = code.strip().lower()
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
