"""Linux packaging: a portable .tar.gz plus a self-extracting .run installer."""

from __future__ import annotations

from .build import build_linux

__all__ = ["build_linux"]
