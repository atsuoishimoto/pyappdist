"""WiX (MSI) 生成（Phase 3）と MSI ビルド（Phase 5）。

* scan.py     : image を走査し中立な Directory/File IR を作る
* guid.py     : upgrade_code を namespace にした安定 GUID
* generate.py : IR → WiX v4 XML 文字列（純粋関数, Linux 完結）
* build.py    : 生成 .wxs を ``wix build`` で MSI 化（Windows / .exe ブリッジ）
"""

from __future__ import annotations

from .build import build_msi
from .generate import generate_wxs
from .scan import DirNode, FileNode, scan_image

__all__ = ["DirNode", "FileNode", "scan_image", "generate_wxs", "build_msi"]
