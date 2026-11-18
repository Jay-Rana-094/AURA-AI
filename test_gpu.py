"""Tests for Phase 9.1 — GPU usage in Diagnostics.

GPUtil is not installed on this VM, so the GPU is stubbed in
sys.modules (same pattern as test_whisper.py stubs
faster-whisper): a fake RTX 3050, a missing package, an empty
GPU list, and a failing read.

    python test_gpu.py
"""

import os
import sys
import tempfile
import types

from aura.brain import (
    handle,
    pop_gui_action,
    set_custom_store,
    set_memory,
)
from aura.chat import set_chat_enabled
from aura.chat import set_key_file_path as set_chat_key_file_path
from aura.chat import set_settings_path as set_chat_settings_path
from aura.commands.custom import CustomStore
from aura.gpu import (
    describe_gpu,
    execute_gpu_command,
    format_gpu_info,
    get_gpu_info,
    parse_gpu_command,
)
from aura.language import set_settings_path as set_language_settings_path
from aura.memory import Memory


class _FakeGPU:
    def __init__(self):
        self.name = "NVIDIA GeForce RTX 3050 6GB Laptop GPU"
        self.load = 0.23
        self.memoryUsed = 1536
        self.memoryTotal = 6144
        self.temperature = 54


def _install_gputil_stub(gpus):
    stub = types.ModuleType("GPUtil")
    stub.getGPUs = lambda: gpus
    sys.modules["GPUtil"] = stub


def main():
    tmp = tempfile.mkdtemp()
    set_chat_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_key_file_path(os.path.join(tmp, "groq_api_key.txt"))
    set_language_settings_path(os.path.join(tmp, "settings.json"))
    set_chat_enabled(False)
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))

    # --- With a GPU: load %, VRAM, temperature. -------------------
    _install_gputil_stub([_FakeGPU()])
    info = get_gpu_info()
    assert info["available"] is True, info
    assert info["name"] == "NVIDIA GeForce RTX 3050 6GB Laptop GPU"
    assert info["load"] == 23, info
    assert info["memory_used_gb"] == 1.5, info
    assert info["memory_total_gb"] == 6.0, info
    assert info["temperature"] == 54, info

    lines = format_gpu_info(info)
    assert any("RTX 3050" in line for line in lines), lines
    assert any("23%" in line for line in lines), lines
    assert any("1.5 GB of 6.0 GB" in line for line in lines), lines
    assert any("54" in line and "C" in line for line in lines), lines

    spoken = describe_gpu(info)
    assert "23%" in spoken and "1.5" in spoken and "54" in spoken, spoken

    # --- Missing package: honest, never a crash. ------------------
    sys.modules.pop("GPUtil", None)
    info = get_gpu_info()
    assert info["available"] is False, info
    assert "GPUtil" in info["reason"] and "pip install" in info["reason"], info
    assert format_gpu_info(info) == [f"GPU: {info['reason']}"]
    assert "can't see a GPU" in describe_gpu(info), describe_gpu(info)

    # --- No GPU at all, and a failing read. -----------------------
    _install_gputil_stub([])
    info = get_gpu_info()
    assert info["available"] is False, info
    assert "No NVIDIA GPU" in info["reason"], info

    stub = types.ModuleType("GPUtil")

    def _boom():
        raise RuntimeError("nvidia-smi not found")

    stub.getGPUs = _boom
    sys.modules["GPUtil"] = stub
    info = get_gpu_info()
    assert info["available"] is False, info
    assert "GPU read failed" in info["reason"], info
    sys.modules.pop("GPUtil", None)

    # --- Parser: every phrasing, and no false friends. ------------
    for phrase in (
        "gpu usage",
        "gpu status",
        "what's my gpu usage",
        "what is my gpu usage",
        "how is my gpu",
        "how's my gpu",
        "gpu temperature",
        "how hot is my gpu",
        "what's my gpu load",
    ):
        assert parse_gpu_command(phrase) is not None, phrase
    assert parse_gpu_command("what is the time") is None
    assert parse_gpu_command("open spotify") is None

    # --- Voice end to end through handle(). -----------------------
    _install_gputil_stub([_FakeGPU()])
    try:
        reply, quit_ = handle("what's my gpu usage")
        assert "23%" in reply and "RTX 3050" in reply, reply
        assert not quit_
        reply, _ = handle("gpu status")
        assert "54" in reply, reply
        # A taught phrase with the same words still wins.
        set_custom_store(CustomStore(os.path.join(tmp, "custom2.json")))
        reply, _ = handle(
            "teach aura what's my gpu usage means what is the time")
        assert "Got it" in reply, reply
        reply, _ = handle("what's my gpu usage")
        assert "It's" in reply, reply
        # Unrelated commands leave the GPU alone; help mentions it.
        reply, _ = handle("what is the time")
        assert "23%" not in reply, reply
        assert "gpu" in handle("help")[0].lower()
        # Without a GPU the voice answer stays honest.
        sys.modules.pop("GPUtil", None)
        reply, _ = handle("gpu usage")
        assert "can't see a GPU" in reply, reply
    finally:
        sys.modules.pop("GPUtil", None)

    # --- execute_gpu_command is the same answer as describe. ------
    _install_gputil_stub([_FakeGPU()])
    try:
        assert execute_gpu_command({"kind": "gpu_usage"}) == describe_gpu(
            get_gpu_info()
        )
    finally:
        sys.modules.pop("GPUtil", None)

    print("All GPU tests passed.")


if __name__ == "__main__":
    main()
