"""Tests for Phase 8C — Groq conversational fallback.

The fallback is AUTOMATIC (Jay, 2026-11-15): when AURA has no
command for something, it asks Groq on its own — no "turn on"
step. The flag only exists to turn it OFF, so chat is ON by
default on a fresh install. Tests stub requests.post (no network).

    python test_chat.py
"""

import os
import tempfile

import requests

from aura import chat
from aura.brain import (
    handle,
    pop_gui_action,
    set_custom_store,
    set_memory,
)
from aura.chat import (
    CHAT_MODEL,
    DECOMMISSIONED_MODELS,
    ChatError,
    chat_available,
    chat_reply,
    chat_status,
    get_api_key,
    is_chat_enabled,
    set_chat_enabled,
    set_key_file_path,
    set_settings_path,
)
from aura.commands.custom import CustomStore
from aura.language import save_language
from aura.memory import Memory


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _groq_payload(answer="Paris is the capital of France."):
    return {"choices": [{"message": {"content": answer}}]}


def main():
    tmp = tempfile.mkdtemp()
    settings_path = os.path.join(tmp, "settings.json")
    key_path = os.path.join(tmp, "groq_api_key.txt")
    set_settings_path(settings_path)
    set_key_file_path(key_path)
    set_memory(Memory(":memory:"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    save_language("en")

    # The real env must not leak into the tests.
    saved_env = os.environ.pop("GROQ_API_KEY", None)

    # --- Flag: ON by default, persists an explicit off. -----------
    assert is_chat_enabled() is True, "chat must be ON by default"
    assert chat_available() is False, "no key yet, so not available"
    # The configured model must be one Groq still serves: the
    # 2026-08-16 llama-3.3-70b-versatile retirement 404'd every
    # call until the pin was changed — the suite must catch a
    # stale pin, not ship it.
    assert CHAT_MODEL not in DECOMMISSIONED_MODELS, CHAT_MODEL
    set_chat_enabled(False)
    assert is_chat_enabled() is False
    assert chat_available() is False
    assert chat_status() == {
        "enabled": False, "key_set": False, "model": CHAT_MODEL,
    }, chat_status()
    set_chat_enabled(True)
    assert is_chat_enabled() is True

    # --- Key: env var wins, else the key file, else None. --------
    assert get_api_key() is None
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write("file-key-123\n")
    assert get_api_key() == "file-key-123"
    assert chat_available() is True, "on + key = available"
    os.environ["GROQ_API_KEY"] = "env-key-456"
    assert get_api_key() == "env-key-456"
    del os.environ["GROQ_API_KEY"]

    # --- chat_reply: payload shape + history + errors. ------------
    calls = []
    real_post = requests.post

    def _stub_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(payload=_groq_payload())

    requests.post = _stub_post
    try:
        reply = chat_reply(
            "what is the capital of france",
            history=[("hello", "Hi!")],
        )
        assert reply == "Paris is the capital of France.", reply
        assert len(calls) == 1
        call = calls[0]
        assert call["json"]["model"] == CHAT_MODEL, call["json"]
        assert call["headers"]["Authorization"] == "Bearer file-key-123"
        messages = call["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert "AURA" in messages[0]["content"]
        assert messages[1] == {"role": "user", "content": "hello"}
        assert messages[2] == {"role": "assistant", "content": "Hi!"}
        assert messages[-1] == {
            "role": "user", "content": "what is the capital of france",
        }, messages

        # Hinglish mode asks Groq for Hinglish back.
        reply = chat_reply("delhi mein mausam kaisa hai", language="hi")
        assert "Hinglish" in calls[-1]["json"]["messages"][0]["content"]

        # 401: bad key, said plainly. 500: generic error.
        def _stub_401(url, headers=None, json=None, timeout=None):
            return _FakeResponse(status_code=401, payload={})

        requests.post = _stub_401
        try:
            chat_reply("hello")
            raise AssertionError("401 must raise ChatError")
        except ChatError as exc:
            assert "key" in str(exc).lower(), exc

        def _stub_500(url, headers=None, json=None, timeout=None):
            return _FakeResponse(status_code=500, payload={})

        requests.post = _stub_500
        try:
            chat_reply("hello")
            raise AssertionError("500 must raise ChatError")
        except ChatError:
            pass

        # 404: the model is gone (retired) — the error says so
        # plainly, carrying Groq's own text, instead of a bare
        # "HTTP 404" that reads like a broken key.
        def _stub_404(url, headers=None, json=None, timeout=None):
            return _FakeResponse(status_code=404, payload={
                "error": {
                    "message": "The model `openai/gpt-oss-120b` does "
                               "not exist or you do not have access "
                               "to it.",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                },
            })

        requests.post = _stub_404
        try:
            chat_reply("hello")
            raise AssertionError("404 must raise ChatError")
        except ChatError as exc:
            assert "no longer exists" in str(exc), exc
            assert "does not exist" in str(exc), exc

        def _stub_down(url, headers=None, json=None, timeout=None):
            raise requests.ConnectionError("offline")

        requests.post = _stub_down
        try:
            chat_reply("hello")
            raise AssertionError("offline must raise ChatError")
        except ChatError as exc:
            assert "internet" in str(exc).lower(), exc

        def _stub_bad(url, headers=None, json=None, timeout=None):
            return _FakeResponse(bad_json=True)

        requests.post = _stub_bad
        try:
            chat_reply("hello")
            raise AssertionError("bad JSON must raise ChatError")
        except ChatError:
            pass

        def _stub_empty(url, headers=None, json=None, timeout=None):
            return _FakeResponse(payload=_groq_payload("   "))

        requests.post = _stub_empty
        try:
            chat_reply("hello")
            raise AssertionError("empty answer must raise ChatError")
        except ChatError:
            pass
    finally:
        requests.post = real_post

    # No key at all: honest error, not a crash.
    os.remove(key_path)
    try:
        chat_reply("hello")
        raise AssertionError("missing key must raise ChatError")
    except ChatError as exc:
        assert "Groq API key" in str(exc), exc

    # --- Brain routing: automatic fallback, commands still win. ---
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write("file-key-123")
    set_chat_enabled(True)
    calls.clear()
    requests.post = _stub_post
    try:
        # No command matches -> Groq answers automatically.
        reply, quit_ = handle("what is the capital of france")
        assert reply == "Paris is the capital of France.", reply
        assert not quit_
        assert len(calls) == 1, calls
        # A built-in still wins — Groq is never asked.
        reply, _ = handle("what is the time")
        assert "It's" in reply, reply
        assert len(calls) == 1, calls
        # A taught phrase still wins over Groq too.
        reply, _ = handle(
            "teach aura what is the capital of france means "
            "what is the time")
        assert "Got it" in reply, reply
        reply, _ = handle("what is the capital of france")
        assert "It's" in reply, reply
        assert len(calls) == 1, calls
        # Turn it off: back to the honest "I don't know". (A fresh
        # question — the capital one is still taught to mean the
        # time above, so it would answer with the time either way.)
        reply, _ = handle("turn off chat mode")
        assert "off" in reply.lower(), reply
        assert pop_gui_action() == "chat_refresh"
        reply, _ = handle("what is the population of india")
        assert reply == "I don't know how to do that yet.", reply
        assert len(calls) == 1, calls
        # Turn it back on + status.
        reply, _ = handle("turn on chat mode")
        assert "on" in reply.lower(), reply
        reply, _ = handle("is chat mode on")
        assert "Chat mode is on" in reply, reply
        assert "Groq" in handle("help")[0]
    finally:
        requests.post = real_post

    # Chat on but key missing: "turn on" says what to do, while an
    # unmatched question keeps the old honest fallback (no nagging
    # about the key on every question).
    os.remove(key_path)
    set_chat_enabled(True)
    assert chat_available() is False
    reply, _ = handle("turn on chat mode")
    assert "Groq API key" in reply, reply
    reply, _ = handle("what is the population of india")
    assert reply == "I don't know how to do that yet.", reply

    if saved_env is not None:
        os.environ["GROQ_API_KEY"] = saved_env
    print("All chat tests passed.")


if __name__ == "__main__":
    main()
