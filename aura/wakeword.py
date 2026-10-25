"""Wake-word matching — kept in its own module on purpose.

It has no heavy imports (no SpeechRecognition, no Vosk), so it can be
unit-tested anywhere, including machines without the voice packages.
"""

import re


def contains_wake_word(text: str, wake_word: str = "aura") -> bool:
    """True if ``wake_word`` appears as a whole word in ``text``."""
    return re.search(rf"\b{re.escape(wake_word)}\b", text.lower()) is not None
