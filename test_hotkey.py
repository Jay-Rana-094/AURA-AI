"""Tests for Phase 9.2B — global hotkey.

No real hook is created here: pynput is either absent (this VM
has no pynput — the honest-degradation path is tested for real)
or faked in sys.modules (same pattern as test_tray.py stubs
pystray). The fake listener blocks on an event so the lifecycle
can be asserted without a display.

    python test_hotkey.py
"""

import os
import sys
import tempfile
import threading
import types

from aura.brain import handle, pop_gui_action, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.hotkey import (
    DEFAULT_HOTKEY_COMBO,
    Hotkey,
    _reset_cache,
    execute_hotkey_command,
    format_hotkey_combo,
    get_hotkey_combo,
    hotkey_available,
    hotkey_status,
    is_hotkey_enabled,
    parse_hotkey_combo,
    parse_hotkey_command,
    set_hotkey_combo,
    set_hotkey_enabled,
    set_settings_path,
)
from aura.memory import Memory


class _FakeGlobalHotKeys(threading.Thread):
    """Stands in for pynput.keyboard.GlobalHotKeys: run()
    blocks until stop(), like the real listener thread."""

    die_immediately = False
    fail_start = False
    created = []

    def __init__(self, mapping):
        super().__init__(daemon=True)
        self.mapping = mapping
        self._event = threading.Event()
        _FakeGlobalHotKeys.created.append(self)

    def run(self):
        if _FakeGlobalHotKeys.die_immediately:
            return
        self._event.wait(timeout=10)

    def stop(self):
        self._event.set()


class _FakeKeyboardModule:
    GlobalHotKeys = _FakeGlobalHotKeys


def _install_fake_pynput():
    """Put a fake pynput.keyboard in sys.modules."""
    pynput = types.ModuleType("pynput")
    pynput.keyboard = _FakeKeyboardModule()
    sys.modules["pynput"] = pynput
    sys.modules["pynput.keyboard"] = _FakeKeyboardModule()
    _FakeGlobalHotKeys.created.clear()
    _FakeGlobalHotKeys.die_immediately = False
    _FakeGlobalHotKeys.fail_start = False
    _reset_cache()


def _remove_fake_pynput():
    sys.modules.pop("pynput", None)
    sys.modules.pop("pynput.keyboard", None)
    _reset_cache()


def main():
    tmp = tempfile.mkdtemp()
    set_settings_path(os.path.join(tmp, "settings.json"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Combo parsing: every accepted form, and the refusals. ---
    assert parse_hotkey_combo("ctrl alt a") == "<ctrl>+<alt>+a"
    assert parse_hotkey_combo("ctrl+alt+a") == "<ctrl>+<alt>+a"
    assert parse_hotkey_combo("alt ctrl a") == "<ctrl>+<alt>+a", \
        "modifier order is canonicalised"
    assert parse_hotkey_combo("control alt a") == "<ctrl>+<alt>+a"
    assert parse_hotkey_combo("ctrl shift h") == "<ctrl>+<shift>+h"
    assert parse_hotkey_combo("alt f1") == "<alt>+<f1>"
    assert parse_hotkey_combo("cmd space") == "<cmd>+<space>"
    assert parse_hotkey_combo("ctrl alt shift s") == (
        "<ctrl>+<alt>+<shift>+s")
    assert parse_hotkey_combo("Ctrl+Alt+A") == "<ctrl>+<alt>+a"
    assert parse_hotkey_combo("ctrl 1") == "<ctrl>+1"
    for bad in (
        "a",  # bare letter would hijack normal typing
        "ctrl",  # modifier only
        "ctrl alt",  # no regular key
        "ctrl ctrl a",  # duplicate modifier
        "ctrl a b",  # two regular keys
        "ctrl banana",  # unknown word
        "",
        "ctrl alt f13",  # no such key
    ):
        assert parse_hotkey_combo(bad) is None, bad
    assert format_hotkey_combo("<ctrl>+<alt>+a") == "Ctrl+Alt+A"
    assert format_hotkey_combo("<ctrl>+<shift>+h") == "Ctrl+Shift+H"
    assert format_hotkey_combo("<alt>+<f1>") == "Alt+F1"
    assert format_hotkey_combo("<cmd>+<space>") == "Win+Space"
    # Display form round-trips through the parser.
    assert parse_hotkey_combo(
        format_hotkey_combo("<ctrl>+<alt>+a")) == "<ctrl>+<alt>+a"

    # --- Defaults: on, Ctrl+Alt+A. --------------------------------
    assert is_hotkey_enabled() is True, "hotkey is ON by default"
    assert get_hotkey_combo() == DEFAULT_HOTKEY_COMBO == "<ctrl>+<alt>+a"
    status = hotkey_status()
    assert status["enabled"] is True
    assert status["combo"] == "<ctrl>+<alt>+a"
    assert status["combo_display"] == "Ctrl+Alt+A"

    # --- Enable / disable / set persists. -------------------------
    set_hotkey_enabled(False)
    assert is_hotkey_enabled() is False
    set_hotkey_enabled(True)
    set_hotkey_combo("<ctrl>+<shift>+h")
    assert get_hotkey_combo() == "<ctrl>+<shift>+h"
    try:
        set_hotkey_combo("a")
        raise AssertionError("bare letter must not save")
    except ValueError:
        pass
    assert get_hotkey_combo() == "<ctrl>+<shift>+h", \
        "bad combo must not save"
    set_hotkey_combo(DEFAULT_HOTKEY_COMBO)

    # --- No pynput on this VM: honest degradation, for real. -----
    _remove_fake_pynput()
    assert hotkey_available() is False
    assert hotkey_status()["available"] is False
    icon = Hotkey(on_press=lambda: None)
    assert icon.running is False
    assert icon.start() is False, "no pynput, no listener"
    assert icon.running is False
    icon.stop()  # safe when never started
    reply, action = execute_hotkey_command({"kind": "toggle_on"})
    assert "isn't available" in reply, reply
    assert action is None
    reply, action = execute_hotkey_command(
        {"kind": "set_combo", "combo": "<ctrl>+<shift>+h", "raw": ""})
    assert "isn't available" in reply, reply
    assert action is None
    reply, action = execute_hotkey_command({"kind": "status"})
    assert "isn't available" in reply, reply

    # --- Brain routing without pynput. ----------------------------
    assert pop_gui_action() is None
    reply, quit_ = handle("turn on hotkey")
    assert "isn't available" in reply and not quit_, reply
    assert pop_gui_action() is None, "no apply when nothing to apply"
    reply, _ = handle("what is my hotkey")
    assert "isn't available" in reply, reply

    # --- With a fake pynput: full lifecycle. ----------------------
    _install_fake_pynput()
    try:
        assert hotkey_available() is True
        calls = []
        hk = Hotkey(on_press=lambda: calls.append("pressed"))
        assert hk.start() is True
        assert hk.running is True
        assert hk.combo == "<ctrl>+<alt>+a"
        # The listener got exactly one mapping, keyed by the combo.
        assert len(_FakeGlobalHotKeys.created) == 1
        fake = _FakeGlobalHotKeys.created[0]
        assert list(fake.mapping) == ["<ctrl>+<alt>+a"]
        # Simulating the press calls the callback.
        fake.mapping["<ctrl>+<alt>+a"]()
        assert calls == ["pressed"], calls
        # Second start with the same combo is a no-op True.
        assert hk.start() is True
        assert len(_FakeGlobalHotKeys.created) == 1
        # Restart with a new combo rebinds (old listener stopped).
        assert hk.restart("<ctrl>+<shift>+h") is True
        assert hk.combo == "<ctrl>+<shift>+h"
        assert len(_FakeGlobalHotKeys.created) == 2
        assert fake._event.is_set(), "old listener was not stopped"
        hk.stop()
        assert hk.running is False
        hk.stop()  # safe twice

        # A listener that dies at once (hook refused) reports False.
        _FakeGlobalHotKeys.die_immediately = True
        hk2 = Hotkey(on_press=lambda: None)
        assert hk2.start() is False
        assert hk2.running is False
        _FakeGlobalHotKeys.die_immediately = False

        # --- Brain routing with pynput. ---------------------------
        assert pop_gui_action() is None
        reply, quit_ = handle("turn off hotkey")
        assert "off" in reply and not quit_, reply
        assert is_hotkey_enabled() is False
        assert pop_gui_action() == "hotkey_apply"
        reply, _ = handle("turn on hotkey")
        assert "Ctrl+Alt+A" in reply, reply
        assert is_hotkey_enabled() is True
        assert pop_gui_action() == "hotkey_apply"
        reply, _ = handle("set hotkey to ctrl shift h")
        assert "Ctrl+Shift+H" in reply, reply
        assert get_hotkey_combo() == "<ctrl>+<shift>+h"
        assert pop_gui_action() == "hotkey_apply"
        reply, _ = handle("set hotkey to banana")
        assert "didn't understand" in reply, reply
        assert get_hotkey_combo() == "<ctrl>+<shift>+h", \
            "bad combo must not save"
        assert pop_gui_action() is None
        reply, _ = handle("what is my hotkey")
        assert "Ctrl+Shift+H" in reply, reply
        reply, _ = handle("hotkey status")
        assert "Ctrl+Shift+H" in reply, reply

        # "stop hotkey" must hit step 4m, NOT the built-in exit
        # rule ("stop" is an exit word).
        set_hotkey_enabled(True)
        reply, quit_ = handle("stop hotkey")
        assert quit_ is False, "stop hotkey must not quit AURA"
        assert is_hotkey_enabled() is False
        assert pop_gui_action() == "hotkey_apply"

        # Custom phrases beat built-ins: teach "turn off
        # hotkey" to mean something else, and the toggle must
        # not run (same rule as every other built-in).
        set_hotkey_enabled(True)
        reply, _ = handle(
            "teach aura turn off hotkey means what is the time")
        assert "got it" in reply.lower(), reply
        reply, quit_ = handle("turn off hotkey")
        assert is_hotkey_enabled() is True, \
            "custom phrase ran, not the toggle"
        assert quit_ is False
        assert pop_gui_action() is None
    finally:
        _remove_fake_pynput()

    # --- Back to no pynput: the cache really resets. --------------
    assert hotkey_available() is False
    reply, action = execute_hotkey_command({"kind": "toggle_on"})
    assert action is None

    print("All hotkey tests passed.")


if __name__ == "__main__":
    main()
