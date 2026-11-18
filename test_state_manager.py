"""Tests for Phase 10.1 — Shared State Manager + pill publishing.

The manager itself is pure (no window, no OS): one event bus,
``STATE_CHANGED`` events carrying a payload dict. The pill test
builds the real IslandGUI and skips itself when no display is
available (headless CI / this Linux VM).

    python test_state_manager.py
"""

import tkinter as tk

from aura.gui import IslandGUI
from aura.state_manager import (
    STATE_CHANGED,
    STATES,
    StateManager,
)


def _display_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


def main():
    # The eight canonical states, exactly as designed.
    assert STATES == (
        "IDLE", "LISTENING", "THINKING", "EXECUTING", "SPEAKING",
        "WAITING_CONFIRMATION", "SUCCESS", "ERROR",
    ), STATES

    mgr = StateManager()
    assert mgr.current_state() == "IDLE"
    assert mgr.current_status() is None

    # A transition publishes a payload dict to STATE_CHANGED
    # subscribers: canonical state, status line, pill state.
    seen = []
    mgr.subscribe(STATE_CHANGED, lambda payload: seen.append(payload))
    assert mgr.set_state("LISTENING", status="Listening...",
                         pill_state="listening") is True
    assert mgr.current_state() == "LISTENING"
    assert mgr.current_status() == "Listening..."
    assert seen == [{
        "state": "LISTENING",
        "status": "Listening...",
        "pill_state": "listening",
    }]

    # An identical set is a no-op — subscribers are not spammed.
    assert mgr.set_state("LISTENING", status="Listening...",
                         pill_state="listening") is False
    assert len(seen) == 1

    # A new status on the same state DOES publish.
    assert mgr.set_state("LISTENING", status="Still listening...",
                         pill_state="listening") is True
    assert len(seen) == 2
    assert seen[-1]["status"] == "Still listening..."

    # An unknown state is rejected loudly and the current state
    # is untouched (a typo must never silently move the bus).
    try:
        mgr.set_state("DANCING")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown state was accepted")
    assert mgr.current_state() == "LISTENING"

    # Unsubscribe stops the calls. (The first listener is still
    # subscribed, so a set fires it once; the second listener
    # below fires too — two appends per set until it is removed.)
    listener = lambda payload: seen.append(payload)  # noqa: E731
    mgr.subscribe(STATE_CHANGED, listener)
    mgr.set_state("THINKING", status="Thinking...")
    assert len(seen) == 4
    mgr.unsubscribe(STATE_CHANGED, listener)
    mgr.set_state("EXECUTING", status="Running it...")
    assert len(seen) == 5

    # A failing subscriber never breaks the bus.
    def _boom(payload):
        raise RuntimeError("subscriber blew up")

    mgr.subscribe(STATE_CHANGED, _boom)
    assert mgr.set_state("SPEAKING", status="Speaking...") is True
    assert mgr.current_state() == "SPEAKING"

    # The pill publishes its states through on_state (Phase
    # 10.1 wiring) — a set_state on the pill lands on the bus.
    if _display_available():
        published = []
        gui = IslandGUI(
            on_mic=lambda: None,
            on_engine_change=lambda engine: None,
            on_state=lambda state, status: published.append(
                (state, status)),
        )
        try:
            gui.set_state("listening", "Listening...")
            gui.root.update()  # set_state applies via after(0)
            assert ("listening", "Listening...") in published, published
            gui.set_state("error", "Whisper error: boom")
            gui.root.update()
            assert ("error", "Whisper error: boom") in published
        finally:
            gui.root.destroy()

    print("test_state_manager: OK")


if __name__ == "__main__":
    main()
