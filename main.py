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

Phase 8A: double-click the pill (or say "open control center") to
open the Control Center window — today's briefing, notes/todos/
reminders, history, settings, diagnostics, and a typed-command
box that runs through the same brain as a voice turn.

Run with: python main.py  (or run.bat on Windows)
"""

import os
import threading
import time

from aura.brain import get_memory, handle, pop_gui_action
from aura.chat import chat_status, set_chat_enabled
from aura.control_center import ControlCenter
from aura.gui import IslandGUI
from aura.language import load_language
from aura.listener import Listener
from aura.models import MODEL_CANDIDATES, pick_model_dir
from aura.speaker import Speaker
from aura.theme import load_theme_name, save_theme_name
from aura.wake_settings import display_wake_word, load_wake_word
from aura.wakeword import contains_wake_word


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
    # Turn generations: a mic tap during speech starts a newer turn,
    # and only the newest turn may reset the pill state or clear
    # turn_active when it finishes.
    turn_gen = {"n": 0}

    def _wake_prompt():
        """Pill text for wake mode, using the current custom word."""
        return f"Say '{display_wake_word(load_wake_word())}'..."

    def _speak_with_barge(reply: str) -> bool:
        """Speak ``reply``, listening for the wake word meanwhile.

        Returns True if the user barged in by voice. The speech runs
        on its own thread; the wake-word wait ends when speech ends
        (its stop event) or when the word is heard. Voice barging is
        skipped for replies that contain the wake word themselves,
        and for a missing Vosk model (the wait then returns at once
        and speech simply plays out).
        """
        speech_done = threading.Event()

        def _say():
            try:
                speaker.say(reply)
            finally:
                speech_done.set()

        say_thread = threading.Thread(target=_say, daemon=True)
        say_thread.start()
        word = load_wake_word()
        if contains_wake_word(reply, word):
            say_thread.join()
            return False
        with mic_lock:
            detected, _ = listener.wait_for_wake_word(
                speech_done, wake_word=word
            )
        if detected:
            speaker.stop()
            say_thread.join()
            return True
        say_thread.join()
        return False

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
        the status line."""
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

    def run_typed_command(text: str):
        """Phase 8A: a command typed in the Control Center. Same
        brain as a voice turn — the reply is shown in the window
        and spoken aloud. Runs on a worker thread."""
        def _run():
            gui = gui_ref["gui"]
            lang = load_language()
            listener.set_language(lang)
            speaker.set_language(lang)
            # A brain failure surfaces as a reply, never as a silent
            # dead thread: typed commands used to vanish with no
            # response at all when handle() raised.
            try:
                reply, should_quit = handle(text)
            except Exception as exc:  # noqa: BLE001 - surfaced as a reply
                reply, should_quit = f"Something went wrong: {exc}", False
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
            gui.set_state("speaking", "Speaking...")
            speaker.say(reply)
            if should_quit:
                gui.close()
                return
            try:
                if wake_enabled["on"]:
                    gui.set_state("wake", _wake_prompt())
                else:
                    gui.set_state("idle", "AURA — tap the mic and speak")
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass

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
                reply, should_quit = handle(text)
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
                gui.set_state("speaking", "Speaking...")
                barged = _speak_with_barge(reply)
                if barged:
                    # Cut in mid-sentence: the user wants something
                    # else, so listen for it instead of quitting.
                    continue
                if should_quit:
                    gui.close()
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
                    try:
                        if wake_enabled["on"]:
                            gui.set_state("wake", _wake_prompt())
                        else:
                            gui.set_state(
                                "idle", "AURA — tap the mic and speak")
                    except Exception:  # noqa: BLE001, S110 - window may be closed
                        pass

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
                    for row in get_memory().due_reminders():
                        if turn_active.is_set():
                            break  # leave it due; next poll retries
                        # Phase 7: reminders speak in the saved mode.
                        speaker.set_language(load_language())
                        try:
                            gui.set_state("speaking", "Reminder!")
                            gui.show_transcript(f"Reminder: {row['text']}")
                        except Exception:  # noqa: BLE001, S110
                            return  # window closed
                        speaker.say(f"Reminder: {row['text']}")
                        get_memory().mark_notified(row["id"])
                        # Notification center (Phase 6): log the fired
                        # reminder so Jay can catch up on it later.
                        # Never allowed to break the reminder loop.
                        try:
                            get_memory().add_notification(
                                f"Reminder: {row['text']}"
                            )
                        except Exception:  # noqa: BLE001, S110 - log is best effort
                            pass
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
    )
    gui_ref["gui"] = gui
    threading.Thread(target=_wake_loop, daemon=True).start()
    threading.Thread(target=_reminder_loop, daemon=True).start()
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
