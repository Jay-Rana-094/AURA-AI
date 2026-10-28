"""File search — Phase 6.

Find files by name in Documents, Downloads and Desktop, spoken
back by voice. No index, no new packages: a plain walk of the
three folders, newest first.

Behaviour (deliberately narrow, so nothing opens by surprise):
  - one match for "find"/"open file" -> opened + confirmed.
  - several matches -> listed (name + folder), so a more specific
    name narrows it to one.
  - "where is ..." never opens anything, it only reports.
  - nothing found -> says so, naming the folders searched.

The opener lives behind the module-level _open_file() so tests
can stub it without a Windows box.
"""

import os
import re

# Words Vosk hears around the real search terms ("find my report
# file" -> just "report").
_FILLERS = {
    "my", "the", "a", "an", "file", "files", "document", "documents",
    "please", "for",
}

_MAX_MATCHES = 50
_LIST_LIMIT = 5


def default_roots():
    """Documents, Downloads and Desktop under the user's home."""
    home = os.path.expanduser("~")
    roots = []
    for name in ("Documents", "Downloads", "Desktop"):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            roots.append(path)
    return roots


def _open_file(path: str) -> bool:
    """Open ``path`` with its default app. Windows only."""
    if os.name != "nt":
        return False
    try:
        os.startfile(path)  # noqa: S606 - path came from our own search
        return True
    except Exception:  # noqa: BLE001 - any failure reads as False
        return False


def _query_words(raw: str):
    """Strip filler words, leaving the real search terms."""
    return [w for w in raw.strip().lower().split() if w not in _FILLERS]


def _search(words, roots):
    """Files whose names contain every word, newest first.

    Returns a list of (path, display) where display is the name
    plus its folder relative to the searched root, e.g.
    "report.pdf in Downloads/old". Stops at _MAX_MATCHES.
    """
    matches = []
    for root in roots:
        root_name = os.path.basename(root.rstrip(os.sep))
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden folders (e.g. .cache) and stop early.
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                lowered = name.lower()
                if all(w in lowered for w in words):
                    path = os.path.join(dirpath, name)
                    rel = os.path.relpath(dirpath, root)
                    folder = root_name if rel == "." else (
                        f"{root_name}/{rel.replace(os.sep, '/')}"
                    )
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        mtime = 0
                    matches.append((mtime, path, f"{name} in {folder}"))
                    if len(matches) >= _MAX_MATCHES:
                        break
            if len(matches) >= _MAX_MATCHES:
                break
        if len(matches) >= _MAX_MATCHES:
            break
    matches.sort(key=lambda item: item[0], reverse=True)
    return [(path, display) for _, path, display in matches]


def parse_file_command(text: str):
    """Match spoken text to a file request. None if no match."""
    t = text.strip().lower()
    m = re.match(r"^(find|search for|look for|locate)( my| the)? (.+)$", t)
    if m:
        words = _query_words(m.group(3))
        if not words:
            return {"kind": "ask"}
        return {"kind": "search", "words": words}
    m = re.match(r"^where is (my |the )?(.+)$", t)
    if m:
        words = _query_words(m.group(2))
        if not words:
            return {"kind": "ask"}
        return {"kind": "locate", "words": words}
    m = re.match(r"^open (file|document) (.+)$", t)
    if m:
        words = _query_words(m.group(2))
        if not words:
            return {"kind": "ask"}
        return {"kind": "search", "words": words}
    return None


def execute_file_command(cmd: dict, roots=None) -> str:
    """Carry out a parsed file command and reply."""
    if cmd["kind"] == "ask":
        return "What file should I look for?"
    roots = roots if roots is not None else default_roots()
    if not roots:
        return "I couldn't find your Documents, Downloads or Desktop folders."
    query = " ".join(cmd["words"])
    matches = _search(cmd["words"], roots)
    if not matches:
        return (
            f"I couldn't find a file named '{query}' in Documents, "
            "Downloads or Desktop."
        )
    if cmd["kind"] == "locate":
        if len(matches) == 1:
            return f"Found {matches[0][1]}."
        shown = "; ".join(display for _, display in matches[:_LIST_LIMIT])
        reply = f"Found {len(matches)} matching files: {shown}."
        if len(matches) > _LIST_LIMIT:
            reply += f" And {len(matches) - _LIST_LIMIT} more."
        return reply
    # search / open: a single match opens, several get listed.
    if len(matches) == 1:
        path, display = matches[0]
        if _open_file(path):
            return f"Found {display}. Opening it."
        return f"Found {display}, but I couldn't open it."
    shown = "; ".join(display for _, display in matches[:_LIST_LIMIT])
    reply = (
        f"Found {len(matches)} matching files: {shown}. "
        "Say a more specific name to open one."
    )
    if len(matches) > _LIST_LIMIT:
        reply += f" And {len(matches) - _LIST_LIMIT} more."
    return reply
