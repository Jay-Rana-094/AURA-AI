"""AURA's brain — Phase 2.

Order of handling:
  1. Pending confirmation: if the last turn asked "are you sure?",
     this turn's yes/no decides it. Nothing else is parsed first.
  2. Command packs (apps, web, media, system).
  3. Built-in replies (greetings, time, date, identity, exit).
  4. Honest fallback for anything not built yet.

``handle`` returns (reply, should_quit).
"""

import re
from datetime import datetime

from aura.commands import CONFIRM_KINDS, execute_command, parse_command
from aura.commands.custom import (
    CustomStore,
    execute_custom_management,
    parse_custom_management,
)
from aura.commands.memory_cmds import (
    execute_memory_command,
    parse_memory_command,
)
from aura.commands.history_cmds import (
    execute_history_command,
    parse_history_command,
)
from aura.memory import Memory
from aura.wake_settings import (
    DEFAULT_WAKE_WORD,
    display_wake_word,
    load_wake_word,
    save_wake_word,
    validate_wake_word,
)

_YES = {"yes", "yeah", "yep", "yup", "confirm", "sure", "do it", "go ahead"}
_NO = {"no", "nope", "cancel", "never mind", "nevermind", "stop", "don't"}

_pending = None
_memory = None
_custom_store = None


def get_custom_store() -> CustomStore:
    """The shared custom-command store (lazy: created on first use)."""
    global _custom_store
    if _custom_store is None:
        _custom_store = CustomStore()
    return _custom_store


def set_custom_store(store: CustomStore) -> None:
    """Swap the store — used by tests (temp file)."""
    global _custom_store
    _custom_store = store


def get_memory() -> Memory:
    """The shared memory store (lazy: created on first use)."""
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory


def set_memory(memory: Memory) -> None:
    """Swap the store — used by tests (in-memory DB)."""
    global _memory
    _memory = memory


def _now_time() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def _today() -> str:
    return datetime.now().strftime("%A, %B %d, %Y")


def handle_wake_word_command(cleaned: str):
    """Wake-word voice commands (Phase 5). Returns a reply, or None
    if this turn is not a wake-word command. The word is stored in
    aura_settings.json, so the wake loop picks it up on its next
    listen cycle and the pill shows it right away."""
    match = re.match(r"(change|set)( my| the)? wake word to (.+)$", cleaned)
    if match:
        phrase = match.group(3).strip().rstrip(".!?")
        reason = validate_wake_word(phrase)
        if reason is not None:
            return reason
        save_wake_word(phrase)
        shown = display_wake_word(phrase)
        return f"Wake word changed to '{shown}'. Say '{shown}' to wake me."
    if cleaned in ("reset wake word", "reset my wake word"):
        save_wake_word(DEFAULT_WAKE_WORD)
        return "Wake word reset to 'Aura'."
    if cleaned in (
        "what is my wake word",
        "what is the wake word",
        "what's my wake word",
    ):
        return (
            f"Your wake word is "
            f"'{display_wake_word(load_wake_word())}'."
        )
    return None


def handle(text: str, _from_custom: bool = False):
    global _pending
    cleaned = text.strip().lower()
    if not cleaned:
        return "I didn't catch that.", False

    # 1. Pending confirmation from the previous turn.
    if _pending is not None:
        cmd = _pending
        _pending = None
        if cleaned in _YES or cleaned.startswith("yes"):
            return execute_command(cmd), False
        return "Okay, cancelled.", False

    # 1b. Wake-word commands (Phase 5): change / reset / ask.
    wake_reply = handle_wake_word_command(cleaned)
    if wake_reply is not None:
        return wake_reply, False

    # 2. Custom-command management (teach / list / forget).
    mgmt = parse_custom_management(cleaned)
    if mgmt is not None:
        return execute_custom_management(mgmt, get_custom_store()), False

    # 3. Custom phrases — exact match only. The mapped command runs
    # with _from_custom=True so it can never trigger another custom
    # phrase (no loops, no self-triggering).
    if not _from_custom:
        mapped = get_custom_store().match(cleaned)
        if mapped is not None:
            return handle(mapped, _from_custom=True)

    # 4. Memory commands (notes, todos, reminders).
    mem_cmd = parse_memory_command(cleaned)
    if mem_cmd is not None:
        return execute_memory_command(mem_cmd, get_memory()), False

    # 4b. Conversation-history questions (Phase 5).
    hist_cmd = parse_history_command(cleaned)
    if hist_cmd is not None:
        return execute_history_command(hist_cmd, get_memory()), False

    # 5. Command packs.
    cmd = parse_command(cleaned)
    if cmd is not None:
        if cmd["kind"] in CONFIRM_KINDS:
            _pending = cmd
            return (
                f"Are you sure you want to {cmd['confirm_text']}? "
                "Say yes to confirm or no to cancel."
            ), False
        return execute_command(cmd), False

    # 6. Built-in replies.
    if cleaned in ("help", "what can you do", "what can you do aura"):
        return (
            "I can open apps and websites, search Google and YouTube, "
            "control volume and media, lock or power your PC, remember "
            "notes, keep todos, set reminders, and run your custom "
            "commands. Say 'list my custom commands' to see those. "
            "You can also say 'change my wake word to...' to pick a "
            "new wake word, or 'what did we talk about' to hear our "
            "recent conversation."
        ), False
    if re.search(r"\b(hello|hi|hey)\b", cleaned):
        return "Hey! I'm AURA, your assistant. What can I do for you?", False
    if "time" in cleaned:
        return f"It's {_now_time()}.", False
    if "date" in cleaned or "day is it" in cleaned or "today" in cleaned:
        return f"Today is {_today()}.", False
    if "your name" in cleaned or "who are you" in cleaned:
        return "I'm AURA — your voice-controlled assistant, running right on your PC.", False
    if re.search(r"\b(stop|exit|quit|goodbye|bye)\b", cleaned):
        return "Goodbye! Talk to you soon.", True

    # 7. Honest fallback.
    return "I don't know how to do that yet.", False
