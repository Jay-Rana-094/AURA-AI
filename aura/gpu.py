"""GPU telemetry — Phase 9.1.

The Control Center's Diagnostics tab already shows CPU / RAM /
disk / battery via psutil, but psutil cannot see the GPU. This
module reads it with GPUtil, which shells out to nvidia-smi —
already on Jay's PC with the NVIDIA driver (RTX 3050, driver
546.56). GPUtil is a pure helper: no tkinter, no side effects,
so it is unit-testable anywhere (tests stub the GPUtil module
in sys.modules, the same way test_whisper.py stubs
faster-whisper).

    get_gpu_info() -> dict
    format_gpu_info(info) -> [lines]   (Diagnostics tab)
    describe_gpu(info) -> str          (spoken reply)

When GPUtil is missing or there is no NVIDIA GPU, the dict is
{"available": False, "reason": ...} and the Diagnostics tab
shows that reason honestly instead of crashing.
"""

import re


def get_gpu_info() -> dict:
    """One dict for the first GPU, or {"available": False,
    "reason": ...}. GPUtil is imported lazily so this module
    imports fine on a PC where it is not installed yet."""
    try:
        import GPUtil
    except Exception:  # noqa: BLE001 - missing package is a state, not a crash
        return {
            "available": False,
            "reason": "GPUtil is not installed — "
                      "run: pip install -r requirements.txt",
        }
    try:
        gpus = GPUtil.getGPUs()
    except Exception as exc:  # noqa: BLE001 - telemetry never breaks the window
        return {"available": False, "reason": f"GPU read failed: {exc}"}
    if not gpus:
        return {
            "available": False,
            "reason": "No NVIDIA GPU detected on this PC.",
        }
    gpu = gpus[0]  # Jay's PC has one GPU (RTX 3050); take the first.
    return {
        "available": True,
        "name": gpu.name,
        "load": round(gpu.load * 100),  # GPUtil reports load as 0..1
        "memory_used_gb": gpu.memoryUsed / 1024,  # GPUtil reports MB
        "memory_total_gb": gpu.memoryTotal / 1024,
        "temperature": gpu.temperature,
    }


def format_gpu_info(info: dict) -> list:
    """One text line per GPU stat, for the Diagnostics tab."""
    if not info.get("available"):
        return [f"GPU: {info.get('reason', 'unavailable')}"]
    return [
        f"GPU: {info['name']}",
        f"GPU load: {info['load']}%  "
        f"({info['memory_used_gb']:.1f} GB of "
        f"{info['memory_total_gb']:.1f} GB VRAM)",
        f"GPU temperature: {info['temperature']:.0f}°C",
    ]


def describe_gpu(info: dict) -> str:
    """One spoken sentence with the numbers."""
    if not info.get("available"):
        return f"I can't see a GPU on this PC — {info.get('reason', 'unavailable')}"
    return (
        f"Your GPU, {info['name']}, is at {info['load']}% load, "
        f"using {info['memory_used_gb']:.1f} of "
        f"{info['memory_total_gb']:.1f} GB of video memory, "
        f"at {info['temperature']:.0f} degrees."
    )


def parse_gpu_command(text: str):
    """Match spoken text to a GPU-usage question. None if no match."""
    t = text.strip().lower()
    if t in (
        "gpu usage",
        "gpu status",
        "what's my gpu usage",
        "what is my gpu usage",
        "how is my gpu",
        "how's my gpu",
        "what's my gpu doing",
        "gpu temperature",
        "how hot is my gpu",
    ):
        return {"kind": "gpu_usage"}
    if re.search(r"\bgpu (usage|status|load|temperature|temp)\b", t):
        return {"kind": "gpu_usage"}
    return None


def execute_gpu_command(cmd: dict) -> str:
    """Answer a GPU question. ``cmd`` is unused for now — the
    only kind is "gpu_usage" — but the parse/execute split stays,
    like the other packs."""
    return describe_gpu(get_gpu_info())
