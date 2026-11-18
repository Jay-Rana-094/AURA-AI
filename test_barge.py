"""Tests for Phase 5 voice interruption / barge-in (no mic needed).

The speaker plumbing is tested with a real subprocess: a long
sleep is started through _run_hidden, stop() kills it, and the
call returns promptly. The echo guard (replies containing the
wake word skip voice barging) is tested through the matcher.

Barge-in fix (2026-11-17): typed commands cut in-progress
speech (speaker.stop() first), typed replies speak through the
same barge listener as voice turns, and "stop" phrases trigger
a barge like the wake word does. speak_with_barge lives in
aura/barge.py so it can be tested here with a stubbed listener
— no microphone, no GUI.

    python test_barge.py
"""

import threading
import time

from aura.barge import speak_with_barge
from aura.speaker import Speaker
from aura.wakeword import (
    STOP_PHRASES,
    contains_any_phrase,
    contains_stop_phrase,
    contains_wake_word,
)


class _FakeListener:
    """Stands in for Listener.wait_for_wake_word / listen."""

    def __init__(self, detected=True, wait_for_start=None):
        self.detected = detected
        self.wait_calls = []
        self.listen_calls = 0
        self._wait_for_start = wait_for_start

    def wait_for_wake_word(self, stop_event, wake_word="aura",
                           extra_triggers=None):
        self.wait_calls.append(
            (wake_word, tuple(extra_triggers or ())))
        if self._wait_for_start is not None:
            # Only answer once speech has actually started, so
            # stop() cannot race the worker picking up the job.
            self._wait_for_start.wait(timeout=5)
        return self.detected, ""

    def listen(self, timeout=8.0):
        self.listen_calls += 1
        return "", "nope"


def _slow_say_factory(speaker, started, result):
    """A slow speech engine that stops promptly on stop().

    Speaks for up to 60 s, polling the stop flag — the shape a
    real long reply (a briefing) has on the speaker queue.
    """

    def _slow_say(text):
        started.set()
        for _ in range(600):
            if speaker._stop_requested.is_set():
                result["interrupted"] = True
                return
            time.sleep(0.1)
        result["interrupted"] = False

    return _slow_say


def main():
    speaker = Speaker()

    # stop() with nothing playing is a harmless no-op.
    speaker.stop()
    speaker.stop()

    # A long-running process started through the killable runner
    # must die promptly when stop() is called.
    result = {}

    def _run():
        result["rc"], result["err"] = speaker._run_hidden(
            ["python3", "-c", "import time; time.sleep(30)"]
        )

    thread = threading.Thread(target=_run)
    started = time.time()
    thread.start()
    time.sleep(0.5)  # let the process start
    speaker.stop()
    thread.join(timeout=5)
    assert not thread.is_alive(), "stop() did not kill the process"
    assert time.time() - started < 5, "stop() took too long"
    assert result["rc"] < 0, result  # killed, not exited normally

    # A normal short process still completes and reports success.
    rc, err = speaker._run_hidden(["python3", "-c", "pass"])
    assert rc == 0 and err == "", (rc, err)

    # say() with a stubbed instant engine returns, and the speaker
    # keeps working afterwards (the worker thread survives).
    speaker._speak_powershell = lambda text: None  # noqa: E731
    speaker._speak_pyttsx3 = lambda text: None  # noqa: E731
    speaker.say("hello")
    speaker.stop()
    speaker.say("still works")

    # Echo guard: a reply containing the wake word must skip voice
    # barging, or AURA's own speech would trigger it.
    assert contains_wake_word("Hey! I'm AURA, your assistant.", "aura")
    assert contains_wake_word("Say 'Jarvis' to wake me.", "jarvis")
    assert not contains_wake_word("It's 10:30 in the morning.", "aura")

    # --- Stop-phrase matcher (barge-in fix). ----------------------
    for text in (
        "stop",
        "Stop.",
        "please stop speaking",
        "be quiet please",
        "quiet!",
        "enough already",
        "It's time to stop",
    ):
        assert contains_stop_phrase(text), text
    for text in (
        "",
        "I stopped the car",
        "nonstop music",
        "stopping now",
        "It's 10:30 in the morning.",
    ):
        assert not contains_stop_phrase(text), text
    assert contains_any_phrase("say aura now", ("aura",))
    assert not contains_any_phrase("say aura now", ("hello",))
    assert STOP_PHRASES == (
        "stop", "stop speaking", "be quiet", "quiet", "enough",
    )

    # --- speak_with_barge: a stop phrase cuts the reply. ----------
    # Fresh speaker with a slow engine, so the cut is observable.
    slow_speaker = Speaker()
    started_evt = threading.Event()
    slow_result = {}
    slow_say = _slow_say_factory(slow_speaker, started_evt, slow_result)
    slow_speaker._speak_powershell = slow_say
    slow_speaker._speak_pyttsx3 = slow_say
    mic_lock = threading.Lock()
    listener = _FakeListener(detected=True, wait_for_start=started_evt)
    t0 = time.time()
    barged = speak_with_barge(
        slow_speaker, listener, mic_lock,
        "Here is a very long reply that goes on and on.",
    )
    assert barged is True, "stop-phrase barge was not detected"
    assert time.time() - t0 < 5, "barge took too long to cut speech"
    assert slow_result.get("interrupted") is True, slow_result
    # The barge listener was given the stop phrases, and no voice
    # turn was started — speak_with_barge only ever waits, it
    # never listens for a command.
    assert listener.wait_calls == [("aura", STOP_PHRASES)], listener.wait_calls
    assert listener.listen_calls == 0, "barge started a voice turn"
    # The speaker is idle afterwards: the next reply speaks at once.
    slow_speaker._speak_powershell = lambda text: None  # noqa: E731
    slow_speaker._speak_pyttsx3 = lambda text: None  # noqa: E731
    slow_speaker.say("clean after barge")

    # --- speak_with_barge: no trigger, speech plays out. ----------
    listener2 = _FakeListener(detected=False)
    t0 = time.time()
    barged = speak_with_barge(
        speaker, listener2, mic_lock, "A short reply.")
    assert barged is False, "no trigger, yet barged"
    assert time.time() - t0 < 5, "unbarged reply was slow"
    assert listener2.wait_calls == [("aura", STOP_PHRASES)]

    # --- Echo guard: a reply containing a stop phrase (or the wake
    # word) never arms the barge listener — AURA's own speech
    # must not self-trigger. ---------------------------------------
    for reply in (
        "To stop it, say 'turn off chat mode'.",
        "Say 'Aura' to wake me.",
    ):
        listener3 = _FakeListener(detected=True)
        barged = speak_with_barge(speaker, listener3, mic_lock, reply)
        assert barged is False, reply
        assert listener3.wait_calls == [], reply

    # --- Typed command cuts in-progress speech. -------------------
    # This is the exact mechanism run_typed_command now uses: a
    # typed command calls speaker.stop() first, so the new reply
    # does not queue behind the old speech (the reported bug).
    cut_speaker = Speaker()
    cut_started = threading.Event()
    cut_result = {}
    cut_say = _slow_say_factory(cut_speaker, cut_started, cut_result)
    cut_speaker._speak_powershell = cut_say
    cut_speaker._speak_pyttsx3 = cut_say
    first_done = threading.Event()

    def _first_reply():
        cut_speaker.say("First, a very long reply that goes on.")
        first_done.set()

    first_thread = threading.Thread(target=_first_reply)
    first_thread.start()
    assert cut_started.wait(timeout=5), "first reply never started"
    t0 = time.time()
    cut_speaker.stop()  # what the typed command does first
    first_thread.join(timeout=5)
    assert not first_thread.is_alive(), "stop() did not cut the reply"
    assert time.time() - t0 < 5, "typed cut took too long"
    assert cut_result.get("interrupted") is True, cut_result
    # The new reply then speaks at once instead of waiting behind
    # the old one.
    cut_speaker._speak_powershell = lambda text: None  # noqa: E731
    cut_speaker._speak_pyttsx3 = lambda text: None  # noqa: E731
    t0 = time.time()
    cut_speaker.say("Second reply.")
    assert time.time() - t0 < 5, "new reply was stuck behind the old one"

    print("All barge-in tests passed.")


if __name__ == "__main__":
    main()
