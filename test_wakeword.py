"""Tests for wake-word detection (pure function, no microphone needed).

    python test_wakeword.py
"""

from aura.wakeword import contains_wake_word


def main():
    assert contains_wake_word("aura")
    assert contains_wake_word("hey aura")
    assert contains_wake_word("Aura open notepad")
    assert contains_wake_word("say aura please")
    assert contains_wake_word("AURA")
    assert not contains_wake_word("hello there")
    assert not contains_wake_word("ora")  # mishearing, not the word
    assert not contains_wake_word("auraking")  # must be a whole word
    assert not contains_wake_word("")
    print("All wake-word tests passed.")


if __name__ == "__main__":
    main()
