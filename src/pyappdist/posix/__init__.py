"""Shared POSIX packaging (Linux and macOS): a self-extracting .run installer."""

from __future__ import annotations

from .build import build_posix

__all__ = ["build_posix"]
