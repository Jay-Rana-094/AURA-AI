"""Offline text-to-speech for AURA (nothing leaves the PC).

HISTORY OF THIS FILE (why it looks the way it does):
- v0.1.0: pyttsx3 engine created on the main thread, spoken from fresh
  worker threads. Speech died after the first utterance (COM objects
  must only be touched from their creating thread).
- v0.1.1: engine moved onto one dedicated thread, spoken via a queue.
  Still went silent after the first line.
- v0.1.2: added engine.stop() reset + engine rebuild on failure, plus
  a speech log. The log then proved the app hears and answers every
  turn — pyttsx3 reported "SPEAK OK" for every utterance — yet only
  the first one was audible. pyttsx3/SAPI5 can silently produce no
  sound while returning success, so no pyttsx3-side fix can detect it.
- v0.1.3 (current): on Windows, speech goes through the built-in
  System.Speech engine via a fresh PowerShell process per utterance.
  No reused engine, no leftover state to go silent. pyttsx3 remains
  only as a fallback (and for non-Windows).
- FIX (2026-10-26): the PowerShell helper window is now hidden
  (CREATE_NO_WINDOW). Without it, Windows popped a visible window
  up for every utterance — it appeared while AURA talked and
  vanished when the sentence ended.
- Phase 5 (barge-in): the speaker is interruptible. ``stop()`` kills
  the speech process (or stops the fallback engine) so the user can
  cut AURA off mid-sentence, from the mic button or by saying the
  wake word while it talks. A stop when nothing is playing is a
  harmless no-op, and the stop flag is cleared when the next
  utterance starts, so a stray stop never silences later speech.

System.Speech is part of Windows itself — no download, no internet.
"""

import os
import platform
import queue
import subprocess
import threading

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura-speech.log",
)


def _log(line: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class Speaker:
    def __init__(self, rate: int = 175):
        self._rate = rate
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        # Barge-in state: what is speaking right now, if anything.
        self._current_proc = None
        self._current_engine = None
        self._proc_lock = threading.Lock()
        self._stop_requested = threading.Event()

    def stop(self) -> None:
        """Interrupt the utterance in progress, if any.

        Safe to call anytime — with nothing playing it just sets a
        flag the next utterance clears. Never blocks: killing the
        process (or stopping the engine) is what unblocks say().
        """
        self._stop_requested.set()
        with self._proc_lock:
            proc = self._current_proc
            engine = self._current_engine
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001, S110 - already gone
                pass
        if engine is not None:
            try:
                engine.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass

    def _run_hidden(self, cmd) -> tuple[int, str]:
        """Run ``cmd`` with no window, tracking it for stop().

        Returns (returncode, stderr). A kill from stop() shows up as
        a negative returncode, which the caller treats as an
        interruption, not a failure.
        """
        startupinfo = None
        creationflags = 0
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        with self._proc_lock:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            proc = self._current_proc
        try:
            _, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()
            raise RuntimeError("Speech process timed out")
        finally:
            with self._proc_lock:
                self._current_proc = None
        return proc.returncode, stderr.strip()

    def _speak_powershell(self, text: str) -> None:
        """Speak via Windows' built-in System.Speech (fresh process).

        The helper process runs with its window hidden: without
        CREATE_NO_WINDOW, Windows shows a console window for the
        PowerShell process, so a window popped up for every spoken
        reply and closed when the sentence finished."""
        safe = text.replace("'", "''").replace("\r", " ").replace("\n", " ")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{safe}') | Out-Null"
        )
        returncode, stderr = self._run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        )
        if self._stop_requested.is_set():
            return  # interrupted by stop(): not an error
        if returncode != 0:
            raise RuntimeError(stderr or "PowerShell speech failed")

    def _speak_pyttsx3(self, text: str) -> None:
        """Fallback: fresh pyttsx3 engine per utterance, then discarded."""
        import pyttsx3

        engine = pyttsx3.init()
        with self._proc_lock:
            self._current_engine = engine
        try:
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        finally:
            with self._proc_lock:
                self._current_engine = None
            try:
                engine.stop()
            except Exception:  # noqa: BLE001, S110 - best effort cleanup
                pass

    def _worker(self):
        while True:
            text, done = self._jobs.get()
            self._stop_requested.clear()
            try:
                if platform.system() == "Windows":
                    try:
                        self._speak_powershell(text)
                    except Exception as exc:  # noqa: BLE001 - fall back
                        _log(f"System.Speech failed ({exc!r}), trying pyttsx3")
                        self._speak_pyttsx3(text)
                else:
                    self._speak_pyttsx3(text)
                if self._stop_requested.is_set():
                    _log(f"SPEAK INTERRUPTED: {text}")
                else:
                    _log(f"SPEAK OK: {text}")
            except Exception as exc:  # noqa: BLE001 - never kill the thread
                _log(f"SPEAK FAIL: {exc!r} (text was: {text})")
            finally:
                done.set()

    def say(self, text: str) -> None:
        """Speak ``text`` aloud, blocking until it finishes."""
        if not text:
            return
        done = threading.Event()
        self._jobs.put((text, done))
        done.wait()

    def set_rate(self, rate: int) -> None:
        self._rate = rate
