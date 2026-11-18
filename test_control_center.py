"""Tests for Phase 8A — Control Center window.

Telemetry and brain routing need no window; the window tests
build the real Control Center and skip themselves when no
display is available (headless CI / this Linux VM).

    python test_control_center.py
"""

import os
import tempfile
import tkinter as tk

from aura.brain import (
    handle,
    pop_gui_action,
    set_custom_store,
    set_memory,
)
from aura.chat import (
    CHAT_MODEL,
    is_chat_enabled,
    set_chat_enabled,
)
from aura.chat import set_key_file_path as set_chat_key_file_path
from aura.chat import set_settings_path as set_chat_settings_path
from aura.commands.custom import CustomStore
from aura.control_center import ControlCenter, format_telemetry, get_telemetry
from aura.memory import Memory
from aura.morning import (
    get_morning_time,
    is_morning_enabled,
    set_morning_enabled,
)
from aura.morning import set_settings_path as set_morning_settings_path
from aura.hotkey import (
    get_hotkey_combo,
    is_hotkey_enabled,
    set_hotkey_enabled,
)
from aura.hotkey import set_settings_path as set_hotkey_settings_path
from aura.personality import load_mode, save_mode
from aura.personality import set_settings_path as set_personality_settings_path
from aura.theme import THEMES, set_settings_path


def _display_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


def main():
    tmp = tempfile.mkdtemp()
    # Keep settings out of the real folder: the window test applies
    # themes, which persist the choice.
    set_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_key_file_path(os.path.join(tmp, "groq_api_key.txt"))
    # Phase 9.2A: the morning briefing reads the same temp file
    # (different keys), so the real aura_settings.json is untouched.
    set_morning_settings_path(os.path.join(tmp, "settings.json"))
    # Phase 9.2B: the hotkey reads the same temp file too.
    set_hotkey_settings_path(os.path.join(tmp, "settings.json"))
    # Phase 10.1: the personality mode reads the same temp
    # file too (different key), so the real settings stay put.
    set_personality_settings_path(os.path.join(tmp, "settings.json"))
    # Phase 9.2B: fake pynput so the hotkey reads as available
    # (this VM has no pynput — the listener itself is main.py's
    # job and is never started here, so it stays "not running").
    import sys as _sys
    import types as _types
    _pynput_stub = _types.ModuleType("pynput")
    _kb_stub = _types.ModuleType("pynput.keyboard")
    _kb_stub.GlobalHotKeys = object
    _pynput_stub.keyboard = _kb_stub
    _sys.modules["pynput"] = _pynput_stub
    _sys.modules["pynput.keyboard"] = _kb_stub
    from aura.hotkey import _reset_cache as _reset_hotkey_cache
    _reset_hotkey_cache()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Telemetry: shape is stable with or without psutil. --------
    stats = get_telemetry()
    assert isinstance(stats, dict) and "available" in stats, stats
    lines = format_telemetry(stats)
    assert isinstance(lines, list) and len(lines) >= 1, lines
    if stats["available"]:
        assert any(line.startswith("CPU:") for line in lines), lines
        assert any(line.startswith("RAM:") for line in lines), lines
        assert any(line.startswith("Disk:") for line in lines), lines
        assert stats["cpu_count"] >= 1, stats
        assert 0 <= stats["ram_percent"] <= 100, stats
    else:
        assert "psutil" in lines[0], lines

    # --- GPU (Phase 9.1): same honesty, one shared line set. -----
    import sys
    import types
    from aura.control_center import telemetry_lines

    class _FakeGPU:
        name = "NVIDIA GeForce RTX 3050 6GB Laptop GPU"
        load = 0.23
        memoryUsed = 1536
        memoryTotal = 6144
        temperature = 54

    stub = types.ModuleType("GPUtil")
    stub.getGPUs = lambda: [_FakeGPU()]
    sys.modules["GPUtil"] = stub
    try:
        lines = telemetry_lines()
        assert any(line.startswith("GPU:") for line in lines), lines
        assert any("23%" in line for line in lines), lines
        assert any("1.5 GB of 6.0 GB" in line for line in lines), lines
        assert any("54" in line for line in lines), lines
    finally:
        sys.modules.pop("GPUtil", None)
    # Without GPUtil the GPU half degrades but the rest stays.
    lines = telemetry_lines()
    assert any(line.startswith("GPU:") for line in lines), lines
    assert any("GPUtil" in line for line in lines), lines
    if stats["available"]:
        assert any(line.startswith("CPU:") for line in lines), lines

    # --- Voice routing: open / close, and custom phrases win. -----
    assert pop_gui_action() is None
    reply, quit_ = handle("open control center")
    assert "Control Center" in reply and not quit_, reply
    assert pop_gui_action() == "open_control_center"
    assert pop_gui_action() is None  # cleared after one pop
    reply, _ = handle("show the control center")
    assert pop_gui_action() == "open_control_center"
    reply, _ = handle("close control center")
    assert "Control Center" in reply, reply
    assert pop_gui_action() == "close_control_center"
    reply, _ = handle("hide the control center")
    assert pop_gui_action() == "close_control_center"
    # A taught phrase with the same words still wins (Phases 1-7
    # rule: custom phrases beat built-ins).
    set_custom_store(CustomStore(os.path.join(tmp, "custom2.json")))
    reply, _ = handle("teach aura open control center means what is the time")
    assert "Got it" in reply, reply
    reply, _ = handle("open control center")
    assert "It's" in reply, reply
    assert pop_gui_action() is None  # the custom phrase ran, not the window
    # Unrelated commands leave the action alone.
    reply, _ = handle("what is the time")
    assert pop_gui_action() is None
    assert "control center" in handle("help")[0].lower()

    if not _display_available():
        print("All control-center tests passed "
              "(window tests skipped: no display).")
        return

    # --- Window: builds, tabs switch, lists act, theme applies. ----
    root = tk.Tk()
    root.withdraw()

    # Pill double-click: the binding exists, and a stationary
    # double-click fires the callback (a moved pill does not).
    from aura.gui import IslandGUI
    opened_pill = {"n": 0}
    pill = IslandGUI(
        on_mic=lambda: None,
        on_engine_change=lambda e: None,
        on_control_center=lambda: opened_pill.__setitem__("n", 1),
    )
    try:
        assert pill.canvas.bind("<Double-Button-1>"), (
            "no double-click binding on the pill")
        pill.root.update_idletasks()
        pill._control_center_open()
        assert opened_pill["n"] == 1
        # Simulate a drag: press position recorded, pill then moved
        # -> the double-click must NOT open the window.
        opened_pill["n"] = 0
        pill._press_root_x = pill.root.winfo_x() + 50
        pill._control_center_open()
        assert opened_pill["n"] == 0
    finally:
        pill.close()

    mem = Memory(":memory:")
    mem.add_note("buy milk")
    mem.add_todo("finish report", priority="high")
    mem.add_todo("water plants", priority="low")
    mem.add_turn("hello", "Hey! I'm AURA.")
    opened = {"n": 0}

    cc = ControlCenter(
        root, mem,
        on_typed_command=lambda text: opened.__setitem__("n", 1),
        on_theme=lambda name: None,
        on_engine_change=lambda engine: None,
        get_engine=lambda: "offline",
        on_close=lambda: None,
        # Phase 10.1: injected live state + focus, so the
        # Diagnostics / Today lines are tested without main.py.
        get_state_status=lambda: {"state": "SPEAKING",
                                  "status": "Speaking..."},
        get_focus_status=lambda: {"active": True, "status": "focus",
                                  "line": "Focus: 15 minutes left "
                                          "(Coding)",
                                  "on_break": False},
    )
    try:
        assert cc.window.winfo_exists()
        assert cc.window.title() == "AURA — Control Center"
        # Today tab shows the briefing + todo.
        today = cc.today_box.get("1.0", "end")
        assert "finish report" in today, today
        # Lists tab: notes/todos render, add + complete work.
        cc.show_tab("Notes · Todos · Reminders")
        assert cc._lists["notes"].size() == 1
        assert cc._lists["todos"].size() == 2
        cc._lists["todos"].selection_set(0)
        cc._act_on_selected("todos")
        assert cc._lists["todos"].size() == 1
        assert mem.list_todos()[0]["text"] == "water plants"
        # History tab shows the turn.
        cc.show_tab("History")
        hist = cc.history_box.get(0, "end")
        assert any("hello" in line for line in hist), hist
        # Settings tab: theme applies and persists the name — and
        # the WHOLE open window follows at once (no reopen needed).
        cc.show_tab("Settings")
        cc._apply_theme("emerald")
        root.update()  # apply_theme() repaints via after(0)
        assert cc._theme_name == "emerald"
        assert cc.core_canvas.itemcget(
            cc.core_orb, "fill") == THEMES["emerald"]["orb_fill"]
        assert cc.core_canvas.itemcget(
            cc.core_orb, "outline") == THEMES["emerald"]["accent"]
        assert cc.cmd_reply.cget("fg") == THEMES["emerald"]["label"]
        assert cc.tab_buttons["Settings"].cget(
            "bg") == THEMES["emerald"]["accent"]
        assert cc._lists["notes"].cget(
            "selectbackground") == THEMES["emerald"]["control"]
        control_btns = []

        def _walk(widget):
            for child in widget.winfo_children():
                if (child.winfo_class() == "Button"
                        and child not in cc.tab_buttons.values()):
                    control_btns.append(child)
                _walk(child)

        _walk(cc.window)
        assert control_btns, "no control buttons found to recolor"
        assert all(
            b.cget("bg") == THEMES["emerald"]["control"]
            for b in control_btns
        ), [b.cget("bg") for b in control_btns]
        # A second theme switch recolors again, from the new colours.
        cc._apply_theme("rose")
        root.update()
        assert cc.core_canvas.itemcget(
            cc.core_orb, "fill") == THEMES["rose"]["orb_fill"]
        assert cc.cmd_reply.cget("fg") == THEMES["rose"]["label"]
        # Typed command box forwards the text.
        cc.cmd_entry.insert(0, "what is the time")
        cc._send_typed()
        assert opened["n"] == 1
        cc.show_typed_reply("It's 10:00 AM.")
        root.update()  # after(0) callbacks need a real update, not just idletasks
        assert "10:00" in cc.cmd_reply.cget("text")
        # Diagnostics tab renders without psutil, too.
        cc.show_tab("Diagnostics")
        diag = cc.diag_box.get("1.0", "end")
        assert "Engine: offline" in diag, diag
        assert f"Theme: {cc._theme_name}" in diag, diag
        # Telemetry live-tick writes into the box — CPU lines
        # plus the Phase 9.1 GPU lines (or the honest
        # "not installed" line when GPUtil is missing here).
        cc._tick_telemetry()
        root.update()
        tele = cc.telemetry_box.get("1.0", "end")
        assert tele.strip(), tele
        assert "GPU:" in tele, tele
        # Engine switch from elsewhere (voice / pill menu / typed
        # command): refresh follows it — the Settings radio and
        # header must show the new engine without reopening the
        # window (8B v4 fix). Before, only the pill menu synced.
        cc.get_engine = lambda: "whisper"
        cc.refresh_all()
        root.update()
        assert cc.engine_var.get() == "whisper"
        assert "Engine: whisper" in cc.header_sub.cget("text")
        cc.show_tab("Diagnostics")
        diag = cc.diag_box.get("1.0", "end")
        assert "Engine: whisper" in diag, diag
        # Chat fallback (Phase 8C): checkbox follows the flag (ON
        # by default), the status line names the model + key
        # state, and a voice toggle refreshes it without
        # reopening — same pattern as the engine radio (8B v4).
        assert cc.chat_var.get() is True, "chat is ON by default"
        assert CHAT_MODEL in cc.chat_msg.cget("text")
        assert "missing" in cc.chat_msg.cget("text")
        cc.chat_var.set(False)
        cc._change_chat()
        assert is_chat_enabled() is False
        set_chat_enabled(True)
        cc.refresh_all()
        root.update()
        assert cc.chat_var.get() is True
        cc.show_tab("Diagnostics")
        diag = cc.diag_box.get("1.0", "end")
        assert "Chat fallback (Groq): on, key missing" in diag, diag
        # Morning briefing (Phase 9.2A): checkbox follows the flag
        # (ON by default), the status line names the time, the time
        # entry saves (and re-enables when off), and a voice toggle
        # refreshes it without reopening — same pattern as chat.
        cc.show_tab("Settings")
        assert cc.morning_var.get() is True, "briefing is ON by default"
        assert "8:00 AM" in cc.morning_msg.cget("text")
        assert cc.morning_entry.get() == "08:00"
        cc.morning_var.set(False)
        cc._change_morning()
        assert is_morning_enabled() is False
        assert "off" in cc.morning_msg.cget("text")
        cc.morning_entry.delete(0, "end")
        cc.morning_entry.insert(0, "7:30")
        cc._save_morning_time()
        assert get_morning_time() == "07:30"
        assert is_morning_enabled() is True, "setting a time re-enables"
        assert cc.morning_var.get() is True
        assert "7:30 AM" in cc.morning_msg.cget("text")
        cc.morning_entry.delete(0, "end")
        cc.morning_entry.insert(0, "nonsense")
        cc._save_morning_time()
        assert "didn't parse" in cc.morning_msg.cget("text")
        assert get_morning_time() == "07:30", "bad time must not save"
        set_morning_enabled(False)
        cc.refresh_all()
        root.update()
        assert cc.morning_var.get() is False
        set_morning_enabled(True)
        cc.refresh_all()
        root.update()
        assert cc.morning_var.get() is True
        # System tray (Phase 9.2A): this VM has no pystray, so the
        # status line says so honestly instead of pretending.
        assert "not available" in cc.tray_msg.cget("text")
        # Global hotkey (Phase 9.2B): checkbox follows the flag
        # (ON by default), the combo entry saves (and re-enables
        # when off), a bad combo is refused, and a direct flag
        # change refreshes without reopening — same pattern as
        # the morning briefing.
        cc.show_tab("Settings")
        assert cc.hotkey_var.get() is True, "hotkey is ON by default"
        assert "Ctrl+Alt+A" in cc.hotkey_msg.cget("text")
        assert cc.hotkey_entry.get() == "Ctrl+Alt+A"
        cc.hotkey_var.set(False)
        cc._change_hotkey()
        assert is_hotkey_enabled() is False
        assert "off" in cc.hotkey_msg.cget("text")
        cc.hotkey_entry.delete(0, "end")
        cc.hotkey_entry.insert(0, "ctrl shift h")
        cc._save_hotkey_combo()
        assert get_hotkey_combo() == "<ctrl>+<shift>+h"
        assert is_hotkey_enabled() is True, "setting a combo re-enables"
        assert cc.hotkey_var.get() is True
        assert "Ctrl+Shift+H" in cc.hotkey_msg.cget("text")
        cc.hotkey_entry.delete(0, "end")
        cc.hotkey_entry.insert(0, "banana")
        cc._save_hotkey_combo()
        assert "didn't parse" in cc.hotkey_msg.cget("text")
        assert get_hotkey_combo() == "<ctrl>+<shift>+h", \
            "bad combo must not save"
        set_hotkey_enabled(False)
        cc.refresh_all()
        root.update()
        assert cc.hotkey_var.get() is False
        set_hotkey_enabled(True)
        cc.refresh_all()
        root.update()
        assert cc.hotkey_var.get() is True
        # Google Calendar (Phase 9.2B): no credentials file on
        # this VM, so the status line says so honestly — either
        # "not connected" (libraries present) or "not
        # available" (libraries missing), never "connected".
        cal_text = cc.calendar_msg.cget("text")
        assert ("not connected" in cal_text
                or "not available" in cal_text), cal_text
        # Personality modes (Phase 10.1): the radio follows the
        # saved mode (Friendly by default), a click persists it
        # and refreshes the status line, and a voice/typed switch
        # refreshes the radio without reopening — same pattern
        # as chat / the morning briefing.
        cc.show_tab("Settings")
        assert cc.personality_var.get() == "friendly", \
            "Friendly is the default mode"
        assert "Friendly" in cc.personality_msg.cget("text")
        cc.personality_var.set("aura")
        cc._change_personality()
        assert load_mode() == "aura"
        assert "Aura" in cc.personality_msg.cget("text")
        save_mode("silent")
        cc.refresh_all()
        root.update()
        assert cc.personality_var.get() == "silent"
        assert "no spoken replies" in cc.personality_msg.cget("text")
        save_mode("friendly")
        cc.refresh_all()
        root.update()
        assert cc.personality_var.get() == "friendly"
        # Diagnostics (Phase 10.1): the shared state and the
        # live focus session show here, and the Today tab names
        # the session too.
        cc.show_tab("Diagnostics")
        diag = cc.diag_box.get("1.0", "end")
        assert "State: SPEAKING — Speaking..." in diag, diag
        assert "Focus: 15 minutes left (Coding)" in diag, diag
        cc.show_tab("Today")
        today = cc.today_box.get("1.0", "end")
        assert "Focus: 15 minutes left (Coding)" in today, today
        # The hotkey's focus helper puts the cursor in the
        # typed-command box (this is what Ctrl+Alt+A does).
        cc.focus_command_box()
        root.update()
        assert cc.cmd_entry.focus_get() == cc.cmd_entry, \
            "command box did not take focus"
        cc.show_tab("Diagnostics")
        diag = cc.diag_box.get("1.0", "end")
        assert "Morning briefing: on, at 7:30 AM" in diag, diag
        assert "last fired never" in diag, diag
        assert "System tray: NOT AVAILABLE" in diag, diag
        assert "Global hotkey: on, Ctrl+Shift+H, available, not running" in diag, diag
        assert ("Google Calendar: not connected" in diag
                or "Google Calendar: NOT AVAILABLE" in diag), diag
    finally:
        cc.close()
        assert not cc._alive
        root.destroy()
    print("All control-center tests passed.")


if __name__ == "__main__":
    main()
