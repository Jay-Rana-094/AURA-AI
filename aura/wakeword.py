"""Wake-word matching — kept in its own module on purpose.

It has no heavy imports (no SpeechRecognition, no Vosk), so it can be
unit-tested anywhere, including machines without the voice packages.
"""

import re


def contains_wake_word(text: str, wake_word: str = "aura") -> bool:
    """True if ``wake_word`` appears as a whole word in ``text``.

    Phase 7: Hindi transcripts render the name as Devanagari, so
    the default word also matches "ऑरा" (substring match — word
    boundaries are unreliable across scripts).
    """
    lowered = text.lower()
    if re.search(rf"\b{re.escape(wake_word)}\b", lowered) is not None:
        return True
    if wake_word == "aura" and "ऑरा" in text:
        return True
    return False
