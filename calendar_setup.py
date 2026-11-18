"""One-time Google Calendar setup — Phase 9.2B.

Connects AURA to your Google Calendar (read-only) so today's
events appear in the daily briefing and "what's on my calendar
today" works. Run once, from this folder:

    python calendar_setup.py

What it needs first (see README, "Phase 9.2B — Google
Calendar"):
  1. A project in Google Cloud Console with the Google
     Calendar API enabled.
  2. An OAuth client ID of type "Desktop app", downloaded as
     JSON and saved as google_credentials.json next to main.py.
  3. Your own Google account added as a test user on the
     OAuth consent screen (the app stays in Testing mode).

What it does: opens Google's login page in your browser,
waits on http://127.0.0.1:8889 for the redirect (a loopback
address — no redirect URI needs registering for a Desktop
app client), and saves the login to google_token.json next
to main.py (that file is a secret too — never share it).
After that, restart AURA; the token refreshes itself.
"""

import json
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_CRED_PATH = os.path.join(_BASE, "google_credentials.json")
_TOKEN_PATH = os.path.join(_BASE, "google_token.json")
_PORT = 8889
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _credentials_are_downloaded() -> bool:
    """The file must be the JSON Google Cloud Console
    downloads for a Desktop app client (an "installed" or
    "web" object) — a flat client_id/client_secret file
    cannot drive the login flow, so say so plainly instead
    of failing inside the library."""
    try:
        with open(_CRED_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    for key in ("installed", "web"):
        inner = data.get(key)
        if isinstance(inner, dict) and inner.get("client_id"):
            return True
    return False


def main() -> int:
    if not os.path.exists(_CRED_PATH):
        print(
            "No Google credentials found.\n"
            "In Google Cloud Console (console.cloud.google.com):\n"
            "  1. Create a project and enable the Google Calendar API.\n"
            "  2. Set up the OAuth consent screen (External) and add\n"
            "     your own Google account as a test user.\n"
            "  3. Create an OAuth client ID of type \"Desktop app\"\n"
            "     and download its JSON.\n"
            "Save that downloaded JSON as google_credentials.json\n"
            "next to main.py, then run this script again.\n"
            "Full steps are in the README (Phase 9.2B)."
        )
        return 1
    if not _credentials_are_downloaded():
        print(
            "google_credentials.json is not the file Google Cloud\n"
            "Console downloads — it must be the full JSON for a\n"
            "\"Desktop app\" OAuth client (it has an \"installed\"\n"
            "section with a client_id). Re-download it from\n"
            "Google Cloud Console > Google Auth platform > Clients\n"
            "and save it as google_credentials.json, then run this\n"
            "script again."
        )
        return 1
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "The Google libraries aren't installed yet. Run:\n"
            "  pip install -r requirements.txt\n"
            "then run this script again."
        )
        return 1
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            _CRED_PATH, SCOPES)
        creds = flow.run_local_server(port=_PORT)
    except OSError:
        print(
            f"The login server could not use port {_PORT} — "
            "something else is using it. Close that program and "
            "run this script again."
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - login failed, say so
        print(f"Google login failed: {exc}")
        return 1
    if not creds or not creds.refresh_token:
        print(
            "Google did not return a login — try running this "
            "script again."
        )
        return 1
    with open(_TOKEN_PATH, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    try:
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:
        pass  # best effort; Windows ignores the mode anyway
    print("Google Calendar is connected. Restart AURA and say "
          "\"what's on my calendar today\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
