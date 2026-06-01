"""Minimal app for end-to-end verification of pyappdist run as an editable install."""

from __future__ import annotations

import sys


def main() -> int:
    print("pyappdist e2e smoke: OK")
    print(f"python {sys.version}")
    return 0
