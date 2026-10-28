"""Notification center — Phase 6.

AURA's own notification history: reminders that fired (spoken by
the reminder loop, and logged so Jay can catch up on anything that
fired while he was away). Listing notifications marks them read;
"clear" empties the log.

This deliberately does NOT read Windows toast notifications: an
unpackaged Python app cannot reliably get that access. If Jay
wants system toasts too, that is a separate, setup-heavy feature.
"""

import re
from datetime import datetime

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _fmt(row) -> str:
    """A notification as one spoken fragment, with its time."""
    when = datetime.strptime(row["created_at"], _TIME_FORMAT)
    clock = when.strftime("%I:%M %p").lstrip("0")
    if when.date() == datetime.now().date():
        return f"{row['text']} at {clock}"
    return f"{row['text']} on {when.strftime('%B %d')} at {clock}"


def parse_notification_command(text: str):
    """Match spoken text to a notification request. None if no match."""
    t = text.strip().lower()
    if t in (
        "clear notifications",
        "clear my notifications",
        "dismiss notifications",
        "dismiss my notifications",
        "delete notifications",
    ):
        return {"kind": "clear"}
    if (
        re.search(r"\bhow many notifications", t)
        or t == "notification count"
    ):
        return {"kind": "count"}
    if (
        re.search(
            r"\b(what|show|any|check|read|list)( my)? notifications?\b", t
        )
        or t in (
            "do i have notifications",
            "do i have any notifications",
            "notifications",
        )
    ):
        return {"kind": "list"}
    return None


def execute_notification_command(cmd: dict, memory) -> str:
    """Carry out a parsed notification command and reply."""
    kind = cmd["kind"]
    if kind == "clear":
        memory.clear_notifications()
        return "Notifications cleared."
    if kind == "count":
        n = memory.unread_notification_count()
        if n == 0:
            return "No new notifications."
        if n == 1:
            return "You have 1 new notification."
        return f"You have {n} new notifications."
    if kind == "list":
        total = memory.unread_notification_count()
        rows = memory.unread_notifications(5)
        if not rows:
            return "No new notifications."
        items = "; ".join(_fmt(row) for row in rows)
        memory.mark_notifications_read()
        plural = "s" if total != 1 else ""
        reply = f"You have {total} new notification{plural}: {items}."
        if total > len(rows):
            reply += f" And {total - len(rows)} more."
        return reply
    return "Sorry, I didn't catch that notification request."
