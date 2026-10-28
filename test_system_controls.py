"""Tests for the system-controls batch: screenshot + radio toggles.

The Windows APIs cannot run here, so this tests what can be
tested: phrasing -> parsed command, the generated PowerShell
scripts, the execute wiring (with stubbed system functions), and
the non-Windows guards.

    python test_system_controls.py
"""

import aura.commands as cmds
from aura.commands import execute_command, parse_command
from aura.commands.system import (
    _radio_script,
    _screenshot_script,
    screenshot,
    set_radio,
)


def main():
    # --- Parser: every phrasing lands on the right kind/state. ---
    cases = [
        ("take a screenshot", {"kind": "screenshot"}),
        ("screenshot", {"kind": "screenshot"}),
        ("capture the screen", {"kind": "screenshot"}),
        ("turn on bluetooth", {"kind": "radio", "radio": "bluetooth", "state": "On"}),
        ("turn bluetooth off", {"kind": "radio", "radio": "bluetooth", "state": "Off"}),
        ("switch wifi on", {"kind": "radio", "radio": "wifi", "state": "On"}),
        ("turn wi-fi off", {"kind": "radio", "radio": "wifi", "state": "Off"}),
        ("turn off wi fi", {"kind": "radio", "radio": "wifi", "state": "Off"}),
        ("enable bluetooth", {"kind": "radio", "radio": "bluetooth", "state": "On"}),
        ("disable wifi", {"kind": "radio", "radio": "wifi", "state": "Off"}),
        ("turn on airplane mode", {"kind": "radio", "radio": "airplane", "state": "On"}),
        ("turn airplane mode off", {"kind": "radio", "radio": "airplane", "state": "Off"}),
        ("enable airplane mode", {"kind": "radio", "radio": "airplane", "state": "On"}),
    ]
    for phrase, expected in cases:
        cmd = parse_command(phrase)
        assert cmd is not None, phrase
        for key, value in expected.items():
            assert cmd[key] == value, (phrase, cmd)
    # Neighbours must not be hijacked by the new branches.
    assert parse_command("open notepad")["kind"] == "open_app"
    assert parse_command("lock my pc")["kind"] == "lock"
    assert parse_command("shut down")["kind"] == "shutdown"

    # --- Script generation: the Windows-bound logic, as text. ---
    shot = _screenshot_script("C:\\Users\\Jay\\Pictures\\shot.png")
    assert "CopyFromScreen" in shot and "shot.png" in shot, shot
    bt = _radio_script("Bluetooth", "On")
    assert "Bluetooth" in bt and "RadioState]::On" in bt, bt
    wf = _radio_script("WiFi", "Off")
    assert "WiFi" in wf and "RadioState]::Off" in wf, wf
    ap = _radio_script(None, "Off")
    assert "foreach" in ap and "RadioState]::Off" in ap, ap
    assert "RequestAccessAsync" in bt and "GetRadiosAsync" in bt

    # --- Wiring: execute routes to the system functions. ---
    real_shot, real_radio = cmds.screenshot, cmds.set_radio
    try:
        cmds.screenshot = lambda: "Screenshot saved: shot.png"
        cmds.set_radio = lambda r, s: f"{r} {s}"
        assert execute_command({"kind": "screenshot"}) == (
            "Screenshot saved: shot.png"
        )
        assert execute_command(
            {"kind": "radio", "radio": "wifi", "state": "Off"}
        ) == "wifi Off"
    finally:
        cmds.screenshot, cmds.set_radio = real_shot, real_radio

    # --- Guards: on this non-Windows box, the real functions refuse. ---
    assert screenshot() == "Screenshots only work on Windows."
    assert set_radio("wifi", "On") == "Radio controls only work on Windows."

    print("All system-controls tests passed.")


if __name__ == "__main__":
    main()
