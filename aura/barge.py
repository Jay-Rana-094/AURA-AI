"""Speaking with voice barge-in (Phase 5, extended 2026-11-17).

``speak_with_barge`` speaks a reply while listening for an
interruption, so the user can cut AURA off mid-sentence instead
of waiting for a long reply (a daily briefing, for example) to
finish. It used to live as a closure inside main.py, where no
test could reach it; it moved here so the barge behaviour is
unit-testable, and so both the voice turn and the typed command
can share the exact same path.

What stops speech now:
- the wake word ("Aura", or the custom word) — a voice turn then
  loops back to listen for the follow-up command;
- a stop phrase ("stop", "stop speaking", "be quiet", "quiet",
  "enough") — same cut, no new turn is started by the caller;
- the mic tap, or a typed command — those call speaker.stop()
  directly (see main.py), which kills the speech process.

The barge listener is the offline Vosk engine only, like wake-word
listening — it never sends audio anywhere. It is skipped for
replies that contain the wake word or a stop phrase themselves
(the help text says "turn off chat mode to stop that", for
example) — otherwise AURA's own speech would trigger it.
"""

import threading

from aura.wakeword import (
    STOP_PHRASES,
    contains_stop_phrase,
    contains_wake_word,
)


def speak_with_barge(speaker, listener, mic_lock, reply: str,
                     wake_word: str = "aura") -> bool:
    """Speak ``reply``, listening for the wake word or a stop
    phrase meanwhile.

    Returns True if the user barged in by voice. The speech runs
    on its own thread; the wake-word wait ends when speech ends
    (its stop event) or when a trigger is heard. Skipped (speech
    simply plays out) for replies that contain the wake word or a
    stop phrase themselves, and for a missing Vosk model (the wait
    then returns at once).
    """
    speech_done = threading.Event()

    def _say():
        try:
            speaker.say(reply)
        finally:
            speech_done.set()

    say_thread = threading.Thread(target=_say, daemon=True)
    say_thread.start()
    if contains_wake_word(reply, wake_word) or contains_stop_phrase(reply):
        say_thread.join()
        return False
    with mic_lock:
        detected, _ = listener.wait_for_wake_word(
            speech_done, wake_word=wake_word, extra_triggers=STOP_PHRASES
        )
    if detected:
        speaker.stop()
        say_thread.join()
        return True
    say_thread.join()
    return False
