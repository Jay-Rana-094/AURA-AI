"""Proactive morning briefing — Phase 9.2A.

AURA speaks the daily briefing unprompted once each morning at a
configured time (default 8:00 AM). The scheduler lives in main.py
(a light thread that checks the clock every 30 seconds); this
module owns only the settings, the time parsing, and the pure
should-it-fire decision, so all of it is unit-testable with no
waiting and no window.

The rules (Jay's spec, 2026-11-15):
  - Only while AURA is running. AURA is not a service — it cannot
    wake the PC or speak when it is closed.
  - Never twice in one day: the fired date is persisted in
    aura_settings.json, so a restart after the briefing does not
    fire it again.
  - Never late: if AURA starts after the configured time, that
    day is skipped — a "morning briefing" at noon is not a
    morning briefing. The scheduler records when it started and
    the decision function checks it.
  - A short grace window (10 minutes) covers a poll landing just
    after the time, or the PC waking from sleep right after it —
    beyond that, the day is missed, not chased.

Settings live in aura_settings.json next to main.py (same file
as the wake word, theme, language and chat flag), so they survive
restarts. Voice: "turn off morning briefing" / "turn on morning
briefing" / "set morning briefing to 7:30" / "when is my morning
briefing". The Control Center Settings tab has the same controls.
"""

import json
import os
import re
from datetime import datetime, timedelta

DEFAULT_BRIEFING_TIME = "08:00"
DEFAULT_BRIEFING_ENABLED = True
# Fire at most this long after the configured time.
_GRACE_MINUTES = 10

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura_settings.json",
)


def set_settings_path(path: str) -> None:
    """Point storage elsewhere — used by tests (temp file)."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def is_morning_enabled() -> bool:
    """The morning briefing is ON by default — Jay asked for it
    (Phase 9.2A). Saying "turn off morning briefing" persists
    False and is the only way to stop it."""
    return bool(_load_settings().get("morning_briefing", True))


def set_morning_enabled(enabled: bool) -> None:
    """Persist the morning-briefing flag (already validated)."""
    data = _load_settings()
    data["morning_briefing"] = bool(enabled)
    _save_settings(data)


def get_morning_time() -> str:
    """The configured time as "HH:MM" (24-hour), or the default
    when nothing valid was ever saved."""
    raw = _load_settings().get("morning_briefing_time", DEFAULT_BRIEFING_TIME)
    if isinstance(raw, str):
        try:
            datetime.strptime(raw, "%H:%M")
            return raw
        except ValueError:
            pass
    return DEFAULT_BRIEFING_TIME


def set_morning_time(hhmm: str) -> None:
    """Persist a time as "HH:MM". Raises ValueError on a bad value
    — the caller speaks the error instead of saving garbage."""
    datetime.strptime(hhmm, "%H:%M")  # raises ValueError when invalid
    data = _load_settings()
    data["morning_briefing_time"] = hhmm
    _save_settings(data)


def get_last_fired():
    """The date ("YYYY-MM-DD") the briefing last fired, or None."""
    raw = _load_settings().get("morning_briefing_last")
    if isinstance(raw, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return None


def mark_fired(date_str: str | None = None) -> None:
    """Record that the briefing fired (today by default)."""
    data = _load_settings()
    data["morning_briefing_last"] = (
        date_str or datetime.now().strftime("%Y-%m-%d")
    )
    _save_settings(data)


def format_briefing_time(hhmm: str) -> str:
    """'08:00' -> '8:00 AM', '19:30' -> '7:30 PM'."""
    when = datetime.strptime(hhmm, "%H:%M")
    return when.strftime("%I:%M %p").lstrip("0")


def parse_briefing_time(text: str):
    """Parse a spoken time into "HH:MM" (24-hour), or None.

    Accepts "7:30", "7:30 am", "7:30 pm", "7 am", "7 pm",
    "19:30". With no am/pm marker, an hour of 1-12 is
    read as AM — this is a *morning* briefing, so "7:30" means
    7:30 in the morning, not the evening.
    """
    t = text.strip().lower().rstrip(".!?")
    match = re.match(
        r"^(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?$", t
    )
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = (match.group(3) or "").replace(".", "")
    if minute > 59:
        return None
    if marker:
        if hour < 1 or hour > 12:
            return None
        if marker == "pm" and hour != 12:
            hour += 12
        elif marker == "am" and hour == 12:
            hour = 0
    else:
        if hour > 23:
            return None
        # No marker and a 1-12 hour: morning, so AM.
    return f"{hour:02d}:{minute:02d}"


def should_fire(now: datetime, scheduled: str, last_fired=None,
                started_at=None) -> bool:
    """Pure decision: should the briefing fire right now?

    ``now`` is the current time, ``scheduled`` the configured
    "HH:MM", ``last_fired`` the persisted "YYYY-MM-DD" (or None),
    ``started_at`` when the scheduler thread started (or None
    when the caller does not track it). True only when all of
    these hold: not already fired today; now is at or just after
    the scheduled time (within the grace window); and AURA did
    not start after the scheduled time today.
    """
    if last_fired == now.strftime("%Y-%m-%d"):
        return False
    try:
        sched = datetime.strptime(scheduled, "%H:%M")
    except ValueError:
        return False
    sched_dt = now.replace(hour=sched.hour, minute=sched.minute,
                           second=0, microsecond=0)
    if now < sched_dt:
        return False
    if now > sched_dt + timedelta(minutes=_GRACE_MINUTES):
        return False
    if (started_at is not None
            and started_at.date() == now.date()
            and started_at.time() > sched_dt.time()):
        return False
    return True


def morning_status() -> dict:
    """One dict for the Control Center + Diagnostics tab."""
    time_str = get_morning_time()
    return {
        "enabled": is_morning_enabled(),
        "time": time_str,
        "time_display": format_briefing_time(time_str),
        "last_fired": get_last_fired(),
    }


def parse_morning_command(text: str):
    """Match spoken text to a morning-briefing request.
    None if no match."""
    t = text.strip().lower()
    if t in (
        "turn off morning briefing",
        "disable morning briefing",
        "turn morning briefing off",
        "disable the morning briefing",
        "turn off the morning briefing",
        "stop morning briefing",
        "stop the morning briefing",
    ):
        return {"kind": "toggle_off"}
    if t in (
        "turn on morning briefing",
        "enable morning briefing",
        "turn morning briefing on",
        "enable the morning briefing",
        "turn on the morning briefing",
    ):
        return {"kind": "toggle_on"}
    if t in (
        "is morning briefing on",
        "morning briefing status",
        "when is my morning briefing",
        "what time is my morning briefing",
        "morning briefing time",
    ):
        return {"kind": "status"}
    match = re.match(
        r"(set|change)( the| my)? morning briefing( time)? to (.+)$", t
    )
    if match:
        return {
            "kind": "set_time",
            "time": parse_briefing_time(match.group(4)),
            "raw": match.group(4).strip(),
        }
    return None


def execute_morning_command(cmd: dict):
    """Run a parsed morning-briefing command.

    Returns (reply, gui_action): the reply to speak, and a
    "morning_refresh" action when the open Control Center must
    follow the change (same channel as chat mode's
    "chat_refresh" — the brain records it and main.py applies
    it). Status questions return no action.
    """
    kind = cmd["kind"]
    if kind == "toggle_off":
        set_morning_enabled(False)
        return ("Morning briefing is off — I won't speak the "
                "briefing in the morning anymore."), "morning_refresh"
    if kind == "toggle_on":
        set_morning_enabled(True)
        when = format_briefing_time(get_morning_time())
        return (
            f"Morning briefing is on — I'll speak your daily "
            f"briefing at {when} every morning.",
            "morning_refresh",
        )
    if kind == "set_time":
        if cmd["time"] is None:
            return (
                "I didn't understand that time — try something like "
                "'set morning briefing to 7:30 AM'.",
                None,
            )
        set_morning_time(cmd["time"])
        if not is_morning_enabled():
            set_morning_enabled(True)
            note = " I've turned the morning briefing on too."
        else:
            note = ""
        return (
            f"Morning briefing set for "
            f"{format_briefing_time(cmd['time'])}.{note}",
            "morning_refresh",
        )
    if kind == "status":
        status = morning_status()
        if not status["enabled"]:
            return "Morning briefing is off.", None
        fired = status["last_fired"]
        fired_note = (
            f" It last fired on {fired}."
            if fired else " It hasn't fired yet."
        )
        return (
            f"Morning briefing is on, at {status['time_display']} "
            f"every morning.{fired_note}",
            None,
        )
    return "I don't know how to do that yet.", None
