"""Tests for Phase 6 daily briefing (no microphone needed).

    python test_briefing.py
"""

import os
import tempfile
from datetime import datetime, timedelta

import requests

from aura.brain import handle, set_custom_store, set_memory
from aura.commands.briefing import build_briefing, parse_briefing_command
from aura.commands.custom import CustomStore
from aura.memory import Memory
from aura.weather import _reset_cache


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)
    now = datetime(2026, 10, 28, 8, 5)  # a Wednesday morning

    # Phase 9.1: the briefing carries one weather line, so the
    # fetch is stubbed (no real network) — a good response here,
    # an offline one below.
    real_get = requests.get

    def _stub_ok(url, params=None, timeout=None):
        return _FakeResponse(payload={"current": {
            "temperature_2m": 28.4,
            "weather_code": 0,
            "wind_speed_10m": 12.3,
        }})

    requests.get = _stub_ok
    _reset_cache()

    # --- Empty day: nothing due, nothing pending. ---
    reply = build_briefing(mem, now)
    assert "Good morning" in reply and "October 28" in reply, reply
    assert "No reminders due today" in reply, reply
    assert "todo list is clear" in reply, reply
    assert "Weather in Vadodara: 28°C, clear sky, wind 12 km/h." in reply, reply

    # --- A full day: overdue + today + tomorrow (excluded). ---
    mem.add_reminder("call mom", now - timedelta(hours=1))
    mem.add_reminder("take medicine", now.replace(hour=9, minute=0), "daily")
    mem.add_reminder("team call", now.replace(hour=17, minute=0))
    mem.add_reminder("dentist", now + timedelta(days=1))
    mem.add_todo("finish report", "high")
    mem.add_todo("buy milk")
    mem.add_todo("water plants", "low")
    reply = build_briefing(mem, now)
    assert "Overdue reminders: call mom" in reply, reply
    assert "take medicine at 9:00 AM (every day)" in reply, reply
    assert "team call at 5:00 PM" in reply, reply
    assert "dentist" not in reply, reply  # tomorrow, not today
    assert "Pending todos (3)" in reply, reply
    assert reply.index("finish report") < reply.index("buy milk"), reply
    assert reply.index("buy milk") < reply.index("water plants"), reply
    assert "(high priority)" in reply and "(low priority)" in reply, reply

    # --- Phase 9.2B: the briefing carries one calendar line
    # when connected, and omits it silently when not. --------
    import aura.commands.briefing as briefing_mod
    real_calendar_line = briefing_mod.calendar_line
    briefing_mod.calendar_line = lambda now=None: (
        "Today's calendar: Team standup at 10:00 AM.")
    reply = build_briefing(mem, now)
    assert "Today's calendar: Team standup at 10:00 AM." in reply, reply
    briefing_mod.calendar_line = lambda now=None: None
    reply = build_briefing(mem, now)
    assert "calendar" not in reply.lower(), reply
    assert "Overdue reminders" in reply and "Pending todos" in reply, reply
    briefing_mod.calendar_line = real_calendar_line

    # --- Parser: every phrasing, and no false friends. ---
    for phrase in (
        "daily briefing",
        "morning briefing",
        "brief me",
        "good morning",
        "what's my day look like",
        "what's on today",
        "what do i have today",
    ):
        assert parse_briefing_command(phrase) is not None, phrase
    assert parse_briefing_command("open notepad") is None
    assert parse_briefing_command("what is the time") is None

    # --- Voice end to end through handle(). ---
    # handle() uses the real clock, so seed one reminder for today
    # in real terms (the Oct-28 seeds above are "tomorrow" now).
    mem.add_reminder("take medicine", datetime.now() + timedelta(hours=1))
    reply, _ = handle("daily briefing")
    assert "finish report" in reply and "take medicine" in reply, reply
    reply, _ = handle("what do i have today")
    assert "Reminders today" in reply, reply

    # --- Offline: the weather line is omitted silently — the
    # briefing never carries a weather error message. -----------
    def _stub_down(url, params=None, timeout=None):
        raise requests.ConnectionError("offline")

    requests.get = _stub_down
    _reset_cache()
    reply = build_briefing(mem, now)
    assert "Weather in Vadodara" not in reply, reply
    assert "couldn't" not in reply.lower(), reply
    # ...but the rest of the briefing is untouched.
    assert "Overdue reminders" in reply and "Pending todos" in reply, reply

    requests.get = real_get
    print("All daily-briefing tests passed.")


if __name__ == "__main__":
    main()
