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

from aura.chat import (
    ChatError,
    chat_available,
    chat_reply,
    get_api_key,
    is_chat_enabled,
    set_chat_enabled,
)
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
from aura.commands.spotify_cmds import (
    execute_spotify_command,
    parse_spotify_command,
)
from aura.commands.facts_cmds import (
    execute_facts_command,
    parse_facts_command,
)
from aura.commands.focus_cmds import (
    execute_focus_command,
    parse_focus_command,
)
from aura.commands.personality_cmds import (
    execute_personality_command,
    parse_personality_command,
)
from aura.focus import FocusManager
from aura.calendar import (
    execute_calendar_command,
    parse_calendar_command,
)
from aura.gpu import execute_gpu_command, parse_gpu_command
from aura.hotkey import execute_hotkey_command, parse_hotkey_command
from aura.morning import execute_morning_command, parse_morning_command
from aura.tray import execute_tray_command, parse_tray_command
from aura.weather import execute_weather_command, parse_weather_command
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
# Phase 8A: a voice command that opens or closes the Control Center
# cannot open a window from the brain (it has no GUI). handle()
# records the request here, and main.py reads + clears it right
# after the turn's handle() call. Phase 8B reuses the same channel
# for engine switches ("engine_whisper", "engine_offline",
# "engine_google"). See pop_gui_action().
_gui_action = None


def pop_gui_action():
    """Take the pending GUI request ("open_control_center" /
    "close_control_center" / "engine_whisper" / "engine_offline" /
    "engine_google" / "chat_refresh" / "personality_refresh"), or
    None. Main.py calls this after every handle() — including typed
    commands from the window."""
    global _gui_action
    action, _gui_action = _gui_action, None
    return action


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


_focus_manager = None


def get_focus_manager() -> FocusManager:
    """The shared focus session manager (lazy: created on first use)."""
    global _focus_manager
    if _focus_manager is None:
        _focus_manager = FocusManager()
    return _focus_manager


def set_focus_manager(manager) -> None:
    """Swap the manager — used by tests (fake clock)."""
    global _focus_manager
    _focus_manager = manager


def confirmation_pending() -> bool:
    """True when the last turn asked "are you sure?" and is awaiting
    a yes/no. main.py uses this to show the WAITING_CONFIRMATION
    state on the pill."""
    return _pending is not None


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
    global _pending, _gui_action
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

    # 3b. Control Center (Phase 8A). Placed AFTER custom phrases so
    # a taught phrase with the same words still wins, like every
    # other built-in. The brain only records the request — main.py
    # opens or closes the window (the brain has no GUI).
    if cleaned in ("open control center", "open the control center",
                   "show control center", "show the control center",
                   "open control centre", "open the control centre"):
        _gui_action = "open_control_center"
        return "Opening the Control Center.", False
    if cleaned in ("close control center", "close the control center",
                   "hide control center", "hide the control center",
                   "close control centre", "close the control centre"):
        _gui_action = "close_control_center"
        return "Closing the Control Center.", False

    # 3c. Speech engine (Phase 8B). Same channel as 3b, same rule:
    # a taught phrase with the same words still wins. The brain
    # only records the request — main.py switches the listener.
    _engine_match = re.match(
        r"(switch|change|use)( the| my)? (engine|speech engine|"
        r"recognition engine)? ?to (offline|vosk|google|whisper)$",
        cleaned,
    )
    if _engine_match:
        word = _engine_match.group(4)
        engine = "offline" if word in ("offline", "vosk") else word
        _gui_action = f"engine_{engine}"
        return f"Switching to the {engine} engine.", False
    if cleaned in ("switch to whisper", "use whisper",
                   "switch to the whisper engine"):
        _gui_action = "engine_whisper"
        return "Switching to the whisper engine.", False
    if cleaned in ("switch to offline", "use offline",
                   "switch to vosk", "use vosk"):
        _gui_action = "engine_offline"
        return "Switching to the offline engine.", False
    if cleaned in ("switch to google", "use google"):
        _gui_action = "engine_google"
        return "Switching to the google engine.", False

    # 3d. Chat fallback controls (Phase 8C). Same placement rule
    # as 3b/3c: after custom phrases, so a taught phrase still
    # wins. The flag is set here; main.py refreshes the open
    # Control Center via the "chat_refresh" gui action, so its
    # checkbox follows a voice/typed toggle (like the engine
    # radio did in 8B v4).
    if cleaned in ("turn on chat mode", "enable chat mode",
                   "turn chat mode on", "enable chat",
                   "turn on conversation mode",
                   "enable conversation mode",
                   "enable conversation fallback"):
        set_chat_enabled(True)
        _gui_action = "chat_refresh"
        if get_api_key() is None:
            return (
                "Chat mode is on, but I don't have a Groq API key "
                "yet — add your key to the GROQ_API_KEY environment "
                "variable, or save it in a groq_api_key.txt file "
                "next to main.py, then ask me anything.", False)
        return ("Chat mode is on — I'll answer questions I don't "
                "have a command for, using Groq.", False)
    if cleaned in ("turn off chat mode", "disable chat mode",
                   "turn chat mode off", "disable chat",
                   "turn off conversation mode",
                   "disable conversation mode",
                   "disable conversation fallback"):
        set_chat_enabled(False)
        _gui_action = "chat_refresh"
        return "Chat mode is off.", False
    if cleaned in ("is chat mode on", "chat mode status",
                   "is conversation mode on"):
        if is_chat_enabled():
            key_note = ("with your Groq key ready"
                        if get_api_key() is not None
                        else "but no Groq key is set yet")
            return f"Chat mode is on, {key_note}.", False
        return "Chat mode is off.", False

    # 4a. Long-term memory (Phase 10.1): explicit facts. Routed
    # BEFORE the note/todo/reminder step so a fact-shaped "remember
    # that..." wins over note_add — while the plain note phrase
    # ("remember that my keys are on the desk") matches no fact
    # pattern and still lands as a note.
    facts_cmd = parse_facts_command(cleaned)
    if facts_cmd is not None:
        return execute_facts_command(facts_cmd, get_memory()), False

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

    # 4d2. Personality modes (Phase 10.1). The mode is persisted
    # here; main.py refreshes the open Control Center via the
    # "personality_refresh" gui action, so its radios follow a
    # voice/typed switch (the chat_refresh pattern from 8C).
    pers_cmd = parse_personality_command(cleaned)
    if pers_cmd is not None:
        _gui_action = "personality_refresh"
        return execute_personality_command(pers_cmd), False

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

    # 4h. GPU usage (Phase 9.1). Reads the GPU through GPUtil;
    # the reply is honest when there is no GPU to read.
    gpu_cmd = parse_gpu_command(cleaned)
    if gpu_cmd is not None:
        return execute_gpu_command(gpu_cmd), False

    # 4i. Weather (Phase 9.1). The standalone question speaks
    # the same line the briefing carries (or says it is
    # unavailable right now).
    weather_cmd = parse_weather_command(cleaned)
    if weather_cmd is not None:
        return execute_weather_command(weather_cmd), False

    # 4j. Spotify (Phase 9.1). Routed before the command packs
    # so "play lo-fi on Spotify" plays (or opens the web search
    # when the API is not connected) instead of falling through
    # to a generic web search.
    spotify_cmd = parse_spotify_command(cleaned)
    if spotify_cmd is not None:
        return execute_spotify_command(spotify_cmd), False

    # 4k. Morning briefing (Phase 9.2A). The toggle / time /
    # status commands. Placed before the built-ins on purpose:
    # "stop morning briefing" contains "stop", which the
    # built-in exit rule would otherwise catch first.
    morning_cmd = parse_morning_command(cleaned)
    if morning_cmd is not None:
        reply, action = execute_morning_command(morning_cmd)
        if action is not None:
            _gui_action = action
        return reply, False

    # 4l. System tray (Phase 9.2A). "minimize to tray" / "show
    # the pill". The executor returns the GUI action (or None
    # when the tray is not available — the pill then stays).
    tray_cmd = parse_tray_command(cleaned)
    if tray_cmd is not None:
        reply, action = execute_tray_command(tray_cmd)
        if action is not None:
            _gui_action = action
        return reply, False

    # 4m. Global hotkey (Phase 9.2B). Toggle / set / status.
    # Placed before the built-ins on purpose: "stop hotkey"
    # contains "stop", which the built-in exit rule would
    # otherwise catch first (same reason as the morning
    # briefing at 4k).
    hotkey_cmd = parse_hotkey_command(cleaned)
    if hotkey_cmd is not None:
        reply, action = execute_hotkey_command(hotkey_cmd)
        if action is not None:
            _gui_action = action
        return reply, False

    # 4n. Google Calendar (Phase 9.2B). "what's on my calendar
    # today" / "any meetings today". Routed before the command
    # packs so it never falls through to a web search.
    calendar_cmd = parse_calendar_command(cleaned)
    if calendar_cmd is not None:
        reply, _ = execute_calendar_command(calendar_cmd)
        return reply, False

    # 4o. Focus Mode (Phase 10.1). Routed BEFORE the command
    # packs: aura/commands/__init__.py matches "start..." via the
    # app opener, so a focus command would otherwise open an app
    # instead of starting a session.
    focus_cmd = parse_focus_command(cleaned)
    if focus_cmd is not None:
        return (
            execute_focus_command(
                focus_cmd, get_focus_manager(), get_memory()
            ),
            False,
        )

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
            "to switch to Hindi. Say 'open control center' — or "
            "double-click the pill — to open the Control Center "
            "window with today's briefing, your lists, history, "
            "settings and live system stats. I listen with three "
            "engines — offline Vosk, Google, and Whisper on your "
            "graphics card — and you can switch between them from "
            "the pill menu, the Control Center, or by saying "
            "'switch engine to whisper'. If I don't have a command "
            "for something, I ask Groq for an answer automatically "
            "— say 'turn off chat mode' to stop that. I can also "
            "tell you the weather — say 'what's the weather' — and "
            "the daily briefing carries it too. Say 'what's my gpu "
            "usage' for the graphics card's load, memory and "
            "temperature, or check the Diagnostics tab. And for "
            "Spotify: 'play lo-fi on Spotify' searches and plays "
            "it when Spotify is connected (otherwise I open the "
            "web search), 'what's playing' tells you the current "
            "track, and 'pause Spotify' or 'next song on Spotify' "
            "work with the media keys, no setup needed. I can "
            "also speak your daily briefing every morning at "
            "8:00 — say 'turn off morning briefing' to stop "
            "that, or 'set morning briefing to 7:30' to change "
            "the time. And I can hide in the system tray — say "
            "'minimize to tray' — then double-click the tray "
            "icon, or say 'show the pill', to bring me back. "
            "Press Ctrl+Alt+A anywhere to open the command box "
            "— say 'set hotkey to ctrl shift h' to change it, "
            "or 'turn off hotkey' to stop it. And once Google "
            "Calendar is connected, say 'what's on my calendar "
            "today' for your events — they are in the daily "
            "briefing too. I also remember facts you tell me — "
            "say 'remember that Nexture is my MERN stack project' "
            "and later ask 'what stack does Nexture use', or "
            "'list what you remember'. I have five personality "
            "modes — say 'switch to Aura mode' or 'turn on silent "
            "mode' — and a Focus Mode: 'start a 50-minute coding "
            "session', 'start Pomodoro', 'how much time is "
            "remaining', or 'end focus mode'."
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

    # 7. Conversational fallback (Phase 8C): only when no command
    # matched and chat mode is on AND a key is set — this runs
    # last on purpose, so commands always win. Without a key the
    # old honest fallback stands (see chat_available()).
    if chat_available():
        try:
            reply = chat_reply(
                text.strip(),
                history=_recent_history(),
                language=load_language(),
            )
        except ChatError as exc:
            return str(exc), False
        if reply:
            return reply, False
    return "I don't know how to do that yet.", False


def _recent_history(limit: int = 4):
    """Last few turns, oldest first, for the chat fallback's
    context. The current turn is not recorded yet, so it is not
    in here — the question itself is passed separately."""
    turns = get_memory().recent_turns(limit=limit)
    return [
        (row["user_text"], row["reply_text"])
        for row in reversed(turns)
    ]
