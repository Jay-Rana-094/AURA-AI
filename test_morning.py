"""Tests for Phase 9.2A — proactive morning briefing.

Pure settings / time / decision logic, plus the voice routing
through the brain. No waiting, no window: the scheduler thread
itself lives in main.py and is deliberately not tested here —
should_fire() is the whole decision, and it is pure.

    python test_morning.py
"""

import os
import tempfile
from datetime import datetime

from aura.brain import handle, pop_gui_action, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.memory import Memory
from aura.morning import (
    DEFAULT_BRIEFING_TIME,
    format_briefing_time,
    get_last_fired,
    get_morning_time,
    is_morning_enabled,
    mark_fired,
    morning_status,
    parse_briefing_time,
    parse_morning_command,
    set_morning_enabled,
    set_morning_time,
    set_settings_path,
    should_fire,
)


def _at(hour, minute):
    return datetime(2026, 11, 18, hour, minute)


def main():
    tmp = tempfile.mkdtemp()
    # Morning settings live in their own temp file — the real
    # aura_settings.json next to main.py is never touched.
    set_settings_path(os.path.join(tmp, "settings.json"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Defaults: on, 8:00 AM, never fired. ----------------------
    assert is_morning_enabled() is True, "briefing is ON by default"
    assert get_morning_time() == DEFAULT_BRIEFING_TIME == "08:00"
    assert get_last_fired() is None
    status = morning_status()
    assert status == {"enabled": True, "time": "08:00",
                      "time_display": "8:00 AM", "last_fired": None}, status

    # --- Enable / disable persists. -------------------------------
    set_morning_enabled(False)
    assert is_morning_enabled() is False
    set_morning_enabled(True)
    assert is_morning_enabled() is True

    # --- Time: set + get, bad values rejected. ---------------------
    set_morning_time("07:30")
    assert get_morning_time() == "07:30"
    for bad in ("25:00", "7:60", "abc", "7:30 XM", ""):
        try:
            set_morning_time(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"set_morning_time({bad!r}) accepted")
    assert get_morning_time() == "07:30", "bad set must not clobber"

    # --- Display format. -------------------------------------------
    assert format_briefing_time("08:00") == "8:00 AM"
    assert format_briefing_time("19:30") == "7:30 PM"
    assert format_briefing_time("00:00") == "12:00 AM"
    assert format_briefing_time("12:00") == "12:00 PM"

    # --- Spoken time parsing. --------------------------------------
    assert parse_briefing_time("7:30") == "07:30"
    assert parse_briefing_time("7:30 am") == "07:30"
    assert parse_briefing_time("7:30 pm") == "19:30"
    assert parse_briefing_time("7 am") == "07:00"
    assert parse_briefing_time("7 pm") == "19:00"
    assert parse_briefing_time("19:30") == "19:30"
    assert parse_briefing_time("12 am") == "00:00"
    assert parse_briefing_time("12 pm") == "12:00"
    assert parse_briefing_time("7:30am") == "07:30"
    for bad in ("25:00", "7:60", "tomorrow", "7:30 XM", "", "13 pm"):
        assert parse_briefing_time(bad) is None, bad

    # --- The fire decision (pure). ---------------------------------
    # At the time, not fired yet, started before it: fire.
    assert should_fire(_at(8, 0), "08:00", None, _at(7, 0)) is True
    # One minute early: no.
    assert should_fire(_at(7, 59), "08:00", None, _at(7, 0)) is False
    # Inside the 10-minute grace window: yes; past it: no.
    assert should_fire(_at(8, 10), "08:00", None, _at(7, 0)) is True
    assert should_fire(_at(8, 11), "08:00", None, _at(7, 0)) is False
    # Already fired today: never twice.
    assert should_fire(_at(8, 0), "08:00", "2026-11-18",
                        _at(7, 0)) is False
    # Fired yesterday: a new day fires again.
    assert should_fire(_at(8, 0), "08:00", "2026-11-17",
                        _at(7, 0)) is True
    # Started after the briefing time today: the day is skipped.
    assert should_fire(_at(8, 6), "08:00", None, _at(8, 5)) is False
    # Started late yesterday: irrelevant, today still fires.
    assert should_fire(_at(8, 0), "08:00", None,
                        datetime(2026, 11, 17, 9, 0)) is True
    # No started_at tracked: the late-start rule does not apply.
    assert should_fire(_at(8, 0), "08:00", None, None) is True
    # Bad configured time: never fires.
    assert should_fire(_at(8, 0), "xx", None, _at(7, 0)) is False

    # --- mark_fired persists the date. ------------------------------
    mark_fired("2026-11-18")
    assert get_last_fired() == "2026-11-18"
    assert should_fire(_at(8, 0), "08:00", get_last_fired(),
                        _at(7, 0)) is False
    mark_fired("2026-11-17")  # reset for the routing tests below

    # --- Voice routing through the brain. --------------------------
    assert pop_gui_action() is None
    reply, quit_ = handle("turn off morning briefing")
    assert "off" in reply and not quit_, reply
    assert pop_gui_action() == "morning_refresh"
    assert is_morning_enabled() is False
    reply, _ = handle("turn on morning briefing")
    assert "on" in reply, reply
    assert pop_gui_action() == "morning_refresh"
    assert is_morning_enabled() is True
    # Setting a time re-enables when off, like the Control Center.
    handle("turn off morning briefing")
    pop_gui_action()
    reply, _ = handle("set morning briefing to 7:30")
    assert "7:30 AM" in reply, reply
    assert get_morning_time() == "07:30"
    assert is_morning_enabled() is True
    assert pop_gui_action() == "morning_refresh"
    reply, _ = handle("set morning briefing to 7:30 pm")
    assert "7:30 PM" in reply, reply
    assert get_morning_time() == "19:30"
    assert pop_gui_action() == "morning_refresh"
    reply, _ = handle("set morning briefing to nonsense")
    assert "didn't understand" in reply, reply
    assert pop_gui_action() is None
    assert get_morning_time() == "19:30", "bad set must not clobber"
    reply, _ = handle("when is my morning briefing")
    assert "7:30 PM" in reply, reply
    assert pop_gui_action() is None  # status asks for no refresh
    # "stop morning briefing" must hit step 4k, NOT the built-in
    # exit rule — it contains "stop".
    reply, quit_ = handle("stop morning briefing")
    assert "off" in reply and not quit_, reply
    assert pop_gui_action() == "morning_refresh"
    assert is_morning_enabled() is False
    # A taught phrase with the same words still wins (Phases 1-7
    # rule: custom phrases beat built-ins).
    set_morning_enabled(True)
    reply, _ = handle(
        "teach aura turn off morning briefing means what is the time")
    assert "Got it" in reply, reply
    reply, _ = handle("turn off morning briefing")
    assert "It's" in reply, reply
    assert pop_gui_action() is None
    assert is_morning_enabled() is True, "custom phrase ran, not the toggle"
    # Unrelated commands leave the action alone.
    reply, _ = handle("what is the time")
    assert pop_gui_action() is None
    assert "morning briefing" in handle("help")[0].lower()
    # parse_morning_command itself: no match for anything else.
    assert parse_morning_command("what is the time") is None
    assert parse_morning_command("goodbye") is None

    print("All morning-briefing tests passed.")


if __name__ == "__main__":
    main()
