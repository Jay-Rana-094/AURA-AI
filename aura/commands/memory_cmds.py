"""Memory commands — Phase 3 (notes, todos, reminders).

Parsing is separated from executing, like the Phase 2 packs:
  parse_memory_command(text) -> dict | None   (no side effects)
  execute_memory_command(cmd, memory) -> reply str

Time language understood for reminders:
  "in 30 minutes", "in 2 hours",
  "at 5 pm", "at 5:30 pm", "at 17:30",
  "tomorrow at 9 am".
A bare hour ("at 5") is read as pm — the usual spoken meaning.
If the time already passed today, it rolls to tomorrow.
"No time" + "remind me to X" becomes a todo instead of a reminder.

Phase 5 — repeating reminders:
  "remind me to X every day at 9 am" (daily),
  "remind me to X every Monday at 8 am" (weekly, that weekday),
  "remind me every day at 9 am to X" (same, other word order).
A repeating reminder needs a time; without one AURA says so
instead of silently storing a one-shot. Repeating reminders are
listed/cancelled separately ("list my recurring reminders",
"cancel recurring reminder 1").
"""

import re
from datetime import datetime, timedelta

_WORD_NUMS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _normalize_numbers(body: str) -> str:
    """Rewrite spoken numbers as digits before time parsing.

    Offline recognizers often transcribe "in one minute" or "at five
    pm" as words, not digits. Without this, those reminders silently
    lost their time and fell through to the todo fallback (a real
    Phase 3.0 bug: reminders showed up in the todo list and never
    fired, because they were never reminders at all).
    """
    body = re.sub(r"\bp\s*m\b", "pm", body)
    body = re.sub(r"\ba\s*m\b", "am", body)
    body = re.sub(r"\bin half an hour\b", "in 30 minutes", body)
    body = re.sub(r"\bin an? minute\b", "in 1 minute", body)
    body = re.sub(r"\bin an? hour\b", "in 1 hour", body)
    for word, num in _WORD_NUMS.items():
        body = re.sub(rf"\b{word}\b", str(num), body)
    return body


def _hour_24(hour: int, ampm: str | None) -> int:
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    if ampm is None:
        if hour <= 11:
            return hour + 12  # bare hour spoken as pm ("at 5")
        return hour  # 12 = noon, 13-23 = 24-hour clock
    return hour


def _strip_match(body: str, m) -> str:
    """Body with the matched span removed, whitespace collapsed."""
    return " ".join((body[: m.start()] + " " + body[m.end() :]).split())


def _parse_time(body: str):
    """Find a time expression in ``body``.

    Returns (datetime | None, body_without_time_expr).
    """
    body = _normalize_numbers(body)
    now = datetime.now()

    m = re.search(r"\bin (\d+) minutes?\b", body)
    if m:
        when = now + timedelta(minutes=int(m.group(1)))
        return when, _strip_match(body, m)
    m = re.search(r"\bin (\d+) hours?\b", body)
    if m:
        when = now + timedelta(hours=int(m.group(1)))
        return when, _strip_match(body, m)

    m = re.search(
        r"\btomorrow at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", body
    )
    if m:
        hour = _hour_24(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or 0)
        day = now + timedelta(days=1)
        when = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return when, _strip_match(body, m)

    m = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", body)
    if m:
        hour = _hour_24(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or 0)
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        return when, _strip_match(body, m)

    return None, body


def _fmt_time(when: datetime) -> str:
    return when.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


def _parse_priority(text: str):
    """Extract a priority phrase from todo text (Phase 5).

    Returns (priority, stripped_text). "high priority task X",
    "X with high priority" and "X high priority" all work; anything
    else is a plain medium-priority todo.
    """
    m = re.match(r"^(high|medium|low) priority (todo|task)[: ]+(.+)", text)
    if m:
        return m.group(1), m.group(3).strip()
    m = re.match(r"^(high|medium|low) priority[: ]+(.+)", text)
    if m:
        return m.group(1), m.group(2).strip()
    m = re.search(r"\s+(with )?(high|medium|low) priority\s*$", text)
    if m:
        return m.group(2), text[: m.start()].strip()
    return "medium", text


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_recurrence(body: str):
    """Find a repeat phrase in ``body`` (Phase 5).

    Returns (recurrence | None, weekday | None, body_without_phrase).
    "every day" -> daily; "every week" -> weekly; "every Monday"
    -> weekly on Mondays. Anything else -> no repeat.
    """
    m = re.search(
        r"\bevery (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        body,
    )
    if m:
        return "weekly", _WEEKDAYS[m.group(1)], _strip_match(body, m)
    m = re.search(r"\bevery day\b", body)
    if m:
        return "daily", None, _strip_match(body, m)
    m = re.search(r"\bevery week\b", body)
    if m:
        return "weekly", None, _strip_match(body, m)
    return None, None, body


def _shift_to_weekday(when: datetime, target: int) -> datetime:
    """Move ``when`` forward to the next ``target`` weekday (0=Mon).

    If ``when`` is already on that weekday in the future, it stays.
    """
    days_ahead = (target - when.weekday()) % 7
    if days_ahead == 0 and when <= datetime.now():
        days_ahead = 7
    return when + timedelta(days=days_ahead)


def parse_memory_command(text: str):
    """Match spoken text to a memory command. None if no match."""
    t = text.strip().lower()

    # --- Reminders (checked before todos: "remind me to X" is both) ---
    # "remind me every day at 9 am to X" (repeat phrase first).
    m = re.search(r"remind me every (.+?) to (.+)", t)
    if m:
        recurrence, weekday, time_part = _parse_recurrence(
            "every " + m.group(1)
        )
        when, _ = _parse_time(time_part)
        if when is not None:
            if weekday is not None:
                when = _shift_to_weekday(when, weekday)
            return {
                "kind": "reminder_add",
                "text": m.group(2).strip(),
                "when": when,
                "recurrence": recurrence,
            }
        if recurrence is not None:
            return {
                "kind": "reminder_recurring_no_time",
                "text": m.group(2).strip(),
            }
    m = re.search(r"remind me at (.+?) to (.+)", t)
    if m:
        when, _ = _parse_time("at " + m.group(1))
        if when is not None:
            recurrence, weekday, task = _parse_recurrence(
                m.group(2).strip()
            )
            if weekday is not None:
                when = _shift_to_weekday(when, weekday)
            return {
                "kind": "reminder_add",
                "text": task,
                "when": when,
                "recurrence": recurrence,
            }
    m = re.search(r"remind me to (.+)", t)
    if m:
        body = m.group(1).strip()
        recurrence, weekday, body = _parse_recurrence(body)
        when, rest = _parse_time(body)
        if when is not None:
            if weekday is not None:
                when = _shift_to_weekday(when, weekday)
            return {
                "kind": "reminder_add",
                "text": rest.strip(),
                "when": when,
                "recurrence": recurrence,
            }
        if recurrence is not None:
            return {
                "kind": "reminder_recurring_no_time",
                "text": rest.strip(),
            }
        # No time found: still a todo, but flagged so the reply says
        # so explicitly instead of silently pretending it's a reminder.
        return {"kind": "todo_add", "text": body, "from_reminder": True}

    # --- Notes ---
    m = re.search(r"^(remember|note) (that )?(.+)", t)
    if m:
        body = m.group(3).strip()
        if body.startswith("to "):
            return {"kind": "todo_add", "text": body[3:].strip()}
        return {"kind": "note_add", "text": body}
    if re.search(r"what did (you|i) (remember|ask)", t) or re.search(
        r"(show|list|what are) my notes", t
    ):
        return {"kind": "note_list"}
    m = re.search(r"delete note (\d+)", t)
    if m:
        return {"kind": "note_delete", "number": int(m.group(1))}

    # --- Todos ---
    m = re.search(r"add (high|medium|low) priority (todo|task) (.+)", t)
    if m:
        text = re.sub(
            r"\s+to (my )?(todo|to-do|task) list\s*$",
            "",
            m.group(3).strip(),
        )
        return {"kind": "todo_add", "text": text, "priority": m.group(1)}
    m = re.search(r"add (.+?) to (my )?(todo|to-do|task) list", t)
    if m:
        # Anything after "... list" may carry the priority.
        raw = m.group(1).strip() + t[m.end() :]
        priority, text = _parse_priority(raw)
        return {"kind": "todo_add", "text": text, "priority": priority}
    m = re.search(r"add (to my )?(todo|to-do|task) list:? (.+)", t)
    if m:
        priority, text = _parse_priority(m.group(3).strip())
        return {"kind": "todo_add", "text": text, "priority": priority}
    if re.search(r"(show|list|what are) my (todos|todo list|tasks)", t) or (
        t in ("my todos", "my todo list")
    ):
        return {"kind": "todo_list"}
    m = re.search(
        r"(show|list|what are) my (high|medium|low) priority "
        r"(todos|todo list|tasks)",
        t,
    )
    if m:
        return {"kind": "todo_list_priority", "priority": m.group(2)}
    m = re.search(
        r"(set|make|mark|change) (todo|task) ?(\d+) "
        r"(to |as )?(high|medium|low) priority",
        t,
    )
    if m:
        return {
            "kind": "todo_set_priority",
            "number": int(m.group(3)),
            "priority": m.group(5),
        }
    m = re.search(r"(complete|finish) (todo|task)? ?(\d+)", t)
    if m:
        return {"kind": "todo_complete", "number": int(m.group(3))}
    m = re.search(r"mark (todo|task)? ?(\d+) (done|complete)", t)
    if m:
        return {"kind": "todo_complete", "number": int(m.group(2))}

    # --- Reminders: recurring list / cancel (before the generic ones) ---
    if (
        re.search(r"(show|list|what are) my recurring reminders", t)
        or t == "my recurring reminders"
    ):
        return {"kind": "reminder_recurring_list"}
    m = re.search(r"(cancel|stop|delete) recurring reminder (\d+)", t)
    if m:
        return {"kind": "reminder_recurring_cancel", "number": int(m.group(2))}

    # --- Reminders: list / cancel ---
    if re.search(r"(show|list|what are) my reminders", t) or t == "my reminders":
        return {"kind": "reminder_list"}
    m = re.search(r"cancel reminder (\d+)", t)
    if m:
        return {"kind": "reminder_cancel", "number": int(m.group(1))}

    return None


def _numbered(rows, key="text") -> str:
    return "; ".join(f"{i}. {row[key]}" for i, row in enumerate(rows, 1))


def execute_memory_command(cmd: dict, memory) -> str:
    """Perform a parsed memory command and return what AURA says."""
    kind = cmd["kind"]

    if kind == "note_add":
        memory.add_note(cmd["text"])
        return "Noted."
    if kind == "note_list":
        rows = memory.list_notes()
        if not rows:
            return "You don't have any notes yet."
        return f"Your notes: {_numbered(rows)}."
    if kind == "note_delete":
        text = memory.delete_note(cmd["number"])
        if text is None:
            return f"There is no note number {cmd['number']}."
        return f"Deleted note: {text}."

    if kind == "todo_add":
        priority = cmd.get("priority", "medium")
        memory.add_todo(cmd["text"], priority)
        if cmd.get("from_reminder"):
            return (
                f"No time mentioned, so I added it to your todo list "
                f"instead of setting a reminder: {cmd['text']}."
            )
        if priority == "high":
            return f"Added as high priority: {cmd['text']}."
        if priority == "low":
            return f"Added as low priority: {cmd['text']}."
        return f"Added to your todo list: {cmd['text']}."
    if kind == "todo_list":
        rows = memory.list_todos()
        if not rows:
            return "Your todo list is empty. Nice work."
        parts = []
        for i, row in enumerate(rows, 1):
            part = f"{i}. {row['text']}"
            prio = row["priority"] if "priority" in row.keys() else None
            if prio == "high":
                part += " [high]"
            elif prio == "low":
                part += " [low]"
            parts.append(part)
        return f"Your todos: {'; '.join(parts)}."
    if kind == "todo_list_priority":
        rows = memory.list_todos(cmd["priority"])
        if not rows:
            return f"You don't have any {cmd['priority']} priority todos."
        return (
            f"Your {cmd['priority']} priority todos: {_numbered(rows)}."
        )
    if kind == "todo_set_priority":
        text = memory.set_todo_priority(cmd["number"], cmd["priority"])
        if text is None:
            return f"There is no todo number {cmd['number']}."
        return (
            f"Todo {cmd['number']} set to {cmd['priority']} priority: "
            f"{text}."
        )
    if kind == "todo_complete":
        text = memory.complete_todo(cmd["number"])
        if text is None:
            return f"There is no todo number {cmd['number']}."
        return f"Done: {text}."

    if kind == "reminder_add":
        memory.add_reminder(cmd["text"], cmd["when"], cmd.get("recurrence"))
        if cmd.get("recurrence") == "daily":
            return (
                f"Repeating every day from {_fmt_time(cmd['when'])}: "
                f"{cmd['text']}."
            )
        if cmd.get("recurrence") == "weekly":
            weekday = cmd["when"].strftime("%A")
            return (
                f"Repeating every {weekday} from {_fmt_time(cmd['when'])}: "
                f"{cmd['text']}."
            )
        return f"Reminder set for {_fmt_time(cmd['when'])}: {cmd['text']}."
    if kind == "reminder_recurring_no_time":
        return (
            "For a repeating reminder I need a time — say it like "
            f"'remind me to {cmd['text']} every day at 9 am'."
        )
    if kind == "reminder_list":
        rows = memory.list_reminders()
        if not rows:
            return "You don't have any reminders set."
        parts = []
        for i, row in enumerate(rows, 1):
            when = datetime.strptime(
                row["remind_at"], "%Y-%m-%d %H:%M:%S"
            )
            part = (
                f"{i}. {row['text']} at "
                f"{when.strftime('%I:%M %p').lstrip('0')}"
            )
            rec = row["recurrence"] if "recurrence" in row.keys() else None
            if rec == "daily":
                part += " (every day)"
            elif rec == "weekly":
                part += f" (every {when.strftime('%A')})"
            parts.append(part)
        return f"Your reminders: {'; '.join(parts)}."
    if kind == "reminder_cancel":
        text = memory.cancel_reminder(cmd["number"])
        if text is None:
            return f"There is no reminder number {cmd['number']}."
        return f"Cancelled reminder: {text}."
    if kind == "reminder_recurring_list":
        rows = memory.list_recurring()
        if not rows:
            return "You don't have any repeating reminders."
        parts = []
        for i, row in enumerate(rows, 1):
            when = datetime.strptime(
                row["remind_at"], "%Y-%m-%d %H:%M:%S"
            )
            if row["recurrence"] == "daily":
                every = "every day"
            else:
                every = f"every {when.strftime('%A')}"
            parts.append(
                f"{i}. {row['text']}, {every}, "
                f"next at {when.strftime('%I:%M %p').lstrip('0')}"
            )
        return f"Your repeating reminders: {'; '.join(parts)}."
    if kind == "reminder_recurring_cancel":
        text = memory.cancel_recurring(cmd["number"])
        if text is None:
            return f"There is no repeating reminder number {cmd['number']}."
        return f"Cancelled repeating reminder: {text}."

    return "I don't know how to do that yet."
