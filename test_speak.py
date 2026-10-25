"""Isolate the speaker: speaks twice, with a pause between.

Run this alone if speech ever stops after the first utterance:
    python test_speak.py
You should hear both lines. If you only hear the first, the problem is
the speech engine on this PC, not AURA's listening or GUI code.
"""

import time

from aura.speaker import Speaker

if __name__ == "__main__":
    speaker = Speaker()
    print("Speaking line 1...")
    speaker.say("Testing one.")
    time.sleep(1)
    print("Speaking line 2...")
    speaker.say("Testing two.")
    print("Done — if you heard both lines, the speaker is fine.")
