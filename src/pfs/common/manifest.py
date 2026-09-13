"""Directory scanning and selection expansion."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Iterable

TYPE_FILE = "file"
TYPE_DIR = "dir"


@dataclass
class Entry:
    path: str  # posix-style, relative to the shared root
    type: str  # TYPE_FILE | TYPE_DIR
    size: int
    mtime: int

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Entry":
        return Entry(
            path=str(d["path"]),
            type=str(d.get("type", TYPE_FILE)),
            size=int(d.get("size", 0)),
            mtime=int(d.get("mtime", 0)),
        )


def _rel(root: str, full: str) -> str:
    return os.path.relpath(full, root).replace(os.sep, "/")


def scan_folder(root: str) -> list[Entry]:
    """Walk ``root`` and return a sorted manifest of files and directories."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

    entries: list[Entry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        if os.path.abspath(dirpath) != root:
            try:
                mtime = int(os.path.getmtime(dirpath))
            except OSError:
                mtime = 0
            entries.append(Entry(_rel(root, dirpath), TYPE_DIR, 0, mtime))
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            entries.append(Entry(_rel(root, full), TYPE_FILE, st.st_size, int(st.st_mtime)))

    entries.sort(key=lambda e: e.path)
    return entries


def expand_selection(entries: Iterable[Entry], selected: Iterable[str]) -> list[Entry]:
    """Expand a list of file/dir paths into the concrete file entries to fetch."""
    entries = list(entries)
    files = {e.path: e for e in entries if e.type == TYPE_FILE}

    result: list[Entry] = []
    seen: set[str] = set()
    for raw in selected:
        p = raw.strip().strip("/")
        if not p:
            continue
        if p in files:
            candidates = [files[p]]
        else:
            prefix = p + "/"
            candidates = [f for f in files.values() if f.path.startswith(prefix)]
        for entry in candidates:
            if entry.path not in seen:
                seen.add(entry.path)
                result.append(entry)
    return result
