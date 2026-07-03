"""macOS packaging: a self-extracting .run installer."""

from __future__ import annotations

from .build import build_macos

__all__ = ["build_macos"]
