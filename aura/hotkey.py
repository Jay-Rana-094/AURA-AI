"""Global hotkey — Phase 9.2B.

Press Ctrl+Alt+A anywhere on the PC — even while AURA is
minimized to the tray — and the Control Center opens with the
cursor in the typed-command box, so Jay can type a command
without touching the mouse or the pill.

Library choice: pynput (GlobalHotKeys), not ``keyboard``.
Both sit on the same Windows low-level keyboard hook
(WH_KEYBOARD_LL), which is global by nature — it fires no
matter which window has focus, so it keeps working while the
pill is hidden in the tray — and neither needs admin rights
for a normal user session. The difference is maintenance and
fit: ``keyboard`` 0.13.5 is unmaintained since 2020 and its
Windows hook is known to stop silently; pynput is actively
maintained (1.8.2), and GlobalHotKeys is purpose-built for
exactly one job — "<ctrl>+<alt>+a" -> callback — on its own
listener thread with its own message pump, so it can never
freeze the pill. One known limit, shared by both libraries:
keys typed into a window running as Administrator may not
reach a non-elevated hook — a Windows rule (UIPI), not a bug.

Settings live in aura_settings.json next to main.py (same file
as the wake word, theme, morning briefing): ``hotkey_enabled``
(ON by default) and ``hotkey_combo`` (canonical pynput form,
default "<ctrl>+<alt>+a"). Voice: "turn off hotkey" / "turn on
hotkey" / "set hotkey to ctrl shift h" / "what is my hotkey".
The Control Center Settings tab has the same switch and a
combo box. A combo must have at least one modifier and exactly
one regular key — a bare letter would hijack normal typing,
so it is refused.
"""

import json
import os
import re
import threading
import time

DEFAULT_HOTKEY_COMBO = "<ctrl>+<alt>+a"
DEFAULT_HOTKEY_ENABLED = True

# Fixed modifier order, so "<alt>+<ctrl>+a" and
# "<ctrl>+<alt>+a" are the same combo everywhere.
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")
_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "cmd",
    "windows": "cmd",
    "cmd": "cmd",
    "command": "cmd",
    "super": "cmd",
}
_NAMED_KEYS = {
    "space": "space",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "esc": "esc",
    "escape": "esc",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "page_up": "page_up",
    "pagedown": "page_down",
    "page_down": "page_down",
    "delete": "delete",
    "backspace": "backspace",
    "insert": "insert",
}

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)

# Cached import result: the pynput module once loaded, False when
# the import failed. _reset_cache() exists for tests.
_pynput = None


def _reset_cache() -> None:
    """Forget the cached import result — used by tests."""
    global _pynput
    _pynput = None


def _load_pynput():
    """Import pynput.keyboard once, or None when unavailable."""
    global _pynput
    if _pynput is None:
        try:
            from pynput import keyboard
            _pynput = keyboard
        except Exception:  # noqa: BLE001 - no hotkey on this PC
            _pynput = False
    return _pynput or None


def hotkey_available() -> bool:
    """True when pynput imports (a global-hook backend exists)."""
    return _load_pynput() is not None


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def is_hotkey_enabled() -> bool:
    """The hotkey is ON by default — Jay asked for it (Phase
    9.2B). Saying "turn off hotkey" persists False and is the
    only way to stop it."""
    return bool(_load_settings().get("hotkey_enabled", True))


def set_hotkey_enabled(enabled: bool) -> None:
    """Persist the hotkey flag (already validated)."""
    data = _load_settings()
    data["hotkey_enabled"] = bool(enabled)
    _save_settings(data)


def parse_hotkey_combo(text: str):
    """Parse a combo into canonical pynput form, or None.

    Accepts "ctrl alt a", "ctrl+alt+a", "control alt a",
    "ctrl shift h", "alt f1", "cmd space". At least one
    modifier and exactly one regular key — a bare letter, a
    modifier-only combo, or an unknown word all return None.
    """
    raw = text.strip().lower()
    if not raw:
        return None
    # Split on whitespace and "+"; angle brackets are stripped
    # so the canonical form ("<ctrl>+<alt>+a") parses too —
    # set_hotkey_combo() and the Settings entry both feed
    # canonical strings back through here.
    tokens = [t.strip("<>") for t in re.split(r"[\s+]+", raw) if t]
    modifiers = []
    key = None
    for token in tokens:
        if token in _MODIFIER_ALIASES:
            name = _MODIFIER_ALIASES[token]
            if name in modifiers:
                return None  # "ctrl ctrl a" is not a combo
            modifiers.append(name)
            continue
        if len(token) == 1 and token.isalnum():
            if key is not None:
                return None  # two regular keys
            key = token
            continue
        if re.match(r"^f([1-9]|1[0-2])$", token):
            if key is not None:
                return None
            key = token
            continue
        if token in _NAMED_KEYS:
            if key is not None:
                return None
            key = _NAMED_KEYS[token]
            continue
        return None  # unknown word
    if not modifiers or key is None:
        return None
    ordered = [m for m in _MODIFIER_ORDER if m in modifiers]
    parts = [f"<{m}>" for m in ordered]
    # Single letters/digits stay bare ("a"); named keys keep
    # their brackets ("<f1>", "<space>") — that is pynput's
    # own canonical form, as HotKey.parse produces it.
    parts.append(key if len(key) == 1 else f"<{key}>")
    return "+".join(parts)


def format_hotkey_combo(canonical: str) -> str:
    """'<ctrl>+<alt>+a' -> 'Ctrl+Alt+A', for display."""
    parts = []
    for token in canonical.split("+"):
        token = token.strip().strip("<>")
        if not token:
            continue
        if token == "cmd":
            parts.append("Win")
        elif len(token) == 1:
            parts.append(token.upper())
        elif token == "page_up":
            parts.append("PageUp")
        elif token == "page_down":
            parts.append("PageDown")
        else:
            parts.append(token.capitalize())
    return "+".join(parts) if parts else canonical


def get_hotkey_combo() -> str:
    """The configured combo in canonical form, or the default
    when nothing valid was ever saved."""
    raw = _load_settings().get("hotkey_combo", DEFAULT_HOTKEY_COMBO)
    if isinstance(raw, str):
        parsed = parse_hotkey_combo(raw)
        if parsed is not None:
            return parsed
    return DEFAULT_HOTKEY_COMBO


def set_hotkey_combo(canonical: str) -> None:
    """Persist a combo in canonical form. Raises ValueError on
    a bad value — the caller speaks the error instead of
    saving garbage."""
    parsed = parse_hotkey_combo(canonical)
    if parsed is None:
        raise ValueError(f"not a valid hotkey combo: {canonical!r}")
    data = _load_settings()
    data["hotkey_combo"] = parsed
    _save_settings(data)


def hotkey_status() -> dict:
    """One dict for the Control Center + Diagnostics tab. The
    module-level view cannot know whether the icon's listener
    is actually running — that is instance state (main.py
    passes both, like the tray status)."""
    combo = get_hotkey_combo()
    return {
        "enabled": is_hotkey_enabled(),
        "combo": combo,
        "combo_display": format_hotkey_combo(combo),
        "available": hotkey_available(),
        "running": False,
    }


class Hotkey:
    """AURA's global hotkey, on pynput's own listener thread.

    ``on_press`` runs on that thread — main.py schedules the
    GUI work with after(0), so the callback itself must stay
    tiny and never raise (a raising callback is caught here,
    so a bug in the handler can never kill the listener).
    """

    def __init__(self, on_press, combo=None):
        self.on_press = on_press
        self._combo = combo or DEFAULT_HOTKEY_COMBO
        self._listener = None
        self._running = False

    @property
    def running(self) -> bool:
        """True while the listener thread is up."""
        return self._running

    @property
    def combo(self) -> str:
        """The combo this listener was started with."""
        return self._combo

    def _safe_press(self):
        try:
            self.on_press()
        except Exception:  # noqa: BLE001 - the listener must survive
            pass

    def start(self, combo=None) -> bool:
        """Start listening for ``combo`` (or the one this object
        was built with). Returns False when pynput is not
        installed, the combo does not parse, or the listener
        dies at once — the pill then runs exactly as before.
        Safe to call twice with the same combo (a no-op True).
        """
        combo = combo or self._combo
        if parse_hotkey_combo(combo) is None:
            return False
        if self._running and combo == self._combo:
            return True
        self.stop()
        mod = _load_pynput()
        if mod is None:
            return False
        try:
            self._listener = mod.GlobalHotKeys(
                {combo: self._safe_press})
            self._listener.start()
        except Exception:  # noqa: BLE001 - hotkey never breaks startup
            self._listener = None
            return False
        # The hook registers on the listener thread: give it a
        # moment, and report False only if the thread actually
        # died (a hook that was refused). A slow start that is
        # still alive after the wait counts as running.
        deadline = time.time() + 0.5
        while time.time() < deadline:
            if not self._listener.is_alive():
                self._listener = None
                return False
            time.sleep(0.05)
        self._combo = combo
        self._running = True
        return True

    def restart(self, combo=None) -> bool:
        """Rebind to ``combo`` (or the current one). A restart
        with the same combo while running is a no-op True."""
        if self._running and (combo is None or combo == self._combo):
            return True
        return self.start(combo)

    def stop(self):
        """Stop listening. Safe to call anytime, including
        twice — the join is skipped from the listener thread
        itself, because joining your own thread would
        deadlock."""
        listener = self._listener
        self._listener = None
        self._running = False
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            thread = listener
            if isinstance(thread, threading.Thread) and (
                    thread is not threading.current_thread()):
                thread.join(timeout=2)


def parse_hotkey_command(text: str):
    """Match spoken text to a hotkey request. None if no match."""
    t = text.strip().lower()
    if t in (
        "turn off hotkey",
        "disable hotkey",
        "turn hotkey off",
        "disable the hotkey",
        "turn off the hotkey",
        "stop hotkey",
        "stop the hotkey",
    ):
        return {"kind": "toggle_off"}
    if t in (
        "turn on hotkey",
        "enable hotkey",
        "turn hotkey on",
        "enable the hotkey",
        "turn on the hotkey",
    ):
        return {"kind": "toggle_on"}
    if t in (
        "what is my hotkey",
        "what's my hotkey",
        "hotkey status",
        "what hotkey",
        "is hotkey on",
        "what is the hotkey",
    ):
        return {"kind": "status"}
    match = re.match(r"(set|change)( the| my)? hotkey( to)? (.+)$", t)
    if match:
        return {
            "kind": "set_combo",
            "combo": parse_hotkey_combo(match.group(4)),
            "raw": match.group(4).strip(),
        }
    return None


def execute_hotkey_command(cmd: dict):
    """Run a parsed hotkey command.

    Returns (reply, gui_action): the reply to speak, and a
    "hotkey_apply" action when the listener must be (re)bound
    — the brain records it and main.py applies it (same
    channel as the morning briefing's "morning_refresh").
    Status questions return no action.
    """
    kind = cmd["kind"]
    if kind == "toggle_off":
        set_hotkey_enabled(False)
        return ("Hotkey is off — Ctrl+Alt+A won't do anything "
                "until you turn it back on."), "hotkey_apply"
    if kind == "toggle_on":
        if not hotkey_available():
            return (
                "The hotkey isn't available on this PC — pynput "
                "isn't installed. Run: pip install -r "
                "requirements.txt, then restart AURA.",
                None,
            )
        set_hotkey_enabled(True)
        combo = format_hotkey_combo(get_hotkey_combo())
        return (
            f"Hotkey is on — press {combo} anywhere to open "
            "the command box.",
            "hotkey_apply",
        )
    if kind == "set_combo":
        if cmd["combo"] is None:
            return (
                "I didn't understand that hotkey — try something "
                "like 'set hotkey to ctrl shift h'. It needs at "
                "least one modifier (ctrl, alt, shift) and one "
                "key.",
                None,
            )
        if not hotkey_available():
            return (
                "The hotkey isn't available on this PC — pynput "
                "isn't installed. Run: pip install -r "
                "requirements.txt, then restart AURA.",
                None,
            )
        set_hotkey_combo(cmd["combo"])
        if not is_hotkey_enabled():
            set_hotkey_enabled(True)
            note = " I've turned the hotkey on too."
        else:
            note = ""
        return (
            f"Hotkey set to "
            f"{format_hotkey_combo(cmd['combo'])}.{note}",
            "hotkey_apply",
        )
    if kind == "status":
        status = hotkey_status()
        if not status["available"]:
            return (
                "The hotkey isn't available on this PC — pynput "
                "isn't installed. Run: pip install -r "
                "requirements.txt, then restart AURA.",
                None,
            )
        if not status["enabled"]:
            return "Hotkey is off.", None
        return (
            f"Hotkey is on: {status['combo_display']} opens the "
            "command box from anywhere.",
            None,
        )
    return "I don't know how to do that yet.", None
