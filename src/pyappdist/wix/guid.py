"""安定 GUID 生成。

Component GUID は upgrade_code を namespace とした uuid5(install 相対パス) で
決定的に生成する。同じ配置・同じ upgrade_code なら毎回同じ GUID になり、
MajorUpgrade のコンポーネント同一性が保たれる。
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
    """``upgrade_code`` を namespace に ``relpath`` から決定的な GUID を作る。"""
    namespace = uuid.UUID(str(upgrade_code))
    return str(uuid.uuid5(namespace, relpath)).upper()
