"""pyappdist の例外階層。"""

from __future__ import annotations


class PyappdistError(Exception):
    """pyappdist のすべての例外の基底。"""


class ConfigError(PyappdistError):
    """pyproject.toml / [tool.pyappdist] の不備。"""


class BuildError(PyappdistError):
    """ビルド工程（wheel / runtime / image など）の失敗。"""
