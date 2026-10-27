"""AURA's window — a Dynamic Island-style pill, top-centre of the screen.

Neon-island look: a glowing blue/purple pill with a waveform orb on the
left, the status + transcript in the middle, and circular mic / dot /
wake controls on the right. Drag the pill to move it; it stays on top
of other windows.

Sharp on scaled displays: on Windows with display scaling above 100%
(125%/150%), a normal tkinter window gets bitmap-stretched by Windows
and looks blurry. This file tells Windows the app is DPI-aware and
scales all pixel geometry by the system scale factor, so the pill
renders natively sharp at the same apparent size. Font sizes are
deliberately NOT scaled here — tkinter already scales point sizes
itself once the app is DPI-aware, so scaling them again would
double-size the text. On a 100% display the scale factor is 1.0 and
this file behaves exactly like the previous glow pill.

The GUI never does listening or speaking itself — it only shows state
and forwards button presses to callbacks in main.py, so the window
stays responsive while voice work happens on worker threads.

Interface (unchanged from the classic pill, so main.py needs no edits):
    IslandGUI(on_mic, on_engine_change, on_wake_toggle)
    set_state(state, status)   # idle/listening/thinking/speaking/error/wake
    show_transcript(text)
    set_wake_active(active)
    run() / close()
"""

import random
import tkinter as tk


def _display_scale():
    """Return the Windows display scale factor (1.0 on 100% scaling).

    Also marks the process DPI-aware BEFORE any window exists, so
    Windows stops bitmap-stretching the pill. Safe no-op off Windows.
    """
    try:
        import ctypes
        try:
            ctypes.windll.shlcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        try:
            return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
        except Exception:
            return 1.0
    except Exception:
        return 1.0


SCALE = _display_scale()


def _px(v):
    """Scale a pixel value by the display factor (no-op at 100%)."""
    return int(round(v * SCALE))


PILL_WIDTH = _px(680)
PILL_HEIGHT = _px(84)
TOP_MARGIN = _px(12)

BG = "#030308"
TEXT = "#f2f2f2"
DIM = "#8a8a8a"
LABEL = "#7ec8ff"

DOT_COLORS = {
    "idle": "#555555",
    "listening": "#2bff88",
    "thinking": "#ffb020",
    "speaking": "#35a0ff",
    "error": "#ff453a",
    "wake": "#c96bff",
}

ORB_RING = {
    "idle": "#8b5cf6",
    "listening": "#2bff88",
    "thinking": "#ffb020",
    "speaking": "#35a0ff",
    "error": "#ff453a",
    "wake": "#c96bff",
}

BAR_COLORS = ["#67e8f9", "#a78bfa", "#67e8f9", "#a78bfa", "#67e8f9"]
BAR_BASE = [_px(10), _px(16), _px(22), _px(16), _px(10)]


def _rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Draw a rounded rectangle on a canvas (tkinter has no native one)."""
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y2 - radius,
        x2, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class IslandGUI:
    def __init__(self, on_mic, on_engine_change, on_wake_toggle=None):
        """on_mic: called when the mic button is pressed.
        on_engine_change(engine): called with "offline" or "google".
        on_wake_toggle(enabled): called when the wake button is tapped."""
        self.on_mic = on_mic
        self.on_engine_change = on_engine_change
        self.on_wake_toggle = on_wake_toggle
        self._wake_on = False
        self._state = "idle"
        self._busy = False
        self._animating = False

        self.root = tk.Tk()
        self.root.title("AURA")
        self.root.overrideredirect(True)  # borderless, like the Island
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)

        screen_w = self.root.winfo_screenwidth()
        x = (screen_w - PILL_WIDTH) // 2
        self.root.geometry(f"{PILL_WIDTH}x{PILL_HEIGHT}+{x}+{TOP_MARGIN}")

        self.canvas = tk.Canvas(
            self.root, width=PILL_WIDTH, height=PILL_HEIGHT,
            bg=BG, highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        # Neon glow: layered rounded rects behind the pill, fading out.
        _rounded_rect(self.canvas, 0, 0, PILL_WIDTH, PILL_HEIGHT, _px(40),
                      fill="#12083a", outline="")
        _rounded_rect(self.canvas, _px(4), _px(4),
                      PILL_WIDTH - _px(4), PILL_HEIGHT - _px(4), _px(36),
                      fill="#1b0f4d", outline="")
        _rounded_rect(self.canvas, _px(8), _px(8),
                      PILL_WIDTH - _px(8), PILL_HEIGHT - _px(8), _px(32),
                      fill="#241a66", outline="")
        # The pill itself + a bright top highlight line.
        _rounded_rect(self.canvas, _px(12), _px(12),
                      PILL_WIDTH - _px(12), PILL_HEIGHT - _px(12), _px(30),
                      fill="#0b0b1e", outline="#5b8cff", width=_px(2))
        self.canvas.create_line(_px(40), _px(13), PILL_WIDTH - _px(40), _px(13),
                                fill="#6ea8ff", width=max(1, _px(1)))

        # Waveform orb (left). Concentric circles + 5 animated bars.
        cx, cy, r = _px(44), _px(42), _px(24)
        self.orb_outer = self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill="#12082b", outline=ORB_RING["idle"], width=_px(2))
        self.canvas.create_oval(
            cx - r + _px(6), cy - r + _px(6), cx + r - _px(6), cy + r - _px(6),
            fill="#2b1666", outline="")
        self.bar_ids = []
        bar_x = [cx - _px(16), cx - _px(8), cx, cx + _px(8), cx + _px(16)]
        for bx, h, color in zip(bar_x, BAR_BASE, BAR_COLORS):
            self.bar_ids.append(self.canvas.create_line(
                bx, cy - h // 2, bx, cy + h // 2, fill=color, width=_px(4),
                capstyle="round"))

        # Labels + status/transcript text.
        # (Font sizes stay unscaled: tkinter scales point sizes itself
        # once the app is DPI-aware.)
        self.canvas.create_text(
            _px(88), _px(20), anchor="w", text="AURA",
            fill=LABEL, font=("Segoe UI", 10, "bold"))
        self.status_text = self.canvas.create_text(
            _px(88), _px(40), anchor="w",
            text="Hey Jay... how can I help you today?",
            fill=TEXT, font=("Segoe UI", 11, "bold"))
        self.transcript_text = self.canvas.create_text(
            _px(88), _px(60), anchor="w", text="", fill=DIM,
            font=("Segoe UI", 9))

        # Engine selector (small, dark, bottom-middle of the pill).
        self.engine_var = tk.StringVar(value="offline")
        self.engine_menu = tk.OptionMenu(
            self.root, self.engine_var, "offline", "google",
            command=self._engine_changed)
        self.engine_menu.configure(
            bg="#141438", fg=LABEL, activebackground="#1e1e5e",
            relief="flat", bd=0, font=("Segoe UI", 8), highlightthickness=0)
        self.engine_menu.place(x=_px(440), y=_px(58),
                               width=_px(88), height=_px(16))

        # Circular mic button (right).
        self.mic_circle = self.canvas.create_oval(
            _px(561), _px(23), _px(599), _px(61),
            fill="#141438", outline="#35a0ff", width=_px(2))
        self.mic_glyph = self.canvas.create_text(
            _px(580), _px(42), text="\U0001f3a4", fill="white",
            font=("Segoe UI", 14))
        self.canvas.tag_bind(self.mic_circle, "<Button-1>", self._mic_pressed)
        self.canvas.tag_bind(self.mic_glyph, "<Button-1>", self._mic_pressed)

        # Status dot (between mic and wake).
        self.dot = self.canvas.create_oval(
            _px(607), _px(37), _px(617), _px(47),
            fill=DOT_COLORS["idle"], outline="")

        # Wake ring (far right): glowing ring + centre dot when on.
        self.wake_ring = self.canvas.create_oval(
            _px(631), _px(25), _px(665), _px(59),
            fill="#141438", outline="#444444", width=_px(3))
        self.wake_dot = self.canvas.create_oval(
            _px(643), _px(37), _px(653), _px(47), fill="#444444", outline="")
        self.canvas.tag_bind(self.wake_ring, "<Button-1>", self._wake_pressed)
        self.canvas.tag_bind(self.wake_dot, "<Button-1>", self._wake_pressed)
        self._button_items = {
            self.mic_circle, self.mic_glyph, self.wake_ring, self.wake_dot}

        # Drag the pill to move it (clicks on buttons don't drag).
        self._drag_x = 0
        self._drag_y = 0
        self._drag_ok = False
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)

    # -- user actions -------------------------------------------------------
    def _mic_pressed(self, event=None):
        if self._busy:
            return
        self.on_mic()

    def _wake_pressed(self, event=None):
        self._wake_on = not self._wake_on
        self.set_wake_active(self._wake_on)
        if self.on_wake_toggle:
            self.on_wake_toggle(self._wake_on)

    def set_wake_active(self, active: bool):
        """Show the wake ring as on (green/cyan) or off. Thread-safe."""
        self._wake_on = active
        ring = "#2bff88" if active else "#444444"
        dot = "#2bff88" if active else "#444444"
        self.root.after(0, lambda: (
            self.canvas.itemconfig(self.wake_ring, outline=ring),
            self.canvas.itemconfig(self.wake_dot, fill=dot)))

    def _engine_changed(self, value):
        self.on_engine_change(value)

    def _drag_start(self, event):
        under = self.canvas.find_withtag("current")
        if under and under[0] in self._button_items:
            self._drag_ok = False
            return
        self._drag_ok = True
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag_move(self, event):
        if not self._drag_ok:
            return
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # -- state updates (safe to call from worker threads via after()) -------
    def set_state(self, state: str, status: str):
        """state: idle/listening/thinking/speaking/error/wake.
        "wake" is NOT busy: the mic button stays usable while AURA
        waits for the wake word."""
        def _apply():
            self._state = state
            self.canvas.itemconfig(
                self.dot, fill=DOT_COLORS.get(state, DOT_COLORS["idle"]))
            self.canvas.itemconfig(
                self.orb_outer, outline=ORB_RING.get(state, ORB_RING["idle"]))
            self.canvas.itemconfig(self.status_text, text=status)
            self._busy = state in ("listening", "thinking", "speaking")
            self.canvas.itemconfig(
                self.mic_circle,
                outline="#444444" if self._busy else "#35a0ff")
            if state in ("listening", "speaking") and not self._animating:
                self._animating = True
                self._animate_wave()
            elif state not in ("listening", "speaking"):
                self._animating = False
                self._set_bars(BAR_BASE)
        self.root.after(0, _apply)

    def _set_bars(self, heights):
        cy = _px(42)
        for bar_id, h in zip(self.bar_ids, heights):
            x1, _, x2, _ = self.canvas.coords(bar_id)
            self.canvas.coords(bar_id, x1, cy - h // 2, x2, cy + h // 2)

    def _animate_wave(self):
        if not self._animating:
            return
        heights = [random.randint(_px(6), _px(26)) for _ in BAR_BASE]
        heights[2] = max(heights[2], _px(18))  # centre bar stays tallest
        self._set_bars(heights)
        self.root.after(130, self._animate_wave)

    def show_transcript(self, text: str):
        short = text if len(text) <= 44 else text[:41] + "..."
        self.root.after(0, lambda: self.canvas.itemconfig(
            self.transcript_text, text=short))

    def run(self):
        self.root.mainloop()

    def close(self):
        self._animating = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass
