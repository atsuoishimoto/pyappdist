"""Tests for wheelhouse helpers (no pip involved)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import Config
from pyappdist.errors import BuildError
from pyappdist.wheels import app_wheel_version


def _touch(wheelhouse: Path, *names: str) -> None:
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for name in names:
        (wheelhouse / name).write_bytes(b"")


def test_app_wheel_version(sample_config: Config, tmp_path: Path):
    _touch(
        tmp_path,
        "helloworld-1.5.0.dev3+g1a2b3c-py3-none-any.whl",
        "numpy-2.1.0-cp312-cp312-win_amd64.whl",
    )
    assert app_wheel_version(sample_config, tmp_path) == "1.5.0.dev3+g1a2b3c"


def test_app_wheel_version_canonical_name(sample_config: Config, tmp_path: Path):
    # Wheel filenames escape the project name (my-app -> my_app, case folded).
    config = dataclasses.replace(sample_config, dist_name="Hello-World")
    _touch(tmp_path, "hello_world-2.0.0-py3-none-any.whl")
    assert app_wheel_version(config, tmp_path) == "2.0.0"


def test_app_wheel_version_missing(sample_config: Config, tmp_path: Path):
    _touch(tmp_path, "numpy-2.1.0-cp312-cp312-win_amd64.whl")
    with pytest.raises(BuildError, match="run build-wheels first"):
        app_wheel_version(sample_config, tmp_path)


def test_app_wheel_version_ambiguous(sample_config: Config, tmp_path: Path):
    _touch(
        tmp_path,
        "helloworld-1.0.0-py3-none-any.whl",
        "helloworld-2.0.0-py3-none-any.whl",
    )
    with pytest.raises(BuildError, match="multiple versions"):
        app_wheel_version(sample_config, tmp_path)
