"""AURA AI — Phase 5 entry point (with custom wake word + memory + custom).

Two ways to talk to AURA:
  - Tap the mic button: one command, as before.
  - Tap the 👂 button: wake-word mode. AURA listens continuously
    (offline Vosk only — audio never leaves the PC) for the wake
    word (default "Aura"; say "change my wake word to..." to pick
    another). Say the wake word, then your command; afterwards it
    goes back to waiting. Tap 👂 again to switch it off.

One mic lock serializes the wake stream and command listens so they
never fight over the microphone. Voice work always runs on worker
threads so the pill never freezes, and every turn ends in
try/finally so the pill always returns to a usable state.

Phase 5 barge-in: while AURA speaks, say the wake word (or tap the
mic) to cut it off and give a new command. Voice barging listens
with the offline engine only, and it is skipped for replies that
contain the wake word themselves — otherwise AURA's own speech
would trigger it.

Barge-in fix (2026-11-17): typed commands also cut speech — a typed
command stops in-progress speech first, and typed replies speak
through the same barge listener as voice turns, so the wake word
or "stop" cuts them mid-reply too (a barged typed reply just stops;
it never starts a voice turn). See aura/barge.py.

Phase 8A: double-click the pill (or say "open control center") to
open the Control Center window — today's briefing, notes/todos/
reminders, history, settings, diagnostics, and a typed-command
box that runs through the same brain as a voice turn.

Run with: python main.py  (or run.bat on Windows)
"""

import os
import threading
import time
from datetime import datetime

from aura.barge import speak_with_barge
from aura.brain import (
    confirmation_pending,
    get_focus_manager,
    get_memory,
    handle,
    pop_gui_action,
)
from aura.calendar import calendar_status
from aura.chat import chat_status, set_chat_enabled
from aura.commands.briefing import build_briefing
from aura.control_center import ControlCenter
from aura.focus import FocusManager
from aura.gui import IslandGUI
from aura.hotkey import (
    Hotkey,
    format_hotkey_combo,
    get_hotkey_combo,
    hotkey_available,
    is_hotkey_enabled,
    set_hotkey_combo,
    set_hotkey_enabled,
)
from aura.language import load_language
from aura.listener import Listener
from aura.models import MODEL_CANDIDATES, pick_model_dir
from aura.morning import (
    get_last_fired,
    get_morning_time,
    is_morning_enabled,
    mark_fired,
    morning_status,
    set_morning_enabled,
    should_fire,
)
from aura.personality import (
    describe_mode,
    format_reply,
    is_silent,
    load_mode,
    personality_status,
    save_mode,
    voice_rate,
)
from aura.speaker import Speaker
from aura.state_manager import StateManager
from aura.theme import load_theme_name, save_theme_name
from aura.tray import TrayIcon, tray_available
from aura.wake_settings import display_wake_word, load_wake_word


def main():
    listener = Listener(engine="offline")
    speaker = Speaker()
    gui_ref: dict = {}

    # Mic ownership: the wake stream holds this while waiting, and a
    # command turn holds it while listening. Speaking never holds it.
    mic_lock = threading.Lock()

    wake_enabled = {"on": False}
    wake_stop = threading.Event()
    turn_active = threading.Event()
    # Phase 8A: the Control Center window (None until opened) and
    # the engine name its Settings tab shows.
    control_center = {"win": None}
    current_engine = {"name": "offline"}
    # Phase 9.2A: when AURA started (the morning scheduler skips a
    # day when AURA started after the briefing time), and the tray
    # icon holder (None until started — see the bottom of main()).
    started_at = {"at": datetime.now()}
    tray_icon = {"obj": None}
    # Phase 9.2B: the global-hotkey listener holder (None until
    # started — same shape as the tray holder).
    hotkey = {"obj": None}
    # Turn generations: a mic tap during speech starts a newer turn,
    # and only the newest turn may reset the pill state or clear
    # turn_active when it finishes.
    turn_gen = {"n": 0}
    # Phase 10.1: the shared state manager — the pill, voice turns
    # and typed commands publish here; later features (avatar,
    # gestures, meeting capture) read it instead of tracking their
    # own state. It never raises into a turn (see _publish_state).
    state_manager = StateManager()

    def _wake_prompt():
        """Pill text for wake mode, using the current custom word."""
        return f"Say '{display_wake_word(load_wake_word())}'..."

    # Phase 10.1: pill display states -> canonical bus states.
    # "wake" is a pill rendering of IDLE (waiting for the wake
    # word), so the bus carries it as IDLE plus the pill state.
    _PILL_TO_STATE = {
        "listening": "LISTENING",
        "thinking": "THINKING",
        "speaking": "SPEAKING",
        "error": "ERROR",
        "idle": "IDLE",
        "wake": "IDLE",
    }

    def _publish_state(state, status=None, pill_state=None):
        """Publish to the shared StateManager. Never raises — a
        state failure must never break a turn."""
        try:
            state_manager.set_state(
                state, status=status, pill_state=pill_state)
        except Exception:  # noqa: BLE001, S110 - bus never breaks a turn
            pass

    def _on_pill_state(state, status):
        """Phase 10.1: the pill changed state (gui.py's on_state
        callback) — publish the mapped canonical state."""
        _publish_state(_PILL_TO_STATE.get(state, "IDLE"),
                       status=status, pill_state=state)

    def _log_notification(text: str):
        """Phase 10.1: log a notification — or hold it while a
        focus session is running (held entries return to the log
        when the session ends). Never raises."""
        try:
            focus = get_focus_manager()
            if focus.active:
                focus.hold_notification(text)
                return
            get_memory().add_notification(text)
        except Exception:  # noqa: BLE001, S110 - log is best effort
            pass

    def _speak_with_barge(reply: str) -> bool:
        """Speak ``reply`` with voice barge-in (see aura/barge.py).

        Thin adapter over the shared helper: the voice turn loops
        back to listen when this returns True; the typed command
        just stops (see run_typed_command).
        """
        return speak_with_barge(
            speaker, listener, mic_lock, reply, load_wake_word()
        )

    def open_control_center():
        """Phase 8A: open the Control Center, or raise it if it is
        already open. Runs on the GUI thread (double-click, or
        scheduled with after() from a voice turn)."""
        win = control_center["win"]
        if win is not None and win._alive:
            win.raise_window()
            win.refresh_all()
            return
        cc = ControlCenter(
            gui_ref["gui"].root,
            get_memory(),
            on_typed_command=run_typed_command,
            on_theme=lambda name: (
                save_theme_name(name),
                gui_ref["gui"].set_theme(name),
            ),
            on_engine_change=on_engine_change,
            get_engine=lambda: current_engine["name"],
            get_whisper_info=listener.whisper_info,
            on_chat_change=on_chat_change,
            get_chat_status=chat_status,
            on_morning_change=on_morning_change,
            get_morning_status=morning_status,
            get_tray_status=_tray_status,
            on_hotkey_change=on_hotkey_change,
            get_hotkey_status=_get_hotkey_status,
            on_hotkey_combo=on_hotkey_combo,
            get_calendar_status=calendar_status,
            on_personality_change=on_personality_change,
            get_personality_status=personality_status,
            get_state_status=_get_state_status,
            get_focus_status=_get_focus_status,
            on_close=lambda: control_center.__setitem__("win", None),
        )
        control_center["win"] = cc

    def close_control_center():
        """Phase 8A: close the Control Center if it is open."""
        win = control_center["win"]
        if win is not None:
            win.close()

    def _apply_gui_action():
        """Phase 8A: a voice/typed command asked for the Control
        Center — open or close it on the GUI thread. Phase 8B:
        an engine switch — hand it to on_engine_change, which
        switches the listener, syncs the pill menu and updates
        the status line. Phase 9.2A: a morning-briefing toggle —
        refresh the open Control Center like chat mode; a tray
        hide/show — hide or bring back the pill on the GUI
        thread."""
        action = pop_gui_action()
        if action == "open_control_center":
            gui_ref["gui"].root.after(0, open_control_center)
        elif action == "close_control_center":
            gui_ref["gui"].root.after(0, close_control_center)
        elif action is not None and action.startswith("engine_"):
            on_engine_change(action[len("engine_"):])
        elif action == "chat_refresh":
            # Phase 8C: a voice/typed chat-mode toggle — the open
            # Control Center's checkbox must follow, like the
            # engine radio did in 8B v4.
            win = control_center["win"]
            if win is not None and win._alive:
                try:
                    gui_ref["gui"].root.after(0, win.refresh_all)
                except Exception:  # noqa: BLE001, S110 - window may be closed
                    pass
        elif action == "morning_refresh":
            # Phase 9.2A: same as chat_refresh, for the morning
            # briefing checkbox + time.
            win = control_center["win"]
            if win is not None and win._alive:
                try:
                    gui_ref["gui"].root.after(0, win.refresh_all)
                except Exception:  # noqa: BLE001, S110 - window may be closed
                    pass
        elif action == "personality_refresh":
            # Phase 10.1: same as chat_refresh, for the personality
            # radios — a voice/typed switch must show here without
            # reopening the window.
            win = control_center["win"]
            if win is not None and win._alive:
                try:
                    gui_ref["gui"].root.after(0, win.refresh_all)
                except Exception:  # noqa: BLE001, S110 - window may be closed
                    pass
        elif action == "tray_hide":
            # Phase 9.2A: hide the pill in the tray. Guard: if the
            # icon never actually started (backend refused), do
            # NOT hide — the pill would vanish with no way back
            # except voice. The brain already refused the hide
            # when pystray is not installed at all; this covers
            # the rarer start-time failure.
            obj = tray_icon["obj"]
            if obj is not None and obj.running:
                gui_ref["gui"].root.after(0, _hide_pill)
            else:
                try:
                    gui = gui_ref["gui"]
                    gui.set_state(
                        "error",
                        "Tray icon isn't running — pill staying visible")
                    gui.show_transcript(
                        "AURA: The tray icon isn't running, so the "
                        "pill is staying visible.")
                except Exception:  # noqa: BLE001, S110 - window may be closed
                    pass
        elif action == "tray_show":
            gui_ref["gui"].root.after(0, _show_pill)
        elif action == "hotkey_apply":
            # Phase 9.2B: a voice/typed hotkey toggle or combo
            # change — (re)bind the listener to the current
            # settings, then refresh the open Control Center so
            # its checkbox and combo box follow (same pattern as
            # morning_refresh above).
            _apply_hotkey_settings()
            win = control_center["win"]
            if win is not None and win._alive:
                try:
                    gui_ref["gui"].root.after(0, win.refresh_all)
                except Exception:  # noqa: BLE001, S110 - window may be closed
                    pass

    def run_typed_command(text: str):
        """Phase 8A: a command typed in the Control Center. Same
        brain as a voice turn — the reply is shown in the window
        and spoken aloud. Runs on a worker thread."""
        def _run():
            # Barge-in fix (2026-11-17): a typed command cuts any
            # speech in progress first — exactly like the mic tap
            # does. Without this, the new reply queued behind the
            # old speech and the old reply played to the end.
            speaker.stop()
            gui = gui_ref["gui"]
            lang = load_language()
            listener.set_language(lang)
            speaker.set_language(lang)
            # Phase 10.1: the personality mode's voice rate.
            speaker.set_rate(voice_rate())
            # Phase 10.1: this turn is executing a command.
            _publish_state("EXECUTING")
            # A brain failure surfaces as a reply, never as a silent
            # dead thread: typed commands used to vanish with no
            # response at all when handle() raised.
            failed = False
            try:
                reply, should_quit = handle(text)
            except Exception as exc:  # noqa: BLE001 - surfaced as a reply
                reply, should_quit = f"Something went wrong: {exc}", False
                failed = True
            # Phase 10.1: the personality mode formats the reply
            # (tone + verbosity) before it is shown or spoken, so
            # the transcript, the history and the voice all agree.
            reply = format_reply(reply)
            _apply_gui_action()
            try:
                gui.set_theme(load_theme_name())
            except Exception:  # noqa: BLE001, S110 - theme never breaks a turn
                pass
            _recolor_control_center()
            try:
                get_memory().add_turn(text, reply)
            except Exception:  # noqa: BLE001, S110 - history is best effort
                pass
            gui.show_transcript(f"AURA: {reply}")
            win = control_center["win"]
            if win is not None and win._alive:
                win.show_typed_reply(reply)
            # Barge-in fix (2026-11-17): typed replies speak
            # through the same barge listener as voice turns, so
            # the wake word or "stop" cuts them mid-reply. A
            # barged typed reply just stops — there is no voice
            # turn to loop back into, and a barged goodbye must
            # not quit AURA, so should_quit is skipped then.
            # Phase 10.1: Silent mode speaks nothing at all.
            if is_silent():
                barged = False
            else:
                gui.set_state("speaking", "Speaking...")
                barged = _speak_with_barge(reply)
            if should_quit and not barged:
                _shutdown()
                return
            # Phase 10.1: a finished turn pulses SUCCESS, then
            # the pill reset below publishes IDLE — and when the
            # reply asked "are you sure?", the bus ends at
            # WAITING_CONFIRMATION so later features can see it.
            if not failed:
                _publish_state("SUCCESS", status="Done")
            try:
                if wake_enabled["on"]:
                    gui.set_state("wake", _wake_prompt())
                else:
                    gui.set_state("idle", "AURA — tap the mic and speak")
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass
            if confirmation_pending():
                _publish_state(
                    "WAITING_CONFIRMATION",
                    status="Waiting for your yes or no...",
                )

        threading.Thread(target=_run, daemon=True).start()

    def _recolor_control_center():
        """Phase 8A: after a theme change (voice or typed), recolor
        the open Control Center window too, so it follows the pill
        live. apply_theme() is thread-safe."""
        win = control_center["win"]
        if win is not None and win._alive:
            try:
                win.apply_theme(load_theme_name())
            except Exception:  # noqa: BLE001, S110 - theme never breaks a turn
                pass

    def _voice_turn():
        """Listen -> brain -> speak, looping on a voice barge-in.

        If the user says the wake word while AURA speaks, speech
        stops and the turn loops back to listen for the follow-up
        command. Runs on a worker thread.
        """
        gui = gui_ref["gui"]
        turn_gen["n"] += 1
        my_gen = turn_gen["n"]
        turn_active.set()
        # Phase 8B v2: did this turn end in a failure? A failed turn
        # keeps its error on the pill — the old finally block reset
        # every turn to idle, so listen errors flashed and vanished
        # and a dead mic looked like silence.
        failed = False
        try:
            while True:
                failed = False
                # Phase 7: listen and speak in the saved language.
                # Read fresh each turn so a voice switch ("speak
                # Hindi") takes effect on the very next turn.
                lang = load_language()
                listener.set_language(lang)
                speaker.set_language(lang)
                # Phase 10.1: the personality mode's voice rate.
                speaker.set_rate(voice_rate())
                # Phase 8B v2: load the model BEFORE showing
                # "Listening...". The old code set "Loading..." and
                # then overwrote it at once, so the minutes-long
                # first download looked like a dead mic — and speech
                # during it was never recorded, because recording
                # only starts after the load finishes.
                if (listener.engine == "whisper"
                        and not listener.whisper_loaded):
                    gui.set_state(
                        "thinking",
                        "Loading Whisper model (first run downloads it)...")
                    ok, load_error = listener.preload_whisper()
                    if not ok:
                        failed = True
                        gui.set_state("error", load_error)
                        gui.show_transcript(f"AURA: {load_error}")
                        return
                gui.set_state("listening", "Listening...")
                with mic_lock:
                    text, error = listener.listen(timeout=8.0)
                if error:
                    failed = True
                    gui.set_state("error", error)
                    gui.show_transcript(f"AURA: {error}")
                    return
                gui.show_transcript(f"You: {text}")
                gui.set_state("thinking", "Thinking...")
                # Phase 10.1: this turn is executing a command.
                _publish_state("EXECUTING", pill_state="thinking")
                reply, should_quit = handle(text)
                # Phase 10.1: the personality mode formats the
                # reply (tone + verbosity) before it is shown or
                # spoken, so the transcript, the history and the
                # voice all agree.
                reply = format_reply(reply)
                # Phase 8A: "open/close control center" — open or
                # close the window on the GUI thread.
                _apply_gui_action()
                # Theme change (Phase 6): a theme command saves the
                # new theme in settings; recolor the pill before
                # speaking, so the change lands with the reply.
                try:
                    gui.set_theme(load_theme_name())
                except Exception:  # noqa: BLE001, S110 - theme never breaks a turn
                    pass
                # Phase 8A: the open Control Center follows the
                # pill's theme too, live.
                _recolor_control_center()
                # Conversation history (Phase 5): record the turn.
                # Never allowed to break the turn itself.
                try:
                    get_memory().add_turn(text, reply)
                except Exception:  # noqa: BLE001, S110 - history is best effort
                    pass
                gui.show_transcript(f"AURA: {reply}")
                # Phase 10.1: Silent mode speaks nothing at all —
                # the reply still shows in the transcript.
                if is_silent():
                    barged = False
                else:
                    gui.set_state("speaking", "Speaking...")
                    barged = _speak_with_barge(reply)
                if barged:
                    # Cut in mid-sentence: the user wants something
                    # else, so listen for it instead of quitting.
                    continue
                if should_quit:
                    _shutdown()
                    return
                return
        except Exception as exc:  # noqa: BLE001 - keep the pill alive
            failed = True
            try:
                gui.set_state("error", f"Something went wrong: {exc}")
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass
            return
        finally:
            # Never leave the pill stuck — but only the newest turn
            # may reset state, so a mic-tap barge is not clobbered
            # by the older turn finishing behind it. A failed turn
            # keeps its error visible instead of resetting to idle.
            if my_gen == turn_gen["n"]:
                turn_active.clear()
                if not failed:
                    # Phase 10.1: a finished turn pulses SUCCESS,
                    # then the pill reset below publishes IDLE.
                    _publish_state("SUCCESS", status="Done")
                    try:
                        if wake_enabled["on"]:
                            gui.set_state("wake", _wake_prompt())
                        else:
                            gui.set_state(
                                "idle", "AURA — tap the mic and speak")
                    except Exception:  # noqa: BLE001, S110 - window may be closed
                        pass
                    # Phase 10.1: when the reply asked "are you
                    # sure?", the bus ends at WAITING_CONFIRMATION
                    # (after the pill's IDLE) so later features
                    # can see that AURA is awaiting a yes/no.
                    if confirmation_pending():
                        _publish_state(
                            "WAITING_CONFIRMATION",
                            status="Waiting for your yes or no...",
                        )

    def on_mic():
        # Tapping the mic takes manual control: stop wake mode first
        # so its stream releases the mic, cut off any speech in
        # progress (mic-button barge-in), then run one turn.
        if wake_enabled["on"]:
            set_wake(False)
        speaker.stop()
        threading.Thread(target=_voice_turn, daemon=True).start()

    def on_engine_change(engine: str):
        current_engine["name"] = engine
        listener.set_engine(engine)
        # Phase 8B: keep the pill's engine menu in sync when the
        # switch came from voice or the Control Center.
        gui_ref["gui"].set_engine(engine)
        # Phase 8B v4: the open Control Center must follow too. A
        # voice/typed switch used to update the pill and (via the
        # theme recolor) the header, but left the Settings radio on
        # the old engine until the window was reopened — so Jay had
        # to switch it manually a second time. refresh_all() runs
        # on the GUI thread; this function can be called from a
        # voice worker thread, so it is scheduled with after(0).
        win = control_center["win"]
        if win is not None and win._alive:
            try:
                gui_ref["gui"].root.after(0, win.refresh_all)
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass
        gui = gui_ref["gui"]
        if wake_enabled["on"]:
            gui.set_state("wake", _wake_prompt())
        else:
            gui.set_state("idle", f"Engine: {engine} — tap the mic and speak")

    def on_chat_change(enabled: bool):
        """Phase 8C: the Control Center's chat-mode checkbox.
        Persists the flag; the window refreshes itself."""
        set_chat_enabled(enabled)

    def on_morning_change(enabled: bool):
        """Phase 9.2A: the Control Center's morning-briefing
        checkbox. Persists the flag; the window refreshes itself."""
        set_morning_enabled(enabled)

    def on_personality_change(mode: str):
        """Phase 10.1: the Control Center's personality picker.
        Persists the mode; the window refreshes itself."""
        save_mode(mode)

    def _get_state_status():
        """Phase 10.1: live state for the Control Center."""
        return {
            "state": state_manager.current_state(),
            "status": state_manager.current_status(),
        }

    def _get_focus_status():
        """Phase 10.1: live focus status for the Control Center."""
        focus = get_focus_manager()
        return {
            "active": focus.active,
            "status": focus.status(),
            "line": focus.status_line(),
            "on_break": focus.on_break,
        }

    def _apply_hotkey_settings():
        """Phase 9.2B: (re)bind the global-hotkey listener to
        the current settings — start it when enabled and
        pynput is there, stop it otherwise. Safe to call
        anytime; a failed start leaves AURA exactly as before
        and the Control Center's status line says so."""
        obj = hotkey["obj"]
        if obj is None:
            return
        try:
            if is_hotkey_enabled() and hotkey_available():
                obj.restart(get_hotkey_combo())
            else:
                obj.stop()
        except Exception:  # noqa: BLE001, S110 - best effort
            pass

    def on_hotkey_change(enabled: bool):
        """Phase 9.2B: the Control Center's hotkey checkbox.
        Persists the flag and (re)binds the listener; the
        window refreshes its own status line."""
        set_hotkey_enabled(enabled)
        _apply_hotkey_settings()

    def on_hotkey_combo(combo: str):
        """Phase 9.2B: the Control Center's Set hotkey button.
        Persists the combo (re-enabling the hotkey when it was
        off, like the morning time does), rebinds the listener,
        and refreshes the open Control Center."""
        set_hotkey_combo(combo)
        if not is_hotkey_enabled():
            set_hotkey_enabled(True)
        _apply_hotkey_settings()
        win = control_center["win"]
        if win is not None and win._alive:
            try:
                gui_ref["gui"].root.after(0, win.refresh_all)
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass

    def _get_hotkey_status():
        """Phase 9.2B: live hotkey status for the Control
        Center — settings plus availability plus whether the
        listener is actually running (the module-level
        hotkey_status() can only report the first two)."""
        status = {
            "enabled": is_hotkey_enabled(),
            "combo": get_hotkey_combo(),
            "available": hotkey_available(),
            "running": False,
        }
        status["combo_display"] = format_hotkey_combo(status["combo"])
        obj = hotkey["obj"]
        status["running"] = bool(obj is not None and obj.running)
        return status

    def _on_hotkey():
        """Phase 9.2B: the global hotkey was pressed. Runs on
        pynput's listener thread — the GUI work is scheduled
        with after(0), and the callback itself never raises."""
        try:
            gui_ref["gui"].root.after(0, _hotkey_show)
        except Exception:  # noqa: BLE001, S110 - window may be closed
            pass

    def _hotkey_show():
        """Phase 9.2B: bring the pill back (it may be hidden in
        the tray), open the Control Center, and put the cursor
        in the typed-command box. Runs on the GUI thread."""
        try:
            _show_pill()
            open_control_center()
            win = control_center["win"]
            if win is not None and win._alive:
                win.focus_command_box()
        except Exception:  # noqa: BLE001, S110 - window may be closed
            pass

    def _tray_status():
        """Phase 9.2A: live tray status for the Control Center —
        availability plus whether the icon is actually running
        (the module-level tray_status() can only report
        availability — running is instance state)."""
        obj = tray_icon["obj"]
        return {
            "available": tray_available(),
            "running": bool(obj is not None and obj.running),
        }

    def _hide_pill():
        """Phase 9.2A: withdraw the pill — and the Control Center,
        which is its child window — so AURA runs in the tray.
        Voice (wake word / typed commands) and the tray menu keep
        working; only the visible window goes away. Runs on the
        GUI thread."""
        try:
            gui_ref["gui"].root.withdraw()
        except Exception:  # noqa: BLE001, S110 - window may be closed
            pass

    def _show_pill():
        """Phase 9.2A: bring the pill back from the tray. Runs on
        the GUI thread."""
        try:
            root = gui_ref["gui"].root
            root.deiconify()
            root.lift()
        except Exception:  # noqa: BLE001, S110 - window may be closed
            pass

    def _shutdown():
        """Phase 9.2A: stop the tray icon, then close the pill.
        Runs on the GUI thread (the tray menu's Quit schedules it
        with after(0); the voice/typed goodbye paths call it
        from a worker thread, where the tray stop is still safe
        and the pill close goes through the GUI's own destroy).
        Phase 9.2B: the hotkey listener stops first, for the
        same reason — a dead AURA must not keep a global hook."""
        hk = hotkey["obj"]
        if hk is not None:
            try:
                hk.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
        obj = tray_icon["obj"]
        if obj is not None:
            try:
                obj.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass
        gui_ref["gui"].close()

    def _speak_briefing():
        """Phase 9.2A: build + speak the daily briefing, inline
        (the caller is already a background thread — the morning
        scheduler or the tray menu). Never raises, never touches
        the mic; a failure just means no briefing this time."""
        gui = gui_ref["gui"]
        try:
            text = build_briefing(get_memory())
        except Exception:  # noqa: BLE001 - no briefing, no crash
            return
        try:
            gui.set_state("speaking", "Good morning!")
            gui.show_transcript("AURA: " + text)
        except Exception:  # noqa: BLE001 - window closed
            return
        try:
            speaker.set_language(load_language())
            # Phase 10.1: the personality mode's voice rate;
            # Silent mode speaks nothing (the text still shows).
            speaker.set_rate(voice_rate())
            if not is_silent():
                speaker.say(text)
        except Exception:  # noqa: BLE001, S110 - speech is best effort
            pass
        _log_notification("Morning briefing spoken.")
        try:
            if wake_enabled["on"]:
                gui.set_state("wake", _wake_prompt())
            else:
                gui.set_state("idle", "AURA — tap the mic and speak")
        except Exception:  # noqa: BLE001, S110 - window may be closed
            pass

    def _morning_loop():
        """Phase 9.2A: speak the daily briefing once each morning.
        Polls every 30 seconds. The fired date is persisted, so a
        restart after the briefing never fires it twice; a start
        after the briefing time skips the day (should_fire checks
        started_at); a due briefing waits for the next poll when a
        voice turn is active, and the 10-minute grace window
        covers the wait. Never raises — a failed poll retries."""
        while True:
            try:
                if is_morning_enabled():
                    now = datetime.now()
                    if should_fire(now, get_morning_time(),
                                   get_last_fired(),
                                   started_at["at"]):
                        if not turn_active.is_set():
                            # Mark FIRST, in the same synchronous
                            # block as the speak: a restart
                            # mid-briefing must not fire it again.
                            mark_fired(now.strftime("%Y-%m-%d"))
                            _speak_briefing()
                        # Else: leave the day unmarked — the next
                        # poll (30 s) retries inside the grace
                        # window once the turn finishes.
            except Exception:  # noqa: BLE001, S110 - retry next poll
                pass
            time.sleep(30)

    def _tray_briefing():
        """Phase 9.2A: the tray menu's "Daily briefing" item. Runs
        on the tray thread — the speaking itself goes on a worker
        thread. If a voice turn is active, say so on the pill
        instead of talking over it."""
        if turn_active.is_set():
            try:
                gui_ref["gui"].show_transcript(
                    "AURA: Busy — try the briefing again in a moment.")
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass
            return
        threading.Thread(target=_speak_briefing, daemon=True).start()

    def set_wake(enabled: bool):
        wake_enabled["on"] = enabled
        if enabled:
            wake_stop.clear()
        else:
            wake_stop.set()
        gui_ref["gui"].set_wake_active(enabled)

    def on_wake_toggle(enabled: bool):
        set_wake(enabled)

    def _wake_loop():
        """Background loop: wait for 'Aura', run a turn, repeat."""
        gui = gui_ref["gui"]
        while True:
            if not wake_enabled["on"]:
                time.sleep(0.2)
                continue
            # Phase 7: wake-word listening follows the language mode
            # too (the Hindi model hears "ऑरा").
            listener.set_language(load_language())
            try:
                gui.set_state("wake", _wake_prompt())
            except Exception:  # noqa: BLE001, S110 - window closed
                return
            with mic_lock:
                detected, error = listener.wait_for_wake_word(
                    wake_stop, wake_word=load_wake_word()
                )
            if error:
                # e.g. Vosk model missing: wake mode cannot work.
                try:
                    gui.set_state("error", error)
                except Exception:  # noqa: BLE001, S110 - window closed
                    return
                set_wake(False)
                continue
            if detected:
                _voice_turn()  # runs inline; loop re-arms afterwards

    def _reminder_loop():
        """Speak reminders when due. Never interrupts a voice turn —
        a due reminder waits for the next poll if a turn is active."""
        gui = gui_ref["gui"]
        while True:
            try:
                if not turn_active.is_set():
                    # Phase 10.1: a finished focus phase moves
                    # into its break (or ends the session) — the
                    # result is spoken like a reminder, and held
                    # notifications come back when the session is
                    # fully over. A due poll waits for the next
                    # cycle when a turn is active, like reminders.
                    focus_result = get_focus_manager().poll(
                        get_memory())
                    if focus_result in ("session_done", "break_done"):
                        if focus_result == "break_done":
                            get_focus_manager().flush_held_notifications(
                                get_memory())
                            spoken = (
                                "Break's over — ready for another "
                                "focus session?"
                            )
                        else:
                            spoken = (
                                "Your focus session is done — time "
                                "for a break."
                            )
                        speaker.set_language(load_language())
                        speaker.set_rate(voice_rate())
                        try:
                            gui.set_state("speaking", "Focus!")
                            gui.show_transcript(f"AURA: {spoken}")
                        except Exception:  # noqa: BLE001, S110
                            return  # window closed
                        # Phase 10.1: Silent mode speaks nothing
                        # (the text still shows).
                        if not is_silent():
                            speaker.say(spoken)
                        _log_notification(spoken)
                        try:
                            if wake_enabled["on"]:
                                gui.set_state("wake", _wake_prompt())
                            else:
                                gui.set_state(
                                    "idle", "AURA — tap the mic and speak"
                                )
                        except Exception:  # noqa: BLE001, S110
                            return
                    for row in get_memory().due_reminders():
                        if turn_active.is_set():
                            break  # leave it due; next poll retries
                        # Phase 7: reminders speak in the saved mode.
                        speaker.set_language(load_language())
                        speaker.set_rate(voice_rate())
                        try:
                            gui.set_state("speaking", "Reminder!")
                            gui.show_transcript(f"Reminder: {row['text']}")
                        except Exception:  # noqa: BLE001, S110
                            return  # window closed
                        # Phase 10.1: Silent mode speaks nothing
                        # (the reminder still shows, and is logged
                        # below like always).
                        if not is_silent():
                            speaker.say(f"Reminder: {row['text']}")
                        get_memory().mark_notified(row["id"])
                        # Notification center (Phase 6): log the fired
                        # reminder so Jay can catch up on it later.
                        # Phase 10.1: held during a focus session.
                        _log_notification(f"Reminder: {row['text']}")
                        try:
                            if wake_enabled["on"]:
                                gui.set_state("wake", _wake_prompt())
                            else:
                                gui.set_state(
                                    "idle", "AURA — tap the mic and speak"
                                )
                        except Exception:  # noqa: BLE001, S110
                            return
            except Exception:  # noqa: BLE001, S110 - retry next poll
                pass
            time.sleep(30)

    gui = IslandGUI(
        on_mic=on_mic,
        on_engine_change=on_engine_change,
        on_wake_toggle=on_wake_toggle,
        on_control_center=open_control_center,
        # Phase 10.1: every pill state change is published to
        # the shared StateManager (see _on_pill_state).
        on_state=_on_pill_state,
    )
    gui_ref["gui"] = gui
    # Phase 9.2A: tray icon — best effort, started once. When
    # pystray/Pillow are missing, or the backend refuses, start()
    # returns False and AURA runs exactly as before with the pill
    # as the only UI; "minimize to tray" then says so honestly
    # instead of hiding the pill (see _apply_gui_action).
    # The tray callbacks run on the tray thread, so the GUI ones
    # are scheduled with after(0); Quit schedules the GUI-thread
    # shutdown for the same reason.
    tray = TrayIcon(
        on_show=lambda: gui.root.after(0, _show_pill),
        on_hide=lambda: gui.root.after(0, _hide_pill),
        on_briefing=_tray_briefing,
        on_quit=lambda: gui.root.after(0, _shutdown),
    )
    tray_icon["obj"] = tray
    tray.start()
    # Phase 9.2B: global hotkey — best effort, started once.
    # When pynput is missing, or the hook is refused, start()
    # returns False and AURA runs exactly as before; "turn on
    # hotkey" then says so honestly instead of claiming it
    # works (see execute_hotkey_command). The listener runs on
    # pynput's own thread, so it can never freeze the pill,
    # and it keeps working while the pill is hidden in the
    # tray — the hook is global, not tied to any window.
    hk = Hotkey(on_press=_on_hotkey)
    hotkey["obj"] = hk
    if is_hotkey_enabled():
        hk.start()
    threading.Thread(target=_wake_loop, daemon=True).start()
    threading.Thread(target=_reminder_loop, daemon=True).start()
    threading.Thread(target=_morning_loop, daemon=True).start()
    # Startup hint: the offline engine needs a Vosk model. If none is
    # installed, say so immediately instead of failing on first listen.
    if pick_model_dir(MODEL_CANDIDATES) is None:
        gui.set_state(
            "error",
            "Vosk model missing — switch engine to Google or install it",
        )
    gui.run()


if __name__ == "__main__":
    main()
