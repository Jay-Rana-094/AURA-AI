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


#: Phrases that stop speech mid-reply (barge-in fix, 2026-11-17).
#: Saying one of these while AURA speaks cuts the reply off, the
#: same way the wake word does. Whole-word/phrase matching, like
#: the wake word — "stop" must not fire inside "stopped" or
#: "nonstop". No Hindi equivalents: the Hindi pack has no
#: stop/interrupt vocabulary (its "बंद करो" means "close it",
#: not "stop speaking"), so there is no clean fit to add.
STOP_PHRASES = ("stop", "stop speaking", "be quiet", "quiet", "enough")


def contains_any_phrase(text: str, phrases) -> bool:
    """True if any of ``phrases`` appears as a whole word/phrase
    in ``text`` (case-insensitive)."""
    lowered = text.lower()
    return any(
        re.search(rf"\b{re.escape(phrase)}\b", lowered) is not None
        for phrase in phrases
    )


def contains_stop_phrase(text: str) -> bool:
    """True if ``text`` contains a stop phrase (see STOP_PHRASES)."""
    return contains_any_phrase(text, STOP_PHRASES)
