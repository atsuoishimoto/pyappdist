"""WiX (MSI) generation (Phase 3) and MSI build (Phase 5).

* scan.py     : scan the image and build a neutral Directory/File IR
* guid.py     : stable GUIDs using upgrade_code as the namespace
* generate.py : IR -> WiX v4 XML string (pure function, runs entirely on Linux)
* build.py    : turn the generated .wxs into an MSI via ``wix build`` (Windows / .exe bridge)
"""

from __future__ import annotations

from .build import build_msi
from .generate import generate_wxs
from .scan import DirNode, FileNode, scan_image

__all__ = ["DirNode", "FileNode", "scan_image", "generate_wxs", "build_msi"]
