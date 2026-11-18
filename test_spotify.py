"""Tests for Phase 9.1 — Spotify control.

Two layers: local media keys (no setup, Windows-only) and the
Web API (optional, needs a Spotify app + one-time login). All
HTTP is stubbed (requests.get / post / put) and the browser
open is stubbed — no real network, no real Spotify account.

    python test_spotify.py
"""

import json
import os
import tempfile
import time
import webbrowser

import requests

from aura import spotify
from aura.brain import handle, set_custom_store, set_memory
from aura.chat import set_chat_enabled
from aura.chat import set_key_file_path as set_chat_key_file_path
from aura.chat import set_settings_path as set_chat_settings_path
from aura.commands.custom import CustomStore
from aura.commands.spotify_cmds import (
    execute_spotify_command,
    parse_spotify_command,
)
from aura.language import set_settings_path as set_language_settings_path
from aura.memory import Memory
from aura.spotify import SpotifyError


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _track_item(name="Lo-Fi Beats", artist="Chillhop", uri="spotify:track:abc"):
    return {"name": name, "artists": [{"name": artist}], "uri": uri}


def _playlist_item(name="Lo-Fi Vibes", uri="spotify:playlist:xyz"):
    return {
        "name": name,
        "owner": {"display_name": "Spotify"},
        "uri": uri,
    }


def _write_token(path, access="acc-valid", refresh="ref-1", expires_in=3600):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": time.time() + expires_in,
        }, fh)


def main():
    tmp = tempfile.mkdtemp()
    creds_path = os.path.join(tmp, "spotify_credentials.json")
    token_path = os.path.join(tmp, "spotify_token.json")
    spotify.set_credentials_path(creds_path)
    spotify.set_token_path(token_path)
    set_chat_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_key_file_path(os.path.join(tmp, "groq_api_key.txt"))
    set_language_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_enabled(False)
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    saved_env = {}
    for var in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        saved_env[var] = os.environ.pop(var, None)

    try:
        # --- Credentials: env wins, else JSON file, else lines. ----
        assert spotify.get_credentials() == (None, None)
        assert spotify.api_configured() is False
        with open(creds_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"client_id": "file-id", "client_secret": "file-secret"}, fh)
        assert spotify.get_credentials() == ("file-id", "file-secret")
        assert spotify.api_configured() is True
        os.environ["SPOTIFY_CLIENT_ID"] = "env-id"
        assert spotify.get_credentials() == ("env-id", "file-secret")
        del os.environ["SPOTIFY_CLIENT_ID"]
        with open(creds_path, "w", encoding="utf-8") as fh:
            fh.write("client_id=line-id\nclient_secret=line-secret\n")
        assert spotify.get_credentials() == ("line-id", "line-secret")
        os.remove(creds_path)
        assert spotify.get_credentials() == (None, None)

        # --- Auth URL: right host, redirect, scopes. ---------------
        with open(creds_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"client_id": "my-id", "client_secret": "my-secret"}, fh)
        url = spotify.get_auth_url()
        assert url.startswith("https://accounts.spotify.com/authorize"), url
        assert "client_id=my-id" in url, url
        assert "127.0.0.1%3A8888%2Fcallback" in url, url
        assert "user-modify-playback-state" in url, url
        assert "user-read-currently-playing" in url, url

        # --- exchange_code: tokens saved, failures honest. ----------
        real_post = requests.post
        posts = []

        def _stub_token_ok(url, data=None, headers=None, timeout=None):
            posts.append({"url": url, "data": data, "headers": headers})
            assert url == "https://accounts.spotify.com/api/token", url
            assert "Basic " in headers["Authorization"], headers
            return _FakeResponse(payload={
                "access_token": "acc-new",
                "refresh_token": "ref-new",
                "expires_in": 3600,
            })

        requests.post = _stub_token_ok
        try:
            assert spotify.exchange_code("auth-code-1") is True
            saved = json.load(open(token_path, encoding="utf-8"))
            assert saved["access_token"] == "acc-new", saved
            assert saved["refresh_token"] == "ref-new", saved
            assert saved["expires_at"] > time.time(), saved
            assert spotify.has_token() is True

            # A failed exchange saves nothing.
            def _stub_token_bad(url, data=None, headers=None, timeout=None):
                return _FakeResponse(status_code=400, payload={})

            requests.post = _stub_token_bad
            os.remove(token_path)
            assert spotify.exchange_code("bad-code") is False
            assert os.path.exists(token_path) is False
        finally:
            requests.post = real_post

        # --- Access token: valid one reused, expired one refreshed.
        # A refresh that omits the refresh token keeps the old one.
        _write_token(token_path, access="acc-valid", refresh="ref-1")
        assert spotify._access_token() == "acc-valid"
        _write_token(
            token_path, access="acc-stale", refresh="ref-1", expires_in=-10)

        def _stub_refresh(url, data=None, headers=None, timeout=None):
            assert data["grant_type"] == "refresh_token", data
            assert data["refresh_token"] == "ref-1", data
            return _FakeResponse(payload={
                "access_token": "acc-refreshed", "expires_in": 3600,
            })

        requests.post = _stub_refresh
        try:
            assert spotify._access_token() == "acc-refreshed"
            saved = json.load(open(token_path, encoding="utf-8"))
            assert saved["refresh_token"] == "ref-1", saved
            assert saved["access_token"] == "acc-refreshed", saved
        finally:
            requests.post = real_post

        # --- Play a track: search, then play by URI on the PC. ---
        # Every play goes through the devices list first, so the
        # GET stub answers both /search and /me/player/devices.
        _write_token(token_path)
        real_get = requests.get
        real_put = requests.put
        gets = []
        puts = []
        _pc_devices = {"devices": [{
            "id": "pc-1", "name": "Jay's PC", "type": "Computer",
            "is_active": True,
        }]}

        def _stub_search_track(url, headers=None, params=None, timeout=None):
            gets.append({"url": url, "params": params})
            if url == "https://api.spotify.com/v1/me/player/devices":
                return _FakeResponse(payload=_pc_devices)
            assert url == "https://api.spotify.com/v1/search", url
            assert headers["Authorization"] == "Bearer acc-valid", headers
            assert params["q"] == "lo-fi", params
            assert params["type"] == "track", params
            assert params["limit"] == 1, params
            return _FakeResponse(payload={
                "tracks": {"items": [_track_item()]}})

        def _stub_put_ok(url, headers=None, json=None, timeout=None):
            puts.append({"url": url, "json": json})
            assert url == "https://api.spotify.com/v1/me/player/play", url
            return _FakeResponse(status_code=204, payload=None)

        requests.get = _stub_search_track
        requests.put = _stub_put_ok
        try:
            reply = spotify.play_track("lo-fi")
            assert reply == "Playing Lo-Fi Beats by Chillhop on Spotify.", reply
            assert puts[0]["json"] == {
                "uris": ["spotify:track:abc"], "device_id": "pc-1"}, puts

            # --- No track? A playlist match plays by context. ------
            def _stub_search_playlist(url, headers=None, params=None,
                                      timeout=None):
                if url.endswith("/me/player/devices"):
                    return _FakeResponse(payload=_pc_devices)
                if params["type"] == "track":
                    return _FakeResponse(payload={"tracks": {"items": []}})
                return _FakeResponse(payload={
                    "playlists": {"items": [_playlist_item()]}})

            requests.get = _stub_search_playlist
            puts.clear()
            reply = spotify.play_track("lo-fi vibes")
            assert reply == (
                "Playing the Lo-Fi Vibes playlist on Spotify."
            ), reply
            assert puts[0]["json"] == {
                "context_uri": "spotify:playlist:xyz",
                "device_id": "pc-1"}, puts

            # --- Nothing found at all. ------------------------------
            def _stub_search_none(url, headers=None, params=None,
                                  timeout=None):
                key = params["type"] + "s"
                return _FakeResponse(payload={key: {"items": []}})

            requests.get = _stub_search_none
            reply = spotify.play_track("zzzqqq")
            assert reply == "I couldn't find zzzqqq on Spotify.", reply

            # --- No active device: plain words, not a bare 404. -----
            requests.get = _stub_search_track

            def _stub_put_no_device(url, headers=None, json=None,
                                    timeout=None):
                return _FakeResponse(status_code=404, payload={
                    "error": {"reason": "NO_ACTIVE_DEVICE"}})

            requests.put = _stub_put_no_device
            reply = spotify.play_track("lo-fi")
            assert "isn't open on any device" in reply, reply

            # --- Free account: Premium is Spotify's rule. -----------
            # The 403 raises (with web_fallback) instead of
            # returning — the caller opens the web search.
            def _stub_put_premium(url, headers=None, json=None, timeout=None):
                return _FakeResponse(status_code=403, payload={})

            requests.put = _stub_put_premium
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("403 must raise SpotifyError")
            except SpotifyError as exc:
                assert "Premium" in str(exc), exc
                assert exc.web_fallback is True, exc

            # --- A rejected login says to re-run the setup. ---------
            def _stub_search_401(url, headers=None, params=None,
                                 timeout=None):
                return _FakeResponse(status_code=401, payload={})

            requests.get = _stub_search_401
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("401 must raise SpotifyError")
            except SpotifyError as exc:
                assert "spotify_setup.py" in str(exc), exc

            # --- A 403 search carries Spotify's own reason. -------
            # (Feb 2026 rule: the app owner needs Premium — a
            # bare "HTTP 403" hid that completely.)
            def _stub_search_403_premium(url, headers=None, params=None,
                                         timeout=None):
                return _FakeResponse(status_code=403, payload={
                    "error": {"message": "Active premium subscription "
                              "required for the owner of the app"}})

            requests.get = _stub_search_403_premium
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("403 must raise SpotifyError")
            except SpotifyError as exc:
                assert "premium" in str(exc).lower(), exc
                assert "403" in str(exc), exc
                assert exc.web_fallback is True, exc

            # --- ...unless the body carries no message at all. -----
            def _stub_search_403_empty(url, headers=None, params=None,
                                       timeout=None):
                return _FakeResponse(status_code=403, payload={})

            requests.get = _stub_search_403_empty
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("403 must raise SpotifyError")
            except SpotifyError as exc:
                assert "HTTP 403" in str(exc), exc
                assert "Premium" not in str(exc), exc
                assert exc.web_fallback is True, exc

            def _stub_search_403_bad_json(url, headers=None, params=None,
                                          timeout=None):
                return _FakeResponse(status_code=403, bad_json=True)

            requests.get = _stub_search_403_bad_json
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("403 must raise SpotifyError")
            except SpotifyError as exc:
                assert "HTTP 403" in str(exc), exc

            # --- Offline: honest, never a crash. --------------------
            def _stub_get_down(url, headers=None, params=None, timeout=None):
                raise requests.ConnectionError("offline")

            requests.get = _stub_get_down
            try:
                spotify.play_track("lo-fi")
                raise AssertionError("offline must raise SpotifyError")
            except SpotifyError as exc:
                assert "internet" in str(exc).lower(), exc

            # --- Device choice: the PC always wins over the phone.
            # (The bug: with no device_id, Spotify played on the
            # last-active device — the phone — while AURA said
            # "Playing ...".) A plain search stub answers the
            # /search call; the devices list varies per case.
            def _stub_get_devices(devices):
                def _stub(url, headers=None, params=None, timeout=None):
                    if url.endswith("/me/player/devices"):
                        return _FakeResponse(payload={"devices": devices})
                    return _stub_search_track(
                        url, headers, params, timeout)
                return _stub

            _phone_active = {
                "id": "phone-1", "name": "Jay's phone",
                "type": "Smartphone", "is_active": True,
            }
            _pc_active = {
                "id": "pc-2", "name": "Jay's PC",
                "type": "Computer", "is_active": True,
            }
            _pc_idle = {
                "id": "pc-2", "name": "Jay's PC",
                "type": "Computer", "is_active": False,
            }
            requests.put = _stub_put_ok

            # An active PC beats an active phone.
            requests.get = _stub_get_devices([_phone_active, _pc_active])
            puts.clear()
            reply = spotify.play_track("lo-fi")
            assert reply == (
                "Playing Lo-Fi Beats by Chillhop on Spotify."), reply
            assert puts[0]["json"]["device_id"] == "pc-2", puts

            # An idle PC still beats an active phone.
            requests.get = _stub_get_devices([_phone_active, _pc_idle])
            puts.clear()
            reply = spotify.play_track("lo-fi")
            assert puts[0]["json"]["device_id"] == "pc-2", puts

            # No Computer at all: honest words, and NO play call —
            # never silently play on the phone.
            requests.get = _stub_get_devices([_phone_active, {
                "id": "speaker-1", "name": "Speaker",
                "type": "Speaker", "is_active": False,
            }])
            puts.clear()
            reply = spotify.play_track("lo-fi")
            assert "isn't open on your PC" in reply, reply
            assert puts == [], puts

            # The devices call itself failing is an honest error.
            def _stub_devices_down(url, headers=None, params=None,
                                   timeout=None):
                if url.endswith("/me/player/devices"):
                    raise requests.ConnectionError("offline")
                return _stub_search_track(url, headers, params, timeout)

            requests.get = _stub_devices_down
            try:
                spotify.play_track("lo-fi")
                raise AssertionError(
                    "devices failure must raise SpotifyError")
            except SpotifyError as exc:
                assert "internet" in str(exc).lower(), exc

            # The picker itself: active PC, then any PC, then None.
            assert spotify._pick_pc_device(
                [_phone_active, _pc_idle]) == _pc_idle
            assert spotify._pick_pc_device(
                [_phone_active, _pc_active]) == _pc_active
            assert spotify._pick_pc_device([_phone_active]) is None
            assert spotify._pick_pc_device([]) is None
        finally:
            requests.get = real_get
            requests.put = real_put

        # --- What's playing: playing / paused / nothing. -----------
        def _stub_playing(url, headers=None, params=None, timeout=None):
            return _FakeResponse(payload={
                "is_playing": True,
                "item": _track_item("Midnight City", "M83"),
            })

        requests.get = _stub_playing
        try:
            assert spotify.currently_playing() == (
                "Playing Midnight City by M83 on Spotify."
            )

            def _stub_paused(url, headers=None, params=None, timeout=None):
                return _FakeResponse(payload={
                    "is_playing": False,
                    "item": _track_item("Midnight City", "M83"),
                })

            requests.get = _stub_paused
            assert spotify.currently_playing() == (
                "Paused on Midnight City by M83 on Spotify."
            )

            def _stub_none(url, headers=None, params=None, timeout=None):
                return _FakeResponse(status_code=204, payload=None)

            requests.get = _stub_none
            assert spotify.currently_playing() == (
                "Nothing is playing on Spotify right now."
            )
        finally:
            requests.get = real_get

        # --- Premium 403: the browser search opens instead. -------
        # (Free account: the API is blocked, but the web player
        # works — so "play X" falls back to the web search
        # instead of stopping at the error.)
        opened_premium = []
        real_open2 = webbrowser.open
        webbrowser.open = lambda url: opened_premium.append(url) or True
        try:
            # 403 on the search call itself.
            requests.get = _stub_search_403_premium
            reply = execute_spotify_command(
                {"kind": "play_on_spotify", "query": "lo-fi"})
            assert "Premium" in reply and "browser" in reply, reply
            assert "press play there" in reply, reply
            assert opened_premium == [
                "https://open.spotify.com/search/lo-fi"], opened_premium

            # 403 on the play PUT, search fine.
            requests.get = _stub_search_track
            requests.put = _stub_put_premium
            opened_premium.clear()
            reply = execute_spotify_command(
                {"kind": "play_on_spotify", "query": "lo-fi"})
            assert "Premium" in reply and "browser" in reply, reply
            assert "press play there" in reply, reply
            assert opened_premium == [
                "https://open.spotify.com/search/lo-fi"], opened_premium

            # 401: still the re-run-setup words, no browser open.
            requests.get = _stub_search_401
            opened_premium.clear()
            reply = execute_spotify_command(
                {"kind": "play_on_spotify", "query": "lo-fi"})
            assert "spotify_setup.py" in reply, reply
            assert opened_premium == [], opened_premium
        finally:
            requests.get = real_get
            requests.put = real_put
            webbrowser.open = real_open2

        # --- No login at all: None, so the caller can fall back. ---
        os.remove(token_path)
        assert spotify.has_token() is False
        assert spotify.play_track("lo-fi") is None
        assert spotify.currently_playing() is None
    finally:
        for var, value in saved_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value

    # --- Parser: every phrasing, and no false friends. ------------
    assert parse_spotify_command(
        "play lo-fi beats on spotify") == {
            "kind": "play_on_spotify", "query": "lo-fi beats"}
    assert parse_spotify_command(
        "play lofi using spotify") == {
            "kind": "play_on_spotify", "query": "lofi"}
    assert parse_spotify_command(
        "what's playing") == {"kind": "now_playing"}
    assert parse_spotify_command(
        "what song is this") == {"kind": "now_playing"}
    assert parse_spotify_command(
        "pause spotify") == {"kind": "media_key", "action": "play_pause"}
    assert parse_spotify_command(
        "play spotify") == {"kind": "media_key", "action": "play_pause"}
    assert parse_spotify_command(
        "play music on spotify") == {"kind": "media_key", "action": "play_pause"}
    assert parse_spotify_command(
        "next song on spotify") == {"kind": "media_key", "action": "next"}
    assert parse_spotify_command(
        "previous track on spotify") == {
            "kind": "media_key", "action": "previous"}
    assert parse_spotify_command("what is the time") is None
    assert parse_spotify_command("open spotify") is None
    assert parse_spotify_command("play something on youtube") is None

    # --- Bare "play <name>": Spotify too (Jay's habit). --------
    assert parse_spotify_command(
        "play lofi") == {"kind": "play_on_spotify", "query": "lofi"}
    assert parse_spotify_command(
        "play fresh") == {"kind": "play_on_spotify", "query": "fresh"}
    assert parse_spotify_command(
        "play music") == {"kind": "media_key", "action": "play_pause"}
    assert parse_spotify_command("play lofi on youtube") is None
    assert parse_spotify_command("play") is None

    # --- Local media keys: no setup, Windows-only in practice. ----
    # (This VM is Linux, so the key press itself is refused
    # honestly — the routing is what is tested here.)
    assert execute_spotify_command(
        {"kind": "media_key", "action": "play_pause"}
    ) == "Media keys only work on Windows."

    # --- Not connected: the browser search, said plainly. ---------
    opened = []
    real_open = webbrowser.open
    webbrowser.open = lambda url: opened.append(url) or True
    try:
        reply = execute_spotify_command(
            {"kind": "play_on_spotify", "query": "lo-fi beats"})
        assert "isn't connected" in reply and "browser" in reply, reply
        assert opened == [
            "https://open.spotify.com/search/lo-fi+beats"], opened
        reply = execute_spotify_command({"kind": "now_playing"})
        assert "isn't connected" in reply, reply
    finally:
        webbrowser.open = real_open

    # --- Voice end to end through handle(). -----------------------
    webbrowser.open = lambda url: opened.append(url) or True
    try:
        opened.clear()
        reply, quit_ = handle("play lo-fi on spotify")
        assert "isn't connected" in reply and "browser" in reply, reply
        assert opened == ["https://open.spotify.com/search/lo-fi"], opened
        assert not quit_
        reply, _ = handle("what's playing")
        assert "isn't connected" in reply, reply
        # A taught phrase with the same words still wins.
        set_custom_store(CustomStore(os.path.join(tmp, "custom2.json")))
        reply, _ = handle(
            "teach aura play lo-fi on spotify means what is the time")
        assert "Got it" in reply, reply
        reply, _ = handle("play lo-fi on spotify")
        assert "It's" in reply, reply
        # Unrelated commands leave Spotify alone; help mentions it.
        reply, _ = handle("what is the time")
        assert "Spotify" not in reply, reply
        assert "spotify" in handle("help")[0].lower()
    finally:
        webbrowser.open = real_open

    print("All Spotify tests passed.")


if __name__ == "__main__":
    main()
