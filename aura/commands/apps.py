"""App launcher pack (Windows).

Allow-list only: voice can open exactly the apps named here, nothing
else. If the executable is not on this PC, AURA says so instead of
failing silently.
"""

import shutil
import subprocess

# Spoken name -> executable. Aliases included so "open vs code",
# "open code" and "open vscode" all work.
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "vs code": "code.exe",
    "vscode": "code.exe",
    "code": "code.exe",
    "paint": "mspaint.exe",
    "terminal": "wt.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "spotify": "spotify.exe",
}


def find_app(target: str):
    """Return (spoken_name, exe) for a target, or None.

    Matches when the target equals an app name or contains one
    ("open vs code please" -> "vs code").
    """
    target = target.strip().lower()
    if target in APPS:
        return target, APPS[target]
    # Longest names first so "vs code" wins over "code".
    for name in sorted(APPS, key=len, reverse=True):
        if name in target:
            return name, APPS[name]
    return None


def open_app(name: str, exe: str) -> str:
    if shutil.which(exe) is None:
        return f"I couldn't find {name} on this PC."
    try:
        subprocess.Popen([exe])
    except OSError:
        return f"I couldn't open {name}."
    return f"Opening {name}."
