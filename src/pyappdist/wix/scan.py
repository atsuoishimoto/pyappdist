"""image ディレクトリを走査し、中立な Directory/File IR を生成する。

生成は決定的（名前順）。WiX 生成（generate.py）とは独立した純粋なデータで、
ゴールデンテストや単体テストで扱いやすいようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileNode:
    src: Path   # 走査元の絶対パス
    name: str   # ファイル名
    rel: str    # install ルートからの相対パス (posix 区切り)


@dataclass(frozen=True)
class DirNode:
    name: str                      # ディレクトリ名（ルートは ""）
    rel: str                       # install ルートからの相対パス（ルートは ""）
    subdirs: tuple["DirNode", ...]
    files: tuple[FileNode, ...]


def scan_image(image_dir: Path) -> DirNode:
    """``image_dir`` を走査して install ルートの DirNode を返す。"""
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
