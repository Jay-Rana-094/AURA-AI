"""Hinglish voice pack — Phase 7.

AURA understands Hindi and answers in Hinglish when the language
mode is "hi" (see aura/language.py). The pack covers the daily-use
core: greetings, time, date, opening apps, notes, todos, reminders,
briefing, notifications, help, identity and goodbye. Anything
outside this set falls through to the English packs, which still
work in Hindi mode (app and site names are English anyway) — those
replies stay in English, a known v1 limitation.

Transcripts in Hindi mode arrive in Devanagari (Vosk Hindi and
Google hi-IN both output it), so matching is Devanagari-first,
with common Roman forms as alternates. Replies are Roman Hinglish
— the way people actually talk ("Namaste! Batao, kya karna hai?")
— which also suits the voice: Hinglish is Roman script, so the
speaker prefers an Indian English (en-IN) voice for it, with the
Hindi voice as backup.

Parsing is separated from execution, like the other packs.
"""

import re
import shutil
import subprocess
from datetime import datetime, timedelta

from aura.commands.apps import find_app

_ASCII_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Hinglish dates use English weekday/month names — that is how
# people say them ("Tuesday, 28 October").
_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday",
]
_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Hindi number words -> digits (enough for times: 1-15, 20-60).
_NUMBER_WORDS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5,
    "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14,
    "पंद्रह": 15, "बीस": 20, "पच्चीस": 25, "तीस": 30,
    "चालीस": 40, "पैंतालीस": 45, "पचास": 50, "साठ": 60,
}


def _normalize(text: str) -> str:
    """Lowercase + Devanagari digits to ASCII, for matching."""
    return text.strip().lower().translate(_ASCII_DIGITS)


def _hinglish_clock(when: datetime) -> str:
    """A time as Hinglish speech: "8 bajkar 5 minute" / "8 baje"."""
    hour = when.hour % 12 or 12
    if when.minute == 0:
        return f"{hour} baje"
    return f"{hour} bajkar {when.minute} minute"


def _hinglish_date(when: datetime) -> str:
    """A date as Hinglish speech: "Tuesday, 28 October"."""
    return (
        f"{_WEEKDAYS[when.weekday()]}, "
        f"{when.day} {_MONTHS[when.month - 1]}"
    )


def _hinglish_datetime(when: datetime, now: datetime) -> str:
    """Clock today, date + clock otherwise."""
    if when.date() == now.date():
        return _hinglish_clock(when)
    return f"{_hinglish_date(when)} {_hinglish_clock(when)}"


def _words_to_digits(text: str) -> str:
    """Replace Hindi number words with digits ("पाँच" -> "5")."""
    for word, num in _NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", str(num), text)
    return text


# -- language switching (checked in both modes, before all else) --------

def parse_language_command(text: str):
    """Match a language-switch request. None if no match.

    "speak Hindi" / "हिंदी में बोलो" -> hi;
    "speak English" / "अंग्रेज़ी में बोलो" -> en.
    "speak Hinglish" also switches to hi, since hi now speaks
    Hinglish.

    Transliterations matter: in Hindi mode the Hindi recognizer
    writes spoken English words in Devanagari ("speak English"
    arrives as "स्पीक इंग्लिश"), so both scripts are accepted for
    both the language name and the verb. A bare language name
    ("English") also switches — in context it can only mean the
    mode — and mode/verb words (mode, change, करो, वापस) cover
    phrasings like "English mode" or "इंग्लिश में चेंज करो".
    Trigger words are only checked together with a language word,
    so "hindi song" or "इंग्लिश गाना चलाओ" still do not switch.
    """
    t = _normalize(text)
    hi_words = ("hindi", "हिंदी", "हिन्दी", "hinglish", "हिंग्लिश")
    en_words = ("english", "इंग्लिश", "इंगलिश", "अंग्रेज़ी", "अंग्रेजी")
    if t in hi_words:
        return {"kind": "lang", "language": "hi"}
    if t in en_words:
        return {"kind": "lang", "language": "en"}
    verbs = (
        "bolo", "बोलो", "speak", "स्पीक", "स्पिक", "baat", "बात",
        "स्विच", "switch", "change", "चेंज", "mode", "मोड",
        "करो", "वापस", "जाओ",
    )
    if any(w in t for w in hi_words) and any(v in t for v in verbs):
        return {"kind": "lang", "language": "hi"}
    if any(w in t for w in en_words) and any(v in t for v in verbs):
        return {"kind": "lang", "language": "en"}
    return None


# -- Hindi command parsing -------------------------------------------------

def parse_hindi_command(text: str):
    """Match Hindi speech to a command. None if no match."""
    t = _normalize(text)

    if (
        any(w in t for w in ("अलविदा", "alvida", "फिर मिलेंगे", "phir milenge"))
        or t in ("bye", "band karo", "बंद करो")
    ):
        return {"kind": "goodbye"}
    if (
        any(w in t for w in ("नमस्ते", "नमस्कार", "namaste", "namaskar"))
        or t in ("hi", "hello", "hey")
    ):
        return {"kind": "greeting"}
    if (
        "समय" in t or "samay" in t or "kitne baje" in t
        or "time kya" in t or "baje hain" in t
    ):
        return {"kind": "time"}
    if (
        "तारीख" in t or "tarikh" in t or "कौन सा दिन" in t
        or "kaun sa din" in t
    ):
        return {"kind": "date"}
    if any(
        w in t
        for w in (
            "तुम्हारा नाम", "tumhara naam", "आपका नाम", "aapka naam",
        )
    ):
        return {"kind": "identity"}
    m = re.match(
        r"^(.+?)\s*(खोलो|kholo|खोल दो|khol do)(\s+please)?\s*$", t
    )
    if m:
        app = re.sub(r"\s*(ko|को)\s*$", "", m.group(1)).strip()
        if app:
            return {"kind": "open_app", "app": app}
    m = re.match(
        r"^(याद रखो|yaad rakho|note लिखो|note likho|note karo)\s+(.+)$", t
    )
    if m:
        return {"kind": "note_add", "text": m.group(2)}
    if "note" in t and any(
        w in t for w in ("dikhao", "दिखाओ", "batao", "बताओ")
    ):
        return {"kind": "note_list"}
    m = re.match(
        r"^(काम जोड़ो|kaam jodo|todo जोड़ो|todo jodo)\s+(.+)$", t
    )
    if m:
        return {"kind": "todo_add", "text": m.group(2)}
    if any(w in t for w in ("kaam", "काम", "todo")) and any(
        w in t for w in ("dikhao", "दिखाओ", "batao", "बताओ")
    ):
        return {"kind": "todo_list"}
    if "याद दिलाओ" in t or "yaad dilao" in t:
        return {"kind": "reminder_add", "text": t}
    if "reminder" in t and any(
        w in t for w in ("dikhao", "दिखाओ", "batao", "बताओ")
    ):
        return {"kind": "reminder_list"}
    if (
        "briefing" in t or "ब्रीफिंग" in t
        or t in ("suprabhat", "सुप्रभात", "good morning")
    ):
        return {"kind": "briefing"}
    if "notification" in t and (
        any(w in t for w in ("dikhao", "दिखाओ", "batao", "बताओ"))
        or t == "notifications"
    ):
        return {"kind": "notifications"}
    if (
        "क्या कर" in t or "kya kar" in t or t == "help"
        or "मदद" in t
    ):
        return {"kind": "help"}
    return None


# -- Hindi reminder time parsing -------------------------------------------

def _parse_reminder(text: str, now: datetime):
    """Extract (reminder_text, when, when_display) from Hindi speech.

    Time forms: "N मिनट में" (in N minutes), "N घंटे में" (in N
    hours), "N बजे" (today at N, bare hour = pm like Phase 3).
    Returns None if no usable time was heard.
    """
    t = _words_to_digits(text)
    m = re.search(r"(\d+)\s*(मिनट|minute)s?\s*(में|mein)", t)
    if m:
        when = now + timedelta(minutes=int(m.group(1)))
        display = f"{m.group(1)} minute mein"
        rest = t[: m.start()] + t[m.end():]
        return _clean_reminder_text(rest), when, display
    m = re.search(r"(\d+)\s*(घंटे|घंटा|ghante|ghanta)\s*(में|mein)", t)
    if m:
        when = now + timedelta(hours=int(m.group(1)))
        display = f"{m.group(1)} ghante mein"
        rest = t[: m.start()] + t[m.end():]
        return _clean_reminder_text(rest), when, display
    m = re.search(r"(\d+)\s*(बजे|baje)", t)
    if m:
        hour = int(m.group(1))
        if hour < 12:
            hour += 12  # bare hour = pm, same rule as Phase 3
        when = now.replace(hour=hour % 24, minute=0, second=0,
                           microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        display = _hinglish_clock(when)
        rest = t[: m.start()] + t[m.end():]
        return _clean_reminder_text(rest), when, display
    return None


def _clean_reminder_text(rest: str) -> str:
    """Strip the command words, leaving what to be reminded about."""
    rest = re.sub(r"(याद दिलाओ|yaad dilao|yaad dila do)", "", rest)
    rest = re.sub(r"\s*(की|ko|ki)\s*$", "", rest)
    rest = re.sub(r"^\s*(मुझे|mujhe)\s+", "", rest)
    return " ".join(rest.split()).strip(" ,।")


# -- Hinglish briefing -------------------------------------------------------

def _hinglish_briefing(memory, now: datetime) -> str:
    """Daily briefing with Hinglish framing (same data as Phase 6)."""
    if now.hour < 12:
        greet = "Suprabhat"
    elif now.hour < 17:
        greet = "Namaste"
    else:
        greet = "Shubh sandhya"
    parts = [f"{greet}! Aaj {_hinglish_date(now)} hai."]

    rows = memory.list_reminders()
    today = []
    overdue = []
    for row in rows:
        when = datetime.strptime(row["remind_at"], "%Y-%m-%d %H:%M:%S")
        if when <= now:
            overdue.append((row, when))
        elif when.date() == now.date():
            today.append((row, when))
    if overdue:
        items = "; ".join(
            f"{row['text']} ({_hinglish_clock(when)})"
            for row, when in overdue
        )
        parts.append(f"Ye reminders reh gaye hain: {items}.")
    if today:
        items = "; ".join(
            f"{row['text']} {_hinglish_clock(when)}"
            + (
                " (har din)"
                if row["recurrence"] == "daily"
                else ""
            )
            for row, when in today
        )
        parts.append(f"Aaj ke reminders: {items}.")
    if not overdue and not today:
        parts.append("Aaj koi reminder nahi hai.")

    todos = memory.list_todos()
    if todos:
        shown = todos[:5]
        items = []
        for row in shown:
            item = row["text"]
            if row["priority"] == "high":
                item += " (zaroori)"
            items.append(item)
        text = f"Aapke {len(todos)} kaam hain: " + "; ".join(items) + "."
        if len(todos) > 5:
            text += f" Aur {len(todos) - 5} zyada."
        parts.append(text)
    else:
        parts.append("Todo list khaali hai.")
    return " ".join(parts)


# -- execution ---------------------------------------------------------------

def execute_hindi_command(cmd: dict, memory) -> str:
    """Carry out a parsed Hindi command and reply in Hinglish."""
    kind = cmd["kind"]
    now = datetime.now()

    if kind == "goodbye":
        return "Alvida! Phir milenge."
    if kind == "greeting":
        return "Namaste! Batao, kya karna hai?"
    if kind == "time":
        hour = now.hour % 12 or 12
        if now.minute == 0:
            return f"Abhi {hour} baje hain."
        return f"Abhi {hour} bajkar {now.minute} minute hue hain."
    if kind == "date":
        return f"Aaj {_hinglish_date(now)} hai."
    if kind == "identity":
        return "Mera naam AURA hai."
    if kind == "open_app":
        found = find_app(cmd["app"])
        if not found:
            return f"Mujhe {cmd['app']} nahi mila."
        name, exe = found
        if shutil.which(exe) is None:
            return f"{name} is PC par nahi mila."
        try:
            subprocess.Popen([exe])
        except OSError:
            return f"{name} kholne mein dikkat hui."
        return f"{name} khul raha hai."
    if kind == "note_add":
        memory.add_note(cmd["text"])
        return "Note save ho gaya."
    if kind == "note_list":
        notes = memory.list_notes()
        if not notes:
            return "Koi note nahi hai."
        items = "; ".join(row["text"] for row in notes[-5:])
        return f"Aapke notes: {items}."
    if kind == "todo_add":
        memory.add_todo(cmd["text"])
        return f"Kaam jod diya: {cmd['text']}."
    if kind == "todo_list":
        todos = memory.list_todos()
        if not todos:
            return "Todo list khaali hai."
        items = []
        for row in todos[:5]:
            item = row["text"]
            if row["priority"] == "high":
                item += " (zaroori)"
            items.append(item)
        reply = f"Aapke {len(todos)} kaam hain: " + "; ".join(items) + "."
        if len(todos) > 5:
            reply += f" Aur {len(todos) - 5} zyada."
        return reply
    if kind == "reminder_add":
        parsed = _parse_reminder(cmd["text"], now)
        if parsed is None:
            return (
                "Kab yaad dilau? Misaal: "
                "'5 minute mein call karna yaad dilao'."
            )
        text, when, display = parsed
        if not text:
            return "Kya yaad dilau?"
        memory.add_reminder(text, when)
        return f"Reminder lag gaya: {text}, {display} par."
    if kind == "reminder_list":
        rows = memory.list_reminders()
        if not rows:
            return "Koi reminder nahi hai."
        items = "; ".join(
            f"{row['text']} "
            f"({_hinglish_datetime(datetime.strptime(row['remind_at'], '%Y-%m-%d %H:%M:%S'), now)})"
            for row in rows[:5]
        )
        return f"Aapke reminders: {items}."
    if kind == "briefing":
        return _hinglish_briefing(memory, now)
    if kind == "notifications":
        total = memory.unread_notification_count()
        rows = memory.unread_notifications(5)
        if not rows:
            return "Koi naya notification nahi hai."
        items = "; ".join(
            f"{row['text']} "
            f"({_hinglish_datetime(datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S'), now)})"
            for row in rows
        )
        memory.mark_notifications_read()
        reply = f"Aapke {total} naye notifications hain: {items}."
        if total > len(rows):
            reply += f" Aur {total - len(rows)} zyada."
        return reply
    if kind == "help":
        return (
            "Mere kaam: samay aur tarikh batana, app kholna, "
            "note aur kaam jodna, reminder lagana, briefing dena, "
            "notifications dikhana. 'Speak English' kehkar English "
            "mein wapas jayein."
        )
    return "Maaf kijiye, samajh nahi aaya."
