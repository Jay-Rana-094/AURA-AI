"""Clipboard control — Phase 6.

Read the clipboard aloud, copy AURA's last reply (from
conversation history) or a spoken phrase to it, and clear it.
Windows only, using PowerShell's built-in Get-Clipboard /
Set-Clipboard — no new packages, no window pops up.

The PowerShell access lives behind three small module-level
functions (_read_clipboard, _write_clipboard, _clear_clipboard)
so tests can stub them without a Windows box. The executor never
checks the platform itself: on a non-Windows machine the real
accessors fail and the reply says so.
"""

import platform
import re
import subprocess

_READ_LIMIT = 300  # spoken read-backs stay short


def _run_hidden_ps(script: str):
    """Run a PowerShell script with no window. Returns (rc, out, err)."""
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
        timeout=30,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    return proc.returncode, proc.stdout, proc.stderr.strip()


def _read_clipboard():
    """Text on the clipboard, "" if empty, None on failure."""
    if platform.system() != "Windows":
        return None
    try:
        rc, out, _ = _run_hidden_ps("Get-Clipboard -Raw")
    except Exception:  # noqa: BLE001 - any failure reads as None
        return None
    if rc != 0:
        return None
    return out.strip()


def _write_clipboard(text: str) -> bool:
    """Put ``text`` on the clipboard. False on failure."""
    if platform.system() != "Windows":
        return False
    safe = text.replace("'", "''")
    try:
        rc, _, _ = _run_hidden_ps(f"Set-Clipboard -Value '{safe}'")
    except Exception:  # noqa: BLE001 - any failure reads as False
        return False
    return rc == 0


def _clear_clipboard() -> bool:
    """Empty the clipboard. False on failure."""
    if platform.system() != "Windows":
        return False
    try:
        rc, _, _ = _run_hidden_ps("Set-Clipboard -Value ''")
    except Exception:  # noqa: BLE001 - any failure reads as False
        return False
    return rc == 0


def _windows_note() -> str:
    """Explainer appended to failures off Windows."""
    if platform.system() == "Windows":
        return ""
    return " Clipboard control works on Windows."


def parse_clipboard_command(text: str):
    """Match spoken text to a clipboard request. None if no match."""
    t = text.strip().lower()
    # "copy that" first: the generic copy-text pattern below would
    # otherwise swallow "that" as literal text to copy.
    if t in (
        "copy that",
        "copy that to clipboard",
        "copy it",
        "copy it to clipboard",
        "copy your last reply",
        "copy your last reply to clipboard",
    ):
        return {"kind": "copy_last"}
    m = re.match(r"^copy (.+) to (the )?clipboard$", t)
    if m:
        return {"kind": "copy_text", "text": m.group(1)}
    if (
        re.search(r"\b(read|show|check|what'?s on|what is on)( my| the)? clipboard\b", t)
        or t in ("what did i copy", "what's copied", "whats copied")
    ):
        return {"kind": "read"}
    if re.search(r"\b(clear|empty)( my| the)? clipboard\b", t):
        return {"kind": "clear"}
    return None


def execute_clipboard_command(cmd: dict, memory) -> str:
    """Carry out a parsed clipboard command and reply."""
    kind = cmd["kind"]
    if kind == "read":
        text = _read_clipboard()
        if text is None:
            return f"I couldn't read the clipboard.{_windows_note()}"
        if not text:
            return "Your clipboard is empty."
        spoken = " ".join(text.split())
        if len(spoken) > _READ_LIMIT:
            spoken = spoken[:_READ_LIMIT].rsplit(" ", 1)[0] + "…"
        return f"Your clipboard says: {spoken}"
    if kind == "copy_last":
        # The current turn ("copy that") is not recorded yet, so the
        # newest recorded turn is exactly "my last reply".
        turns = memory.recent_turns(1)
        if not turns:
            return "I haven't said anything yet to copy."
        if _write_clipboard(turns[0]["reply_text"]):
            return "Copied my last reply to the clipboard."
        return f"I couldn't write to the clipboard.{_windows_note()}"
    if kind == "copy_text":
        if _write_clipboard(cmd["text"]):
            return f"Copied '{cmd['text']}' to the clipboard."
        return f"I couldn't write to the clipboard.{_windows_note()}"
    if kind == "clear":
        if _clear_clipboard():
            return "Clipboard cleared."
        return f"I couldn't clear the clipboard.{_windows_note()}"
    return "Sorry, I didn't catch that clipboard request."
