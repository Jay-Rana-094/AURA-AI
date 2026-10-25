"""Tests for Phase 2 command parsing + the confirmation flow.

Parsing has no side effects, so these are safe to run anywhere:
    python test_commands.py
Only the confirmation-cancel path is tested through the brain —
confirming with "yes" would actually shut down / restart / sleep,
so that path is deliberately NOT tested here.
"""

from aura.brain import handle
from aura.commands import parse_command


def check(spoken, expected_kind, **expected_fields):
    cmd = parse_command(spoken)
    assert cmd is not None, f"no match for: {spoken!r}"
    assert cmd["kind"] == expected_kind, (
        f"{spoken!r}: got kind {cmd['kind']!r}, expected {expected_kind!r}"
    )
    for key, value in expected_fields.items():
        assert cmd.get(key) == value, (
            f"{spoken!r}: field {key}={cmd.get(key)!r}, expected {value!r}"
        )


def main():
    # Power (confirmation kinds)
    check("shutdown", "shutdown")
    check("please shut down the pc", "shutdown")
    check("restart my computer", "restart")
    check("put the pc to sleep", "sleep")
    # Lock
    check("lock my pc", "lock")
    # Volume / media
    check("volume up", "media_key", action="volume_up")
    check("volume down", "media_key", action="volume_down")
    check("mute", "media_key", action="mute")
    check("next song", "media_key", action="next")
    check("previous song", "media_key", action="previous")
    check("pause the music", "media_key", action="play_pause")
    # YouTube
    check("play arijit singh on youtube", "youtube", query="arijit singh")
    check("search youtube for python tutorials", "youtube", query="python tutorials")
    # Web search
    check("search for best laptops", "web_search", query="best laptops")
    check("search weather in vadodara", "web_search", query="weather in vadodara")
    # Open app / site / URL / fallback
    check("open notepad", "open_app", name="notepad")
    check("launch vs code", "open_app", name="vs code")
    check("open youtube", "open_site", name="youtube")
    check("open example.com", "open_url", url="example.com")
    check("open cute cats", "web_search", query="cute cats")
    # No match -> falls through to built-ins / fallback
    assert parse_command("hello there") is None
    assert parse_command("what is the time") is None

    # Confirmation flow: shutdown asks, "no" cancels, nothing runs.
    reply, quit_ = handle("shutdown")
    assert "Are you sure" in reply and not quit_, reply
    reply, quit_ = handle("no")
    assert reply == "Okay, cancelled." and not quit_, reply
    # After cancelling, normal commands work again.
    reply, quit_ = handle("hello")
    assert "AURA" in reply and not quit_, reply

    print("All Phase 2 command tests passed.")


if __name__ == "__main__":
    main()
