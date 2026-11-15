"""Microphone listening for AURA — three engines, one interface.

Engines (switchable at runtime from the GUI, the Control Center,
or by voice):
- "offline": Vosk, fully on-device. Needs the model folder
  ``models/vosk-model-small-en-us-0.15`` next to main.py. If the model
  folder is missing, this engine reports that clearly instead of
  crashing, and the caller can fall back to Google.
- "google": Google's free web speech API via SpeechRecognition.
  Needs internet; your audio goes to Google's servers.
- "whisper": Faster-Whisper (Phase 8B) — OpenAI's Whisper model
  running locally on the GPU (RTX 3050) or CPU. The "small"
  multilingual model hears both English and Hindi. First use
  downloads the model (~500 MB) from HuggingFace and loads it;
  later listens reuse it. Needs CUDA 12 + cuDNN 9 libraries for
  GPU (``pip install nvidia-cublas-cu12 nvidia-cudnn-cu12``);
  without them it falls back to CPU automatically.

Wake-word listening always uses Vosk, whichever command engine is
active — it must never send audio anywhere, and it is far lighter
than running Whisper continuously.

``listen()`` returns ``(text, error)`` where only one of the two is set,
so the GUI can always show what happened.
"""

import importlib.util
import json
import math
import os
import platform
import queue
import struct
import tempfile
import time
import wave

import speech_recognition as sr

from aura.models import HINDI_MODEL_CANDIDATES, pick_model_dir
from aura.wakeword import contains_wake_word

# Phase 8B: the Whisper model. "small" is multilingual (English +
# Hindi) and fits a 4–6 GB card (RTX 3050 6 GB) at float16; on CPU
# it runs int8. Bigger models ("medium", "large-v3") hear better
# but need more VRAM than this laptop has.
WHISPER_MODEL = "small"

# RMS loudness (int16 samples) that counts as speech, and how long
# of quiet after speech ends a Whisper turn.
_WHISPER_SPEECH_RMS = 400
_WHISPER_END_SILENCE_S = 1.2


def _audio_rms(data: bytes) -> float:
    """Loudness of a chunk of int16 mono audio (0 = silence)."""
    if len(data) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _register_nvidia_dll_dirs():
    """Windows only: put pip-installed NVIDIA runtime DLLs on PATH
    before ctranslate2 loads them.

    Known Windows faster-whisper pitfall: the driver alone is not
    enough, and even after ``pip install nvidia-cublas-cu12
    nvidia-cudnn-cu12`` Windows will not find ``cublas64_12.dll``
    on its own. ctranslate2 resolves cuBLAS with a plain
    LoadLibrary, which consults PATH and ignores
    ``os.add_dll_directory`` — so prepending the pip packages'
    ``bin`` folders to PATH (before faster-whisper is imported) is
    the fix; ``add_dll_directory`` alone is not. No-op on other
    platforms, or when the packages are not installed."""
    if platform.system() != "Windows":
        return
    try:
        spec = importlib.util.find_spec("nvidia")
    except Exception:  # noqa: BLE001 - no nvidia package, nothing to do
        return
    if spec is None or not spec.submodule_search_locations:
        return
    current = os.environ.get("PATH", "")
    for base in spec.submodule_search_locations:
        for sub in ("cublas\\bin", "cudnn\\bin", "cuda_runtime\\bin"):
            folder = os.path.join(base, sub)
            if os.path.isdir(folder) and folder.lower() not in current.lower():
                os.environ["PATH"] = folder + os.pathsep + current
                current = os.environ["PATH"]


def pick_whisper_config():
    """(device, compute_type) for this PC: CUDA float16 when a GPU
    is usable, CPU int8 otherwise. Pure except for the ctranslate2
    probe — safe to call anywhere, including tests."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # noqa: BLE001 - no GPU libs means CPU, not an error
        pass
    return "cpu", "int8"


class Listener:
    def __init__(self, engine: str = "offline", language: str = "en"):
        self.engine = engine  # "offline", "google" or "whisper" (8B)
        # Phase 7: "en" or "hi". Changing it drops the loaded Vosk
        # model so the next listen loads the right language's model.
        # Whisper needs no reload — the language is a transcribe
        # argument, and "small" is multilingual.
        self.language = language if language in ("en", "hi") else "en"
        self._recognizer = sr.Recognizer()
        self._vosk_model = None
        self._vosk_error = None
        self._whisper_model = None
        self._whisper_error = None
        self._whisper_device = None
        self._whisper_compute = None

    # -- engine switching -------------------------------------------------
    def set_engine(self, engine: str) -> None:
        if engine in ("offline", "google", "whisper"):
            self.engine = engine

    def set_language(self, language: str) -> None:
        """Switch listening language, reloading the Vosk model."""
        if language in ("en", "hi") and language != self.language:
            self.language = language
            self._vosk_model = None
            self._vosk_error = None

    @property
    def whisper_loaded(self) -> bool:
        """True once the Whisper model is in memory."""
        return self._whisper_model is not None

    def whisper_info(self):
        """Status for the Control Center diagnostics tab."""
        try:
            import faster_whisper  # noqa: F401
            installed = True
        except Exception:  # noqa: BLE001 - not installed is a state, not an error
            installed = False
        device, compute = pick_whisper_config()
        return {
            "installed": installed,
            "model": WHISPER_MODEL,
            "device": self._whisper_device or device,
            "compute_type": self._whisper_compute or compute,
            "loaded": self._whisper_model is not None,
            "error": self._whisper_error,
        }

    # -- Vosk setup (lazy: only loaded when the offline engine is used) ---
    def _load_vosk(self) -> bool:
        if self._vosk_model is not None:
            return True
        if self._vosk_error is not None:
            return False
        try:
            from vosk import Model

            candidates = (
                HINDI_MODEL_CANDIDATES
                if self.language == "hi"
                else None
            )
            model_dir = pick_model_dir(candidates)
            if model_dir is None:
                if self.language == "hi":
                    self._vosk_error = (
                        "No Hindi Vosk model found in the models folder. "
                        "Download vosk-model-small-hi-0.22 from "
                        "alphacephei.com/vosk/models and extract it into "
                        "the models folder, or switch to the Google engine."
                    )
                else:
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

    # -- Faster-Whisper setup (Phase 8B, lazy like Vosk) ------------------
    def _load_whisper(self, force_cpu: bool = False) -> bool:
        """Load (and first time, download) the Whisper model. The
        download is ~500 MB from HuggingFace and happens once; the
        model stays in memory afterwards. Returns False with
        ``self._whisper_error`` set when it cannot load.

        A failed load is NEVER cached: every attempt starts fresh.
        The old code returned False at once when ``_whisper_error``
        was set, so one failed first load (e.g. a missing CUDA
        library) poisoned every later listen, even though the error
        text promised a CPU fallback "on the next try" — a try that
        never came. A GPU failure now falls back to CPU inside the
        same call instead.

        Phase 8B v3: the NVIDIA DLL folders are registered on PATH
        before the import (see ``_register_nvidia_dll_dirs``) —
        without that, Windows cannot find ``cublas64_12.dll`` even
        when the pip packages are installed. ``force_cpu`` loads
        on CPU directly; the transcribe path uses it for its
        fallback retry."""
        if self._whisper_model is not None:
            return True
        # Fresh attempt every time — never reuse a stale failure.
        self._whisper_error = None
        _register_nvidia_dll_dirs()
        try:
            from faster_whisper import WhisperModel
        except Exception:  # noqa: BLE001 - surfaced to the GUI
            self._whisper_error = (
                "Faster-Whisper is not installed — run: "
                "pip install -r requirements.txt"
            )
            return False
        if force_cpu:
            device, compute = "cpu", "int8"
        else:
            device, compute = pick_whisper_config()
        try:
            self._whisper_model = WhisperModel(
                WHISPER_MODEL, device=device, compute_type=compute
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            if device != "cpu":
                try:
                    self._whisper_model = WhisperModel(
                        WHISPER_MODEL, device="cpu", compute_type="int8"
                    )
                    device, compute = "cpu", "int8"
                except Exception as exc2:  # noqa: BLE001 - surfaced
                    self._whisper_error = (
                        "Could not load the Whisper model "
                        f"(GPU failed: {exc}; CPU failed: {exc2}). "
                        "On GPU, make sure the CUDA 12 libraries are "
                        "installed (pip install nvidia-cublas-cu12 "
                        "nvidia-cudnn-cu12)."
                    )
                    return False
            else:
                self._whisper_error = (
                    f"Could not load the Whisper model "
                    f"({device}/{compute}): {exc}."
                )
                return False
        self._whisper_device = device
        self._whisper_compute = compute
        return True

    def preload_whisper(self) -> tuple[bool, str]:
        """Load the Whisper model now, outside a listen turn, so the
        caller can show an honest "Loading..." state while the
        (first-run) download happens. Returns (True, "") on success
        or (False, error). The old flow loaded inside listen(), so
        the pill had to claim "Listening..." for a download that had
        not started recording yet."""
        if self._load_whisper():
            return True, ""
        return False, self._whisper_error or "Whisper is unavailable."

    @staticmethod
    def _is_cuda_error(exc: Exception) -> bool:
        """True when a failure names the CUDA runtime libraries —
        the `cublas64_12.dll is not found` class of error. Used to
        decide whether a CPU retry is worth attempting."""
        msg = str(exc).lower()
        return any(
            key in msg
            for key in ("cublas", "cudnn", "cudart", "cuda", "nvrtc")
        )

    def _transcribe_once(self, wav_path: str) -> str:
        """One transcription attempt with the loaded model."""
        segments, _info = self._whisper_model.transcribe(
            wav_path,
            language=self.language,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text for seg in segments).strip()

    def _transcribe_wav(self, wav_path: str) -> tuple[str, str]:
        """Transcribe a 16 kHz mono WAV with the loaded model.
        Returns (text, error). Split out so it is testable without
        a microphone.

        Phase 8B v3: the model can load on GPU yet fail at
        inference time — ctranslate2 resolves cuBLAS lazily, so a
        missing ``cublas64_12.dll`` only surfaces here, after the
        load already succeeded. A CUDA-library failure therefore
        rebuilds the model on CPU and retries the same clip once,
        instead of failing the turn."""
        try:
            text = self._transcribe_once(wav_path)
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            if self._is_cuda_error(exc) and self._whisper_device != "cpu":
                self._whisper_model = None
                self._whisper_device = None
                self._whisper_compute = None
                if self._load_whisper(force_cpu=True):
                    try:
                        text = self._transcribe_once(wav_path)
                    except Exception as exc2:  # noqa: BLE001 - surfaced
                        return "", (
                            f"Whisper error: {exc2} "
                            f"(GPU failed first: {exc})"
                        )
                else:
                    return "", (
                        f"Whisper error: {exc} "
                        "(CPU fallback failed: "
                        f"{self._whisper_error})"
                    )
            else:
                return "", f"Whisper error: {exc}"
        if not text:
            return "", "I didn't hear anything. Try again."
        return text, ""

    def _listen_whisper(self, timeout: float = 8.0) -> tuple[str, str]:
        """Record until ~1.2 s of silence after speech (or the
        timeout), then transcribe the whole clip at once. Whisper
        needs the complete utterance — it cannot stream like Vosk."""
        if not self._load_whisper():
            return "", self._whisper_error or "Whisper is unavailable."
        try:
            import pyaudio
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return "", f"Whisper engine is missing a package: {exc}"

        audio_queue: queue.Queue = queue.Queue()

        def _callback(in_data, _frame_count, _time_info, _status):
            audio_queue.put(bytes(in_data))
            return None, pyaudio.paContinue

        mic = pyaudio.PyAudio()
        wav_path = None
        stream = None
        try:
            stream = mic.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
                stream_callback=_callback,
            )
            stream.start_stream()
            frames = []
            speech_started = False
            last_speech = time.time()
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    if speech_started and (
                        time.time() - last_speech
                        > _WHISPER_END_SILENCE_S
                    ):
                        break
                    continue
                frames.append(data)
                if _audio_rms(data) > _WHISPER_SPEECH_RMS:
                    speech_started = True
                    last_speech = time.time()
                elif speech_started and (
                    time.time() - last_speech > _WHISPER_END_SILENCE_S
                ):
                    break
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                pass
            if not speech_started:
                return "", "I didn't hear anything. Try again."
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            with wave.open(wav_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"".join(frames))
            return self._transcribe_wav(wav_path)
        except OSError:
            return "", "No microphone found. Check your mic and try again."
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            return "", f"Microphone error: {exc}"
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                pass
            mic.terminate()
            if wav_path:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

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
        stream = None
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
                if stream is not None:
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
        if self.engine == "whisper":
            return self._listen_whisper(timeout)
        return self._listen_google(timeout)

    def _listen_google(self, timeout: float) -> tuple[str, str]:
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=timeout)
            # en-IN: Google's Indian English model — far better for
            # Indian accents than the default en-US setting. hi-IN
            # when the language mode is Hindi (Phase 7).
            lang = "hi-IN" if self.language == "hi" else "en-IN"
            text = self._recognizer.recognize_google(audio, language=lang)
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
        stream = None
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
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                pass
            mic.terminate()
