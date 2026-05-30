"""Scan the image directory and produce a neutral Directory/File IR.

The output is deterministic (sorted by name). It is pure data, independent of
WiX generation (generate.py), so it is easy to handle in golden and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileNode:
    src: Path   # absolute path of the scanned source
    name: str   # file name
    rel: str    # path relative to the install root (posix separators)


@dataclass(frozen=True)
class DirNode:
    name: str                      # directory name ("" for the root)
    rel: str                       # path relative to the install root ("" for the root)
    subdirs: tuple["DirNode", ...]
    files: tuple[FileNode, ...]


def scan_image(image_dir: Path) -> DirNode:
    """Scan ``image_dir`` and return the install-root DirNode."""
    image_dir = Path(image_dir)
    return _scan(image_dir, "")


def _scan(current: Path, rel: str) -> DirNode:
    subdirs: list[DirNode] = []
    files: list[FileNode] = []
    for entry in sorted(current.iterdir(), key=lambda p: p.name):
        child_rel = f"{rel}/{entry.name}" if rel else entry.name
        if entry.is_dir():
            subdirs.append(_scan(entry, child_rel))
        elif entry.is_file():
            files.append(FileNode(src=entry, name=entry.name, rel=child_rel))
    name = current.name if rel else ""
    return DirNode(name=name, rel=rel, subdirs=tuple(subdirs), files=tuple(files))
