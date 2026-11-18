"""AURA's shared state manager — Phase 10.1.

One event bus for what AURA is doing right now, so the pill, the
Control Center, and later features (avatar, gestures, meeting
capture) all read the SAME state instead of each tracking their
own. This is the foundation the Futuristic doc calls for: "a
central State Manager ... prevents each feature from maintaining
its own independent idea of the assistant's current status."

States (the doc's set):
  IDLE, LISTENING, THINKING, EXECUTING, SPEAKING,
  WAITING_CONFIRMATION, SUCCESS, ERROR.

The pill has one extra display state, "wake" (waiting for the
wake word). That is a pill rendering of IDLE — waiting — so the
bus carries it as IDLE plus the pill state, and the pill renders
its wake colours. Nothing else needs to know about "wake".

Usage:
    manager = StateManager()
    manager.subscribe("STATE_CHANGED", on_state)  # on_state(payload)
    manager.set_state("LISTENING", status="Listening...")
    manager.current_state()  # "LISTENING"

Setting the same state twice in a row emits nothing — a caller
that repeats the current state is not news. The payload carries
the canonical state, an optional human-readable status line,
and the pill state when the change came from the pill.

Pure stdlib, no tkinter — unit-testable anywhere.
"""

import threading

STATES = (
    "IDLE",
    "LISTENING",
    "THINKING",
    "EXECUTING",
    "SPEAKING",
    "WAITING_CONFIRMATION",
    "SUCCESS",
    "ERROR",
)

STATE_CHANGED = "STATE_CHANGED"


class StateManager:
    def __init__(self):
        self._state = "IDLE"
        self._pill_state = "idle"
        self._status = None
        self._subscribers = {}
        self._lock = threading.Lock()

    def current_state(self) -> str:
        """The canonical state right now ("IDLE", "LISTENING", ...)."""
        with self._lock:
            return self._state

    def current_status(self):
        """The last status line set with the state, or None."""
        with self._lock:
            return self._status

    def subscribe(self, event: str, callback) -> None:
        """Call ``callback(payload)`` on every ``emit(event, ...)``.

        Callbacks must never raise into the bus: a failing
        subscriber is skipped, never breaks the emitter or the
        other subscribers.
        """
        with self._lock:
            self._subscribers.setdefault(event, []).append(callback)

    def unsubscribe(self, event: str, callback) -> None:
        with self._lock:
            listeners = self._subscribers.get(event, [])
            if callback in listeners:
                listeners.remove(callback)

    def emit(self, event: str, payload=None) -> None:
        """Notify every subscriber of ``event`` (best effort)."""
        with self._lock:
            listeners = list(self._subscribers.get(event, []))
        for callback in listeners:
            try:
                callback(payload)
            except Exception:  # noqa: BLE001 - a bad subscriber never breaks the bus
                pass

    def set_state(self, state: str, status=None, pill_state=None) -> bool:
        """Move to ``state`` and notify subscribers.

        Returns True when the state actually changed (and an event
        was emitted), False when this was a repeat of the current
        state — repeats are not news, so they emit nothing.
        ``status`` is a human-readable line ("Listening...") carried
        in the payload; ``pill_state`` is the pill's own display
        state ("wake", "idle", ...) when the change came from the
        pill, so the pill can render itself from the bus.
        """
        if state not in STATES:
            raise ValueError(f"Unknown state '{state}'.")
        with self._lock:
            if (
                state == self._state
                and pill_state == self._pill_state
                and status == self._status
            ):
                return False
            self._state = state
            self._pill_state = pill_state
            self._status = status
            payload = {
                "state": state,
                "status": status,
                "pill_state": pill_state,
            }
        self.emit(STATE_CHANGED, payload)
        return True
