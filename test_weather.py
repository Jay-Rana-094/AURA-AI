"""Tests for Phase 9.1 — weather in the daily briefing.

Open-Meteo is a plain GET with no key, so the fetch is tested
with a stubbed requests.get (same pattern as test_chat.py
stubs requests.post): a good response, an HTTP error, a dead
connection, bad JSON, and a missing field. No real network.

    python test_weather.py
"""

import os
import tempfile

import requests

from aura.brain import handle, set_custom_store, set_memory
from aura.chat import set_chat_enabled
from aura.chat import set_key_file_path as set_chat_key_file_path
from aura.chat import set_settings_path as set_chat_settings_path
from aura.commands.custom import CustomStore
from aura.language import set_settings_path as set_language_settings_path
from aura.memory import Memory
from aura.weather import (
    _reset_cache,
    describe_weather_code,
    execute_weather_command,
    fetch_weather,
    format_weather,
    parse_weather_command,
    weather_line,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _good_payload(temp=28.4, code=0, wind=12.3):
    return {"current": {
        "temperature_2m": temp,
        "weather_code": code,
        "wind_speed_10m": wind,
    }}


def main():
    tmp = tempfile.mkdtemp()
    set_chat_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_key_file_path(os.path.join(tmp, "groq_api_key.txt"))
    set_language_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_enabled(False)
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- WMO codes in plain words. --------------------------------
    assert describe_weather_code(0) == "clear sky"
    assert describe_weather_code(2) == "partly cloudy"
    assert describe_weather_code(63) == "rain"
    assert describe_weather_code(95) == "thunderstorm"
    assert describe_weather_code(999) == "mixed conditions"
    assert describe_weather_code("nope") == "mixed conditions"

    # --- Formatter: one spoken line. -------------------------------
    line = format_weather({"temperature": 28.4, "code": 0, "wind_kmh": 12.3})
    assert line == "Weather in Vadodara: 28°C, clear sky, wind 12 km/h.", line

    real_get = requests.get
    calls = []

    def _stub_ok(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(payload=_good_payload())

    requests.get = _stub_ok
    try:
        # --- Fetch: right endpoint, right params, parsed numbers. --
        _reset_cache()
        data = fetch_weather()
        assert data == {
            "temperature": 28.4, "code": 0, "wind_kmh": 12.3,
        }, data
        assert len(calls) == 1, calls
        assert "open-meteo.com" in calls[0]["url"], calls[0]
        assert calls[0]["params"]["latitude"] == 22.31, calls[0]
        assert calls[0]["params"]["longitude"] == 73.18, calls[0]
        assert calls[0]["params"]["timezone"] == "Asia/Kolkata", calls[0]
        assert "temperature_2m" in calls[0]["params"]["current"], calls[0]
        assert calls[0]["timeout"] == 5, calls[0]

        # --- Caching: one fetch serves repeated calls. -------------
        line = weather_line()
        assert line == (
            "Weather in Vadodara: 28°C, clear sky, wind 12 km/h."
        ), line
        assert len(calls) == 2, calls  # fetch_weather above + this cold-cache fetch
        weather_line()
        assert len(calls) == 2, calls  # cached, no second fetch
        _reset_cache()
        weather_line()
        assert len(calls) == 3, calls  # reset forces a fresh fetch

        # --- Failures: all come back as None, never a raise. -------
        def _stub_500(url, params=None, timeout=None):
            return _FakeResponse(status_code=500, payload={})

        requests.get = _stub_500
        _reset_cache()
        assert fetch_weather() is None
        assert weather_line() is None

        def _stub_down(url, params=None, timeout=None):
            raise requests.ConnectionError("offline")

        requests.get = _stub_down
        _reset_cache()
        assert fetch_weather() is None
        assert weather_line() is None

        def _stub_bad(url, params=None, timeout=None):
            return _FakeResponse(bad_json=True)

        requests.get = _stub_bad
        _reset_cache()
        assert fetch_weather() is None

        def _stub_missing(url, params=None, timeout=None):
            return _FakeResponse(payload={"current": {"temperature_2m": 28}})

        requests.get = _stub_missing
        _reset_cache()
        assert fetch_weather() is None
    finally:
        requests.get = real_get

    # --- Parser: every phrasing, and no false friends. ------------
    for phrase in (
        "weather",
        "what's the weather",
        "what is the weather",
        "weather today",
        "what's the weather today",
        "how's the weather",
        "what's the weather like",
        "weather in vadodara",
    ):
        assert parse_weather_command(phrase) is not None, phrase
    assert parse_weather_command("what is the time") is None
    assert parse_weather_command("open spotify") is None

    # --- Voice end to end through handle(). -----------------------
    requests.get = _stub_ok
    try:
        _reset_cache()
        reply, quit_ = handle("what's the weather")
        assert "Vadodara" in reply and "28°C" in reply, reply
        assert not quit_
        reply, _ = handle("weather today")
        assert "clear sky" in reply, reply
        # A taught phrase with the same words still wins.
        set_custom_store(CustomStore(os.path.join(tmp, "custom2.json")))
        reply, _ = handle(
            "teach aura what's the weather means what is the time")
        assert "Got it" in reply, reply
        reply, _ = handle("what's the weather")
        assert "It's" in reply, reply
        # Unrelated commands leave the weather alone; help mentions it.
        reply, _ = handle("what is the time")
        assert "Vadodara" not in reply, reply
        assert "weather" in handle("help")[0].lower()
    finally:
        requests.get = real_get

    # --- Offline: the standalone answer stays honest. -------------
    requests.get = _stub_down
    try:
        _reset_cache()
        reply = execute_weather_command({"kind": "weather"})
        assert "couldn't get the weather" in reply, reply
    finally:
        requests.get = real_get

    print("All weather tests passed.")


if __name__ == "__main__":
    main()
