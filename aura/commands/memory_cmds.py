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


def parse_memory_command(text: str):
    """Match spoken text to a memory command. None if no match."""
    t = text.strip().lower()

    # --- Reminders (checked before todos: "remind me to X" is both) ---
    m = re.search(r"remind me at (.+?) to (.+)", t)
    if m:
        when, _ = _parse_time("at " + m.group(1))
        if when is not None:
            return {
                "kind": "reminder_add",
                "text": m.group(2).strip(),
                "when": when,
            }
    m = re.search(r"remind me to (.+)", t)
    if m:
        body = m.group(1).strip()
        when, rest = _parse_time(body)
        if when is not None:
            return {"kind": "reminder_add", "text": rest.strip(), "when": when}
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
    m = re.search(r"add (.+?) to (my )?(todo|to-do|task) list", t)
    if m:
        return {"kind": "todo_add", "text": m.group(1).strip()}
    m = re.search(r"add (to my )?(todo|to-do|task) list:? (.+)", t)
    if m:
        return {"kind": "todo_add", "text": m.group(3).strip()}
    if re.search(r"(show|list|what are) my (todos|todo list|tasks)", t) or (
        t in ("my todos", "my todo list")
    ):
        return {"kind": "todo_list"}
    m = re.search(r"(complete|finish) (todo|task)? ?(\d+)", t)
    if m:
        return {"kind": "todo_complete", "number": int(m.group(3))}
    m = re.search(r"mark (todo|task)? ?(\d+) (done|complete)", t)
    if m:
        return {"kind": "todo_complete", "number": int(m.group(2))}

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
        memory.add_todo(cmd["text"])
        if cmd.get("from_reminder"):
            return (
                f"No time mentioned, so I added it to your todo list "
                f"instead of setting a reminder: {cmd['text']}."
            )
        return f"Added to your todo list: {cmd['text']}."
    if kind == "todo_list":
        rows = memory.list_todos()
        if not rows:
            return "Your todo list is empty. Nice work."
        return f"Your todos: {_numbered(rows)}."
    if kind == "todo_complete":
        text = memory.complete_todo(cmd["number"])
        if text is None:
            return f"There is no todo number {cmd['number']}."
        return f"Done: {text}."

    if kind == "reminder_add":
        memory.add_reminder(cmd["text"], cmd["when"])
        return f"Reminder set for {_fmt_time(cmd['when'])}: {cmd['text']}."
    if kind == "reminder_list":
        rows = memory.list_reminders()
        if not rows:
            return "You don't have any reminders set."
        parts = "; ".join(
            f"{i}. {row['text']} at "
            f"{datetime.strptime(row['remind_at'], '%Y-%m-%d %H:%M:%S').strftime('%I:%M %p').lstrip('0')}"
            for i, row in enumerate(rows, 1)
        )
        return f"Your reminders: {parts}."
    if kind == "reminder_cancel":
        text = memory.cancel_reminder(cmd["number"])
        if text is None:
            return f"There is no reminder number {cmd['number']}."
        return f"Cancelled reminder: {text}."

    return "I don't know how to do that yet."
