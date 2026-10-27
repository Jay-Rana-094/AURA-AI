"""Tests for Phase 5 voice interruption / barge-in (no mic needed).

The speaker plumbing is tested with a real subprocess: a long
sleep is started through _run_hidden, stop() kills it, and the
call returns promptly. The echo guard (replies containing the
wake word skip voice barging) is tested through the matcher.

    python test_barge.py
"""

import threading
import time

from aura.speaker import Speaker
from aura.wakeword import contains_wake_word


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

    print("All barge-in tests passed.")


if __name__ == "__main__":
    main()
