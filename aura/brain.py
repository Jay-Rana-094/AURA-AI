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
from aura.commands.briefing import build_briefing, parse_briefing_command
from aura.commands.clipboard_cmds import (
    execute_clipboard_command,
    parse_clipboard_command,
)
from aura.commands.file_cmds import (
    execute_file_command,
    parse_file_command,
)
from aura.commands.hindi_cmds import (
    execute_hindi_command,
    parse_hindi_command,
    parse_language_command,
)
from aura.commands.notify_cmds import (
    execute_notification_command,
    parse_notification_command,
)
from aura.commands.theme_cmds import (
    execute_theme_command,
    parse_theme_command,
)
from aura.language import load_language, save_language
from aura.memory import Memory
from aura.speaker import has_hindi_voice
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

    # 1b. Language switch (Phase 7): works in both modes, before
    # everything else except a pending confirmation. Switching to
    # Hindi needs an installed Hindi voice — without one, Hindi
    # text would be read aloud by an English voice.
    lang_cmd = parse_language_command(cleaned)
    if lang_cmd is not None:
        if lang_cmd["language"] == "hi":
            if not has_hindi_voice():
                return (
                    "I couldn't switch to Hindi — no Hindi voice is "
                    "installed on this PC yet. Install the Hindi "
                    "language pack or a Hindi speech voice in Windows "
                    "Settings, then say 'speak Hindi' again.",
                    False,
                )
            save_language("hi")
            return "Hinglish mode on hai. Ab Hinglish mein baat hogi.", False
        save_language("en")
        return "Switching to English.", False

    # 1c. Hindi pack (Phase 7): in Hindi mode, Hindi commands are
    # tried before the English packs. Anything unmatched falls
    # through to the English packs below (their replies stay in
    # English — a known v1 limitation).
    if load_language() == "hi":
        hindi_cmd = parse_hindi_command(cleaned)
        if hindi_cmd is not None:
            reply = execute_hindi_command(hindi_cmd, get_memory())
            return reply, hindi_cmd["kind"] == "goodbye"

    # 1d. Wake-word commands (Phase 5): change / reset / ask.
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

    # 4c. Daily briefing (Phase 6). Routed before the command packs
    # and the built-ins, so "what do I have today" briefs instead
    # of answering with just the date.
    if parse_briefing_command(cleaned) is not None:
        return build_briefing(get_memory()), False

    # 4d. Pill theme changes (Phase 6). The executor only persists
    # the choice; main.py recolors the pill in the same turn.
    theme_cmd = parse_theme_command(cleaned)
    if theme_cmd is not None:
        return execute_theme_command(theme_cmd), False

    # 4e. Clipboard control (Phase 6).
    clip_cmd = parse_clipboard_command(cleaned)
    if clip_cmd is not None:
        return execute_clipboard_command(clip_cmd, get_memory()), False

    # 4f. Notification center (Phase 6).
    notify_cmd = parse_notification_command(cleaned)
    if notify_cmd is not None:
        return execute_notification_command(notify_cmd, get_memory()), False

    # 4g. File search (Phase 6). Routed before the command packs
    # so "open file resume" searches instead of hitting the app
    # opener (which only knows allow-listed apps).
    file_cmd = parse_file_command(cleaned)
    if file_cmd is not None:
        return execute_file_command(file_cmd), False

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
            "recent conversation. I can also take screenshots and "
            "switch Bluetooth, Wi-Fi, and airplane mode. Say 'daily "
            "briefing' for a summary of your day, 'change theme "
            "to emerald' to recolor the pill, 'what's on my "
            "clipboard' to hear what's copied, 'what "
            "notifications do I have' to catch up on reminders "
            "that fired, or 'find my report file' to search "
            "Documents, Downloads and Desktop. Say 'speak Hindi' "
            "to switch to Hindi."
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
