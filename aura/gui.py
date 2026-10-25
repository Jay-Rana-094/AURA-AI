"""AURA's window — a Dynamic Island-style pill, top-centre of the screen.

A small borderless black pill that sits at the top middle of the display,
like the Dynamic Island on a phone: a status dot, a short status line,
the last thing AURA heard, and a mic button. Drag the pill to move it;
it stays on top of other windows.

The GUI never does listening or speaking itself — it only shows state
and forwards button presses to callbacks in main.py, so the window
stays responsive while voice work happens on worker threads.
"""

import tkinter as tk

PILL_WIDTH = 420
PILL_HEIGHT = 64
TOP_MARGIN = 12

BG = "#0a0a0a"
PILL_FILL = "#161616"
PILL_OUTLINE = "#2e2e2e"
TEXT = "#f2f2f2"
DIM = "#8a8a8a"

DOT_COLORS = {
    "idle": "#555555",
    "listening": "#34c759",
    "thinking": "#ff9f0a",
    "speaking": "#0a84ff",
    "error": "#ff453a",
    "wake": "#bf5af2",  # purple: waiting for the wake word
}


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
        _rounded_rect(
            self.canvas, 2, 2, PILL_WIDTH - 2, PILL_HEIGHT - 2, 30,
            fill=PILL_FILL, outline=PILL_OUTLINE, width=1,
        )

        # Status dot.
        self.dot = self.canvas.create_oval(22, 26, 34, 38, fill=DOT_COLORS["idle"], outline="")

        # Status + transcript text.
        self.status_text = self.canvas.create_text(
            46, 18, anchor="w", text="AURA — tap the mic and speak",
            fill=TEXT, font=("Segoe UI", 11, "bold"),
        )
        self.transcript_text = self.canvas.create_text(
            46, 40, anchor="w", text="", fill=DIM, font=("Segoe UI", 9),
        )

        # Wake-word toggle (left of the mic button). Green when on.
        self.wake_btn = tk.Button(
            self.root, text="👂", font=("Segoe UI", 14),
            bg="#222222", fg="white", activebackground="#333333",
            relief="flat", bd=0, command=self._wake_pressed,
            cursor="hand2",
        )
        self.wake_btn.place(x=PILL_WIDTH - 102, y=12, width=40, height=40)

        # Mic button (right side of the pill).
        self.mic_btn = tk.Button(
            self.root, text="🎤", font=("Segoe UI", 14),
            bg="#222222", fg="white", activebackground="#333333",
            relief="flat", bd=0, command=self._mic_pressed,
            cursor="hand2",
        )
        self.mic_btn.place(x=PILL_WIDTH - 56, y=12, width=40, height=40)

        # Engine toggle (small, bottom-right of the pill).
        self.engine_var = tk.StringVar(value="offline")
        self.engine_menu = tk.OptionMenu(
            self.root, self.engine_var, "offline", "google",
            command=self._engine_changed,
        )
        self.engine_menu.configure(
            bg="#222222", fg=DIM, activebackground="#333333",
            relief="flat", bd=0, font=("Segoe UI", 8), highlightthickness=0,
        )
        self.engine_menu.place(x=PILL_WIDTH - 150, y=40, width=84, height=18)

        # Drag the pill to move it.
        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)

        self._busy = False

    # -- user actions -------------------------------------------------------
    def _mic_pressed(self):
        if self._busy:
            return
        self.on_mic()

    def _wake_pressed(self):
        self._wake_on = not self._wake_on
        self.set_wake_active(self._wake_on)
        if self.on_wake_toggle:
            self.on_wake_toggle(self._wake_on)

    def set_wake_active(self, active: bool):
        """Show the wake toggle as on (green) or off. Thread-safe."""
        self._wake_on = active
        bg = "#1f7a33" if active else "#222222"
        self.root.after(0, lambda: self.wake_btn.configure(bg=bg))

    def _engine_changed(self, value):
        self.on_engine_change(value)

    def _drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag_move(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # -- state updates (safe to call from worker threads via after()) -------
    def set_state(self, state: str, status: str):
        """state: idle/listening/thinking/speaking/error/wake.
        "wake" is NOT busy: the mic button stays usable while AURA
        waits for the wake word."""
        def _apply():
            self.canvas.itemconfig(self.dot, fill=DOT_COLORS.get(state, DOT_COLORS["idle"]))
            self.canvas.itemconfig(self.status_text, text=status)
            self._busy = state in ("listening", "thinking", "speaking")
        self.root.after(0, _apply)

    def show_transcript(self, text: str):
        short = text if len(text) <= 52 else text[:49] + "..."
        self.root.after(0, lambda: self.canvas.itemconfig(self.transcript_text, text=short))

    def run(self):
        self.root.mainloop()

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
