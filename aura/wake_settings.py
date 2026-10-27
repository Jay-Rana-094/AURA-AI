"""Custom wake word storage — Phase 5.

The wake word lives in ``aura_settings.json`` next to ``main.py`` so it
survives restarts, and so the pill, the wake loop and the brain all
read the same word. Only the standard library is used here, so this
module stays unit-testable anywhere (like ``wakeword.py``).

Validation rules for a new word (kept deliberately strict — the wake
word is matched on every partial transcript, so it must be easy for
Vosk to hear and hard to trigger by accident):
  - 1–2 words, letters and spaces only, max 20 characters.
  - Must not be an exit word (stop/exit/quit/goodbye/bye): saying
    the wake word must never also mean "close AURA".
"""

import json
import os

DEFAULT_WAKE_WORD = "aura"
_EXIT_WORDS = {"stop", "exit", "quit", "goodbye", "bye"}

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def load_wake_word() -> str:
    """The current wake word, or "aura" if none was ever set."""
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        word = str(data.get("wake_word", "")).strip().lower()
        if word and validate_wake_word(word) is None:
            return word
    except (OSError, ValueError):
        pass
    return DEFAULT_WAKE_WORD


def save_wake_word(word: str) -> None:
    """Persist ``word`` (already validated by the caller)."""
    data = {}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data["wake_word"] = word.strip().lower()
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def validate_wake_word(word: str):
    """Return None if ``word`` is usable, else a short reason why not."""
    cleaned = " ".join(word.strip().lower().split())
    if not cleaned:
        return "I didn't hear a word to use."
    if len(cleaned) > 20:
        return "Keep the wake word short — two words at most."
    if len(cleaned.split()) > 2:
        return "Keep the wake word to one or two words."
    if not all(ch.isalpha() or ch.isspace() for ch in cleaned):
        return "The wake word can only have letters in it."
    if cleaned in _EXIT_WORDS:
        return (
            f"I can't use '{cleaned}' — saying it would also close me."
        )
    return None


def display_wake_word(word: str) -> str:
    """How the word looks in the pill, e.g. "Jarvis", "Hey Jarvis"."""
    return " ".join(part.capitalize() for part in word.split())
