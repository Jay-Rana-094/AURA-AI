"""System control pack (Windows only).

Volume and media keys use the standard Windows virtual-key codes via
ctypes — no extra packages. Shutdown / restart / sleep are NEVER run
directly from a single utterance: the brain holds them as a pending
action and only executes after the user says yes (see brain.py).

Phase 5.1 (2026-10-27): screenshots via .NET
(System.Drawing, no new packages) and Bluetooth / Wi-Fi / airplane
mode via PowerShell + the Windows.Devices.Radios WinRT API. The
radio scripts cannot be tested on a non-Windows machine, so they
need an on-PC test; failures surface as a spoken error reply.
"""

import os
import platform
import subprocess
from datetime import datetime

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


def _run_hidden_ps(script: str):
    """Run a PowerShell script with no window. Returns (rc, stderr)."""
    startupinfo = None
    creationflags = 0
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    return proc.returncode, proc.stderr.strip()


def _screenshot_script(path: str) -> str:
    """Capture the virtual screen (all monitors) to ``path`` as PNG."""
    safe = path.replace("'", "''")
    return (
        "Add-Type -AssemblyName System.Drawing; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
        "$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height); "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size); "
        f"$bmp.Save('{safe}', [System.Drawing.Imaging.ImageFormat]::Png)"
    )


def screenshot() -> str:
    """Take a screenshot, saved under Pictures/AURA Screenshots."""
    if platform.system() != "Windows":
        return "Screenshots only work on Windows."
    folder = os.path.join(
        os.path.expanduser("~"), "Pictures", "AURA Screenshots"
    )
    os.makedirs(folder, exist_ok=True)
    name = datetime.now().strftime("screenshot-%Y%m%d-%H%M%S.png")
    path = os.path.join(folder, name)
    rc, err = _run_hidden_ps(_screenshot_script(path))
    if rc != 0:
        return f"Screenshot failed: {err or 'unknown error'}."
    return f"Screenshot saved: {name}."


_RADIO_PREAMBLE = (
    "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
    "$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
    "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and "
    "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]; "
    "$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
    "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and "
    "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]; "
    "function Await-Op($op, $resultType) { "
    "$task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op)); "
    "$task.Wait(-1) | Out-Null; $task.Result }; "
    "function Await-Action($op) { "
    "$task = $asTaskAction.Invoke($null, @($op)); "
    "$task.Wait(-1) | Out-Null }; "
    "[Windows.Devices.Radios.Radio, Windows.Devices.Radios, "
    "ContentType = WindowsRuntime] | Out-Null; "
    "$access = Await-Op ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) "
    "([Windows.Devices.Radios.RadioAccessStatus]); "
    "if ($access -ne 'Allowed') { throw \"Radio access not allowed: $access\" }; "
    "$radios = Await-Op ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) "
    "([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]); "
)


def _radio_script(kind: str | None, state: str) -> str:
    """Build the WinRT radio script.

    ``kind`` is a WinRT RadioKind name ("Bluetooth"/"WiFi") or None
    for airplane mode, which sets every radio. ``state`` is "On"
    or "Off".
    """
    state_enum = f"[Windows.Devices.Radios.RadioState]::{state}"
    if kind is None:
        action = (
            "foreach ($r in $radios) { "
            f"Await-Action ($r.SetStateAsync({state_enum})) }}"
        )
    else:
        action = (
            f"$target = $radios | Where-Object {{ $_.Kind -eq '{kind}' }} "
            "| Select-Object -First 1; "
            f"if ($null -eq $target) {{ throw 'No {kind} radio found' }} "
            f"Await-Action ($target.SetStateAsync({state_enum}))"
        )
    return _RADIO_PREAMBLE + action


def set_radio(kind: str, state: str) -> str:
    """Set a radio. kind: 'bluetooth' | 'wifi' | 'airplane'.

    Airplane mode sets every radio at once (off = radios off,
    on = radios back on). Voice keeps working locally either way:
    the offline engine needs no connection.
    """
    if platform.system() != "Windows":
        return "Radio controls only work on Windows."
    if kind == "airplane":
        script = _radio_script(None, state)
        label = "Airplane mode"
    else:
        win_kind = {"bluetooth": "Bluetooth", "wifi": "WiFi"}[kind]
        script = _radio_script(win_kind, state)
        label = {"bluetooth": "Bluetooth", "wifi": "Wi-Fi"}[kind]
    rc, err = _run_hidden_ps(script)
    if rc != 0:
        return f"{label} toggle failed: {err or 'unknown error'}."
    return f"{label} {'on' if state == 'On' else 'off'}."
