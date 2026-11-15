"""Conversational fallback — Phase 8C.

When AURA has no command for something, and chat mode is on, the
question goes to Groq's free tier instead of "I don't know how
to do that yet". Commands always win: this runs last in the
brain, after every command pack and built-in reply.

Off by default. Needs a Groq API key:
  - environment variable GROQ_API_KEY, or
  - a groq_api_key.txt file next to main.py (one line, the key).
That file is Jay's own secret: it is never zipped, never pushed
to GitHub (see .gitignore), and never logged.

NOTE (Jay, 2026-11-15): the fallback is AUTOMATIC — when AURA
has no command for something, it goes to Groq on its own, with
no "turn on chat mode" step. The flag only exists to turn it
OFF ("turn off chat mode" / the Control Center checkbox), so
is_chat_enabled() defaults to True on a fresh install.

Model: openai/gpt-oss-120b — Groq's replacement for the retired
llama-3.3-70b-versatile (see CHAT_MODEL). Answers are kept
short (max_tokens 300) because they are spoken aloud.

Only requests (already in requirements.txt) is needed, so this
stays unit-testable anywhere — tests stub requests.post.
"""

import json
import os

import requests

CHAT_MODEL = "openai/gpt-oss-120b"
# Groq retired llama-3.3-70b-versatile for free/developer tiers
# on 2026-08-16 — it now 404s with model_not_found, which looked
# like a broken key until the error body was read. Groq's own
# replacement for the 70B Llama is openai/gpt-oss-120b (the
# 2026-11-15 v2 fix). When this model is retired one day, change
# this one line — and keep test_chat.py's DECOMMISSIONED_MODELS
# guard in sync, so the suite catches a stale pin.
DECOMMISSIONED_MODELS = frozenset({
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
})
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Chat mode lives in aura_settings.json next to main.py (same file
# as the wake word, theme and language), so it survives restarts.
_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)
_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "groq_api_key.txt",
)


class ChatError(Exception):
    """A chat turn failed — the message is safe to speak aloud."""


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def set_key_file_path(path: str) -> None:
    """Point the key file elsewhere — used by tests (temp file)."""
    global _KEY_FILE
    _KEY_FILE = path


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def is_chat_enabled() -> bool:
    """Chat mode is ON by default (Jay, 2026-11-15): when AURA
    has no command for something, it should automatically go to
    Groq — no separate "turn on" step. Saying "turn off chat
    mode" persists False and is the only way to stop it."""
    return bool(_load_settings().get("chat_fallback", True))


def set_chat_enabled(enabled: bool) -> None:
    """Persist the chat-mode flag (already validated by the caller)."""
    data = _load_settings()
    data["chat_fallback"] = bool(enabled)
    _save_settings(data)


def get_api_key():
    """The Groq key: env var first, then the local key file.

    Neither source is ever logged. Returns None when no key is
    set anywhere — the caller then says so, instead of guessing.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(_KEY_FILE, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return None
    return key or None


def chat_status() -> dict:
    """One dict for the Control Center + Diagnostics tab."""
    return {
        "enabled": is_chat_enabled(),
        "key_set": get_api_key() is not None,
        "model": CHAT_MODEL,
    }


def chat_available() -> bool:
    """Chat mode is on AND a key is set — the only state in which
    an automatic fallback can actually answer. When the key is
    missing, the brain keeps the old "I don't know" reply instead
    of nagging about the key on every unknown question; the key
    setup is surfaced once by "turn on chat mode", the Control
    Center status line, and Diagnostics."""
    return is_chat_enabled() and get_api_key() is not None


def _error_detail(resp) -> str:
    """Groq's own error text, if any — short enough to speak.

    A bare "HTTP 404" hid the real cause once already (a retired
    model reads exactly like a broken key), so failures carry the
    provider's message with them from now on."""
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except (ValueError, AttributeError, TypeError):
        return ""
    return str(detail).strip()[:160]


def chat_reply(question: str, history=(), language: str = "en") -> str:
    """Ask Groq for a short spoken answer to ``question``.

    ``history`` is a list of (user_text, reply_text) pairs, oldest
    first, for context. Raises ChatError with a speakable message
    when the key is missing or the service fails — the brain
    returns that message instead of crashing the turn.
    """
    key = get_api_key()
    if key is None:
        raise ChatError(
            "Chat mode is on, but I don't have a Groq API key yet. "
            "Add your key to the GROQ_API_KEY environment variable, "
            "or save it in a groq_api_key.txt file next to main.py."
        )
    if language == "hi":
        lang_line = (
            "Reply in Hinglish (Roman Hindi, the way Jay speaks to "
            "you), not Devanagari."
        )
    else:
        lang_line = "Reply in English."
    system = (
        "You are AURA, Jay's personal voice assistant running on "
        "his Windows PC. Answer the user's question briefly — one "
        "to three sentences — because your answer is spoken aloud. "
        "Be direct and helpful, no filler. " + lang_line
    )
    messages = [{"role": "system", "content": system}]
    for user_text, reply_text in history:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply_text})
    messages.append({"role": "user", "content": question})
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": CHAT_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 300,
            },
            timeout=20,
        )
    except requests.RequestException:
        raise ChatError(
            "I couldn't reach the chat service — check your "
            "internet and try again."
        ) from None
    if resp.status_code == 401:
        raise ChatError(
            "Groq rejected my API key — check that the key in "
            "groq_api_key.txt is still valid."
        )
    if resp.status_code == 404:
        # The model id is gone (retired) — Groq's own text names
        # it, so the next retirement diagnoses itself.
        detail = _error_detail(resp)
        msg = "Groq says that chat model no longer exists."
        if detail:
            msg += f" Groq says: {detail}"
        raise ChatError(msg)
    if resp.status_code != 200:
        detail = _error_detail(resp)
        msg = (
            "The chat service answered with an error "
            f"(HTTP {resp.status_code})."
        )
        if detail:
            msg += f" Groq says: {detail}"
        raise ChatError(msg)
    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise ChatError(
            "The chat service gave back something I couldn't read."
        ) from None
    if not text:
        raise ChatError("The chat service gave back an empty answer.")
    return text
