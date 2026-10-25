"""System control pack (Windows only).

Volume and media keys use the standard Windows virtual-key codes via
ctypes — no extra packages. Shutdown / restart / sleep are NEVER run
directly from a single utterance: the brain holds them as a pending
action and only executes after the user says yes (see brain.py).
"""

import platform
import subprocess

# Kinds that require spoken confirmation before executing.
CONFIRM_KINDS = {"shutdown", "restart", "sleep"}

CONFIRM_TEXT = {
    "shutdown": "shut down your PC",
    "restart": "restart your PC",
    "sleep": "put your PC to sleep",
}

_VK = {
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
}


def _press_key(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)  # key down
    user32.keybd_event(vk, 0, 2, 0)  # key up (KEYEVENTF_KEYUP)


def media_key(action: str) -> str:
    if platform.system() != "Windows":
        return "Media keys only work on Windows."
    _press_key(_VK[action])
    return {
        "volume_up": "Volume up.",
        "volume_down": "Volume down.",
        "mute": "Muted.",
        "play_pause": "Play / pause.",
        "next": "Next track.",
        "previous": "Previous track.",
    }[action]


def lock() -> str:
    if platform.system() != "Windows":
        return "Locking only works on Windows."
    import ctypes

    ctypes.windll.user32.LockWorkStation()
    return "Locking your PC."


def power(action: str) -> str:
    """Run a confirmed power action. Only called after a yes."""
    if platform.system() != "Windows":
        return "Power controls only work on Windows."
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "0"])
        return "Shutting down."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "0"])
        return "Restarting."
    if action == "sleep":
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        )
        return "Going to sleep."
    return "Unknown power action."
