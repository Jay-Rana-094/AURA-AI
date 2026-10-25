"""Microphone listening for AURA — two engines, one interface.

Engines (switchable at runtime from the GUI):
- "offline": Vosk, fully on-device. Needs the model folder
  ``models/vosk-model-small-en-us-0.15`` next to main.py. If the model
  folder is missing, this engine reports that clearly instead of
  crashing, and the caller can fall back to Google.
- "google": Google's free web speech API via SpeechRecognition.
  Needs internet; your audio goes to Google's servers.

``listen()`` returns ``(text, error)`` where only one of the two is set,
so the GUI can always show what happened.
"""

import json
import os
import queue

import speech_recognition as sr

from aura.models import pick_model_dir
from aura.wakeword import contains_wake_word


class Listener:
    def __init__(self, engine: str = "offline"):
        self.engine = engine  # "offline" or "google"
        self._recognizer = sr.Recognizer()
        self._vosk_model = None
        self._vosk_error = None

    # -- engine switching -------------------------------------------------
    def set_engine(self, engine: str) -> None:
        if engine in ("offline", "google"):
            self.engine = engine

    # -- Vosk setup (lazy: only loaded when the offline engine is used) ---
    def _load_vosk(self) -> bool:
        if self._vosk_model is not None:
            return True
        if self._vosk_error is not None:
            return False
        try:
            from vosk import Model

            model_dir = pick_model_dir()
            if model_dir is None:
                self._vosk_error = (
                    "No Vosk model found in the models folder. Download "
                    "vosk-model-small-en-in-0.4 (Indian English, recommended) "
                    "or vosk-model-small-en-us-0.15 from "
                    "alphacephei.com/vosk/models and extract it into the "
                    "models folder, or switch to the Google engine."
                )
                return False
            self._vosk_model = Model(model_dir)
            return True
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            self._vosk_error = f"Could not load Vosk: {exc}"
            return False

    # -- wake word ---------------------------------------------------------
    def wait_for_wake_word(self, stop_event, wake_word: str = "aura"):
        """Listen continuously until ``wake_word`` is heard.

        Always uses the offline Vosk engine, even if the command engine
        is set to Google — wake-word listening must never send audio
        anywhere. Returns (detected, error): detected is False when
        ``stop_event`` is set or the mic fails.
        """
        if not self._load_vosk():
            return False, self._vosk_error or "Vosk is unavailable."

        try:
            import pyaudio
            from vosk import KaldiRecognizer
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return False, f"Offline engine is missing a package: {exc}"

        recognizer = KaldiRecognizer(self._vosk_model, 16000)
        audio_queue: queue.Queue = queue.Queue()

        def _callback(in_data, _frame_count, _time_info, _status):
            audio_queue.put(bytes(in_data))
            return None, pyaudio.paContinue

        mic = pyaudio.PyAudio()
        try:
            stream = mic.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=8000,
                stream_callback=_callback,
            )
            stream.start_stream()
            while not stop_event.is_set():
                try:
                    data = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if recognizer.AcceptWaveform(data):
                    text = json.loads(recognizer.Result()).get("text", "")
                    if contains_wake_word(text, wake_word):
                        return True, ""
                else:
                    partial = json.loads(recognizer.PartialResult()).get(
                        "partial", ""
                    )
                    if contains_wake_word(partial, wake_word):
                        return True, ""
            return False, ""
        except OSError:
            return False, "No microphone found. Check your mic and try again."
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return False, f"Microphone error: {exc}"
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                pass
            mic.terminate()

    # -- main entry point --------------------------------------------------
    def listen(self, timeout: float = 8.0) -> tuple[str, str]:
        """Listen once and return (text, error)."""
        if self.engine == "offline":
            return self._listen_offline(timeout)
        return self._listen_google(timeout)

    def _listen_google(self, timeout: float) -> tuple[str, str]:
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=timeout)
            # en-IN: Google's Indian English model — far better for
            # Indian accents than the default en-US setting.
            text = self._recognizer.recognize_google(audio, language="en-IN")
            return text, ""
        except sr.WaitTimeoutError:
            return "", "I didn't hear anything. Try again."
        except sr.UnknownValueError:
            return "", "Sorry, I couldn't understand that."
        except sr.RequestError:
            return "", "Google engine needs internet — check your connection."
        except OSError:
            return "", "No microphone found. Check your mic and try again."
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return "", f"Microphone error: {exc}"

    def _listen_offline(self, timeout: float) -> tuple[str, str]:
        if not self._load_vosk():
            return "", self._vosk_error or "Vosk is unavailable."

        try:
            import pyaudio
            from vosk import KaldiRecognizer
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return "", f"Offline engine is missing a package: {exc}"

        recognizer = KaldiRecognizer(self._vosk_model, 16000)
        audio_queue: queue.Queue = queue.Queue()

        def _callback(in_data, _frame_count, _time_info, _status):
            audio_queue.put(bytes(in_data))
            return None, pyaudio.paContinue

        mic = pyaudio.PyAudio()
        try:
            stream = mic.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=8000,
                stream_callback=_callback,
            )
            stream.start_stream()
            import time

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        return text, ""
            # Timeout: take whatever partial result exists.
            partial = json.loads(recognizer.FinalResult()).get("text", "").strip()
            if partial:
                return partial, ""
            return "", "I didn't hear anything. Try again."
        except OSError:
            return "", "No microphone found. Check your mic and try again."
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return "", f"Microphone error: {exc}"
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                pass
            mic.terminate()
