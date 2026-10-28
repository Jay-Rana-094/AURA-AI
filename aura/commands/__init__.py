"""Command registry — Phase 2.

Two stages, kept separate on purpose:
  parse_command(text) -> dict | None   (no side effects, testable)
  execute_command(cmd) -> reply str    (performs the action)

The brain calls parse first. If the kind needs confirmation, the
brain stores the parsed command as pending and only calls execute
after the user says yes. Nothing destructive ever runs from parsing.
"""

import re

from .apps import APPS, find_app, open_app
from .system import (
    CONFIRM_KINDS,
    CONFIRM_TEXT,
    lock,
    media_key,
    power,
    screenshot,
    set_radio,
)
from .web import SITES, open_site, open_url, web_search, youtube_search


def parse_command(text: str):
    """Match spoken text to a command. Returns None if no match."""
    t = text.strip().lower()

    # --- Power (confirmation required) ---
    if re.search(r"\b(shut down|shutdown|power off)\b", t):
        return {"kind": "shutdown", "confirm_text": CONFIRM_TEXT["shutdown"]}
    if re.search(r"\brestart\b", t):
        return {"kind": "restart", "confirm_text": CONFIRM_TEXT["restart"]}
    if re.search(r"\b(sleep|hibernate)\b", t):
        return {"kind": "sleep", "confirm_text": CONFIRM_TEXT["sleep"]}

    # --- Lock ---
    if re.search(r"\block\b", t):
        return {"kind": "lock"}

    # --- Screenshot ---
    if re.search(r"\b(take a screenshot|screenshot|capture (the )?screen)\b", t):
        return {"kind": "screenshot"}

    # --- Radios: Bluetooth / Wi-Fi / Airplane mode ---
    def _radio_kind(word: str) -> str:
        return "bluetooth" if word == "bluetooth" else "wifi"

    m = re.search(r"\b(turn|switch) (bluetooth|wi-?fi|wi fi) (on|off)\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": _radio_kind(m.group(2)),
            "state": "On" if m.group(3) == "on" else "Off",
        }
    m = re.search(r"\b(turn|switch) (on|off) (bluetooth|wi-?fi|wi fi)\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": _radio_kind(m.group(3)),
            "state": "On" if m.group(2) == "on" else "Off",
        }
    m = re.search(r"\b(enable|disable) (bluetooth|wi-?fi|wi fi)\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": _radio_kind(m.group(2)),
            "state": "On" if m.group(1) == "enable" else "Off",
        }
    m = re.search(r"\b(turn|switch) airplane mode (on|off)\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": "airplane",
            "state": "On" if m.group(2) == "on" else "Off",
        }
    m = re.search(r"\b(turn|switch) (on|off) airplane mode\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": "airplane",
            "state": "On" if m.group(2) == "on" else "Off",
        }
    m = re.search(r"\b(enable|disable) airplane mode\b", t)
    if m:
        return {
            "kind": "radio",
            "radio": "airplane",
            "state": "On" if m.group(1) == "enable" else "Off",
        }

    # --- Volume / media keys ---
    if re.search(r"\b(volume up|increase volume)\b", t):
        return {"kind": "media_key", "action": "volume_up"}
    if re.search(r"\b(volume down|decrease volume)\b", t):
        return {"kind": "media_key", "action": "volume_down"}
    if re.search(r"\b(mute|unmute)\b", t):
        return {"kind": "media_key", "action": "mute"}
    if re.search(r"\b(next (song|track|music))\b", t):
        return {"kind": "media_key", "action": "next"}
    if re.search(r"\b(previous (song|track|music))\b", t):
        return {"kind": "media_key", "action": "previous"}
    if re.search(r"\b(pause|resume) (the )?(music|song|media)\b", t):
        return {"kind": "media_key", "action": "play_pause"}

    # --- YouTube ---
    m = re.search(r"play (.+?) on youtube", t)
    if m:
        return {"kind": "youtube", "query": m.group(1).strip()}
    m = re.search(r"search youtube for (.+)", t)
    if m:
        return {"kind": "youtube", "query": m.group(1).strip()}
    m = re.search(r"search (for )?(.+?) on youtube", t)
    if m:
        return {"kind": "youtube", "query": m.group(2).strip()}

    # --- Web search ---
    m = re.search(r"search (for )?(.+?)( on google)?$", t)
    if m:
        return {"kind": "web_search", "query": m.group(2).strip()}

    # --- Open app / site / URL / fallback search ---
    m = re.search(r"(open|launch|start|go to) (.+)", t)
    if m:
        target = m.group(2).strip()
        app = find_app(target)
        if app:
            return {"kind": "open_app", "name": app[0], "exe": app[1]}
        for name in sorted(SITES, key=len, reverse=True):
            if name in target:
                return {"kind": "open_site", "name": name}
        if "." in target and " " not in target:
            return {"kind": "open_url", "url": target}
        return {"kind": "web_search", "query": target}

    return None


def execute_command(cmd: dict) -> str:
    """Perform a parsed command and return what AURA should say."""
    kind = cmd["kind"]
    if kind in CONFIRM_KINDS:
        return power(kind)
    if kind == "lock":
        return lock()
    if kind == "screenshot":
        return screenshot()
    if kind == "radio":
        return set_radio(cmd["radio"], cmd["state"])
    if kind == "media_key":
        return media_key(cmd["action"])
    if kind == "open_app":
        return open_app(cmd["name"], cmd["exe"])
    if kind == "open_site":
        return open_site(cmd["name"])
    if kind == "open_url":
        return open_url(cmd["url"])
    if kind == "web_search":
        return web_search(cmd["query"])
    if kind == "youtube":
        return youtube_search(cmd["query"])
    return "I don't know how to do that yet."
