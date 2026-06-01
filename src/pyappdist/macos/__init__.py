"""macOS packaging: assemble ``.app`` bundles, deep-sign, and wrap into a ``.dmg``."""

from __future__ import annotations

from .bundle import build_macos_apps, info_plist
from .icns import make_icns
from .notarize import notarize_and_staple, notarize_app, resolve_notary_profile
from .package import build_dmg
from .sign import SignOptions, deep_sign, entitlements_plist, resolve_sign_options, sign_file

__all__ = [
    "build_macos_apps",
    "info_plist",
    "make_icns",
    "build_dmg",
    "deep_sign",
    "sign_file",
    "SignOptions",
    "resolve_sign_options",
    "entitlements_plist",
    "notarize_and_staple",
    "notarize_app",
    "resolve_notary_profile",
]
