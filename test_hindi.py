"""Tests for Phase 7 Hindi mode (no microphone / Windows box needed
— the voice check is stubbed, the rest is real).

    python test_hindi.py
"""

import os
import sys
import tempfile
import types
from datetime import datetime, timedelta

# listener.py imports SpeechRecognition at module level, which is
# not installed in this test environment. Stub it: the Listener
# language tests never touch the microphone paths.
_sr_stub = types.ModuleType("speech_recognition")


class _RecognizerStub:
    def adjust_for_ambient_noise(self, *args, **kwargs):
        pass

    def listen(self, *args, **kwargs):
        return None

    def recognize_google(self, *args, **kwargs):
        return ""


_sr_stub.Recognizer = _RecognizerStub
_sr_stub.Microphone = object
_sr_stub.WaitTimeoutError = type("WaitTimeoutError", (Exception,), {})
_sr_stub.UnknownValueError = type("UnknownValueError", (Exception,), {})
_sr_stub.RequestError = type("RequestError", (Exception,), {})
sys.modules["speech_recognition"] = _sr_stub

import aura.brain as brain_mod
from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.hindi_cmds import (
    _parse_reminder,
    execute_hindi_command,
    parse_hindi_command,
    parse_language_command,
)
from aura.language import (
    load_language,
    save_language,
    set_settings_path,
)
from aura.listener import Listener
from aura.memory import Memory
from aura.speaker import _powershell_script, _winrt_script, has_hindi_voice
from aura.wakeword import contains_wake_word


def main():
    tmp = tempfile.mkdtemp()
    set_settings_path(os.path.join(tmp, "settings.json"))
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    mem = Memory(":memory:")
    set_memory(mem)
    save_language("en")

    # --- Language persistence: default, round-trip, bad value. ---
    assert load_language() == "en"
    save_language("hi")
    assert load_language() == "hi"
    with open(os.path.join(tmp, "settings.json"), "w") as fh:
        fh.write('{"language": "xx"}')
    assert load_language() == "en"
    save_language("en")

    # --- Language-switch parsing, both directions, no false hits. ---
    assert parse_language_command("speak hindi")["language"] == "hi"
    assert parse_language_command("hindi mein bolo")["language"] == "hi"
    assert parse_language_command("हिंदी में बोलो")["language"] == "hi"
    assert parse_language_command("speak english")["language"] == "en"
    assert parse_language_command("english mein bolo")["language"] == "en"
    assert parse_language_command("अंग्रेज़ी में बोलो")["language"] == "en"
    # Transliterations: what Hindi ASR actually produces for spoken
    # English words (the "speak English" bug, 2026-10-27).
    assert parse_language_command("स्पीक इंग्लिश")["language"] == "en"
    assert parse_language_command("इंग्लिश में बोलो")["language"] == "en"
    assert parse_language_command("स्पीक हिंदी")["language"] == "hi"
    # Broadened forms (2026-10-27 voice-fix round).
    assert parse_language_command("English")["language"] == "en"
    assert parse_language_command("Hindi")["language"] == "hi"
    assert parse_language_command("इंग्लिश")["language"] == "en"
    assert parse_language_command("change to english")["language"] == "en"
    assert parse_language_command("इंग्लिश मोड")["language"] == "en"
    assert parse_language_command("इंग्लिश में चेंज करो")["language"] == "en"
    assert parse_language_command("speak hinglish")["language"] == "hi"
    assert parse_language_command("Hinglish")["language"] == "hi"
    assert parse_language_command("hindi song") is None
    assert parse_language_command("hindi song on karo") is None
    assert parse_language_command("इंग्लिश गाना चलाओ") is None
    assert parse_language_command("open notepad") is None

    # --- Hindi command parsing: Devanagari + Roman. ---
    assert parse_hindi_command("नमस्ते")["kind"] == "greeting"
    assert parse_hindi_command("namaste")["kind"] == "greeting"
    assert parse_hindi_command("समय क्या है")["kind"] == "time"
    assert parse_hindi_command("kitne baje hain")["kind"] == "time"
    assert parse_hindi_command("आज की तारीख")["kind"] == "date"
    assert parse_hindi_command("तुम्हारा नाम क्या है")["kind"] == "identity"
    cmd = parse_hindi_command("notepad खोलो")
    assert cmd["kind"] == "open_app" and cmd["app"] == "notepad", cmd
    cmd = parse_hindi_command("chrome kholo")
    assert cmd["kind"] == "open_app" and cmd["app"] == "chrome", cmd
    cmd = parse_hindi_command("याद रखो दूध खरीदना है")
    assert cmd["kind"] == "note_add" and "दूध" in cmd["text"], cmd
    assert parse_hindi_command("mere notes dikhao")["kind"] == "note_list"
    cmd = parse_hindi_command("काम जोड़ो दूध खरीदना")
    assert cmd["kind"] == "todo_add" and "दूध" in cmd["text"], cmd
    assert parse_hindi_command("mere kaam dikhao")["kind"] == "todo_list"
    assert parse_hindi_command("5 मिनट में कॉल करना याद दिलाओ")["kind"] == (
        "reminder_add"
    )
    assert parse_hindi_command("mere reminders dikhao")["kind"] == (
        "reminder_list"
    )
    assert parse_hindi_command("aaj ka briefing")["kind"] == "briefing"
    assert parse_hindi_command("notifications dikhao")["kind"] == (
        "notifications"
    )
    assert parse_hindi_command("tum kya kar sakte ho")["kind"] == "help"
    assert parse_hindi_command("अलविदा")["kind"] == "goodbye"
    assert parse_hindi_command("open notepad") is None
    assert parse_hindi_command("what is the time") is None

    # --- Hindi reminder time parsing. ---
    now = datetime(2026, 10, 27, 14, 0)
    text, when, display = _parse_reminder(
        "5 मिनट में कॉल करना याद दिलाओ", now
    )
    assert when == now + timedelta(minutes=5), when
    assert "कॉल करना" in text, text
    assert "minute" in display, display
    text, when, display = _parse_reminder("2 घंटे में मीटिंग याद दिलाओ", now)
    assert when == now + timedelta(hours=2), when
    text, when, display = _parse_reminder("5 बजे मीटिंग याद दिलाओ", now)
    assert when == datetime(2026, 10, 27, 17, 0), when  # bare hour = pm
    assert _parse_reminder("कॉल करना याद दिलाओ", now) is None

    # --- Execution: Hinglish replies, memory effects. ---
    reply = execute_hindi_command({"kind": "greeting"}, mem)
    assert "Namaste" in reply, reply
    reply = execute_hindi_command({"kind": "time"}, mem)
    assert "baj" in reply, reply
    reply = execute_hindi_command({"kind": "date"}, mem)
    assert "Aaj" in reply, reply
    reply = execute_hindi_command({"kind": "identity"}, mem)
    assert "AURA" in reply, reply
    reply = execute_hindi_command(
        {"kind": "note_add", "text": "दूध खरीदना है"}, mem
    )
    assert "save" in reply and len(mem.list_notes()) == 1, reply
    reply = execute_hindi_command({"kind": "note_list"}, mem)
    assert "दूध" in reply, reply
    reply = execute_hindi_command(
        {"kind": "todo_add", "text": "दूध खरीदना"}, mem
    )
    assert "jod diya" in reply, reply
    reply = execute_hindi_command({"kind": "todo_list"}, mem)
    assert "दूध" in reply and "kaam" in reply, reply
    reply = execute_hindi_command(
        {"kind": "reminder_add", "text": "5 मिनट में कॉल करना याद दिलाओ"},
        mem,
    )
    assert "Reminder lag gaya" in reply, reply
    assert len(mem.list_reminders()) == 1
    reply = execute_hindi_command({"kind": "reminder_list"}, mem)
    assert "कॉल करना" in reply, reply
    mem.add_notification("Reminder: पानी पीना")
    reply = execute_hindi_command({"kind": "notifications"}, mem)
    assert "पानी पीना" in reply, reply
    assert mem.unread_notification_count() == 0  # listing marks read
    reply = execute_hindi_command({"kind": "briefing"}, mem)
    assert "Aaj" in reply and "दूध" in reply, reply
    reply = execute_hindi_command({"kind": "help"}, mem)
    assert "Speak English" in reply, reply

    # --- Voice switch through handle(), with a stubbed voice check. ---
    brain_mod.has_hindi_voice = lambda: False
    reply, quit_ = handle("speak hindi")
    assert "no Hindi voice" in reply and load_language() == "en", reply
    brain_mod.has_hindi_voice = lambda: True
    reply, quit_ = handle("speak hindi")
    assert load_language() == "hi" and "Hinglish mode" in reply, reply
    reply, quit_ = handle("speak hinglish")
    assert load_language() == "hi" and "Hinglish mode" in reply, reply
    reply, quit_ = handle("समय क्या है")
    assert "baj" in reply, reply
    reply, quit_ = handle("नमस्ते")
    assert "Namaste" in reply, reply
    reply, quit_ = handle("अलविदा")
    assert quit_ is True, reply
    # The 2026-10-27 bug: in Hindi mode, spoken "speak English"
    # arrives transliterated as "स्पीक इंग्लिश" and must still switch.
    save_language("hi")
    reply, quit_ = handle("स्पीक इंग्लिश")
    assert load_language() == "en" and "English" in reply, reply
    reply, quit_ = handle("speak english")
    assert load_language() == "en" and "English" in reply, reply
    save_language("en")

    # --- Wake word: Devanagari alias for the default word. ---
    assert contains_wake_word("ऑरा सुनो", "aura") is True
    assert contains_wake_word("aura listen", "aura") is True
    assert contains_wake_word("aurora", "aura") is False

    # --- Speaker script: hi-IN voice only in Hindi mode. ---
    assert "hi-IN" in _powershell_script("नमस्ते", "hi")
    assert "hi-IN" not in _powershell_script("hello", "en")

    # --- WinRT script: OneCore voice, WAV round-trip, playback.
    script = _winrt_script("नमस्ते")
    assert "hi-IN" in script, script
    assert "SynthesizeTextToStreamAsync" in script, script
    assert "SoundPlayer" in script and "PlaySync" in script, script
    assert "नमस्ते" in script, script
    # Hinglish prefers en-IN; the culture is parameterized.
    script_en = _winrt_script("Namaste", "en-IN")
    assert "en-IN" in script_en and "hi-IN" not in script_en, script_en
    assert "Namaste" in script_en, script_en
    # No unsubstituted placeholders, and quotes are escaped.
    assert "__TEXT__" not in script and "__CULTURE__" not in script, script
    assert "__TEXT__" not in script_en and "__CULTURE__" not in script_en
    assert "''" in _winrt_script("a'b")

    # --- Voice check: no Windows here, so it must be False. ---
    assert has_hindi_voice() is False

    # --- Listener: language switch resets the Vosk model. ---
    listener = Listener(engine="offline", language="en")
    assert listener.language == "en"
    listener.set_language("hi")
    assert listener.language == "hi" and listener._vosk_model is None
    listener.set_language("xx")  # invalid: ignored
    assert listener.language == "hi"

    print("All Hindi tests passed.")


if __name__ == "__main__":
    main()
