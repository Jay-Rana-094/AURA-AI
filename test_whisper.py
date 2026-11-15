"""Tests for Phase 8B — Faster-Whisper engine.

No real model is downloaded here: the transcribe path is tested
with a fake model, the missing-package path is tested for real
(this VM has no faster-whisper), and the window tests run under
Xvfb when a display is available.

    python test_whisper.py
"""

import importlib.util
import os
import platform
import struct
import sys
import tempfile
import tkinter as tk
import types
import wave

# listener.py imports SpeechRecognition at module level, which is
# not installed in this test environment. Stub it (same pattern as
# test_hindi.py): the Whisper tests never touch the Google path.
_sr_stub = types.ModuleType("speech_recognition")


class _RecognizerStub:
    def adjust_for_ambient_noise(self, *args, **kwargs):
        pass

    def listen(self, *args, **kwargs):
        return None

    def recognize_google(self, *args, **kwargs):
        return ""


_sr_stub.Recognizer = _RecognizerStub
_sr_stub.Microphone = object
_sr_stub.WaitTimeoutError = type("WaitTimeoutError", (Exception,), {})
_sr_stub.UnknownValueError = type("UnknownValueError", (Exception,), {})
_sr_stub.RequestError = type("RequestError", (Exception,), {})
sys.modules["speech_recognition"] = _sr_stub

from aura.brain import (
    handle,
    pop_gui_action,
    set_custom_store,
    set_memory,
)
from aura.commands.custom import CustomStore
from aura.listener import (
    WHISPER_MODEL,
    Listener,
    _audio_rms,
    pick_whisper_config,
)
from aura.memory import Memory


def _display_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


class _FakeSeg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, texts):
        self._texts = texts

    def transcribe(self, path, language=None, beam_size=5, vad_filter=True):
        assert os.path.isfile(path), path
        assert language in ("en", "hi"), language
        return [_FakeSeg(t) for t in self._texts], {"language": language}


def _tiny_wav(path):
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)  # 0.1 s of silence


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- Model choice: small multilingual, fits the RTX 3050. ----
    assert WHISPER_MODEL == "small", WHISPER_MODEL

    # --- Device selection: a valid pair, CPU on this GPU-less VM. --
    device, compute = pick_whisper_config()
    assert (device, compute) in (
        ("cuda", "float16"), ("cpu", "int8")), (device, compute)
    assert (device, compute) == ("cpu", "int8"), (device, compute)

    # --- Audio loudness: silence ~ 0, loud noise high. -------------
    assert _audio_rms(b"\x00\x00" * 1000) == 0.0
    loud = struct.pack("<1000h", *([2000] * 1000))
    assert _audio_rms(loud) > 1000, _audio_rms(loud)
    assert _audio_rms(b"") == 0.0

    # --- Engine switching: whisper accepted, junk rejected. ---------
    listener = Listener()
    assert listener.engine == "offline"
    listener.set_engine("whisper")
    assert listener.engine == "whisper"
    listener.set_engine("google")
    assert listener.engine == "google"
    listener.set_engine("nope")
    assert listener.engine == "google"
    assert not listener.whisper_loaded

    # --- Whisper status reporting (no package on this VM). ----------
    info = listener.whisper_info()
    assert set(info) == {
        "installed", "model", "device", "compute_type", "loaded", "error",
    }, info
    assert info["model"] == "small"
    assert info["loaded"] is False
    assert info["installed"] is False  # this VM has no faster-whisper

    # --- Missing package: listen() fails honestly, no crash. -------
    listener.set_engine("whisper")
    text, error = listener.listen(timeout=1.0)
    assert text == "" and "Faster-Whisper" in error, error
    assert "pip install" in error, error

    # --- Preload: missing package fails honestly, and a failed load
    # is NOT cached — the next attempt retries (8B v2 fix). -------
    listener.set_engine("whisper")
    listener._whisper_model = None
    listener._whisper_error = None
    ok, err = listener.preload_whisper()
    assert ok is False and "Faster-Whisper" in err, (ok, err)
    assert "pip install" in err, err

    # --- GPU failure falls back to CPU in the same load, and a
    # failed load never poisons the next attempt. ------------------
    import aura.listener as _listener_mod
    _fw_stub = types.ModuleType("faster_whisper")

    class _FlakyModel:
        calls = []

        def __init__(self, name, device, compute_type):
            _FlakyModel.calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("cuDNN missing")

        def transcribe(self, *args, **kwargs):
            return [], {}

    _fw_stub.WhisperModel = _FlakyModel
    sys.modules["faster_whisper"] = _fw_stub
    _orig_pick = _listener_mod.pick_whisper_config
    _listener_mod.pick_whisper_config = lambda: ("cuda", "float16")
    try:
        listener2 = Listener(engine="whisper")
        ok, err = listener2.preload_whisper()
        assert ok is True and err == "", (ok, err)
        assert listener2.whisper_loaded
        assert _FlakyModel.calls == [
            ("cuda", "float16"), ("cpu", "int8"),
        ], _FlakyModel.calls
        assert listener2._whisper_device == "cpu"
        assert listener2._whisper_compute == "int8"

        class _AlwaysFails:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("nope")

        _fw_stub.WhisperModel = _AlwaysFails
        listener3 = Listener(engine="whisper")
        ok, err = listener3.preload_whisper()
        assert ok is False and "Could not load" in err, (ok, err)
        _fw_stub.WhisperModel = _FlakyModel
        ok, err = listener3.preload_whisper()
        assert ok is True, (ok, err)
    finally:
        sys.modules.pop("faster_whisper", None)
        _listener_mod.pick_whisper_config = _orig_pick

    # --- Mic open failure reports "No microphone found", not a
    # NameError from the cleanup block (8B v2 fix). ----------------
    _pa_stub = types.ModuleType("pyaudio")
    _pa_stub.paInt16 = 8
    _pa_stub.paContinue = 0

    class _FailingPyAudio:
        def open(self, *args, **kwargs):
            raise OSError("no device")

        def terminate(self):
            pass

    _pa_stub.PyAudio = _FailingPyAudio
    sys.modules["pyaudio"] = _pa_stub
    try:
        listener4 = Listener(engine="whisper")
        listener4._whisper_model = _FakeModel(["hello"])
        text, error = listener4._listen_whisper(timeout=1.0)
        assert text == "" and "No microphone" in error, (text, error)
    finally:
        sys.modules.pop("pyaudio", None)

    # --- NVIDIA DLL folders are prepended to PATH on Windows
    # (8B v3 fix) — ctranslate2's LoadLibrary consults PATH. -----
    assert Listener._is_cuda_error(
        RuntimeError("Library cublas64_12.dll is not found"))
    assert Listener._is_cuda_error(RuntimeError("cudnn error"))
    assert not Listener._is_cuda_error(RuntimeError("boom"))
    _nv_root = os.path.join(tmp, "nvidia")
    for sub in ("cublas\\bin", "cudnn\\bin"):
        os.makedirs(os.path.join(_nv_root, sub), exist_ok=True)
    _nv_spec = types.SimpleNamespace(
        submodule_search_locations=[_nv_root])
    _orig_find_spec = importlib.util.find_spec
    _orig_system = platform.system
    _saved_path = os.environ.get("PATH", "")
    try:
        importlib.util.find_spec = lambda name: None
        _listener_mod.platform.system = lambda: "Windows"
        os.environ["PATH"] = _saved_path
        _listener_mod._register_nvidia_dll_dirs()
        assert os.environ.get("PATH", "") == _saved_path
        importlib.util.find_spec = (
            lambda name: _nv_spec if name == "nvidia" else None)
        _listener_mod._register_nvidia_dll_dirs()
        _new_path = os.environ.get("PATH", "")
        assert os.path.join(_nv_root, "cublas\\bin") in _new_path
        assert os.path.join(_nv_root, "cudnn\\bin") in _new_path
        _listener_mod._register_nvidia_dll_dirs()
        assert _new_path.count(
            os.path.join(_nv_root, "cublas\\bin")) == 1
    finally:
        importlib.util.find_spec = _orig_find_spec
        _listener_mod.platform.system = _orig_system
        os.environ["PATH"] = _saved_path

    # --- Transcribe-time CUDA failure rebuilds on CPU and retries
    # the same clip (8B v3 fix). ----------------------------------
    wav_path = os.path.join(tmp, "clip.wav")
    _tiny_wav(wav_path)

    class _GpuFailingModel:
        def transcribe(self, *args, **kwargs):
            raise RuntimeError(
                "Library cublas64_12.dll is not found or "
                "cannot be loaded")

    class _BoomModel:
        def transcribe(self, *args, **kwargs):
            raise RuntimeError("boom")

    _load_calls = []

    def _recording_load(listener):
        def _load(force_cpu=False):
            _load_calls.append(force_cpu)
            listener._whisper_model = _FakeModel(["hello", "world"])
            listener._whisper_device = "cpu"
            listener._whisper_compute = "int8"
            return True
        return _load

    listener5 = Listener(engine="whisper")
    listener5._whisper_model = _GpuFailingModel()
    listener5._whisper_device = "cuda"
    listener5._whisper_compute = "float16"
    listener5._load_whisper = _recording_load(listener5)
    text, error = listener5._transcribe_wav(wav_path)
    assert text == "hello world" and error == "", (text, error)
    assert _load_calls == [True], _load_calls
    assert listener5._whisper_device == "cpu"

    # --- A non-CUDA transcribe error does NOT trigger a rebuild. --
    listener6 = Listener(engine="whisper")
    listener6._whisper_model = _BoomModel()
    listener6._whisper_device = "cuda"
    listener6._load_whisper = _recording_load(listener6)
    text, error = listener6._transcribe_wav(wav_path)
    assert text == "" and error == "Whisper error: boom", (text, error)
    assert _load_calls == [True], _load_calls

    # --- Transcribe path with a fake model (no mic, no download). --
    listener.set_engine("whisper")
    listener._whisper_model = _FakeModel(["hello", "world"])
    wav_path = os.path.join(tmp, "clip.wav")
    _tiny_wav(wav_path)
    text, error = listener._transcribe_wav(wav_path)
    assert text == "hello world" and error == "", (text, error)
    listener._whisper_model = _FakeModel([])
    text, error = listener._transcribe_wav(wav_path)
    assert text == "" and "didn't hear" in error, (text, error)
    listener.language = "hi"
    listener._whisper_model = _FakeModel(["नमस्ते"])
    text, error = listener._transcribe_wav(wav_path)
    assert text == "नमस्ते", (text, error)

    # --- Voice routing: switch phrases set the GUI action. ---------
    assert pop_gui_action() is None
    for phrase, action in (
        ("switch engine to whisper", "engine_whisper"),
        ("switch to whisper", "engine_whisper"),
        ("use whisper", "engine_whisper"),
        ("switch engine to offline", "engine_offline"),
        ("switch engine to vosk", "engine_offline"),
        ("switch to vosk", "engine_offline"),
        ("switch engine to google", "engine_google"),
        ("switch to google", "engine_google"),
        ("change my engine to whisper", "engine_whisper"),
        ("use the google engine", None),  # not a phrasing we support
    ):
        reply, _ = handle(phrase)
        got = pop_gui_action()
        assert got == action, (phrase, reply, got, action)
    # A taught phrase with the same words still wins.
    set_custom_store(CustomStore(os.path.join(tmp, "custom2.json")))
    reply, _ = handle(
        "teach aura switch engine to whisper means what is the time")
    assert "Got it" in reply, reply
    reply, _ = handle("switch engine to whisper")
    assert "It's" in reply, reply
    assert pop_gui_action() is None
    # Unrelated commands leave the action alone; help mentions it.
    reply, _ = handle("what is the time")
    assert pop_gui_action() is None
    assert "whisper" in handle("help")[0].lower()

    if not _display_available():
        print("All whisper tests passed "
              "(window tests skipped: no display).")
        return

    # --- Pill: the engine menu has all three engines, and a voice
    # switch syncs the menu. -----------------------------------------
    from aura.gui import IslandGUI

    root = tk.Tk()
    root.withdraw()
    pill = IslandGUI(
        on_mic=lambda: None,
        on_engine_change=lambda e: None,
    )
    try:
        menu = pill.engine_menu["menu"]
        labels = {
            menu.entrycget(i, "label")
            for i in range(menu.index("end") + 1)
        } - {""}
        assert labels == {"offline", "google", "whisper"}, labels
        pill.set_engine("whisper")
        root.update()
        assert pill.engine_var.get() == "whisper"
        pill.set_engine("nope")
        root.update()
        assert pill.engine_var.get() == "whisper"
    finally:
        pill.close()

    # --- Control Center: whisper radio + diagnostics line. ---------
    from aura.control_center import ControlCenter

    mem = Memory(":memory:")
    cc = ControlCenter(
        root, mem,
        on_typed_command=lambda text: None,
        on_theme=lambda name: None,
        on_engine_change=lambda engine: None,
        get_engine=lambda: "whisper",
        get_whisper_info=lambda: {
            "installed": True, "model": "small", "device": "cuda",
            "compute_type": "float16", "loaded": True, "error": None,
        },
        on_close=lambda: None,
    )
    try:
        cc.show_tab("Settings")
        root.update()
        assert cc.engine_var.get() == "whisper"
        cc.show_tab("Diagnostics")
        root.update()
        diag = cc.diag_box.get("1.0", "end")
        assert "Whisper: model 'small', device cuda (float16), loaded" in diag, diag
        assert "Engine: whisper" in diag, diag
    finally:
        cc.close()
        root.destroy()
    print("All whisper tests passed.")


if __name__ == "__main__":
    main()
