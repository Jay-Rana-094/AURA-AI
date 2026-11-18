"""Spotify voice commands — Phase 9.1.

Two layers, like the feature itself:

  - Local layer (no setup): play / pause / next / previous
    via the Windows media keys — the same mechanism as the
    generic media controls. Works with whatever is playing,
    Spotify or anything else.
  - Web API layer (optional): "play <name> on Spotify" searches
    and plays a track or playlist, and "what's playing" reads
    the current track. Needs the one-time setup
    (spotify_setup.py); when it is NOT configured, "play X on
    Spotify" opens the Spotify web search in the browser and
    says so honestly instead of pretending it played. The
    same web search opens when the API is blocked for want
    of Premium (HTTP 403) — the web player still works on
    a Free account.

"open spotify" already works through the allow-listed apps
(aura/commands/apps.py) and needs no rule here.

    parse_spotify_command(text) -> dict | None
    execute_spotify_command(cmd) -> reply str
"""

import re
import webbrowser
from urllib.parse import quote_plus

from aura import spotify
from aura.commands.system import media_key


def _open_web_search(query: str, message: str | None = None) -> str:
    """Fallback when the API can't play: the browser search,
    said plainly."""
    webbrowser.open(f"https://open.spotify.com/search/{quote_plus(query)}")
    if message is not None:
        return message
    return (
        f"Spotify isn't connected, so I opened the search for "
        f"{query} in your browser instead."
    )


def parse_spotify_command(text: str):
    """Match spoken text to a Spotify command. None if no match.

    The exact media phrases are checked before the "play X on
    Spotify" rule, so "play music on Spotify" resumes playback
    instead of searching for a track called "music"."""
    t = text.strip().lower()

    # --- What's playing? ---
    if t in (
        "what's playing",
        "what is playing",
        "what's playing on spotify",
        "what is playing on spotify",
        "what song is playing",
        "what song is this",
        "what's this song",
        "what is this song",
    ):
        return {"kind": "now_playing"}

    # --- Local media keys, Spotify-flavoured. ---
    if t in (
        "pause spotify",
        "pause the music on spotify",
        "pause spotify music",
        "stop spotify",
    ):
        return {"kind": "media_key", "action": "play_pause"}
    if t in (
        "play spotify",
        "resume spotify",
        "resume the music on spotify",
        "play music on spotify",
    ):
        return {"kind": "media_key", "action": "play_pause"}
    if re.search(r"\bnext (song|track|music) on spotify\b", t):
        return {"kind": "media_key", "action": "next"}
    if re.search(r"\bprevious (song|track|music) on spotify\b", t):
        return {"kind": "media_key", "action": "previous"}

    # --- Play a named track or playlist (Web API). ---
    m = re.match(r"play (.+?) (on|using|in) spotify$", t)
    if m:
        return {"kind": "play_on_spotify", "query": m.group(1).strip()}

    # --- Bare "play <name>": Spotify too (Jay's habit). ---
    # "play music" resumes whatever is paused; anything else
    # searches Spotify. "play X on youtube" stays with the
    # YouTube pack (brain step 5), so it must not match here.
    if t == "play music":
        return {"kind": "media_key", "action": "play_pause"}
    if not t.endswith(" on youtube"):
        m = re.match(r"play (.+)$", t)
        if m:
            return {"kind": "play_on_spotify", "query": m.group(1).strip()}

    return None


def execute_spotify_command(cmd: dict) -> str:
    """Perform a parsed Spotify command and return what AURA
    should say."""
    kind = cmd["kind"]
    if kind == "media_key":
        return media_key(cmd["action"])
    if kind == "now_playing":
        if not spotify.api_configured() or not spotify.has_token():
            return (
                "I can't see what's playing — Spotify isn't "
                "connected. Run spotify_setup.py once to connect "
                "it, then ask again."
            )
        try:
            result = spotify.currently_playing()
        except spotify.SpotifyError as exc:
            return str(exc)
        if result is None:
            return (
                "I can't see what's playing — Spotify isn't "
                "connected. Run spotify_setup.py once to connect "
                "it, then ask again."
            )
        return result
    if kind == "play_on_spotify":
        query = cmd["query"]
        if not spotify.api_configured() or not spotify.has_token():
            return _open_web_search(query)
        try:
            result = spotify.play_track(query)
        except spotify.SpotifyError as exc:
            if exc.web_fallback:
                # The API is blocked (Free account, no Premium)
                # but the web player works — open the search so
                # Jay can press play in the browser himself.
                return _open_web_search(
                    query,
                    "Spotify needs Premium to play that directly, "
                    f"so I opened the search for {query} in your "
                    "browser instead — press play there.")
            return str(exc)
        if result is None:
            return _open_web_search(query)
        return result
    return "I don't know how to do that yet."
