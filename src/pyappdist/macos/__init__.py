"""macOS packaging: assemble ``.app`` bundles, deep-sign, and wrap into a ``.dmg``."""

from __future__ import annotations

from .bundle import build_macos_apps, info_plist
from .icns import make_icns
from .package import build_dmg
from .sign import SignOptions, deep_sign

__all__ = [
    "build_macos_apps",
    "info_plist",
    "make_icns",
    "build_dmg",
    "deep_sign",
    "SignOptions",
]
