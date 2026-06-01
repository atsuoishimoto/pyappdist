"""MSIX packaging (Microsoft Store / sideload)."""

from __future__ import annotations

from .build import build_msix
from .manifest import generate_manifest

__all__ = ["build_msix", "generate_manifest"]
