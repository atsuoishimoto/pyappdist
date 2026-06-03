"""Shared POSIX packaging (Linux and macOS): a portable tarball plus a .run installer."""

from __future__ import annotations

from .build import build_posix

__all__ = ["build_posix"]
