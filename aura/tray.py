"""System tray icon — Phase 9.2A.

The pill has no close button by design, so AURA needs a way to
run in the background: a tray icon with Show pill / Hide pill /
Daily briefing / Quit AURA. The standard Python route is pystray
(+ Pillow for the icon image), both pinned in requirements.txt.

The module is import-safe everywhere: pystray and PIL are only
imported inside _load_pystray(), so importing this module never
fails on a PC without them — tray_available() just returns False
and the pill stays the only UI. The icon runs on its own thread,
so it can never freeze the pill, and stop() cleans it up on quit.

Icon: aura-icon.ico from the source tree (the same icon as the
desktop shortcut used). When the file is missing, a plain
violet square is used instead — the tray still works.

Voice: "minimize to tray" / "hide in tray" / "show the pill".
When the tray is not available, the hide command says so
honestly instead of hiding the pill with no way back.
"""

import os
import threading

_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura-icon.ico",
)

# Cached import result: the pystray module once loaded, False when
# the import failed (pystray / PIL not installed, or no tray
# backend on this platform). _reset_cache() exists for tests.
_pystray = None
_PIL_Image = None


def _reset_cache() -> None:
    """Forget the cached import result — used by tests."""
    global _pystray, _PIL_Image
    _pystray = None
    _PIL_Image = None


def _load_pystray():
    """Import pystray + PIL.Image once, or None when unavailable."""
    global _pystray, _PIL_Image
    if _pystray is None:
        try:
            import pystray
            from PIL import Image
            _pystray = pystray
            _PIL_Image = Image
        except Exception:  # noqa: BLE001 - no tray on this PC
            _pystray = False
            _PIL_Image = False
    return _pystray or None


def tray_available() -> bool:
    """True when pystray + Pillow import (a tray backend exists)."""
    return _load_pystray() is not None


def tray_status() -> dict:
    """Module-level status: availability only. Whether the icon
    is actually running is instance state — see TrayIcon.running
    (main.py passes both to the Control Center)."""
    return {"available": tray_available(), "running": False}


class TrayIcon:
    """AURA's tray icon, on its own thread.

    Callbacks (wired by main.py, all safe to call from the tray
    thread — main.py schedules the GUI ones with after(0)):
      on_show: bring the pill back (deiconify + lift).
      on_hide: hide the pill (withdraw).
      on_briefing: speak the daily briefing.
      on_quit: clean shutdown (stop the tray, close the pill).
    """

    def __init__(self, *, on_show, on_hide, on_briefing, on_quit,
                 icon_path=None):
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_briefing = on_briefing
        self.on_quit = on_quit
        self.icon_path = icon_path or _ICON_PATH
        self._icon = None
        self._thread = None
        self._running = False

    @property
    def running(self) -> bool:
        """True while the icon thread is up."""
        return self._running

    def _load_icon_image(self):
        """The .ico file, or a plain violet square when it is
        missing — the tray still works without the artwork."""
        if os.path.exists(self.icon_path):
            return _PIL_Image.open(self.icon_path)
        return _PIL_Image.new("RGB", (64, 64), (139, 92, 246))

    def start(self) -> bool:
        """Start the tray icon on its own thread.

        Returns False when pystray is not installed, the icon
        image cannot be built, or the tray backend refuses —
        the pill then stays the only UI and nothing else breaks.
        Safe to call twice (a second start is a no-op True).
        """
        if self._running:
            return True
        mod = _load_pystray()
        if mod is None:
            return False
        try:
            image = self._load_icon_image()
            menu = mod.Menu(
                # The first item with default=True is what pystray
                # invokes on a double-click (Windows) — there is no
                # Icon "default_action" attribute in pystray 0.19.x;
                # assigning one after construction is silently
                # ignored, which is why double-click did nothing.
                mod.MenuItem(
                    "Show pill",
                    lambda icon, item: self.on_show(),
                    default=True),
                mod.MenuItem(
                    "Hide pill",
                    lambda icon, item: self.on_hide()),
                mod.MenuItem(
                    "Daily briefing",
                    lambda icon, item: self.on_briefing()),
                mod.Menu.SEPARATOR,
                mod.MenuItem(
                    "Quit AURA",
                    lambda icon, item: self.on_quit()),
            )
            self._icon = mod.Icon("AURA", image, "AURA", menu)
        except Exception:  # noqa: BLE001 - tray never breaks startup
            self._icon = None
            return False
        self._thread = threading.Thread(
            target=self._run_icon, daemon=True)
        self._thread.start()
        self._running = True
        return True

    def _run_icon(self):
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001, S110 - tray thread never raises
            pass
        finally:
            self._running = False

    def stop(self):
        """Stop the tray icon. Safe to call anytime, including
        from a menu callback (the tray thread itself): the join
        is skipped then, because joining your own thread would
        deadlock."""
        icon = self._icon
        self._icon = None
        self._running = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)


def parse_tray_command(text: str):
    """Match spoken text to a tray request. None if no match."""
    t = text.strip().lower()
    if t in (
        "minimize to tray",
        "minimize to the tray",
        "hide in tray",
        "hide in the tray",
        "send to tray",
        "send to the tray",
        "hide the pill",
        "minimize the pill",
    ):
        return {"kind": "hide"}
    if t in (
        "show the pill",
        "show pill",
        "restore the pill",
        "bring back the pill",
        "bring the pill back",
        "show aura",
    ):
        return {"kind": "show"}
    return None


def execute_tray_command(cmd: dict):
    """Run a parsed tray command.

    Returns (reply, gui_action): the reply to speak, and the
    "tray_hide" / "tray_show" action for main.py to apply on the
    GUI thread (the brain has no GUI — same channel as the
    Control Center open/close). Hiding with no tray available
    returns no action and says so honestly, so the pill is never
    hidden with no way back.
    """
    kind = cmd["kind"]
    if kind == "hide":
        if not tray_available():
            return (
                "The system tray isn't available on this PC, so "
                "the pill is staying visible.",
                None,
            )
        return (
            "Minimizing to the tray — I'll keep running in the "
            "background. Double-click the tray icon, or say "
            "'show the pill', to bring me back.",
            "tray_hide",
        )
    if kind == "show":
        return "Showing the pill.", "tray_show"
    return "I don't know how to do that yet.", None
