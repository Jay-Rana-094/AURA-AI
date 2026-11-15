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
        # Telemetry live-tick writes into the box.
        cc._tick_telemetry()
        root.update()
        tele = cc.telemetry_box.get("1.0", "end")
        assert tele.strip(), tele
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
    finally:
        cc.close()
        assert not cc._alive
        root.destroy()
    print("All control-center tests passed.")


if __name__ == "__main__":
    main()
