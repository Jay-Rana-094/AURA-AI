"""Custom commands — Phase 4.

Teach AURA your own phrases by voice:
  "teach aura study time means open vs code"
  "list my custom commands"
  "forget custom command study time"

A custom phrase maps to one ordinary AURA command string, which is
then run through the normal pipeline (so it can be anything AURA
already knows: apps, search, reminders, notes...). The mapping is
stored in ``custom_commands.json`` next to main.py — plain JSON, so
you can also edit it by hand. Matching is exact-phrase: saying
"study time" triggers it, anything else doesn't.

Recursion guard: a mapped command is never re-checked against custom
phrases, so a custom command can never trigger itself (or a loop).
"""

import json
import os
import re

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "custom_commands.json",
)


class CustomStore:
    """Phrase -> command mapping, persisted as JSON."""

    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_PATH
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._data = {str(k).lower(): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        os.replace(tmp, self.path)

    def add(self, phrase: str, command: str) -> None:
        self._data[phrase.strip().lower()] = command.strip()
        self._save()

    def remove(self, phrase: str) -> bool:
        if phrase.strip().lower() in self._data:
            del self._data[phrase.strip().lower()]
            self._save()
            return True
        return False

    def list_all(self) -> dict[str, str]:
        return dict(self._data)

    def match(self, text: str):
        """Return the mapped command for an exact phrase, else None."""
        return self._data.get(text.strip().lower())


def parse_custom_management(text: str):
    """Teach / list / forget commands. None if no match."""
    t = text.strip().lower()

    m = re.search(r"teach (aura )?(.+?) means (.+)", t)
    if m:
        return {
            "kind": "custom_teach",
            "phrase": m.group(2).strip(),
            "command": m.group(3).strip(),
        }
    if re.search(r"list (my )?custom commands", t):
        return {"kind": "custom_list"}
    m = re.search(r"(forget|delete) custom command (.+)", t)
    if m:
        return {"kind": "custom_forget", "phrase": m.group(2).strip()}
    return None


def execute_custom_management(cmd: dict, store: CustomStore) -> str:
    kind = cmd["kind"]
    if kind == "custom_teach":
        store.add(cmd["phrase"], cmd["command"])
        return (
            f"Got it. When you say '{cmd['phrase']}', "
            f"I'll do: {cmd['command']}."
        )
    if kind == "custom_list":
        items = store.list_all()
        if not items:
            return "You don't have any custom commands yet."
        parts = "; ".join(f"'{p}' means '{c}'" for p, c in items.items())
        return f"Your custom commands: {parts}."
    if kind == "custom_forget":
        if store.remove(cmd["phrase"]):
            return f"Forgot '{cmd['phrase']}'."
        return f"I don't have a custom command called '{cmd['phrase']}'."
    return "I don't know how to do that yet."
