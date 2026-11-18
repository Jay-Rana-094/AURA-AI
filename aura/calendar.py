"""Google Calendar in the daily briefing — Phase 9.2B.

Read-only: today's events, spoken in the briefing and on
demand ("what's on my calendar today"). The official Google
client libraries do the work (google-api-python-client +
google-auth), so there is no hand-rolled OAuth here.

Two files next to main.py (both secrets — .gitignore, never
zipped, never pushed, never in chat, same as the Spotify
files):
  - google_credentials.json — the OAuth client downloaded
    from Google Cloud Console (Desktop app type). The
    one-time setup script checks it is the downloaded file.
  - google_token.json — the login tokens from running
    calendar_setup.py once. The access token refreshes
    itself; a refresh that omits nothing is saved back.

When nothing is connected, the briefing silently omits the
calendar line — the same pattern as the weather line (a
missing service is not an error to speak). A failed fetch
(offline, revoked login) is omitted the same way from the
briefing, but the standalone voice question says so honestly
instead of pretending there is nothing on.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_CALENDAR_ID = "primary"
# The calendar line is cached briefly, like the weather line —
# a briefing spoken twice in a row should not hit the network
# twice. A failed fetch is NOT cached, so the next call retries.
_CACHE_MINUTES = 5
_LOCAL_TZ = ZoneInfo("Asia/Kolkata")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CRED_PATH = os.path.join(_BASE, "google_credentials.json")
_TOKEN_PATH = os.path.join(_BASE, "google_token.json")

_cache = {"line": None, "at": None}

# Cached import result: the google modules once loaded, False
# when the import failed. _reset_cache() exists for tests.
_google = None


def _reset_cache() -> None:
    """Forget the cached line AND the cached import result —
    used by tests."""
    global _google
    _cache["line"] = None
    _cache["at"] = None
    _google = None


def _load_google():
    """Import the google client modules once, or None when
    they are not installed yet."""
    global _google
    if _google is None:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            _google = {
                "Request": Request,
                "Credentials": Credentials,
                "build": build,
            }
        except Exception:  # noqa: BLE001 - no calendar on this PC
            _google = False
    return _google or None


def google_available() -> bool:
    """True when the google client libraries import."""
    return _load_google() is not None


def set_credentials_path(path: str) -> None:
    """Point the credentials file elsewhere — used by tests."""
    global _CRED_PATH
    _CRED_PATH = path


def set_token_path(path: str) -> None:
    """Point the token file elsewhere — used by tests."""
    global _TOKEN_PATH
    _TOKEN_PATH = path


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def has_credentials() -> bool:
    """A credentials file is present (downloaded OAuth client
    or a flat client_id/client_secret pair — the setup script
    only accepts the downloaded form, but the reader is
    lenient so an older file still works)."""
    data = _read_json(_CRED_PATH)
    if not isinstance(data, dict):
        return False
    for key in ("installed", "web"):
        inner = data.get(key)
        if isinstance(inner, dict) and inner.get("client_id"):
            return True
    return bool(data.get("client_id") and data.get("client_secret"))


def has_token() -> bool:
    """A login has been completed (a refresh token is stored)."""
    data = _read_json(_TOKEN_PATH)
    return bool(isinstance(data, dict) and data.get("refresh_token"))


def calendar_configured() -> bool:
    """Credentials AND a login are both present."""
    return has_credentials() and has_token()


def _save_token(data: dict) -> None:
    with open(_TOKEN_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:
        pass  # best effort; Windows ignores the mode anyway


def _load_credentials():
    """A valid Credentials object, refreshing it first when
    needed, or None when there is no login yet / the refresh
    failed / the libraries are missing."""
    google = _load_google()
    if google is None:
        return None
    info = _read_json(_TOKEN_PATH)
    if not isinstance(info, dict) or not info.get("refresh_token"):
        return None
    try:
        creds = google["Credentials"].from_authorized_user_info(
            info, SCOPES)
    except Exception:  # noqa: BLE001 - bad token file, not configured
        return None
    if creds.valid:
        return creds
    if not creds.expired or not creds.refresh_token:
        return None
    try:
        creds.refresh(google["Request"]())
    except Exception:  # noqa: BLE001 - revoked / offline
        return None
    try:
        _save_token(json.loads(creds.to_json()))
    except Exception:  # noqa: BLE001, S110 - refresh still counts
        pass
    return creds


def _parse_event(item: dict):
    """One API event -> {summary, start (datetime|None),
    all_day}. Times are converted to IST for display; an
    event without a usable start still shows (summary only)."""
    summary = (item.get("summary") or "(No title)").strip()
    start = item.get("start") or {}
    when = None
    all_day = False
    raw = start.get("dateTime")
    if raw:
        try:
            # fromisoformat handles "+05:30"; the "Z" suffix
            # needs help on older Pythons, so normalise it.
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if when.tzinfo is not None:
                when = when.astimezone(_LOCAL_TZ)
        except ValueError:
            when = None
    elif start.get("date"):
        all_day = True
        try:
            day = datetime.strptime(start["date"], "%Y-%m-%d")
            when = day.replace(tzinfo=_LOCAL_TZ)
        except ValueError:
            when = None
    return {"summary": summary, "start": when, "all_day": all_day}


def _fmt_time(when: datetime) -> str:
    return when.strftime("%I:%M %p").lstrip("0")


def fetch_today_events(now: datetime | None = None):
    """Today's events, soonest first — or None when the
    calendar is not connected, the libraries are missing, or
    the fetch failed (offline, revoked login). Never raises."""
    google = _load_google()
    if google is None or not calendar_configured():
        return None
    creds = _load_credentials()
    if creds is None:
        return None
    now = now or datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    start_iso = day_start.replace(tzinfo=_LOCAL_TZ).isoformat()
    end_iso = day_end.replace(tzinfo=_LOCAL_TZ).isoformat()
    try:
        service = google["build"]("calendar", "v3", credentials=creds)
        result = service.events().list(
            calendarId=_CALENDAR_ID,
            timeMin=start_iso,
            timeMax=end_iso,
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute()
        items = result.get("items", [])
    except Exception:  # noqa: BLE001 - offline / API error
        return None
    try:
        events = [_parse_event(item) for item in items]
    except Exception:  # noqa: BLE001 - unreadable payload
        return None
    events.sort(key=lambda e: (
        e["start"] is None,
        e["start"] or datetime.min.replace(tzinfo=_LOCAL_TZ),
        not e["all_day"],
    ))
    return events


def calendar_line(now: datetime | None = None):
    """One spoken line for the briefing — or None when the
    calendar is not connected or the fetch failed (the
    briefing omits it silently, like the weather line). A
    connected calendar with nothing on still says so: "No
    events on your calendar today." is information, not an
    error."""
    if _cache["line"] is not None and _cache["at"] is not None:
        if datetime.now() < _cache["at"] + timedelta(
                minutes=_CACHE_MINUTES):
            return _cache["line"]
    events = fetch_today_events(now)
    if events is None:
        return None  # not cached — the next call retries
    if not events:
        line = "No events on your calendar today."
    else:
        parts = []
        for event in events:
            if event["all_day"]:
                parts.append(f"{event['summary']} (all day)")
            elif event["start"] is not None:
                parts.append(
                    f"{event['summary']} at {_fmt_time(event['start'])}")
            else:
                parts.append(event["summary"])
        line = "Today's calendar: " + "; ".join(parts) + "."
    _cache["line"] = line
    _cache["at"] = datetime.now()
    return line


def calendar_status() -> dict:
    """One dict for the Control Center + Diagnostics tab."""
    return {
        "available": google_available(),
        "configured": calendar_configured(),
        "has_credentials": has_credentials(),
        "has_token": has_token(),
    }


def parse_calendar_command(text: str):
    """Match spoken text to a calendar request. None if no match."""
    t = text.strip().lower()
    if t in (
        "what's on my calendar today",
        "what is on my calendar today",
        "what's on my calendar",
        "what is on my calendar",
        "any meetings today",
        "do i have any meetings today",
        "do i have any meetings",
        "what meetings do i have today",
        "meetings today",
        "calendar today",
        "what's on the calendar today",
    ):
        return {"kind": "events"}
    if t in (
        "calendar status",
        "is calendar connected",
        "is my calendar connected",
        "is google calendar connected",
    ):
        return {"kind": "status"}
    return None


def execute_calendar_command(cmd: dict):
    """Run a parsed calendar command. Returns (reply, None) —
    calendar never needs a GUI action."""
    kind = cmd["kind"]
    if kind == "status":
        status = calendar_status()
        if not status["available"]:
            return (
                "Google Calendar isn't available on this PC — "
                "the Google libraries aren't installed. Run: pip "
                "install -r requirements.txt, then restart AURA.",
                None,
            )
        if not status["has_credentials"]:
            return (
                "Google Calendar isn't connected — no credentials "
                "file yet. Create an OAuth client in Google Cloud "
                "Console and save it as google_credentials.json "
                "next to main.py, then run calendar_setup.py.",
                None,
            )
        if not status["has_token"]:
            return (
                "Google Calendar has credentials but no login yet "
                "— run calendar_setup.py once to connect it.",
                None,
            )
        return (
            "Google Calendar is connected — today's events are "
            "in your daily briefing.",
            None,
        )
    if kind == "events":
        if not calendar_configured():
            return (
                "Google Calendar isn't connected yet — run "
                "calendar_setup.py once to connect it.",
                None,
            )
        line = calendar_line()
        if line is None:
            return (
                "I couldn't reach Google Calendar — check your "
                "internet and try again.",
                None,
            )
        return line, None
    return "I don't know how to do that yet.", None
