"""AURA Control Center — Phase 8A.

A normal window (title bar, closable with the mouse) that opens
when Jay double-clicks the pill or says "open control center".
It adds a window, not new features: everything it shows comes
from the modules AURA already has.

Contents:
  - Animated core: a pulsing orb in the header, like the pill's
    waveform orb, so the window feels like AURA, not a settings
    dialog.
  - Live telemetry: CPU / RAM / disk / battery, refreshed every
    2 seconds. Needs ``psutil`` (in requirements.txt); without it
    the panel says so and the rest still works.
  - Today: the daily briefing, overdue + today's reminders,
    high-priority todos, unread notification count.
  - Notes / Todos / Reminders: live lists from the memory store,
    with add / delete / complete / cancel controls.
  - History: the recent conversation, with search and clear.
  - Settings: theme picker (recolors the pill too), wake word,
    language mode, speech engine, always-on-top.
  - Diagnostics: engine, Vosk model, language, wake word, theme,
    psutil, Python and platform.

A typed-command box sits at the bottom of every tab: type a
command, press Enter, and it runs through the same brain as a
voice turn (and is spoken aloud, like a voice turn).

The window never does voice work itself — main.py wires the
callbacks (typed commands, theme, engine) so the window stays
a plain view over the running app.

    ControlCenter(parent, memory, on_typed_command=..., on_theme=...,
                  on_engine_change=..., get_engine=...,
                  get_whisper_info=..., on_close=...,
                  on_morning_change=..., get_morning_status=...,
                  get_tray_status=...)
    refresh_all() / show_tab(name) / raise_window() / close()
    show_typed_reply(text)   # safe to call from a worker thread
"""

import math
import os
import platform
import sys
import time
import tkinter as tk

from aura.chat import (
    CHAT_MODEL,
    chat_status,
    is_chat_enabled,
    set_chat_enabled,
)
from aura.morning import (
    DEFAULT_BRIEFING_TIME,
    format_briefing_time,
    get_morning_time,
    is_morning_enabled,
    morning_status,
    parse_briefing_time,
    set_morning_enabled,
    set_morning_time,
)
from aura.tray import tray_status
from aura.calendar import calendar_status
from aura.commands.briefing import build_briefing
from aura.gpu import format_gpu_info, get_gpu_info
from aura.hotkey import (
    DEFAULT_HOTKEY_COMBO,
    format_hotkey_combo,
    get_hotkey_combo,
    hotkey_status,
    is_hotkey_enabled,
    parse_hotkey_combo,
    set_hotkey_combo,
    set_hotkey_enabled,
)
from aura.language import load_language, save_language
from aura.models import HINDI_MODEL_CANDIDATES, MODEL_CANDIDATES, pick_model_dir
from aura.personality import (
    PRESETS,
    describe_mode,
    load_mode,
    personality_status,
    save_mode,
)
from aura.speaker import has_hindi_voice
from aura.theme import THEMES, load_theme_name, save_theme_name
from aura.wake_settings import (
    display_wake_word,
    load_wake_word,
    save_wake_word,
    validate_wake_word,
)

try:
    import psutil
except Exception:  # noqa: BLE001 - psutil is optional; panel degrades
    psutil = None

BG = "#030308"
PANEL = "#0b0b1e"
TEXT = "#f2f2f2"
DIM = "#8a8a8a"
INPUT_BG = "#141438"

TABS = ("Today", "Notes · Todos · Reminders", "History", "Settings", "Diagnostics")

TELEMETRY_INTERVAL_MS = 2000
CORE_ANIM_MS = 150


# -- telemetry (pure: no tkinter, so unit-testable anywhere) ---------------
def get_telemetry():
    """Live system stats, or {"available": False, "reason": ...}.

    The first CPU reading after AURA starts is 0.0 (psutil needs a
    prior sample); later ticks are real. Battery is None on a
    desktop PC without one.
    """
    if psutil is None:
        return {
            "available": False,
            "reason": "psutil is not installed — run: pip install psutil",
        }
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        battery = psutil.sensors_battery()
        return {
            "available": True,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(),
            "ram_percent": mem.percent,
            "ram_used_gb": mem.used / (1024 ** 3),
            "ram_total_gb": mem.total / (1024 ** 3),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024 ** 3),
            "battery_percent": (
                battery.percent if battery is not None else None
            ),
            "battery_plugged": (
                battery.power_plugged if battery is not None else None
            ),
        }
    except Exception as exc:  # noqa: BLE001 - telemetry never breaks the window
        return {"available": False, "reason": f"telemetry error: {exc}"}


def format_telemetry(stats):
    """One text line per stat, for the Diagnostics tab."""
    if not stats.get("available"):
        return [stats.get("reason", "telemetry unavailable")]
    lines = [
        f"CPU: {stats['cpu_percent']:.0f}%  "
        f"({stats['cpu_count']} cores)",
        f"RAM: {stats['ram_percent']:.0f}%  "
        f"({stats['ram_used_gb']:.1f} GB of {stats['ram_total_gb']:.1f} GB)",
        f"Disk: {stats['disk_percent']:.0f}% used  "
        f"({stats['disk_free_gb']:.1f} GB free)",
    ]
    if stats["battery_percent"] is None:
        lines.append("Battery: no battery detected")
    else:
        state = (
            "plugged in" if stats["battery_plugged"] else "on battery"
        )
        lines.append(f"Battery: {stats['battery_percent']:.0f}% ({state})")
    return lines


def telemetry_lines() -> list:
    """The live system lines for the Diagnostics tab: psutil
    stats plus the GPU (Phase 9.1). Both halves degrade
    honestly on their own — a missing GPU never hides the CPU
    numbers, and vice versa. Shared by the 2-second tick and
    the Diagnostics refresh so the two never drift apart."""
    return format_telemetry(get_telemetry()) + format_gpu_info(get_gpu_info())


class ControlCenter:
    def __init__(self, parent, memory, *, on_typed_command,
                 on_theme, on_engine_change, get_engine, on_close=None,
                 get_whisper_info=None, on_chat_change=None,
                 get_chat_status=None, on_morning_change=None,
                 get_morning_status=None, get_tray_status=None,
                 on_hotkey_change=None, get_hotkey_status=None,
                 on_hotkey_combo=None, get_calendar_status=None,
                 on_personality_change=None,
                 get_personality_status=None,
                 get_state_status=None, get_focus_status=None):
        """parent: the pill's root window. memory: the Memory store.
        on_typed_command(text): main.py runs it through the brain.
        on_theme(name): main.py saves + recolors the pill.
        on_engine_change(engine): main.py switches the listener.
        get_engine(): current engine name ("offline"/"google"/
        "whisper").
        get_whisper_info(): Phase 8B — listener.whisper_info(),
        or None when the listener does not report it.
        on_chat_change(enabled): Phase 8C — main.py persists the
        chat-mode flag. get_chat_status(): chat_status(), or None
        for the default.
        on_morning_change(enabled): Phase 9.2A — main.py persists
        the morning-briefing flag. get_morning_status():
        morning_status(), or None for the default.
        get_tray_status(): Phase 9.2A — a dict {"available",
        "running"} for the tray icon, or None for the default
        (availability only, running False).
        on_hotkey_change(enabled): Phase 9.2B — main.py persists
        the hotkey flag and (re)binds the listener.
        get_hotkey_status(): hotkey_status(), or None for the
        default. on_hotkey_combo(combo): Phase 9.2B — main.py
        persists the combo and rebinds the listener.
        get_calendar_status(): calendar_status(), or None for
        the default.
        on_personality_change(mode): Phase 10.1 — main.py persists
        the personality mode. get_personality_status():
        personality_status(), or None for the default.
        get_state_status(): Phase 10.1 — a dict {"state",
        "status"} from the shared StateManager, or None for the
        default (IDLE). get_focus_status(): Phase 10.1 — a dict
        {"active", "status", "line", "on_break"} from the focus
        manager, or None for the default (no session).
        on_close(): called (GUI thread) when the window closes."""
        self.memory = memory
        self.on_typed_command = on_typed_command
        self.on_theme = on_theme
        self.on_engine_change = on_engine_change
        self.get_engine = get_engine
        self.get_whisper_info = get_whisper_info
        self.on_chat_change = (
            on_chat_change if on_chat_change is not None
            else set_chat_enabled
        )
        self.get_chat_status = (
            get_chat_status if get_chat_status is not None
            else chat_status
        )
        # Phase 9.2A: morning briefing + tray status, same shape
        # as the chat-mode wiring above.
        self.on_morning_change = (
            on_morning_change if on_morning_change is not None
            else set_morning_enabled
        )
        self.get_morning_status = (
            get_morning_status if get_morning_status is not None
            else morning_status
        )
        self.get_tray_status = (
            get_tray_status if get_tray_status is not None
            else tray_status
        )
        # Phase 9.2B: global hotkey + Google Calendar, same
        # shape as the morning/tray wiring above. The combo
        # callback has no safe default that rebinds the
        # listener — the fallback only persists it (main.py
        # always passes the real one).
        self.on_hotkey_change = (
            on_hotkey_change if on_hotkey_change is not None
            else set_hotkey_enabled
        )
        self.get_hotkey_status = (
            get_hotkey_status if get_hotkey_status is not None
            else hotkey_status
        )
        self.on_hotkey_combo = (
            on_hotkey_combo if on_hotkey_combo is not None
            else set_hotkey_combo
        )
        self.get_calendar_status = (
            get_calendar_status if get_calendar_status is not None
            else calendar_status
        )
        # Phase 10.1: personality modes + shared state + focus,
        # same shape as the chat/morning wiring above.
        self.on_personality_change = (
            on_personality_change if on_personality_change is not None
            else save_mode
        )
        self.get_personality_status = (
            get_personality_status if get_personality_status is not None
            else personality_status
        )
        self.get_state_status = (
            get_state_status if get_state_status is not None
            else (lambda: {"state": "IDLE", "status": None})
        )
        self.get_focus_status = (
            get_focus_status if get_focus_status is not None
            else (lambda: {"active": False, "status": "idle",
                          "line": "", "on_break": False})
        )
        self.on_close = on_close
        self._alive = True
        self._theme_name = load_theme_name()
        self._theme = THEMES[self._theme_name]
        self._current_tab = TABS[0]
        self._telemetry_job = None
        self._core_job = None
        self._core_phase = 0.0

        self.window = tk.Toplevel(parent)
        self.window.title("AURA — Control Center")
        self.window.geometry("880x640")
        self.window.minsize(760, 520)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        # Open in front of other windows, but stay a normal window
        # the user can send behind things (see Settings for topmost).
        self.window.lift()
        self.window.focus_force()

        self._build_header()
        self._build_tabs()
        self._build_today()
        self._build_lists()
        self._build_history()
        self._build_settings()
        self._build_diagnostics()
        self._build_command_box()
        self.show_tab(TABS[0])
        self._animate_core()
        self._tick_telemetry()

    # -- construction -------------------------------------------------------
    def _build_header(self):
        t = self._theme
        header = tk.Frame(self.window, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 4))
        # Animated core: pulsing orb + bars, like the pill's orb.
        self.core_canvas = tk.Canvas(
            header, width=76, height=76, bg=BG, highlightthickness=0)
        self.core_canvas.pack(side="left")
        self.core_orb = self.core_canvas.create_oval(
            18, 18, 58, 58, fill=t["orb_fill"],
            outline=t["accent"], width=2)
        self.core_bars = []
        for i, x in enumerate((26, 34, 42, 50, 58)):
            self.core_bars.append(self.core_canvas.create_line(
                x, 38 - (6 + 4 * (i % 2)), x, 38 + (6 + 4 * (i % 2)),
                fill=t["bars"][i % 2], width=3, capstyle="round"))
        title = tk.Frame(header, bg=BG)
        title.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(title, text="AURA  —  Control Center",
                 fg=TEXT, bg=BG, font=("Segoe UI", 16, "bold"),
                 anchor="w").pack(fill="x")
        self.header_sub = tk.Label(
            title, text=self._header_sub_text(),
            fg=DIM, bg=BG, font=("Segoe UI", 10), anchor="w")
        self.header_sub.pack(fill="x", pady=(2, 0))
        tk.Button(title, text="Close", command=self.close,
                  bg=t["control"], fg=t["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=14, pady=2).pack(
                      anchor="w", pady=(8, 0))

    def _header_sub_text(self):
        return (
            f"Theme: {self._theme_name}  ·  "
            f"Engine: {self.get_engine()}  ·  "
            f"Language: {'Hinglish' if load_language() == 'hi' else 'English'}  ·  "
            f"Wake word: '{display_wake_word(load_wake_word())}'"
        )

    def _build_tabs(self):
        t = self._theme
        bar = tk.Frame(self.window, bg=BG)
        bar.pack(fill="x", padx=16, pady=(8, 0))
        self.tab_buttons = {}
        for name in TABS:
            btn = tk.Button(
                bar, text=name,
                command=lambda n=name: self.show_tab(n),
                bg=t["control"], fg=t["label"],
                activebackground="#1e1e5e", relief="flat", bd=0,
                font=("Segoe UI", 10, "bold"), padx=10, pady=6)
            btn.pack(side="left", padx=(0, 6))
            self.tab_buttons[name] = btn
        self.tab_frames = {}
        for name in TABS:
            frame = tk.Frame(self.window, bg=BG)
            self.tab_frames[name] = frame

    def _section(self, parent, title):
        tk.Label(parent, text=title, fg=self._theme["label"], bg=BG,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(
                     fill="x", pady=(10, 2))

    def _readonly_text(self, parent, height):
        box = tk.Text(parent, height=height, wrap="word",
                      bg=PANEL, fg=TEXT, relief="flat", bd=0,
                      font=("Segoe UI", 11), padx=10, pady=8)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        return box

    def _set_text(self, box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _build_today(self):
        frame = self.tab_frames["Today"]
        self._section(frame, "Today — daily briefing")
        self.today_box = self._readonly_text(frame, 12)
        tk.Button(frame, text="Refresh", command=self._refresh_today,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=12, pady=3).pack(
                      anchor="w", pady=(8, 0))

    def _build_lists(self):
        frame = self.tab_frames["Notes · Todos · Reminders"]
        self._lists = {}
        for key, title, add_label in (
                ("notes", "Notes", "Add note"),
                ("todos", "Todos (high priority first)", "Add todo"),
                ("reminders", "Reminders (not yet fired)", "Cancel selected")):
            self._section(frame, title)
            box = tk.Listbox(frame, height=5, bg=PANEL, fg=TEXT,
                             relief="flat", bd=0, font=("Segoe UI", 10),
                             selectbackground=self._theme["control"])
            box.pack(fill="x")
            self._lists[key] = box
            row = tk.Frame(frame, bg=BG)
            row.pack(fill="x", pady=(2, 0))
            if key in ("notes", "todos"):
                entry = tk.Entry(row, bg=INPUT_BG, fg=TEXT, relief="flat",
                                 bd=0, font=("Segoe UI", 10))
                entry.pack(side="left", fill="x", expand=True, ipady=3)
                if key == "todos":
                    prio = tk.StringVar(value="medium")
                    tk.OptionMenu(row, prio, "high", "medium", "low").pack(
                        side="left", padx=(6, 0))
                    self._todo_prio = prio
                tk.Button(row, text=add_label,
                          command=lambda k=key, e=entry: self._add_item(k, e),
                          bg=self._theme["control"],
                          fg=self._theme["label"],
                          activebackground="#1e1e5e", relief="flat", bd=0,
                          font=("Segoe UI", 9), padx=10).pack(
                              side="left", padx=(6, 0))
                self._lists[key + "_entry"] = entry
            tk.Button(row, text=("Delete selected" if key == "notes"
                                 else "Complete selected" if key == "todos"
                                 else add_label),
                      command=lambda k=key: self._act_on_selected(k),
                      bg=self._theme["control"], fg=self._theme["label"],
                      activebackground="#1e1e5e", relief="flat", bd=0,
                      font=("Segoe UI", 9), padx=10).pack(
                          side="left", padx=(6, 0))

    def _build_history(self):
        frame = self.tab_frames["History"]
        self._section(frame, "Recent conversation (newest first)")
        self.history_box = tk.Listbox(frame, height=14, bg=PANEL, fg=TEXT,
                                      relief="flat", bd=0,
                                      font=("Segoe UI", 10),
                                      selectbackground=self._theme["control"])
        self.history_box.pack(fill="both", expand=True)
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        self.history_search = tk.Entry(row, bg=INPUT_BG, fg=TEXT,
                                       relief="flat", bd=0,
                                       font=("Segoe UI", 10))
        self.history_search.pack(side="left", fill="x", expand=True,
                                 ipady=3)
        self.history_search.bind("<Return>", lambda e: self._search_history())
        tk.Button(row, text="Search",
                  command=self._search_history,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))
        tk.Button(row, text="Show all",
                  command=self._refresh_history,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))
        tk.Button(row, text="Clear history",
                  command=self._clear_history,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))

    def _build_settings(self):
        frame = self.tab_frames["Settings"]
        self._section(frame, "Theme (recolors the pill too)")
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        for name in THEMES:
            tk.Button(row, text=name.capitalize(),
                      command=lambda n=name: self._apply_theme(n),
                      bg=self._theme["control"], fg=self._theme["label"],
                      activebackground="#1e1e5e", relief="flat", bd=0,
                      font=("Segoe UI", 9, "bold"),
                      padx=12, pady=4).pack(side="left", padx=(0, 6))
        self._section(frame, "Wake word")
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self.wake_entry = tk.Entry(row, bg=INPUT_BG, fg=TEXT, relief="flat",
                                   bd=0, font=("Segoe UI", 10))
        self.wake_entry.insert(0, display_wake_word(load_wake_word()))
        self.wake_entry.pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(row, text="Save wake word", command=self._save_wake_word,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))
        self.wake_msg = tk.Label(frame, text="", fg=DIM, bg=BG,
                                 font=("Segoe UI", 9), anchor="w")
        self.wake_msg.pack(fill="x")
        self._section(frame, "Language")
        self.lang_var = tk.StringVar(
            value="hi" if load_language() == "hi" else "en")
        for code, label in (("en", "English"),
                            ("hi", "Hinglish (Hindi mode)")):
            tk.Radiobutton(frame, text=label, variable=self.lang_var,
                           value=code, command=self._save_language,
                           bg=BG, fg=TEXT, selectcolor=PANEL,
                           activebackground=BG, font=("Segoe UI", 10),
                           anchor="w").pack(fill="x")
        self.lang_msg = tk.Label(frame, text="", fg=DIM, bg=BG,
                                 font=("Segoe UI", 9), anchor="w")
        self.lang_msg.pack(fill="x")

        # Phase 10.1: personality modes — five presets as data.
        # A mode only changes tone, verbosity, voice rate and
        # whether replies are spoken; it never changes what AURA
        # is allowed to do. "Aura" is the mode named after AURA
        # itself (the earlier working name "Jarvis" was replaced
        # at Jay's word, 2026-11-17).
        self._section(frame, "Personality")
        self.personality_var = tk.StringVar(value=load_mode())
        for code in ("aura", "professional", "minimal", "friendly",
                     "silent"):
            tk.Radiobutton(frame,
                           text=f"{PRESETS[code]['label']} — "
                           f"{PRESETS[code]['style']}",
                           variable=self.personality_var,
                           value=code,
                           command=self._change_personality,
                           bg=BG, fg=TEXT, selectcolor=PANEL,
                           activebackground=BG, font=("Segoe UI", 10),
                           anchor="w").pack(fill="x")
        self.personality_msg = tk.Label(
            frame, text=self._personality_status_line(),
            fg=DIM, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.personality_msg.pack(fill="x")
        self._section(frame, "Speech engine")
        self.engine_var = tk.StringVar(value=self.get_engine())
        # Phase 8B adds "whisper" — Faster-Whisper on the GPU.
        for code, label in (
                ("offline", "Offline (Vosk — audio stays on this PC)"),
                ("google", "Google (needs internet)"),
                ("whisper",
                 "Whisper (Faster-Whisper — runs on your graphics card)")):
            tk.Radiobutton(frame, text=label, variable=self.engine_var,
                           value=code, command=self._change_engine,
                           bg=BG, fg=TEXT, selectcolor=PANEL,
                           activebackground=BG, font=("Segoe UI", 10),
                           anchor="w").pack(fill="x")
        # Phase 8C: chat fallback — off by default, needs a Groq key.
        self._section(frame, "Chat fallback (Groq)")
        self.chat_var = tk.BooleanVar(value=is_chat_enabled())
        tk.Checkbutton(
            frame,
            text="Chat mode — answer questions AURA has no command "
                 "for (uses Groq)",
            variable=self.chat_var, command=self._change_chat,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, font=("Segoe UI", 10),
            anchor="w").pack(fill="x")
        self.chat_msg = tk.Label(frame, text=self._chat_status_line(),
                                 fg=DIM, bg=BG, font=("Segoe UI", 9),
                                 anchor="w")
        self.chat_msg.pack(fill="x")
        # Phase 9.2A: morning briefing — on by default, spoken once
        # each morning at the time below. The time entry takes
        # "7:30" or "7:30 AM" (bare 1-12 hours read as AM).
        self._section(frame, "Morning briefing")
        self.morning_var = tk.BooleanVar(
            value=is_morning_enabled())
        tk.Checkbutton(
            frame,
            text="Speak the daily briefing every morning",
            variable=self.morning_var, command=self._change_morning,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, font=("Segoe UI", 10),
            anchor="w").pack(fill="x")
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self.morning_entry = tk.Entry(row, bg=INPUT_BG, fg=TEXT,
                                      relief="flat", bd=0,
                                      font=("Segoe UI", 10), width=10)
        self.morning_entry.insert(0, get_morning_time())
        self.morning_entry.pack(side="left", ipady=3)
        tk.Button(row, text="Set time", command=self._save_morning_time,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))
        self.morning_msg = tk.Label(
            frame, text=self._morning_status_line(),
            fg=DIM, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.morning_msg.pack(fill="x")
        # Phase 9.2A: system tray — read-only status. The icon
        # itself is driven from the pill menu / voice ("minimize
        # to tray") and its own menu (Show / Hide / Briefing /
        # Quit); this line just says whether it is up.
        self._section(frame, "System tray")
        self.tray_msg = tk.Label(frame, text=self._tray_status_line(),
                                 fg=DIM, bg=BG, font=("Segoe UI", 9),
                                 anchor="w")
        self.tray_msg.pack(fill="x")
        # Phase 9.2B: global hotkey — on by default, Ctrl+Alt+A.
        # The entry takes "ctrl+alt+a" or "ctrl shift h" (a
        # modifier plus one key — a bare letter is refused, or
        # it would hijack normal typing).
        self._section(frame, "Global hotkey")
        self.hotkey_var = tk.BooleanVar(
            value=is_hotkey_enabled())
        tk.Checkbutton(
            frame,
            text="Open the command box from anywhere on the PC",
            variable=self.hotkey_var, command=self._change_hotkey,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, font=("Segoe UI", 10),
            anchor="w").pack(fill="x")
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self.hotkey_entry = tk.Entry(row, bg=INPUT_BG, fg=TEXT,
                                     relief="flat", bd=0,
                                     font=("Segoe UI", 10), width=16)
        self.hotkey_entry.insert(
            0, format_hotkey_combo(get_hotkey_combo()))
        self.hotkey_entry.pack(side="left", ipady=3)
        tk.Button(row, text="Set hotkey", command=self._save_hotkey_combo,
                  bg=self._theme["control"], fg=self._theme["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10).pack(side="left",
                                                       padx=(6, 0))
        self.hotkey_msg = tk.Label(
            frame, text=self._hotkey_status_line(),
            fg=DIM, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.hotkey_msg.pack(fill="x")
        # Phase 9.2B: Google Calendar — read-only status. The
        # connection itself is a one-time setup on the PC (run
        # calendar_setup.py); this line just says whether it is
        # connected, so a missing calendar is never a surprise.
        self._section(frame, "Google Calendar")
        self.calendar_msg = tk.Label(
            frame, text=self._calendar_status_line(),
            fg=DIM, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.calendar_msg.pack(fill="x")
        self._section(frame, "Window")
        self.topmost_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Keep the Control Center on top",
                       variable=self.topmost_var,
                       command=self._apply_topmost,
                       bg=BG, fg=TEXT, selectcolor=PANEL,
                       activebackground=BG, font=("Segoe UI", 10),
                       anchor="w").pack(fill="x")

    def _build_diagnostics(self):
        frame = self.tab_frames["Diagnostics"]
        self._section(frame, "System — live (refreshes every 2 seconds)")
        self.telemetry_box = self._readonly_text(frame, 5)
        self._section(frame, "AURA — diagnostics")
        self.diag_box = self._readonly_text(frame, 10)

    def _build_command_box(self):
        t = self._theme
        bar = tk.Frame(self.window, bg=BG)
        bar.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(bar, text="Type a command:", fg=DIM, bg=BG,
                 font=("Segoe UI", 9)).pack(side="left")
        self.cmd_entry = tk.Entry(bar, bg=INPUT_BG, fg=TEXT, relief="flat",
                                  bd=0, font=("Segoe UI", 11))
        self.cmd_entry.pack(side="left", fill="x", expand=True,
                            padx=(8, 8), ipady=4)
        self.cmd_entry.bind("<Return>", lambda e: self._send_typed())
        tk.Button(bar, text="Send", command=self._send_typed,
                  bg=t["control"], fg=t["label"],
                  activebackground="#1e1e5e", relief="flat", bd=0,
                  font=("Segoe UI", 10, "bold"), padx=16).pack(side="left")
        self.cmd_reply = tk.Label(self.window, text="", fg=t["label"],
                                  bg=BG, font=("Segoe UI", 10),
                                  anchor="w", wraplength=840,
                                  justify="left")
        self.cmd_reply.pack(fill="x", padx=16, pady=(0, 12))

    # -- tabs ----------------------------------------------------------------
    def show_tab(self, name):
        self._current_tab = name
        for tab, frame in self.tab_frames.items():
            if tab == name:
                frame.pack(fill="both", expand=True, padx=16)
            else:
                frame.pack_forget()
        for tab, btn in self.tab_buttons.items():
            btn.configure(
                bg=self._theme["accent"] if tab == name
                else self._theme["control"],
                fg="white" if tab == name else self._theme["label"])
        self._refresh_tab(name)

    def _refresh_tab(self, name):
        try:
            if name == "Today":
                self._refresh_today()
            elif name == "Notes · Todos · Reminders":
                self._refresh_lists()
            elif name == "History":
                self._refresh_history()
            elif name == "Diagnostics":
                self._refresh_diagnostics()
        except Exception:  # noqa: BLE001 - a stale tab never breaks the window
            pass

    def refresh_all(self):
        """Re-read everything from the memory store."""
        try:
            self.header_sub.configure(text=self._header_sub_text())
            # Phase 8B: a voice-switched engine should show in the
            # Settings radios too, not just the header.
            try:
                self.engine_var.set(self.get_engine())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            # Phase 8C: same for the chat-mode checkbox — a
            # voice/typed toggle must show here without reopening.
            try:
                status = self.get_chat_status()
                self.chat_var.set(status["enabled"])
                self.chat_msg.configure(text=self._chat_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            # Phase 9.2A: same for the morning-briefing checkbox +
            # time, and the tray status line.
            try:
                status = self.get_morning_status()
                self.morning_var.set(status["enabled"])
                self.morning_entry.delete(0, tk.END)
                self.morning_entry.insert(0, status["time"])
                self.morning_msg.configure(
                    text=self._morning_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            try:
                self.tray_msg.configure(text=self._tray_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            # Phase 9.2B: same for the hotkey checkbox + combo
            # and the calendar status line.
            try:
                status = self.get_hotkey_status()
                self.hotkey_var.set(status["enabled"])
                self.hotkey_entry.delete(0, tk.END)
                self.hotkey_entry.insert(
                    0, format_hotkey_combo(status["combo"]))
                self.hotkey_msg.configure(
                    text=self._hotkey_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            try:
                self.calendar_msg.configure(
                    text=self._calendar_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            # Phase 10.1: same for the personality radios, so a
            # voice/typed switch shows here without reopening.
            try:
                status = self.get_personality_status()
                self.personality_var.set(status["mode"])
                self.personality_msg.configure(
                    text=self._personality_status_line())
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
            self._refresh_tab(self._current_tab)
        except Exception:  # noqa: BLE001 - best effort
            pass

    def _refresh_today(self):
        text = build_briefing(self.memory)
        unread = self.memory.unread_notification_count()
        text += f"\n\nUnread notifications: {unread}."
        # Phase 10.1: a live focus session shows here too.
        try:
            fstatus = self.get_focus_status()
            if fstatus["active"]:
                text += f"\n{fstatus['line']}."
        except Exception:  # noqa: BLE001, S110 - Today never breaks
            pass
        self._set_text(self.today_box, text)

    def _refresh_lists(self):
        notes = self._lists["notes"]
        notes.delete(0, "end")
        for i, row in enumerate(self.memory.list_notes(), start=1):
            notes.insert("end", f"{i}. {row['text']}")
        todos = self._lists["todos"]
        todos.delete(0, "end")
        for i, row in enumerate(self.memory.list_todos(), start=1):
            prio = row["priority"] or "medium"
            todos.insert("end", f"{i}. [{prio}] {row['text']}")
        rems = self._lists["reminders"]
        rems.delete(0, "end")
        for i, row in enumerate(self.memory.list_reminders(), start=1):
            rems.insert("end", f"{i}. {row['text']} — {row['remind_at']}")

    def _refresh_history(self):
        self.history_box.delete(0, "end")
        for row in self.memory.recent_turns(limit=20):
            self.history_box.insert(
                "end", f"You: {row['user_text']}")
            self.history_box.insert(
                "end", f"AURA: {row['reply_text']}")

    def _search_history(self):
        query = self.history_search.get().strip()
        self.history_box.delete(0, "end")
        if not query:
            self._refresh_history()
            return
        for row in self.memory.search_turns(query, limit=20):
            self.history_box.insert(
                "end", f"You: {row['user_text']}")
            self.history_box.insert(
                "end", f"AURA: {row['reply_text']}")

    def _clear_history(self):
        self.memory.clear_turns()
        self._refresh_history()

    def _refresh_diagnostics(self):
        self._set_text(self.telemetry_box, "\n".join(telemetry_lines()))
        model = pick_model_dir(MODEL_CANDIDATES)
        hindi_model = pick_model_dir(HINDI_MODEL_CANDIDATES)
        lines = [
            f"Engine: {self.get_engine()}",
            f"Vosk model (English): "
            f"{os.path.basename(model) if model else 'NOT INSTALLED'}",
            f"Vosk model (Hindi): "
            f"{os.path.basename(hindi_model) if hindi_model else 'not installed'}",
        ]
        # Phase 8B: Whisper status (package, model, device, loaded).
        if self.get_whisper_info is not None:
            try:
                info = self.get_whisper_info()
                if not info["installed"]:
                    lines.append(
                        "Whisper: NOT INSTALLED "
                        "(pip install -r requirements.txt)")
                elif info["error"]:
                    lines.append(f"Whisper: error — {info['error']}")
                else:
                    state = (
                        "loaded" if info["loaded"]
                        else "not loaded yet (loads on first use)"
                    )
                    lines.append(
                        f"Whisper: model '{info['model']}', "
                        f"device {info['device']} "
                        f"({info['compute_type']}), {state}")
            except Exception:  # noqa: BLE001 - diagnostics never break
                lines.append("Whisper: status unavailable")
        # Phase 8C: chat fallback status (on/off, key, model).
        try:
            status = self.get_chat_status()
            lines.append(
                f"Chat fallback (Groq): "
                f"{'on' if status['enabled'] else 'off'}, "
                f"key {'set' if status['key_set'] else 'missing'}, "
                f"model {status['model']}")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("Chat fallback (Groq): status unavailable")
        # Phase 9.2A: morning briefing + tray status.
        try:
            status = self.get_morning_status()
            fired = status["last_fired"] or "never"
            lines.append(
                f"Morning briefing: "
                f"{'on' if status['enabled'] else 'off'}, "
                f"at {status['time_display']}, last fired {fired}")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("Morning briefing: status unavailable")
        try:
            tstatus = self.get_tray_status()
            lines.append(
                f"System tray: "
                f"{'available' if tstatus['available'] else 'NOT AVAILABLE'}, "
                f"{'running' if tstatus['running'] else 'not running'}")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("System tray: status unavailable")
        # Phase 9.2B: global hotkey + Google Calendar status.
        try:
            hstatus = self.get_hotkey_status()
            lines.append(
                f"Global hotkey: "
                f"{'on' if hstatus['enabled'] else 'off'}, "
                f"{hstatus['combo_display']}, "
                f"{'available' if hstatus['available'] else 'NOT AVAILABLE'}, "
                f"{'running' if hstatus['running'] else 'not running'}")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("Global hotkey: status unavailable")
        try:
            cstatus = self.get_calendar_status()
            if not cstatus["available"]:
                lines.append(
                    "Google Calendar: NOT AVAILABLE "
                    "(pip install -r requirements.txt)")
            elif not cstatus["configured"]:
                lines.append(
                    "Google Calendar: not connected "
                    "(run calendar_setup.py)")
            else:
                lines.append("Google Calendar: connected")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("Google Calendar: status unavailable")
        # Phase 10.1: shared state + focus status.
        try:
            sstatus = self.get_state_status()
            line = f"State: {sstatus['state']}"
            if sstatus.get("status"):
                line += f" — {sstatus['status']}"
            lines.append(line)
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("State: status unavailable")
        try:
            fstatus = self.get_focus_status()
            if fstatus["active"]:
                lines.append(fstatus["line"])
            else:
                lines.append("Focus: no session running")
        except Exception:  # noqa: BLE001 - diagnostics never break
            lines.append("Focus: status unavailable")
        lines += [
            f"Language: {'Hinglish' if load_language() == 'hi' else 'English'}",
            f"Hindi voice available: {'yes' if has_hindi_voice() else 'no'}",
            f"Wake word: '{display_wake_word(load_wake_word())}'",
            f"Theme: {self._theme_name}",
            f"psutil: {'installed' if psutil is not None else 'NOT INSTALLED'}",
            f"Python: {platform.python_version()}  "
            f"({sys.executable})",
            f"Platform: {platform.platform()}",
        ]
        self._set_text(self.diag_box, "\n".join(lines))

    # -- list actions ---------------------------------------------------------
    def _add_item(self, key, entry):
        text = entry.get().strip()
        if not text:
            return
        if key == "notes":
            self.memory.add_note(text)
        else:
            self.memory.add_todo(text, priority=self._todo_prio.get())
        entry.delete(0, "end")
        self._refresh_lists()

    def _act_on_selected(self, key):
        box = self._lists[key]
        sel = box.curselection()
        if not sel:
            return
        n = sel[0] + 1  # lists are 1-based, like voice commands
        if key == "notes":
            self.memory.delete_note(n)
        elif key == "todos":
            self.memory.complete_todo(n)
        else:
            self.memory.cancel_reminder(n)
        self._refresh_lists()

    # -- settings actions ------------------------------------------------------
    def _apply_theme(self, name):
        try:
            self.on_theme(name)
        except Exception:  # noqa: BLE001 - pill recolor never breaks the window
            pass
        save_theme_name(name)
        self.apply_theme(name)
        self.refresh_all()

    def apply_theme(self, name: str):
        """Recolor the WHOLE window to a named theme — core orb,
        tab bar, every button, accent label and listbox selection
        — so a theme change lands immediately, no reopen needed.
        Thread-safe: the repaint runs on the GUI thread, so a
        voice turn or typed command can call it from a worker
        thread. The state is updated at once so a refresh right
        after already shows the new theme name."""
        if not self._alive or name not in THEMES:
            return
        old_label = self._theme["label"]
        self._theme_name = name
        self._theme = THEMES[name]
        self.window.after(
            0, lambda: self._recolor_now(name, old_label))

    def _recolor_now(self, name, old_label):
        """The actual repaint (runs on the GUI thread). Constants
        (background, panel, text, dim, input fields) never change
        between themes, so only the themed widgets move: the core
        orb + bars, every non-tab button, labels that used the
        old accent colour, and listbox selection colours."""
        if not self._alive:
            return
        t = THEMES[name]
        self.core_canvas.itemconfig(
            self.core_orb, fill=t["orb_fill"], outline=t["accent"])
        for bar, color in zip(
                self.core_bars,
                [t["bars"][i % 2] for i in range(len(self.core_bars))]):
            self.core_canvas.itemconfig(bar, fill=color)
        self.header_sub.configure(text=self._header_sub_text())
        tab_btns = set(self.tab_buttons.values())

        def _walk(widget):
            for child in widget.winfo_children():
                cls = child.winfo_class()
                if cls == "Button" and child not in tab_btns:
                    child.configure(bg=t["control"], fg=t["label"])
                elif cls == "Label":
                    try:
                        if child.cget("fg") == old_label:
                            child.configure(fg=t["label"])
                    except tk.TclError:
                        pass
                elif cls == "Listbox":
                    child.configure(selectbackground=t["control"])
                _walk(child)

        _walk(self.window)
        # Tab bar: the active tab keeps the accent.
        self.show_tab(self._current_tab)

    def _save_wake_word(self):
        word = self.wake_entry.get().strip()
        reason = validate_wake_word(word)
        if reason is not None:
            self.wake_msg.configure(text=reason)
            return
        save_wake_word(word)
        shown = display_wake_word(word)
        self.wake_msg.configure(
            text=f"Wake word changed to '{shown}'.")
        self.header_sub.configure(text=self._header_sub_text())

    def _save_language(self):
        code = self.lang_var.get()
        if code == "hi" and not has_hindi_voice():
            self.lang_msg.configure(
                text="No Hindi voice is installed on this PC — "
                "staying in English.")
            self.lang_var.set("en")
            return
        save_language(code)
        self.lang_msg.configure(
            text="Hinglish mode on." if code == "hi"
            else "English mode on.")
        self.header_sub.configure(text=self._header_sub_text())

    def _change_personality(self):
        """Phase 10.1: the Settings personality radio — persist
        the mode and refresh the status line."""
        try:
            self.on_personality_change(self.personality_var.get())
        except Exception:  # noqa: BLE001 - toggle never breaks the window
            pass
        self.personality_msg.configure(
            text=self._personality_status_line())

    def _personality_status_line(self):
        """Phase 10.1: one honest line about the current mode."""
        try:
            status = self.get_personality_status()
            return status["description"]
        except Exception:  # noqa: BLE001, S110 - status never breaks Settings
            return describe_mode()

    def _change_engine(self):
        self.on_engine_change(self.engine_var.get())
        self.header_sub.configure(text=self._header_sub_text())

    def _chat_status_line(self):
        """One line under the chat checkbox: model + key state."""
        try:
            status = self.get_chat_status()
        except Exception:  # noqa: BLE001 - status never breaks Settings
            status = {"enabled": False, "key_set": False,
                      "model": CHAT_MODEL}
        key = (
            "Groq key: set" if status["key_set"]
            else "Groq key: missing — add GROQ_API_KEY or a "
                 "groq_api_key.txt file next to main.py"
        )
        return f"Model: {status['model']}  ·  {key}"

    def _change_chat(self):
        try:
            self.on_chat_change(self.chat_var.get())
        except Exception:  # noqa: BLE001 - toggle never breaks the window
            pass
        self.chat_msg.configure(text=self._chat_status_line())

    def _morning_status_line(self):
        """One line under the morning-briefing controls: on/off,
        time, and when it last fired."""
        try:
            status = self.get_morning_status()
        except Exception:  # noqa: BLE001 - status never breaks Settings
            status = {"enabled": True, "time": DEFAULT_BRIEFING_TIME,
                      "time_display": "8:00 AM", "last_fired": None}
        if not status["enabled"]:
            return "Morning briefing is off."
        fired = status.get("last_fired")
        fired_note = (f" Last fired {fired}."
                      if fired else " Hasn't fired yet.")
        return (f"On, at {status['time_display']} every morning."
                f"{fired_note}")

    def _change_morning(self):
        try:
            self.on_morning_change(self.morning_var.get())
        except Exception:  # noqa: BLE001 - toggle never breaks the window
            pass
        self.morning_msg.configure(text=self._morning_status_line())

    def _save_morning_time(self):
        raw = self.morning_entry.get().strip()
        parsed = parse_briefing_time(raw)
        if parsed is None:
            self.morning_msg.configure(
                text="That time didn't parse — try 7:30 or 7:30 AM.")
            return
        try:
            set_morning_time(parsed)
        except ValueError:  # noqa: BLE001 - bad time, say so
            self.morning_msg.configure(
                text="That time didn't parse — try 7:30 or 7:30 AM.")
            return
        # Setting a time re-enables the briefing, same as the voice
        # command does — a time with the feature off would be a
        # silent no-op.
        if not is_morning_enabled():
            set_morning_enabled(True)
            self.morning_var.set(True)
        self.morning_entry.delete(0, tk.END)
        self.morning_entry.insert(0, parsed)
        self.morning_msg.configure(text=self._morning_status_line())

    def _tray_status_line(self):
        """One line under the tray section: available / running."""
        try:
            status = self.get_tray_status()
        except Exception:  # noqa: BLE001 - status never breaks Settings
            status = {"available": False, "running": False}
        if not status["available"]:
            return ("Tray icon: not available — "
                    "pip install -r requirements.txt")
        return ("Tray icon: available, "
                f"{'running' if status['running'] else 'not running'}")

    def _hotkey_status_line(self):
        """One line under the hotkey controls: on/off, combo,
        and whether the listener is actually running."""
        try:
            status = self.get_hotkey_status()
        except Exception:  # noqa: BLE001 - status never breaks Settings
            status = {"enabled": True,
                      "combo": DEFAULT_HOTKEY_COMBO,
                      "combo_display": format_hotkey_combo(
                          DEFAULT_HOTKEY_COMBO),
                      "available": False, "running": False}
        if not status["available"]:
            return ("Hotkey: not available — "
                    "pip install -r requirements.txt")
        if not status["enabled"]:
            return "Hotkey is off."
        running = ("listening" if status["running"]
                   else "not listening — restart AURA")
        return (f"On: {status['combo_display']} opens the command "
                f"box. ({running})")

    def _change_hotkey(self):
        try:
            self.on_hotkey_change(self.hotkey_var.get())
        except Exception:  # noqa: BLE001 - toggle never breaks the window
            pass
        self.hotkey_msg.configure(text=self._hotkey_status_line())

    def _save_hotkey_combo(self):
        raw = self.hotkey_entry.get().strip()
        parsed = parse_hotkey_combo(raw)
        if parsed is None:
            self.hotkey_msg.configure(
                text="That hotkey didn't parse — try ctrl+alt+a "
                "(a modifier plus one key).")
            return
        try:
            self.on_hotkey_combo(parsed)
        except ValueError:  # noqa: BLE001 - bad combo, say so
            self.hotkey_msg.configure(
                text="That hotkey didn't parse — try ctrl+alt+a "
                "(a modifier plus one key).")
            return
        except Exception:  # noqa: BLE001 - toggle never breaks the window
            pass
        # Setting a combo re-enables the hotkey, same as the
        # voice command does — a combo with the feature off
        # would be a silent no-op. (main.py's callback does
        # this too; the direct set here covers the fallback
        # path, where the callback only persists the combo.)
        if not is_hotkey_enabled():
            set_hotkey_enabled(True)
            self.hotkey_var.set(True)
        self.hotkey_entry.delete(0, tk.END)
        self.hotkey_entry.insert(0, format_hotkey_combo(parsed))
        self.hotkey_msg.configure(text=self._hotkey_status_line())

    def _calendar_status_line(self):
        """One line under the calendar section: connected or
        what is missing."""
        try:
            status = self.get_calendar_status()
        except Exception:  # noqa: BLE001 - status never breaks Settings
            status = {"available": False, "configured": False,
                      "has_credentials": False, "has_token": False}
        if not status["available"]:
            return ("Calendar: not available — "
                    "pip install -r requirements.txt")
        if not status["has_credentials"]:
            return ("Calendar: not connected — save "
                    "google_credentials.json, then run "
                    "calendar_setup.py")
        if not status["has_token"]:
            return ("Calendar: credentials saved, no login yet — "
                    "run calendar_setup.py")
        return "Calendar: connected — today's events are in the briefing."

    def _apply_topmost(self):
        self.window.attributes("-topmost", self.topmost_var.get())

    # -- typed commands ---------------------------------------------------------
    def _send_typed(self):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self.cmd_entry.delete(0, "end")
        self.cmd_reply.configure(text=f"You: {text}")
        try:
            self.on_typed_command(text)
        except Exception as exc:  # noqa: BLE001 - a bad command never breaks the window
            self.show_typed_reply(f"Something went wrong: {exc}")

    def show_typed_reply(self, text: str):
        """Show a reply under the command box. Thread-safe."""
        if not self._alive:
            return
        self.window.after(
            0, lambda: self.cmd_reply.configure(text=f"AURA: {text}"))

    # -- animation + telemetry loops --------------------------------------------
    def _animate_core(self):
        if not self._alive:
            return
        self._core_phase += 0.35
        pulse = (math.sin(self._core_phase) + 1) / 2  # 0..1
        r = 20 + int(4 * pulse)
        self.core_canvas.coords(self.core_orb, 38 - r, 38 - r, 38 + r, 38 + r)
        for i, bar in enumerate(self.core_bars):
            h = 6 + int(10 * abs(math.sin(self._core_phase + i * 0.9)))
            x = 26 + i * 8
            self.core_canvas.coords(bar, x, 38 - h, x, 38 + h)
        self._core_job = self.window.after(CORE_ANIM_MS, self._animate_core)

    def _tick_telemetry(self):
        if not self._alive:
            return
        if self._current_tab == "Diagnostics":
            self._set_text(self.telemetry_box,
                           "\n".join(telemetry_lines()))
        self._telemetry_job = self.window.after(
            TELEMETRY_INTERVAL_MS, self._tick_telemetry)

    # -- lifecycle ---------------------------------------------------------------
    def raise_window(self):
        try:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        except tk.TclError:
            pass

    def focus_command_box(self):
        """Phase 9.2B: bring the window forward and put the
        cursor in the typed-command box — this is what the
        global hotkey does. Thread-safe: the focus runs on the
        GUI thread. The command box sits at the bottom of
        every tab, so no tab switch is needed."""
        if not self._alive:
            return
        try:
            self.window.after(0, self._focus_command_box_now)
        except tk.TclError:
            pass

    def _focus_command_box_now(self):
        try:
            self.raise_window()
            self.cmd_entry.focus_set()
        except tk.TclError:
            pass

    def close(self):
        if not self._alive:
            return
        self._alive = False
        for job in (self._core_job, self._telemetry_job):
            try:
                if job is not None:
                    self.window.after_cancel(job)
            except Exception:  # noqa: BLE001, S110 - window may be gone
                pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:  # noqa: BLE001, S110 - close is best effort
                pass
