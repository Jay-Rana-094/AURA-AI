"""Daily briefing — Phase 6.

One spoken summary of the day, built only from what AURA already
knows on this PC (no new services, no new keys):
  - greeting + date and time,
  - reminders due today, plus overdue ones,
  - pending todos, high priority first.

Parsing is separated from building, like the other packs:
  parse_briefing_command(text) -> dict | None
  build_briefing(memory, now=None) -> reply str
"""

import re
from datetime import datetime

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _fmt_clock(when: datetime) -> str:
    return when.strftime("%I:%M %p").lstrip("0")


def _greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    if now.hour < 17:
        return "Good afternoon"
    return "Good evening"


def _recurrence_suffix(row) -> str:
    rec = row["recurrence"] if "recurrence" in row.keys() else None
    if rec == "daily":
        return " (every day)"
    if rec == "weekly":
        when = datetime.strptime(row["remind_at"], _TIME_FORMAT)
        return f" (every {when.strftime('%A')})"
    return ""


def build_briefing(memory, now: datetime | None = None) -> str:
    """Compose the briefing from reminders and todos."""
    now = now or datetime.now()
    rows = memory.list_reminders()
    today = []
    overdue = []
    for row in rows:
        when = datetime.strptime(row["remind_at"], _TIME_FORMAT)
        if when <= now:
            overdue.append((row, when))
        elif when.date() == now.date():
            today.append((row, when))

    parts = [
        f"{_greeting(now)}. It's {_fmt_clock(now)} on "
        f"{now.strftime('%A, %B %d')}."
    ]

    if overdue:
        items = "; ".join(
            f"{row['text']} (was {_fmt_clock(when)})"
            for row, when in overdue
        )
        parts.append(f"Overdue reminders: {items}.")
    if today:
        items = "; ".join(
            f"{row['text']} at {_fmt_clock(when)}"
            f"{_recurrence_suffix(row)}"
            for row, when in today
        )
        parts.append(f"Reminders today: {items}.")
    if not overdue and not today:
        parts.append("No reminders due today.")

    todos = memory.list_todos()  # already high-first
    if todos:
        shown = todos[:5]
        items = []
        for row in shown:
            item = row["text"]
            prio = row["priority"] if "priority" in row.keys() else None
            if prio == "high":
                item += " (high priority)"
            elif prio == "low":
                item += " (low priority)"
            items.append(item)
        text = f"Pending todos ({len(todos)}): " + "; ".join(items) + "."
        if len(todos) > 5:
            text += f" And {len(todos) - 5} more."
        parts.append(text)
    else:
        parts.append("Your todo list is clear.")

    return " ".join(parts)


def parse_briefing_command(text: str):
    """Match spoken text to a briefing request. None if no match."""
    t = text.strip().lower()
    if t in (
        "briefing",
        "daily briefing",
        "morning briefing",
        "brief me",
        "good morning",
        "good afternoon",
        "good evening",
    ):
        return {"kind": "briefing"}
    if re.search(r"what'?s (my day look like|on today|on my schedule)", t):
        return {"kind": "briefing"}
    if re.search(r"what do i have (today|on today)", t):
        return {"kind": "briefing"}
    return None
