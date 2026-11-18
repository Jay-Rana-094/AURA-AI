"""Long-term memory voice commands — Phase 10.1.

Explicit saves only: AURA stores a fact when Jay says "remember
that..." (or an update/forget command). It never auto-saves facts from
conversation, and it never invents an answer — an unknown fact is
reported as unknown.

Shapes handled:

* "remember that Nexture is my MERN stack e-commerce project"
  -> project Nexture, key "stack" (value mentions "stack"), else "description"
* "remember that Nexture's stack is MERN"
  -> project Nexture, key "stack"
* "remember my API server uses port 6500"
  -> project "", key "api server port", value "6500"
* "remember my preferred editor is VS Code"
  -> a preference, key "editor"
* "what stack does Nexture use?" / "what port does Nexture use?"
* "what do you remember about Nexture?" / "list what you remember"
* "update Nexture's port to 7000" / "forget Nexture's port"
* "forget fact number 2" / "forget number 2"

Secrets (passwords, tokens, keys) are refused — by the memory layer
and again here, so the refusal message is spoken, not an exception.

Note the guard that keeps this from stealing the notes command: the
old note phrase "remember that my keys are on the desk" has no
"is"/"uses" verb after a subject, so none of the patterns below match
it and it still lands as a note.
"""

import re

from aura.memory import _looks_like_secret

# "remember that <Project>'s <key> is <value>"
_REMEMBER_POSSESSIVE = re.compile(
    r"^remember that ([A-Za-z][\w-]*)'s (\w+(?: \w+)?) is (.+)$",
    re.IGNORECASE,
)
# "remember that <Project> is my <value>" — single-word subject, the
# multi-word value is the description (or the stack when it says so).
_REMEMBER_IS = re.compile(
    r"^remember that ([A-Za-z][\w-]*) is (?:my |an? )?(.+)$",
    re.IGNORECASE,
)
# "remember my <key> is <value>" / "remember that my <key> is <value>"
# / "remember my <key> uses <value>"
_REMEMBER_MY = re.compile(
    r"^remember (?:that )?my ([\w ]+?) (is|uses?) (.+)$",
    re.IGNORECASE,
)
# "remember that <Project> uses <value>"
_REMEMBER_USES = re.compile(
    r"^remember that ([A-Za-z][\w-]*) uses? (.+)$",
    re.IGNORECASE,
)

# "what <key> does <Project> use?" / "what is <Project>'s <key>?"
_ASK_USES = re.compile(
    r"^what (\w+(?: \w+)?) does ([A-Za-z][\w-]*) use\??$",
    re.IGNORECASE,
)
_ASK_POSSESSIVE = re.compile(
    r"^what is ([A-Za-z][\w-]*)'s (\w+(?: \w+)?)\??$",
    re.IGNORECASE,
)
_ASK_ABOUT = re.compile(
    r"^what do you remember about ([A-Za-z][\w-]*)\??$",
    re.IGNORECASE,
)
_ASK_PREFERENCE = re.compile(
    r"^what(?: is)? my ([\w ]+?)\??$",
    re.IGNORECASE,
)

_UPDATE = re.compile(
    r"^update ([A-Za-z][\w-]*)'s (\w+(?: \w+)?) to (.+)$",
    re.IGNORECASE,
)
_FORGET = re.compile(
    r"^forget ([A-Za-z][\w-]*)'s (\w+(?: \w+)?)$",
    re.IGNORECASE,
)
_FORGET_NUMBER = re.compile(
    r"^forget (?:fact )?number (\d+)$",
    re.IGNORECASE,
)

_LIST = re.compile(
    r"^(?:list|show|tell me) (?:what you remember|everything you remember"
    r"|all my facts|my facts)$",
    re.IGNORECASE,
)

# Keys that already have their own status command elsewhere in
# the brain (GPU, hotkey, morning briefing, wake word): "what is
# my <key>?" must fall through to those handlers instead of being
# answered here as a preference ("You haven't told me your gpu
# usage yet" would be wrong — AURA knows it).
_RESERVED_KEYS = frozenset({
    "wake word",
    "gpu",
    "gpu usage",
    "hotkey",
    "morning briefing",
    # "what is my theme" has its own handler (the theme step) —
    # without this the facts step would answer it as a
    # preference ("You haven't told me your theme yet").
    "theme",
})


# Phrases that mark a "remember my ..." save as a preference rather
# than a plain fact, and that _normalise_key strips from a key:
# "preferred editor" -> "editor", so "remember my preferred
# editor is VS Code" and "what is my preferred editor?" both land
# on the key "editor".
_PREFERENCE_KEYS = (
    "preferred ",
    "favourite ",
    "favorite ",
)


def _is_preference(key):
    return key.lower().startswith(_PREFERENCE_KEYS)


def _normalise_key(key):
    """'preferred editor' -> 'editor'; 'api server port' stays as-is."""
    low = key.lower()
    for prefix in _PREFERENCE_KEYS:
        if low.startswith(prefix):
            return key[len(prefix):].strip()
    return key.strip()


def _refuse_secret():
    return "I can't store passwords, tokens, or secret keys."


def parse_facts_command(text):
    """Return a dict describing the fact command, or None."""
    if not text:
        return None
    t = text.strip()
    # "what's my ..." is the same question as "what is my ..."
    t = re.sub(r"^what's\b", "what is", t, flags=re.IGNORECASE)
    low = t.lower()

    m = _REMEMBER_POSSESSIVE.match(t)
    if m:
        return {
            "action": "save",
            "project": m.group(1),
            "key": m.group(2).lower(),
            "value": m.group(3).strip(),
        }
    m = _REMEMBER_IS.match(t)
    if m:
        value = m.group(2).strip()
        key = "stack" if "stack" in value.lower() else "description"
        return {
            "action": "save",
            "project": m.group(1),
            "key": key,
            "value": value,
        }
    m = _REMEMBER_USES.match(t)
    if m:
        return {
            "action": "save",
            "project": m.group(1),
            "key": "uses",
            "value": m.group(2).strip(),
        }
    m = _REMEMBER_MY.match(t)
    if m:
        key = _normalise_key(m.group(1))
        value = m.group(3).strip()
        # "remember my API server uses port 6500" -> key "api server port",
        # value "6500", so "what is my api server port?" finds it.
        if m.group(2).lower().startswith("use"):
            port = re.match(r"^port (\S+)$", value, re.IGNORECASE)
            if port:
                key = f"{key} port"
                value = port.group(1)
        if _is_preference(m.group(1)):
            return {
                "action": "save_preference",
                "key": key.lower(),
                "value": value,
            }
        return {
            "action": "save",
            "project": "",
            "key": key.lower(),
            "value": value,
        }
    m = _ASK_USES.match(t)
    if m:
        return {
            "action": "ask",
            "project": m.group(2),
            "key": m.group(1).lower(),
        }
    m = _ASK_POSSESSIVE.match(t)
    if m:
        return {
            "action": "ask",
            "project": m.group(1),
            "key": m.group(2).lower(),
        }
    m = _ASK_ABOUT.match(t)
    if m:
        return {"action": "about", "project": m.group(1)}
    m = _UPDATE.match(t)
    if m:
        return {
            "action": "update",
            "project": m.group(1),
            "key": m.group(2).lower(),
            "value": m.group(3).strip(),
        }
    m = _FORGET.match(t)
    if m:
        return {
            "action": "forget",
            "project": m.group(1),
            "key": m.group(2).lower(),
        }
    m = _FORGET_NUMBER.match(t)
    if m:
        return {"action": "forget_number", "number": int(m.group(1))}
    if _LIST.match(t):
        return {"action": "list"}
    if low.startswith("what is my ") or low.startswith("what's my "):
        m = _ASK_PREFERENCE.match(t)
        if m:
            key = _normalise_key(m.group(1)).lower()
            if key in _RESERVED_KEYS:
                return None
            return {"action": "ask_preference", "key": key}
    return None


def _describe_fact(fact):
    project = fact["project"]
    subject = f"{project}'s {fact['key']}" if project else fact["key"]
    return f"{subject} is {fact['value']}"


def execute_facts_command(cmd, memory):
    """Run a parsed fact command against a Memory. Returns the reply."""
    action = cmd["action"]

    if action == "save":
        if _looks_like_secret(cmd["key"]) or _looks_like_secret(cmd["value"]):
            return _refuse_secret()
        try:
            memory.save_fact(
                cmd["project"], cmd["key"], cmd["value"], category="general"
            )
        except ValueError:
            return _refuse_secret()
        subject = (
            f"{cmd['project']}'s {cmd['key']}"
            if cmd["project"]
            else cmd["key"]
        )
        return f"Got it. I'll remember that {subject} is {cmd['value']}."

    if action == "save_preference":
        if _looks_like_secret(cmd["key"]) or _looks_like_secret(cmd["value"]):
            return _refuse_secret()
        try:
            memory.save_preference(cmd["key"], cmd["value"])
        except ValueError:
            return _refuse_secret()
        return f"Got it. Your {cmd['key']} is {cmd['value']}."

    if action == "ask":
        fact = memory.get_fact(cmd["project"], cmd["key"])
        if fact is None:
            return (
                f"I don't know {cmd['project']}'s {cmd['key']} yet — "
                "I only remember what you've told me to remember."
            )
        # Uppercase only the first letter — str.capitalize() would
        # mangle values like "MERN" or "VS Code" into "Mern".
        text = _describe_fact(fact)
        return text[:1].upper() + text[1:] + "."

    if action == "ask_preference":
        pref = memory.get_preference(cmd["key"])
        if pref is None:
            return f"You haven't told me your {cmd['key']} yet."
        return f"Your {cmd['key']} is {pref['value']}."

    if action == "about":
        facts = memory.find_facts(cmd["project"])
        if not facts:
            return (
                f"I don't remember anything about {cmd['project']} yet — "
                "tell me something with 'remember that...' and I'll keep it."
            )
        lines = [_describe_fact(f) for f in facts]
        return f"Here's what I remember about {cmd['project']}: " + "; ".join(
            lines
        ) + "."

    if action == "update":
        if _looks_like_secret(cmd["key"]) or _looks_like_secret(cmd["value"]):
            return _refuse_secret()
        existing = memory.get_fact(cmd["project"], cmd["key"])
        if existing is None:
            return (
                f"I don't have {cmd['project']}'s {cmd['key']} saved, "
                "so there's nothing to update — say 'remember that...' first."
            )
        try:
            memory.save_fact(
                cmd["project"], cmd["key"], cmd["value"], category="general"
            )
        except ValueError:
            return _refuse_secret()
        return (
            f"Updated. {cmd['project']}'s {cmd['key']} is now "
            f"{cmd['value']}."
        )

    if action == "forget":
        if memory.delete_fact(cmd["project"], cmd["key"]):
            return (
                f"Forgotten. I no longer remember {cmd['project']}'s "
                f"{cmd['key']}."
            )
        return (
            f"I don't have {cmd['project']}'s {cmd['key']} saved, "
            "so there's nothing to forget."
        )

    if action == "forget_number":
        fact = memory.delete_fact_number(cmd["number"])
        if fact is None:
            return "There's no fact with that number."
        return f"Forgotten. I no longer remember {_describe_fact(fact)}."

    if action == "list":
        facts = memory.list_facts()
        prefs = memory.list_preferences()
        if not facts and not prefs:
            return (
                "I haven't remembered anything yet — say 'remember that...' "
                "and I'll keep it."
            )
        lines = [_describe_fact(f) for f in facts]
        for pref in prefs:
            lines.append(f"your {pref['key']} is {pref['value']}")
        numbered = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
        return "Here's everything I remember: " + "; ".join(numbered) + "."

    return "I don't know how to do that yet."
