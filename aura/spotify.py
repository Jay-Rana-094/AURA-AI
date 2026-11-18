"""Spotify Web API layer — Phase 9.1.

Direct requests calls (no spotipy dependency — the few calls
AURA needs fit in this one module). Two states:

  - Not configured (no client id/secret, or no login yet):
    the voice layer falls back to opening the Spotify web
    search in the browser and says so honestly.
  - Configured: a Spotify app (Client ID + Secret) plus a
    one-time user login (run spotify_setup.py). A refresh
    token is stored in spotify_token.json next to main.py and
    the access token is refreshed automatically.

Playback control needs Spotify Premium and an active device
(the Spotify app open on the PC) — those are Spotify's
rules, not AURA's; both failures are spoken plainly. When
the API is blocked for want of Premium (HTTP 403), the
voice layer falls back to opening the Spotify web search
instead — the web player still works on a Free account.
Playback always targets the PC: when the app isn't open on
the PC, AURA says so instead of silently playing on
another device (e.g. the phone), which is what the bare
/me/player/play call used to do.

Credentials (same pattern as groq_api_key.txt — never in
chat, never zipped, never pushed, see .gitignore):
  - env vars SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET, or
  - spotify_credentials.json next to main.py:
        {"client_id": "...", "client_secret": "..."}
    (key=value lines, client_id=... / client_secret=...,
    are also accepted).

Only requests is needed, so this stays unit-testable
anywhere — tests stub requests.get / post / put.
"""

import base64
import json
import os
import time

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)
_TIMEOUT_SECS = 10

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CRED_PATH = os.path.join(_BASE, "spotify_credentials.json")
_TOKEN_PATH = os.path.join(_BASE, "spotify_token.json")


class SpotifyError(Exception):
    """An API call failed — the message is safe to speak aloud.

    web_fallback=True means the caller should open the Spotify
    web search instead: the API is blocked (a Free account has
    no Premium) but the web player still works in the browser.
    """

    def __init__(self, message, web_fallback=False):
        super().__init__(message)
        self.web_fallback = web_fallback


def set_credentials_path(path: str) -> None:
    """Point the credentials file elsewhere — used by tests."""
    global _CRED_PATH
    _CRED_PATH = path


def set_token_path(path: str) -> None:
    """Point the token file elsewhere — used by tests."""
    global _TOKEN_PATH
    _TOKEN_PATH = path


def _read_credentials_file():
    """(client_id, client_secret) from the file, or (None, None).
    JSON first, key=value lines as a fallback."""
    try:
        with open(_CRED_PATH, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return None, None
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
        return (
            (str(data.get("client_id") or "").strip() or None),
            (str(data.get("client_secret") or "").strip() or None),
        )
    except ValueError:
        pass
    client_id = client_secret = None
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "client_id":
            client_id = value.strip() or None
        elif key.strip() == "client_secret":
            client_secret = value.strip() or None
    return client_id, client_secret


def get_credentials():
    """(client_id, client_secret) — env vars win per field,
    then the credentials file. (None, None) when unset."""
    file_id, file_secret = _read_credentials_file()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip() or file_id
    client_secret = (
        os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip() or file_secret
    )
    return client_id, client_secret


def api_configured() -> bool:
    """A Spotify app is registered (id + secret present)."""
    client_id, client_secret = get_credentials()
    return bool(client_id and client_secret)


def _load_token() -> dict | None:
    try:
        with open(_TOKEN_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_token(token: dict) -> None:
    with open(_TOKEN_PATH, "w", encoding="utf-8") as fh:
        json.dump(token, fh, indent=2)
    try:
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:
        pass  # best effort; Windows ignores the mode anyway


def has_token() -> bool:
    """A login has been completed (a refresh token is stored)."""
    token = _load_token()
    return bool(token and token.get("refresh_token"))


def get_auth_url() -> str | None:
    """The Spotify login page for the one-time setup, or None
    when no app is registered yet."""
    client_id, _ = get_credentials()
    if not client_id:
        return None
    from urllib.parse import urlencode

    return (
        AUTH_URL + "?"
        + urlencode({
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "show_dialog": "true",
        })
    )


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def exchange_code(code: str) -> bool:
    """Swap a login code for tokens and save them. True on
    success — this is what the one-time setup script calls."""
    client_id, client_secret = get_credentials()
    if not client_id or not client_secret:
        return False
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=_TIMEOUT_SECS,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
    except (requests.RequestException, ValueError):
        return False
    if not data.get("access_token") or not data.get("refresh_token"):
        return False
    _save_token({
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + data.get("expires_in", 3600),
    })
    return True


def _access_token():
    """A valid access token, refreshing it first when needed,
    or None when there is no login yet / the refresh failed."""
    token = _load_token()
    if not token or not token.get("refresh_token"):
        return None
    if token.get("access_token") and token.get("expires_at", 0) > time.time() + 60:
        return token["access_token"]
    client_id, client_secret = get_credentials()
    if not client_id or not client_secret:
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=_TIMEOUT_SECS,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if not data.get("access_token"):
        return None
    _save_token({
        "access_token": data["access_token"],
        # Spotify may not return a new refresh token — keep the old one.
        "refresh_token": data.get("refresh_token", token["refresh_token"]),
        "expires_at": time.time() + data.get("expires_in", 3600),
    })
    return data["access_token"]


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _error_detail(resp) -> str:
    """Spotify's own error text, if any — short enough to speak.

    A bare "HTTP 403" hid the real cause once already (the
    Feb 2026 Premium-owner rule reads exactly like a broken
    setup), so failures carry the provider's message with
    them from now on — same pattern as chat.py's
    _error_detail.
    """
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except (ValueError, AttributeError, TypeError):
        return ""
    return str(detail).strip()[:160]


def _search(query: str, token: str, search_type: str):
    """First result of a search, or None when nothing matches.
    Raises SpotifyError on an API failure."""
    try:
        resp = requests.get(
            API_URL + "/search",
            headers=_headers(token),
            params={"q": query, "type": search_type, "limit": 1},
            timeout=_TIMEOUT_SECS,
        )
    except requests.RequestException:
        raise SpotifyError(
            "I couldn't reach Spotify — check your internet and "
            "try again."
        ) from None
    if resp.status_code == 401:
        raise SpotifyError(
            "Spotify rejected the login — run spotify_setup.py "
            "once to connect it again."
        )
    if resp.status_code != 200:
        detail = _error_detail(resp)
        if detail:
            raise SpotifyError(
                "Spotify refused the search "
                f"(HTTP {resp.status_code}): {detail}",
                web_fallback=resp.status_code == 403,
            )
        raise SpotifyError(
            "Spotify answered with an error "
            f"(HTTP {resp.status_code}).",
            web_fallback=resp.status_code == 403,
        )
    try:
        items = resp.json()[search_type + "s"]["items"]
    except (ValueError, KeyError, TypeError):
        raise SpotifyError(
            "Spotify gave back something I couldn't read."
        ) from None
    if not items:
        return None
    item = items[0]
    if search_type == "track":
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        return {
            "kind": "track",
            "name": item["name"],
            "artist": artists,
            "uri": item["uri"],
        }
    return {
        "kind": "playlist",
        "name": item["name"],
        "artist": item.get("owner", {}).get("display_name", ""),
        "uri": item["uri"],
    }


def _get_devices(token: str):
    """All available playback devices, or raise SpotifyError.
    Needs the user-read-playback-state scope (already in
    SCOPES) — no extra permission to ask for."""
    try:
        resp = requests.get(
            API_URL + "/me/player/devices",
            headers=_headers(token),
            timeout=_TIMEOUT_SECS,
        )
    except requests.RequestException:
        raise SpotifyError(
            "I couldn't reach Spotify — check your internet and "
            "try again."
        ) from None
    if resp.status_code == 401:
        raise SpotifyError(
            "Spotify rejected the login — run spotify_setup.py "
            "once to connect it again."
        )
    if resp.status_code != 200:
        raise SpotifyError(
            "Spotify answered with an error "
            f"(HTTP {resp.status_code})."
        )
    try:
        return resp.json()["devices"]
    except (ValueError, KeyError, TypeError):
        raise SpotifyError(
            "Spotify gave back something I couldn't read."
        ) from None


def _pick_pc_device(devices):
    """The PC to play on: the active Computer first, else any
    Computer. None when no Computer device is available —
    the caller then says so instead of playing elsewhere."""
    pcs = [d for d in (devices or []) if d.get("type") == "Computer"]
    for device in pcs:
        if device.get("is_active"):
            return device
    return pcs[0] if pcs else None


def play_track(query: str):
    """Play the best track (else playlist) match for ``query``.

    Returns a speakable reply, or None when Spotify is not
    connected at all (no login) — the caller then falls back
    to the browser search. Raises SpotifyError on API failure.
    """
    token = _access_token()
    if token is None:
        return None
    found = _search(query, token, "track") or _search(query, token, "playlist")
    if found is None:
        return f"I couldn't find {query} on Spotify."
    pc = _pick_pc_device(_get_devices(token))
    if pc is None:
        return (
            f"I found {found['name']}, but Spotify isn't open on "
            "your PC — open the Spotify app on your PC and try "
            "again."
        )
    try:
        if found["kind"] == "track":
            body = {"uris": [found["uri"]], "device_id": pc["id"]}
        else:
            body = {"context_uri": found["uri"], "device_id": pc["id"]}
        resp = requests.put(
            API_URL + "/me/player/play",
            headers=_headers(token),
            json=body,
            timeout=_TIMEOUT_SECS,
        )
    except requests.RequestException:
        raise SpotifyError(
            "I couldn't reach Spotify — check your internet and "
            "try again."
        ) from None
    if resp.status_code == 204:
        if found["kind"] == "track":
            return (
                f"Playing {found['name']} by {found['artist']} "
                "on Spotify."
            )
        return f"Playing the {found['name']} playlist on Spotify."
    if resp.status_code == 404:
        try:
            reason = resp.json().get("error", {}).get("reason", "")
        except (ValueError, AttributeError):
            reason = ""
        if reason == "NO_ACTIVE_DEVICE":
            return (
                f"I found {found['name']}, but Spotify isn't open "
                "on any device — open Spotify on your PC and try "
                "again."
            )
        raise SpotifyError(
            "Spotify couldn't start playback — is the app open?"
        )
    if resp.status_code == 403:
        raise SpotifyError(
            "Playing on demand needs Spotify Premium — this "
            "account can't start playback through the app.",
            web_fallback=True,
        )
    detail = _error_detail(resp)
    if detail:
        raise SpotifyError(
            "Spotify refused the playback "
            f"(HTTP {resp.status_code}): {detail}"
        )
    raise SpotifyError(
        "Spotify answered with an error "
        f"(HTTP {resp.status_code})."
    )


def currently_playing():
    """A speakable line about the current track, or None when
    Spotify is not connected at all. Raises SpotifyError on
    an API failure."""
    token = _access_token()
    if token is None:
        return None
    try:
        resp = requests.get(
            API_URL + "/me/player/currently-playing",
            headers=_headers(token),
            timeout=_TIMEOUT_SECS,
        )
    except requests.RequestException:
        raise SpotifyError(
            "I couldn't reach Spotify — check your internet and "
            "try again."
        ) from None
    if resp.status_code == 204:
        return "Nothing is playing on Spotify right now."
    if resp.status_code == 401:
        raise SpotifyError(
            "Spotify rejected the login — run spotify_setup.py "
            "once to connect it again."
        )
    if resp.status_code != 200:
        raise SpotifyError(
            "Spotify answered with an error "
            f"(HTTP {resp.status_code})."
        )
    try:
        data = resp.json()
        item = data.get("item")
    except (ValueError, AttributeError):
        raise SpotifyError(
            "Spotify gave back something I couldn't read."
        ) from None
    if not item:
        return "Nothing is playing on Spotify right now."
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    state = "Playing" if data.get("is_playing") else "Paused on"
    return f"{state} {item['name']} by {artists} on Spotify."
