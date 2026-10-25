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


def _speak_powershell(text: str) -> None:
    """Speak via Windows' built-in System.Speech (fresh process)."""
    safe = text.replace("'", "''").replace("\r", " ").replace("\n", " ")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Speak('{safe}') | Out-Null"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell speech failed")


def _speak_pyttsx3(text: str) -> None:
    """Fallback: fresh pyttsx3 engine per utterance, then discarded."""
    import pyttsx3

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
    finally:
        try:
            engine.stop()
        except Exception:  # noqa: BLE001, S110 - best effort cleanup
            pass


class Speaker:
    def __init__(self, rate: int = 175):
        self._rate = rate
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        while True:
            text, done = self._jobs.get()
            try:
                if platform.system() == "Windows":
                    try:
                        _speak_powershell(text)
                        _log(f"SPEAK OK (System.Speech): {text}")
                    except Exception as exc:  # noqa: BLE001 - fall back
                        _log(f"System.Speech failed ({exc!r}), trying pyttsx3")
                        _speak_pyttsx3(text)
                        _log(f"SPEAK OK (pyttsx3 fallback): {text}")
                else:
                    _speak_pyttsx3(text)
                    _log(f"SPEAK OK (pyttsx3): {text}")
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
