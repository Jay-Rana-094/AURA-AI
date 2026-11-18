"""Focus Mode voice commands — Phase 10.1.

* "start a 50-minute coding session" / "start a 30-minute session for
  <todo>" (links to an existing todo by substring match; honest when
  no todo matches)
* "start Pomodoro" / "start a 50/10 session"
* "pause my focus session" / "resume my focus session"
* "how much time is remaining?" / "how much time is left in my focus session?"
* "end focus mode" / "end my focus session"
* "start a break" (default 5 minutes)
* "how long have I been focusing?" / "focus history"

The brain owns one FocusManager (``get_focus_manager()``); this module
only parses and executes against it. Breaks move a finished focus
phase into its break automatically via ``FocusManager.poll()`` — the
"start a break" command is for taking one early.
"""

import re

from aura.focus import PRESETS

_START_MINUTES = re.compile(
    r"^start (?:a )?(\d+)[ -]?minute (?:(\w+) )?session(?: for (.+))?$",
    re.IGNORECASE,
)
# "start a focus session for 25 minutes" — the plain-English shape
# from the Phase 10.1 brief. Without this the generic task pattern
# below would read "focus" as a task word and "25 minutes" as a
# todo to link, and answer with a confusing "couldn't find a todo".
_START_SESSION_FOR = re.compile(
    r"^start (?:a )?focus session for (\d+) minutes?$",
    re.IGNORECASE,
)
_START_PRESET = re.compile(
    r"^start (?:a )?(pomodoro|fifty|50/10)(?: (\w+))? session$",
    re.IGNORECASE,
)
_START_POMODORO = re.compile(
    r"^start (?:a )?pomodoro(?: for (.+))?$",
    re.IGNORECASE,
)
_START_TASK = re.compile(
    r"^start (?:a )?(\w+) session(?: for (.+))?$",
    re.IGNORECASE,
)
_PAUSE = re.compile(r"^pause (?:my )?focus(?: session)?$", re.IGNORECASE)
_RESUME = re.compile(r"^resume (?:my )?focus(?: session)?$", re.IGNORECASE)
_REMAINING = re.compile(
    r"^(?:how much time (?:is remaining|is left|do i have left)"
    r"(?: in my focus session)?|how long is my focus session)\??$",
    re.IGNORECASE,
)
_ELAPSED = re.compile(
    r"^how long have i been focusing\??$",
    re.IGNORECASE,
)
_END = re.compile(
    r"^end (?:my )?focus(?: session| mode)?$",
    re.IGNORECASE,
)
_BREAK = re.compile(
    r"^start (?:a )?break(?: for (\d+) minutes?)?$",
    re.IGNORECASE,
)
_HISTORY = re.compile(
    r"^(?:focus history|show my focus history|how much did i focus today)\??$",
    re.IGNORECASE,
)


def _fmt_clock(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_focus_command(text):
    """Return a dict describing the focus command, or None."""
    if not text:
        return None
    t = text.strip()

    m = _START_MINUTES.match(t)
    if m:
        # "for <todo>" is kept separate from the task word: the
        # executor links it to an existing todo and is honest
        # when no todo matches, instead of starting a session
        # named after a todo that doesn't exist.
        return {
            "action": "start",
            "minutes": int(m.group(1)),
            "task": (m.group(2) or "").strip(),
            "for": (m.group(3) or "").strip(),
        }
    m = _START_SESSION_FOR.match(t)
    if m:
        return {
            "action": "start",
            "minutes": int(m.group(1)),
            "task": "",
        }
    m = _START_PRESET.match(t)
    if m:
        name = m.group(1).lower()
        if name == "50/10":
            name = "fifty"
        return {
            "action": "start_preset",
            "preset": name,
            "task": (m.group(2) or "").strip(),
        }
    m = _START_POMODORO.match(t)
    if m:
        return {
            "action": "start_preset",
            "preset": "pomodoro",
            "task": (m.group(1) or "").strip(),
        }
    m = _START_TASK.match(t)
    if m:
        return {
            "action": "start_task",
            "task": m.group(1).strip(),
            "for": (m.group(2) or "").strip(),
        }
    if _PAUSE.match(t):
        return {"action": "pause"}
    if _RESUME.match(t):
        return {"action": "resume"}
    if _REMAINING.match(t):
        return {"action": "remaining"}
    if _ELAPSED.match(t):
        return {"action": "elapsed"}
    if _END.match(t):
        return {"action": "end"}
    m = _BREAK.match(t)
    if m:
        return {
            "action": "break",
            "minutes": int(m.group(1)) if m.group(1) else None,
        }
    if _HISTORY.match(t):
        return {"action": "history"}
    return None


def _link_todo(memory, task):
    """Find a todo whose text contains ``task`` (case-insensitive).

    Returns the todo row dict, or None. An empty task never links.
    """
    if not task or memory is None:
        return None
    for todo in memory.list_todos():
        if task.lower() in todo["text"].lower():
            return todo
    return None


def execute_focus_command(cmd, focus, memory=None):
    """Run a parsed focus command. Returns the reply."""
    action = cmd["action"]

    if action == "start":
        if focus.active:
            return (
                "You're already in a focus session — "
                f"{focus.status_line()}. Say 'end focus mode' first "
                "if you want to start a new one."
            )
        task = cmd.get("task", "")
        if cmd.get("for"):
            todo = _link_todo(memory, cmd["for"])
            if todo is None:
                return (
                    f"I couldn't find a todo about '{cmd['for']}' — "
                    "add it first, or start the session without linking it."
                )
            task = todo["text"]
        elif task:
            todo = _link_todo(memory, task)
            if todo is not None:
                task = todo["text"]
        focus.start(cmd["minutes"], task=task)
        label = f" for {task}" if task else ""
        return (
            f"Focus started — {cmd['minutes']} minutes{label}. "
            "I'll let you know when time's up."
        )

    if action == "start_preset":
        if focus.active:
            return (
                "You're already in a focus session — "
                f"{focus.status_line()}. Say 'end focus mode' first "
                "if you want to start a new one."
            )
        preset = PRESETS[cmd["preset"]]
        task = cmd.get("task", "")
        if task:
            todo = _link_todo(memory, task)
            if todo is not None:
                task = todo["text"]
        focus.start_preset(cmd["preset"], task=task)
        label = f" for {task}" if task else ""
        return (
            f"{preset['label']} started — {preset['work_minutes']} minutes"
            f"{label}. I'll let you know when time's up."
        )

    if action == "start_task":
        if focus.active:
            return (
                "You're already in a focus session — "
                f"{focus.status_line()}. Say 'end focus mode' first "
                "if you want to start a new one."
            )
        task = cmd["task"]
        if cmd.get("for"):
            todo = _link_todo(memory, cmd["for"])
            if todo is None:
                return (
                    f"I couldn't find a todo about '{cmd['for']}' — "
                    "add it first, or start the session without linking it."
                )
            task = todo["text"]
        else:
            todo = _link_todo(memory, task)
            if todo is not None:
                task = todo["text"]
        focus.start_for_task(task)
        return (
            f"Focus started for {task} — I'll let you know when time's up."
        )

    if action == "pause":
        if not focus.active:
            return "There's no focus session running to pause."
        if focus.status() == "paused":
            return "Your focus session is already paused."
        focus.pause()
        return f"Focus paused — {focus.status_line()}."

    if action == "resume":
        if not focus.active:
            return "There's no focus session running to resume."
        if focus.status() != "paused":
            return "Your focus session isn't paused."
        focus.resume()
        return f"Focus resumed — {focus.status_line()}."

    if action == "remaining":
        if not focus.active:
            return "There's no focus session running right now."
        return focus.status_line() + "."

    if action == "elapsed":
        if not focus.active:
            return "There's no focus session running right now."
        return (
            f"You've been focusing for {_fmt_clock(focus.elapsed_seconds())}."
        )

    if action == "end":
        if not focus.active:
            return "There's no focus session running to end."
        elapsed = focus.elapsed_seconds()
        focus.end(memory)
        focus.flush_held_notifications(memory)
        minutes = elapsed // 60
        return (
            f"Focus ended after about {minutes} minutes. "
            "Your held notifications are back in the log."
        )

    if action == "break":
        if not focus.active:
            return "There's no focus session running to take a break from."
        if focus.on_break:
            return "You're already on a break."
        minutes = cmd.get("minutes")
        focus.start_break(memory, break_minutes=minutes)
        return (
            f"Break started — {minutes or 5} minutes. "
            "I'll let you know when it's over."
        )

    if action == "history":
        if memory is None:
            return "I don't have any focus history saved yet."
        sessions = memory.list_focus_sessions(limit=5)
        if not sessions:
            return "You haven't finished a focus session yet."
        lines = []
        for s in sessions:
            task = f" on {s['task']}" if s["task"] else ""
            mins = s["duration_seconds"] // 60
            lines.append(f"{mins} minutes{task} ({s['status']})")
        return "Your recent focus sessions: " + "; ".join(lines) + "."

    return "I don't know how to do that yet."
