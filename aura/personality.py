"""AURA personality modes — Phase 10.1.

Five presets, stored as DATA (not code) in ``aura_settings.json`` under the
``"personality"`` key, following the same load/save pattern as theme and
language. Switching a mode changes only tone, verbosity and voice rate —
never permissions, and never the confirmation rules.

Presets:

* aura      — polished, lightly witty, medium verbosity, rate 175
* professional — formal, direct, short, rate 165
* minimal     — very short, rate 180
* friendly    — casual, warm, medium, rate 175 (the default: today's behaviour)
* silent      — pill/text only, no TTS, minimal verbosity, rate 175

The formatter lives here so the brain never has to know about modes:
``format_reply()`` trims a reply to the mode's verbosity, and ``main.py``
decides whether to speak it at all.
"""

import json
import os

DEFAULT_MODE = "friendly"

PRESETS = {
    "aura": {
        "label": "Aura",
        "style": "polished, lightly witty",
        "verbosity": "medium",
        "speech": True,
        "voice_rate": 175,
    },
    "professional": {
        "label": "Professional",
        "style": "formal, direct",
        "verbosity": "short",
        "speech": True,
        "voice_rate": 165,
    },
    "minimal": {
        "label": "Minimal",
        "style": "terse",
        "verbosity": "minimal",
        "speech": True,
        "voice_rate": 180,
    },
    "friendly": {
        "label": "Friendly",
        "style": "casual, warm",
        "verbosity": "medium",
        "speech": True,
        "voice_rate": 175,
    },
    "silent": {
        "label": "Silent",
        "style": "terse",
        "verbosity": "minimal",
        "speech": False,
        "voice_rate": 175,
    },
}

_SETTINGS_PATH = None


def set_settings_path(path):
    """Override the settings file (used by tests)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def _settings_file():
    if _SETTINGS_PATH is not None:
        return _SETTINGS_PATH
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "aura_settings.json",
    )


def _load_settings():
    try:
        with open(_settings_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data):
    try:
        with open(_settings_file(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def load_mode():
    """The current personality mode name, defaulting to ``friendly``."""
    mode = _load_settings().get("personality", DEFAULT_MODE)
    return mode if mode in PRESETS else DEFAULT_MODE


def save_mode(mode):
    """Persist a mode name. Unknown names are ignored (returns False)."""
    if mode not in PRESETS:
        return False
    data = _load_settings()
    data["personality"] = mode
    _save_settings(data)
    return True


def get_preset(mode=None):
    """The preset dict for a mode (current mode when omitted)."""
    return PRESETS[load_mode() if mode is None else mode]


def is_silent(mode=None):
    """True when the mode speaks nothing (pill/text only)."""
    return not get_preset(mode)["speech"]


def voice_rate(mode=None):
    """Speech rate in words per minute for the mode."""
    return get_preset(mode)["voice_rate"]


# -- Reply formatting -----------------------------------------------------

# Replies that must never be trimmed: questions back to Jay, and anything
# that reports a failure. Cutting those would hide what AURA needs or
# what went wrong.
_NEVER_TRIM_PREFIXES = (
    "I couldn't",
    "I can't",
    "Something went wrong",
    "Sorry",
    "I don't know",
)

# A small explicit tone map for replies AURA says often. Anything not
# listed here is left in its own words — the formatter only trims
# length, it never rewrites meaning.
_TONE = {
    "aura": {
        "Hey Jay... how can I help you today?": (
            "Good to see you, Jay. How may I assist?"
        ),
        "Goodbye, Jay.": "Very well, sir. Powering down.",
        "Okay.": "Consider it done.",
    },
    "professional": {
        "Hey Jay... how can I help you today?": "Hello. How can I help?",
        "Goodbye, Jay.": "Goodbye.",
        "Okay.": "Done.",
    },
    "minimal": {
        "Hey Jay... how can I help you today?": "Ready.",
        "Goodbye, Jay.": "Bye.",
        "Okay.": "Done.",
    },
    "friendly": {},
    "silent": {
        "Hey Jay... how can I help you today?": "Ready.",
        "Goodbye, Jay.": "Bye.",
        "Okay.": "Done.",
    },
}


def _sentences(text):
    """Split on sentence ends, keeping the punctuation attached."""
    parts = []
    current = ""
    for ch in text:
        current += ch
        if ch in ".!?":
            if current.strip():
                parts.append(current.strip())
            current = ""
    if current.strip():
        parts.append(current.strip())
    return parts or [text]


def _trim(text, verbosity):
    """Trim a reply to a verbosity: minimal = 1 sentence, short = 2."""
    if verbosity == "medium":
        return text
    limit = 1 if verbosity == "minimal" else 2
    sentences = _sentences(text)
    if len(sentences) <= limit:
        return text
    return " ".join(sentences[:limit])


def format_reply(reply, mode=None):
    """Apply a personality mode's tone + verbosity to a reply.

    Questions and error/failure replies are never trimmed, so a
    confirmation prompt or an honest failure always reaches Jay whole.
    """
    if not reply:
        return reply
    mode = load_mode() if mode is None else mode
    if mode not in PRESETS:
        mode = DEFAULT_MODE
    preset = PRESETS[mode]
    text = _TONE.get(mode, {}).get(reply, reply)
    stripped = text.strip()
    if "?" in stripped:
        return text
    if stripped.startswith(_NEVER_TRIM_PREFIXES):
        return text
    return _trim(text, preset["verbosity"])


def describe_mode(mode=None):
    """One honest line describing a mode, for voice replies."""
    mode = load_mode() if mode is None else mode
    preset = PRESETS.get(mode, PRESETS[DEFAULT_MODE])
    speech = "spoken replies on" if preset["speech"] else "no spoken replies"
    return (
        f"{preset['label']} mode — {preset['style']}, "
        f"{preset['verbosity']} replies, {speech}."
    )


def personality_status():
    """Live status dict for the Control Center."""
    mode = load_mode()
    return {
        "mode": mode,
        "label": PRESETS[mode]["label"],
        "description": describe_mode(mode),
    }
