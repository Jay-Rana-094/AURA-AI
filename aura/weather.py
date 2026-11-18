"""Weather — Phase 9.1.

Current weather for Vadodara from Open-Meteo — free, no API key,
no account, just a GET request (requests is already a
dependency). Two uses:

  - The daily briefing (build_briefing) includes one weather
    line when the fetch succeeds, and silently omits it when
    offline or on error — a briefing never carries an error
    message about the weather.
  - The standalone voice command ("what's the weather") speaks
    the same line, or says the weather is unavailable right now.

The fetch is cached for 10 minutes (module-level), so a
briefing refresh or a repeated question does not hit the
network every time. Tests reset the cache with
_reset_cache() and stub requests.get — no real network.

    fetch_weather() -> dict | None
    format_weather(data) -> str
    weather_line() -> str | None   (cached, None when unavailable)
    describe_weather_code(code) -> str
"""

import re
import time

import requests

CITY = "Vadodara"
LATITUDE = 22.31
LONGITUDE = 73.18
TIMEZONE = "Asia/Kolkata"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECS = 5
_CACHE_SECS = 600  # 10 minutes

_CACHE = {"line": None, "at": 0.0}

# WMO weather codes (Open-Meteo) -> plain words.
WMO_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with rime",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def _reset_cache() -> None:
    """Clear the cached line — used by tests."""
    _CACHE["line"] = None
    _CACHE["at"] = 0.0


def describe_weather_code(code) -> str:
    """A WMO code in plain words. Unknown codes stay honest."""
    try:
        return WMO_CODES[int(code)]
    except (KeyError, TypeError, ValueError):
        return "mixed conditions"


def fetch_weather() -> dict | None:
    """Fetch the current weather, or None on any failure.

    Never raises: offline, bad JSON, or a changed response shape
    all come back as None, so the caller can omit the line
    silently instead of breaking the briefing."""
    try:
        resp = requests.get(
            WEATHER_URL,
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": TIMEZONE,
            },
            timeout=TIMEOUT_SECS,
        )
        if resp.status_code != 200:
            return None
        current = resp.json()["current"]
        return {
            "temperature": float(current["temperature_2m"]),
            "code": int(current["weather_code"]),
            "wind_kmh": float(current["wind_speed_10m"]),
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def format_weather(data: dict) -> str:
    """One spoken line, e.g. "Weather in Vadodara: 28°C, clear
    sky, wind 12 km/h." """
    return (
        f"Weather in {CITY}: {data['temperature']:.0f}°C, "
        f"{describe_weather_code(data['code'])}, "
        f"wind {data['wind_kmh']:.0f} km/h."
    )


def weather_line() -> str | None:
    """The cached weather line, or None when unavailable.

    A fresh fetch happens at most once every 10 minutes; a
    failed fetch is not cached, so the next call retries."""
    now = time.time()
    if _CACHE["line"] is not None and now - _CACHE["at"] < _CACHE_SECS:
        return _CACHE["line"]
    data = fetch_weather()
    if data is None:
        return None
    line = format_weather(data)
    _CACHE["line"] = line
    _CACHE["at"] = now
    return line


def parse_weather_command(text: str):
    """Match spoken text to a weather question. None if no match."""
    t = text.strip().lower()
    if t in (
        "weather",
        "what's the weather",
        "what is the weather",
        "weather today",
        "what's the weather today",
        "what is the weather today",
        "how's the weather",
        "how is the weather",
        "what's the weather like",
        "what is the weather like",
        "what's the weather in vadodara",
        "what is the weather in vadodara",
        "weather in vadodara",
    ):
        return {"kind": "weather"}
    if re.search(r"\bwhat'?s the weather\b", t):
        return {"kind": "weather"}
    return None


def execute_weather_command(cmd: dict) -> str:
    """Answer a weather question — the same line as the
    briefing, or an honest "unavailable" when the fetch fails."""
    line = weather_line()
    if line is None:
        return (
            "I couldn't get the weather right now — check your "
            "internet and try again."
        )
    return line
