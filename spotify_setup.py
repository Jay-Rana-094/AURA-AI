"""One-time Spotify setup — Phase 9.1.

Connects AURA to your Spotify account so "play <name> on
Spotify" and "what's playing" work through the Web API.
Run once, from this folder:

    python spotify_setup.py

What it needs first (see README, "Phase 9.1 — Spotify"):
  1. A Spotify app at developer.spotify.com/dashboard, with
     Redirect URI http://127.0.0.1:8888/callback.
  2. Its Client ID + Secret in spotify_credentials.json
     (next to main.py) or the SPOTIFY_CLIENT_ID /
     SPOTIFY_CLIENT_SECRET environment variables.

What it does: opens Spotify's login page in your browser,
waits on http://127.0.0.1:8888 for the redirect, swaps the
code for tokens, and saves them to spotify_token.json next
to main.py (that file is a secret too — never share it).
After that, restart AURA; playback control needs Spotify
Premium and the Spotify app open on the PC.
"""

import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from aura import spotify


class _CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):  # noqa: N802 - http.server naming
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            _CallbackHandler.code = query["code"][0]
            message = "Spotify is connected — you can close this tab."
        elif "error" in query:
            _CallbackHandler.error = query["error"][0]
            message = f"Spotify login failed ({_CallbackHandler.error}) — you can close this tab."
        else:
            message = "Waiting for Spotify — this page should not be opened directly."
        body = f"<html><body><h2>{message}</h2></body></html>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the console quiet
        pass


def main() -> int:
    if not spotify.api_configured():
        print(
            "No Spotify app credentials found.\n"
            "Create an app at https://developer.spotify.com/dashboard\n"
            "(Redirect URI: http://127.0.0.1:8888/callback), then save\n"
            "its Client ID and Secret in spotify_credentials.json\n"
            "next to main.py, like this:\n"
            '  {"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}\n'
            "and run this script again."
        )
        return 1
    url = spotify.get_auth_url()
    server = HTTPServer(("127.0.0.1", 8888), _CallbackHandler)
    print("Opening Spotify's login page in your browser...")
    print("Log in and accept, then come back here.")
    webbrowser.open(url)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    thread.join(timeout=180)
    server.shutdown()
    if _CallbackHandler.error:
        print(f"Spotify login failed: {_CallbackHandler.error}")
        return 1
    if not _CallbackHandler.code:
        print("No login arrived in 3 minutes — run the script again.")
        return 1
    if spotify.exchange_code(_CallbackHandler.code):
        print("Spotify is connected. Restart AURA and say "
              "\"play <song> on Spotify\".")
        return 0
    print("Spotify did not accept the login — check the Client "
          "ID/Secret in spotify_credentials.json and try again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
