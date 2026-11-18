"""Tests for Phase 9.2B — Google Calendar in the briefing.

No real Google call is made: the google client libraries are
faked in sys.modules (same pattern as test_tray.py stubs
pystray). The fake service returns canned events so parsing,
timezones, caching, refresh and voice routing are all
asserted with no network.

    python test_calendar.py
"""

import json
import os
import sys
import tempfile
import types
from datetime import datetime

from aura.brain import handle, set_custom_store, set_memory
from aura.calendar import (
    _reset_cache,
    calendar_configured,
    calendar_line,
    calendar_status,
    execute_calendar_command,
    fetch_today_events,
    google_available,
    has_credentials,
    has_token,
    parse_calendar_command,
    set_credentials_path,
    set_token_path,
)
from aura.commands.custom import CustomStore
from aura.memory import Memory


class _FakeCredentials:
    """Stands in for google.oauth2.credentials.Credentials."""

    expired_mode = False
    refresh_calls = []

    def __init__(self, info):
        self._info = dict(info)
        self.refresh_token = info.get("refresh_token")
        self.valid = not _FakeCredentials.expired_mode
        self.expired = _FakeCredentials.expired_mode

    @classmethod
    def from_authorized_user_info(cls, info, scopes):
        return cls(info)

    def refresh(self, request):
        _FakeCredentials.refresh_calls.append(request)
        self._info["token"] = "new-access-token"
        self.valid = True
        self.expired = False

    def to_json(self):
        return json.dumps(self._info)


class _FakeRequest:
    pass


class _FakeListCall:
    def __init__(self, service, kwargs):
        self._service = service
        self.kwargs = kwargs

    def execute(self):
        if self._service.raise_on_execute:
            raise Exception("offline")
        return {"items": self._service.items}


class _FakeEvents:
    def __init__(self, service):
        self._service = service

    def list(self, **kwargs):
        self._service.list_kwargs.append(kwargs)
        return _FakeListCall(self._service, kwargs)


class _FakeService:
    items = []
    list_kwargs = []
    raise_on_execute = False
    build_calls = []

    def events(self):
        return _FakeEvents(self)


def _fake_build(*args, **kwargs):
    _FakeService.build_calls.append((args, kwargs))
    return _FakeService()


def _install_fake_google():
    """Put fake google client modules in sys.modules."""
    google = types.ModuleType("google")
    google.__path__ = []
    auth = types.ModuleType("google.auth")
    auth.__path__ = []
    transport = types.ModuleType("google.auth.transport")
    transport.__path__ = []
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = _FakeRequest
    oauth2 = types.ModuleType("google.oauth2")
    oauth2.__path__ = []
    creds_mod = types.ModuleType("google.oauth2.credentials")
    creds_mod.Credentials = _FakeCredentials
    client = types.ModuleType("googleapiclient")
    client.__path__ = []
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = _fake_build
    sys.modules["google"] = google
    sys.modules["google.auth"] = auth
    sys.modules["google.auth.transport"] = transport
    sys.modules["google.auth.transport.requests"] = requests_mod
    sys.modules["google.oauth2"] = oauth2
    sys.modules["google.oauth2.credentials"] = creds_mod
    sys.modules["googleapiclient"] = client
    sys.modules["googleapiclient.discovery"] = discovery
    _FakeService.items = []
    _FakeService.list_kwargs = []
    _FakeService.raise_on_execute = False
    _FakeService.build_calls = []
    _FakeCredentials.expired_mode = False
    _FakeCredentials.refresh_calls = []
    _reset_cache()


def _remove_fake_google():
    for name in (
        "google", "google.auth", "google.auth.transport",
        "google.auth.transport.requests", "google.oauth2",
        "google.oauth2.credentials", "googleapiclient",
        "googleapiclient.discovery",
    ):
        sys.modules.pop(name, None)
    _reset_cache()


def _write(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


_NOW = datetime(2026, 11, 18, 9, 0)  # a Wednesday morning

_ITEMS = [
    {"summary": "Team standup",
     "start": {"dateTime": "2026-11-18T10:00:00+05:30"}},
    {"summary": "Diwali", "start": {"date": "2026-11-18"}},
    {"summary": "Call with US team",
     "start": {"dateTime": "2026-11-18T14:30:00Z"}},
    {"start": {"dateTime": "2026-11-18T09:00:00+05:30"}},
]


def main():
    tmp = tempfile.mkdtemp()
    cred_path = os.path.join(tmp, "google_credentials.json")
    token_path = os.path.join(tmp, "google_token.json")
    set_credentials_path(cred_path)
    set_token_path(token_path)
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Nothing configured: everything is None, honestly. ------
    _install_fake_google()
    try:
        assert google_available() is True
        assert has_credentials() is False
        assert has_token() is False
        assert calendar_configured() is False
        assert fetch_today_events(_NOW) is None
        assert calendar_line(_NOW) is None
        status = calendar_status()
        assert status == {"available": True, "configured": False,
                          "has_credentials": False,
                          "has_token": False}, status

        # --- Credentials file: downloaded form, flat form, junk. --
        _write(cred_path, {"installed": {
            "client_id": "id-123", "client_secret": "secret-123"}})
        assert has_credentials() is True
        assert calendar_configured() is False, "no token yet"
        _write(cred_path, {"client_id": "id-123",
                           "client_secret": "secret-123"})
        assert has_credentials() is True, "flat form also accepted"
        _write(cred_path, {"not": "credentials"})
        assert has_credentials() is False
        _write(cred_path, {"installed": {
            "client_id": "id-123", "client_secret": "secret-123"}})

        # --- Token file: login present, then fetch + parse. -------
        _write(token_path, {
            "refresh_token": "refresh-abc", "token": "access-abc",
            "client_id": "id-123", "client_secret": "secret-123",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
        })
        assert has_token() is True
        assert calendar_configured() is True
        _FakeService.items = list(_ITEMS)
        events = fetch_today_events(_NOW)
        assert events is not None and len(events) == 4, events
        # All-day first (midnight), then by time; the UTC event
        # converts to IST (14:30Z -> 8:00 PM).
        assert [e["summary"] for e in events] == [
            "Diwali", "(No title)", "Team standup",
            "Call with US team"], events
        assert events[0]["all_day"] is True
        assert events[2]["start"].strftime("%I:%M %p") == "10:00 AM"
        assert events[3]["start"].strftime("%I:%M %p") == "08:00 PM"
        # The API call asked for today only, single events, in order.
        kwargs = _FakeService.list_kwargs[-1]
        assert kwargs["calendarId"] == "primary"
        assert kwargs["timeMin"] == "2026-11-18T00:00:00+05:30", kwargs
        assert kwargs["timeMax"] == "2026-11-19T00:00:00+05:30", kwargs
        assert kwargs["singleEvents"] is True
        assert kwargs["orderBy"] == "startTime"

        # --- The spoken line, and its 5-minute cache. -------------
        line = calendar_line(_NOW)
        assert line == (
            "Today's calendar: Diwali (all day); (No title) at "
            "9:00 AM; Team standup at 10:00 AM; Call with US "
            "team at 8:00 PM."), line
        builds = len(_FakeService.build_calls)
        assert calendar_line(_NOW) == line, "second call is cached"
        assert len(_FakeService.build_calls) == builds, \
            "cached line must not hit the API again"

        # --- Zero events still says so. ---------------------------
        _reset_cache()
        _FakeService.items = []
        assert calendar_line(_NOW) == \
            "No events on your calendar today."

        # --- Offline: None, and NOT cached (next call retries). ---
        _reset_cache()
        _FakeService.items = list(_ITEMS)
        _FakeService.raise_on_execute = True
        assert fetch_today_events(_NOW) is None
        assert calendar_line(_NOW) is None
        _FakeService.raise_on_execute = False
        assert calendar_line(_NOW) is not None, \
            "a failed fetch must not be cached"

        # --- Expired token: refresh runs, new token is saved. -----
        _reset_cache()
        _FakeCredentials.expired_mode = True
        _FakeService.items = list(_ITEMS)
        events = fetch_today_events(_NOW)
        assert events is not None and len(events) == 4, events
        assert len(_FakeCredentials.refresh_calls) == 1, \
            "expired token must refresh once"
        with open(token_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        assert saved["token"] == "new-access-token", saved
        _FakeCredentials.expired_mode = False

        # --- Parser: every phrasing, and no false friends. --------
        for phrase in (
            "what's on my calendar today",
            "what is on my calendar",
            "any meetings today",
            "do i have any meetings today",
            "what meetings do i have today",
            "meetings today",
            "calendar today",
            "calendar status",
            "is calendar connected",
        ):
            assert parse_calendar_command(phrase) is not None, phrase
        assert parse_calendar_command("what's on today") is None, \
            "that is the briefing, not the calendar"
        assert parse_calendar_command("open notepad") is None
        assert parse_calendar_command("what is the time") is None

        # --- Voice end to end through handle(). --------------------
        _reset_cache()
        _FakeService.items = list(_ITEMS)
        reply, quit_ = handle("what's on my calendar today")
        assert "Team standup" in reply and not quit_, reply
        reply, _ = handle("any meetings today")
        assert "Diwali" in reply, reply
        reply, _ = handle("calendar status")
        assert "connected" in reply, reply
        reply, action = execute_calendar_command({"kind": "status"})
        assert action is None, "calendar never needs a GUI action"

        # --- Not configured: the voice question says how to fix it.
        os.remove(token_path)
        _reset_cache()
        reply, _ = handle("what's on my calendar today")
        assert "calendar_setup.py" in reply, reply
        reply, _ = handle("calendar status")
        assert "calendar_setup.py" in reply, reply
    finally:
        _remove_fake_google()

    # --- No google libraries on this VM: honest degradation. -----
    assert google_available() is False
    assert calendar_status()["available"] is False
    assert calendar_configured() is False
    assert fetch_today_events(_NOW) is None
    assert calendar_line(_NOW) is None
    reply, _ = handle("what's on my calendar today")
    assert "isn't connected" in reply, reply

    print("All calendar tests passed.")


if __name__ == "__main__":
    main()
