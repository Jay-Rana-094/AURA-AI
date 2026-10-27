"""Conversation-history questions — Phase 5.

Turns are recorded by the app (main.py) after every handle() call,
so this module only parses questions and answers them from the
turns table. Parsing is separated from executing, like the other
command packs: parse_history_command(text) -> dict | None,
execute_history_command(cmd, memory) -> reply str.
"""

import re


def _short(text: str, limit: int = 60) -> str:
    """Spoken replies stay short: truncate long turns."""
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _fmt_turn(row) -> str:
    return (
        f"you asked '{_short(row['user_text'])}', "
        f"I said '{_short(row['reply_text'])}'"
    )


def parse_history_command(text: str):
    """Match spoken text to a history question. None if no match."""
    t = text.strip().lower()

    # Clear first: it also contains the word "conversation".
    if re.search(
        r"\b(clear|delete|forget)( our| the)? conversation( history)?\b",
        t,
    ) or t in ("clear history", "forget our conversation"):
        return {"kind": "history_clear"}

    # Topic search before the bare form: "what did we talk about
    # notepad" must search, not list everything.
    m = re.search(r"what did (we|you) (talk about|say about) (.+)", t)
    if m:
        return {
            "kind": "history_search",
            "topic": m.group(3).strip().rstrip(".!?"),
        }

    if re.search(r"what did you (just )?say", t):
        return {"kind": "history_last"}

    if (
        re.search(r"what did we talk about", t)
        or re.search(
            r"(show|list|what is)( our| my)? conversation( history)?", t
        )
        or t in ("conversation history", "our conversation")
    ):
        return {"kind": "history_recent"}

    return None


def execute_history_command(cmd: dict, memory) -> str:
    """Perform a parsed history question and return what AURA says."""
    kind = cmd["kind"]

    if kind == "history_recent":
        rows = memory.recent_turns(5)
        if not rows:
            return "We haven't talked about anything yet."
        return (
            "Here's our recent conversation: "
            + "; ".join(_fmt_turn(row) for row in rows)
            + "."
        )
    if kind == "history_search":
        rows = memory.search_turns(cmd["topic"], 5)
        if not rows:
            return (
                f"I don't have anything about {cmd['topic']} "
                "in our conversation."
            )
        return (
            f"About {cmd['topic']}: "
            + "; ".join(_fmt_turn(row) for row in rows)
            + "."
        )
    if kind == "history_last":
        rows = memory.recent_turns(1)
        if not rows:
            return "I haven't said anything yet."
        return f"I just said: '{_short(rows[0]['reply_text'], 120)}'."
    if kind == "history_clear":
        memory.clear_turns()
        return "Conversation history cleared."

    return "I don't know how to do that yet."
