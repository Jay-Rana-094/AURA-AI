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

Run with: python main.py  (or run.bat on Windows)
"""

import os
import threading
import time

from aura.brain import get_memory, handle
from aura.gui import IslandGUI
from aura.listener import Listener
from aura.models import MODEL_CANDIDATES, pick_model_dir
from aura.speaker import Speaker
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
        try:
            while True:
                gui.set_state("listening", "Listening...")
                with mic_lock:
                    text, error = listener.listen(timeout=8.0)
                if error:
                    gui.set_state("error", error)
                    gui.show_transcript("")
                    return
                gui.show_transcript(f"You: {text}")
                gui.set_state("thinking", "Thinking...")
                reply, should_quit = handle(text)
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
            try:
                gui.set_state("error", f"Something went wrong: {exc}")
            except Exception:  # noqa: BLE001, S110 - window may be closed
                pass
            return
        finally:
            # Never leave the pill stuck — but only the newest turn
            # may reset state, so a mic-tap barge is not clobbered
            # by the older turn finishing behind it.
            if my_gen == turn_gen["n"]:
                turn_active.clear()
                try:
                    if wake_enabled["on"]:
                        gui.set_state("wake", _wake_prompt())
                    else:
                        gui.set_state("idle", "AURA — tap the mic and speak")
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
        listener.set_engine(engine)
        gui = gui_ref["gui"]
        if wake_enabled["on"]:
            gui.set_state("wake", _wake_prompt())
        else:
            gui.set_state("idle", f"Engine: {engine} — tap the mic and speak")

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
                        try:
                            gui.set_state("speaking", "Reminder!")
                            gui.show_transcript(f"Reminder: {row['text']}")
                        except Exception:  # noqa: BLE001, S110
                            return  # window closed
                        speaker.say(f"Reminder: {row['text']}")
                        get_memory().mark_notified(row["id"])
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
