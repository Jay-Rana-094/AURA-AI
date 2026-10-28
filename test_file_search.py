"""Tests for Phase 6 file search (no microphone needed — the
opener is stubbed, the searched folders are temp dirs).

    python test_file_search.py
"""

import os
import tempfile

import aura.commands.file_cmds as fs
from aura.brain import handle, set_custom_store, set_memory
from aura.commands.custom import CustomStore
from aura.commands.file_cmds import execute_file_command, parse_file_command
from aura.memory import Memory


def _make_tree():
    """Temp Documents/Downloads/Desktop with a few known files."""
    base = tempfile.mkdtemp()
    roots = []
    for folder in ("Documents", "Downloads", "Desktop"):
        path = os.path.join(base, folder)
        os.makedirs(path)
        roots.append(path)
    docs, downloads, desktop = roots
    open(os.path.join(docs, "report.pdf"), "w").write("a")
    open(os.path.join(docs, "report-final.pdf"), "w").write("b")
    open(os.path.join(downloads, "resume.docx"), "w").write("c")
    open(os.path.join(desktop, "notes.txt"), "w").write("d")
    old = os.path.join(downloads, "old")
    os.makedirs(old)
    open(os.path.join(old, "report-2024.pdf"), "w").write("e")
    return roots


def main():
    tmp = tempfile.mkdtemp()
    set_custom_store(CustomStore(os.path.join(tmp, "custom.json")))
    set_memory(Memory(":memory:"))
    roots = _make_tree()

    # --- Parser: every phrasing, and no false friends. ---
    cmd = parse_file_command("find my report file")
    assert cmd["kind"] == "search" and cmd["words"] == ["report"], cmd
    cmd = parse_file_command("search for resume pdf")
    assert cmd["words"] == ["resume", "pdf"], cmd
    cmd = parse_file_command("where is my resume")
    assert cmd["kind"] == "locate" and cmd["words"] == ["resume"], cmd
    cmd = parse_file_command("open file resume")
    assert cmd["kind"] == "search" and cmd["words"] == ["resume"], cmd
    assert parse_file_command("find file")["kind"] == "ask"
    assert parse_file_command("open notepad") is None
    assert parse_file_command("open vs code") is None
    assert parse_file_command("what is the time") is None

    # --- Executor with a stubbed opener. ---
    opened = []
    fs._open_file = lambda path: opened.append(path) or True

    reply = execute_file_command(
        {"kind": "search", "words": ["report"]}, roots
    )
    assert "3 matching files" in reply, reply
    assert "report.pdf" in reply and "report-final.pdf" in reply, reply
    assert not opened  # several matches: nothing opens by surprise

    reply = execute_file_command(
        {"kind": "search", "words": ["report", "final"]}, roots
    )
    assert "Opening it" in reply and "report-final.pdf" in reply, reply
    assert opened[-1].endswith("report-final.pdf"), opened

    reply = execute_file_command(
        {"kind": "locate", "words": ["resume"]}, roots
    )
    assert "resume.docx" in reply and "Downloads" in reply, reply
    assert len(opened) == 1  # locate never opens

    reply = execute_file_command(
        {"kind": "search", "words": ["nosuchfile123"]}, roots
    )
    assert "couldn't find" in reply, reply

    reply = execute_file_command(
        {"kind": "search", "words": ["notes"]}, roots
    )
    assert "notes.txt" in reply and "Desktop" in reply, reply

    # --- Voice end to end through handle() (real home folders,
    # read-only walk, nonsense name so nothing can match). ---
    reply, _ = handle("where is nosuchfile123xyz")
    assert "couldn't find" in reply, reply

    print("All file-search tests passed.")


if __name__ == "__main__":
    main()
