"""Tests for Phase 9.2A — system tray icon.

No real tray is created here: pystray is either absent (this VM
has no pystray — the honest-degradation path is tested for real)
or faked in sys.modules (same pattern as test_whisper.py stubs
faster-whisper). The fake icon blocks on an event so the thread
lifecycle can be asserted without a display.

    python test_tray.py
"""

import os
import sys
import tempfile
import threading
import types

from aura.brain import handle, pop_gui_action, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.memory import Memory
from aura.tray import (
    TrayIcon,
    _reset_cache,
    execute_tray_command,
    parse_tray_command,
    tray_available,
    tray_status,
)


class _FakeMenuItem:
    def __init__(self, text, action, default=False):
        self.text = text
        self.action = action
        self.default = default


class _FakeMenu:
    SEPARATOR = "SEPARATOR"

    def __init__(self, *items):
        self.items = items


class _FakeIcon:
    """Stands in for pystray.Icon: run() blocks until stop()."""

    def __init__(self, name, image, title, menu):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.ran = False
        self.stopped = False
        self._event = threading.Event()

    def run(self):
        self.ran = True
        self._event.wait(timeout=10)

    def stop(self):
        self.stopped = True
        self._event.set()


class _FakeImageModule:
    opened = []
    created = []

    @staticmethod
    def open(path):
        _FakeImageModule.opened.append(path)
        return f"image:{path}"

    @staticmethod
    def new(mode, size, color):
        _FakeImageModule.created.append((mode, size, color))
        return "image:fallback-square"


def _install_fake_pystray():
    """Put a fake pystray + PIL.Image in sys.modules."""
    stub = types.ModuleType("pystray")
    stub.Menu = _FakeMenu
    stub.MenuItem = _FakeMenuItem
    stub.Icon = _FakeIcon
    sys.modules["pystray"] = stub
    pil = types.ModuleType("PIL")
    pil.__path__ = []
    image_mod = types.ModuleType("PIL.Image")
    image_mod.open = _FakeImageModule.open
    image_mod.new = _FakeImageModule.new
    pil.Image = image_mod
    sys.modules["PIL"] = pil
    sys.modules["PIL.Image"] = image_mod
    _reset_cache()


def _remove_fake_pystray():
    sys.modules.pop("pystray", None)
    sys.modules.pop("PIL", None)
    sys.modules.pop("PIL.Image", None)
    _reset_cache()


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Parsing. ----------------------------------------------------
    assert parse_tray_command("minimize to tray") == {"kind": "hide"}
    assert parse_tray_command("hide in the tray") == {"kind": "hide"}
    assert parse_tray_command("hide the pill") == {"kind": "hide"}
    assert parse_tray_command("show the pill") == {"kind": "show"}
    assert parse_tray_command("bring the pill back") == {"kind": "show"}
    assert parse_tray_command("what is the time") is None
    assert parse_tray_command("open control center") is None

    # --- No pystray on this VM: honest degradation, for real. -------
    _remove_fake_pystray()
    assert tray_available() is False
    assert tray_status() == {"available": False, "running": False}
    reply, action = execute_tray_command({"kind": "hide"})
    assert "isn't available" in reply, reply
    assert action is None, "never hide the pill with no way back"
    reply, action = execute_tray_command({"kind": "show"})
    assert action == "tray_show", "show is always safe"
    icon = TrayIcon(on_show=lambda: None, on_hide=lambda: None,
                    on_briefing=lambda: None, on_quit=lambda: None)
    assert icon.running is False
    assert icon.start() is False, "no pystray, no icon"
    assert icon.running is False
    icon.stop()  # safe when never started

    # --- Brain routing without a tray. -------------------------------
    assert pop_gui_action() is None
    reply, quit_ = handle("minimize to tray")
    assert "isn't available" in reply and not quit_, reply
    assert pop_gui_action() is None
    reply, _ = handle("show the pill")
    assert pop_gui_action() == "tray_show"
    assert "tray" in handle("help")[0].lower()

    # --- With a fake pystray: full lifecycle. ------------------------
    _install_fake_pystray()
    try:
        assert tray_available() is True
        calls = []
        icon = TrayIcon(
            on_show=lambda: calls.append("show"),
            on_hide=lambda: calls.append("hide"),
            on_briefing=lambda: calls.append("briefing"),
            on_quit=lambda: calls.append("quit"),
            icon_path=os.path.join(tmp, "missing.ico"),
        )
        assert icon.start() is True
        assert icon.running is True
        # The fallback square was used — the .ico is missing.
        assert _FakeImageModule.created, "no fallback image built"
        assert not _FakeImageModule.opened, "missing .ico was opened"
        # Second start is a no-op True.
        assert icon.start() is True
        # The menu has Show / Hide / Briefing / separator / Quit,
        # and each item calls its callback.
        items = [i for i in icon._icon.menu.items
                 if isinstance(i, _FakeMenuItem)]
        assert [i.text for i in items] == [
            "Show pill", "Hide pill", "Daily briefing", "Quit AURA",
        ], [i.text for i in items]
        assert icon._icon.menu.items[3] == _FakeMenu.SEPARATOR
        # Double-click must bring the pill back: in pystray the
        # first MenuItem with default=True is the double-click
        # action — "Show pill" and only "Show pill".
        assert [i.default for i in items] == [
            True, False, False, False,
        ], [i.default for i in items]
        assert not hasattr(icon._icon, "default_action"), \
            "pystray has no such attribute — do not rely on it"
        for item in items:
            item.action(None, None)
        assert calls == ["show", "hide", "briefing", "quit"], calls
        fake = icon._icon  # stop() clears the reference
        assert fake.ran is True, "icon thread never ran"
        icon.stop()
        assert icon.running is False
        assert fake.stopped is True
        icon.stop()  # safe twice
        # With a real .ico file, Image.open is used instead.
        _FakeImageModule.opened.clear()
        _FakeImageModule.created.clear()
        ico_path = os.path.join(tmp, "aura-icon.ico")
        with open(ico_path, "wb") as fh:
            fh.write(b"fake-ico")
        icon2 = TrayIcon(
            on_show=lambda: None, on_hide=lambda: None,
            on_briefing=lambda: None, on_quit=lambda: None,
            icon_path=ico_path,
        )
        assert icon2.start() is True
        assert _FakeImageModule.opened == [ico_path]
        icon2.stop()
        assert icon2.running is False
    finally:
        _remove_fake_pystray()

    # --- Back to no pystray: the cache really resets. ---------------
    assert tray_available() is False
    reply, action = execute_tray_command({"kind": "hide"})
    assert action is None

    print("All tray tests passed.")


if __name__ == "__main__":
    main()
