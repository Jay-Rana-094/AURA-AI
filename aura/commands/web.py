"""Website + web search pack.

Opens sites in the default browser. "Play X on YouTube" opens the
YouTube results page for X — picking a video still needs one click,
because autoplaying a specific video would need the YouTube API.
"""

import webbrowser
from urllib.parse import quote_plus

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "gmail": "https://mail.google.com",
    "instagram": "https://www.instagram.com",
    "whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "stackoverflow": "https://stackoverflow.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
}


def open_site(name: str) -> str:
    webbrowser.open(SITES[name])
    return f"Opening {name}."


def open_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."


def web_search(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    return f"Searching Google for {query}."


def youtube_search(query: str) -> str:
    webbrowser.open(
        f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    )
    return f"Searching YouTube for {query}."
