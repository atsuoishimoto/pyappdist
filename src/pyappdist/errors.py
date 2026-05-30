"""pyappdist exception hierarchy."""

from __future__ import annotations


class PyappdistError(Exception):
    """Base for all pyappdist exceptions."""


class ConfigError(PyappdistError):
    """A problem in pyproject.toml / [tool.pyappdist]."""


class BuildError(PyappdistError):
    """A failure in a build step (wheel / runtime / image, etc.)."""
