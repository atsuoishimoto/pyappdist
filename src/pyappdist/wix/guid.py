"""Stable GUID generation.

Component GUIDs are generated deterministically as uuid5(install-relative path)
with upgrade_code as the namespace. The same layout and the same upgrade_code
always yield the same GUID, preserving component identity across MajorUpgrade.
"""

from __future__ import annotations

import uuid


def is_guid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def stable_guid(upgrade_code: str, relpath: str) -> str:
    """Create a deterministic GUID from ``relpath`` using ``upgrade_code`` as the namespace."""
    namespace = uuid.UUID(str(upgrade_code))
    return str(uuid.uuid5(namespace, relpath)).upper()
