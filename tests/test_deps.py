"""Tests for dependency-list resolution (lockfile detection / requirements.txt reference)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.deps import (
    _auto_detect,
    _export_cmd,
    resolve_manager,
    resolve_requirements,
)
from pyappdist.errors import BuildError


def _touch(d: Path, name: str) -> None:
    (d / name).write_text("", encoding="utf-8")


def test_auto_detect_none(tmp_path: Path):
    assert _auto_detect(tmp_path) is None


@pytest.mark.parametrize(
    "lockfile,expected",
    [("uv.lock", "uv"), ("poetry.lock", "poetry"), ("Pipfile.lock", "pipenv"), ("pdm.lock", "pdm")],
)
def test_auto_detect_single(tmp_path: Path, lockfile: str, expected: str):
    _touch(tmp_path, lockfile)
    assert _auto_detect(tmp_path) == expected


def test_auto_detect_priority(tmp_path: Path):
    # When several exist, first wins in the order uv -> poetry -> pipenv -> pdm.
    _touch(tmp_path, "poetry.lock")
    _touch(tmp_path, "pdm.lock")
    _touch(tmp_path, "uv.lock")
    assert _auto_detect(tmp_path) == "uv"


def test_resolve_manager_override_wins(tmp_path: Path):
    _touch(tmp_path, "uv.lock")
    assert resolve_manager(tmp_path, "pdm", log=lambda _m: None) == "pdm"


def test_resolve_manager_auto(tmp_path: Path):
    _touch(tmp_path, "poetry.lock")
    assert resolve_manager(tmp_path, None, log=lambda _m: None) == "poetry"


def test_resolve_manager_fallback_to_requirements_txt(tmp_path: Path):
    # No lockfile, no manager setting, but a checked-in requirements.txt: use it (with a warning).
    _touch(tmp_path, "requirements.txt")
    msgs: list[str] = []
    assert resolve_manager(tmp_path, None, log=msgs.append) == "requirements.txt"
    assert any("warning" in m for m in msgs)


def test_resolve_manager_undeterminable_errors(tmp_path: Path):
    # No manager setting, no lockfile, and no requirements.txt: fail at determination time.
    with pytest.raises(BuildError, match="cannot determine the dependency manager"):
        resolve_manager(tmp_path, None, log=lambda _m: None)


def test_export_cmd_no_extras_is_nodev_default():
    # No extras: the command is the base export (production deps only).
    assert _export_cmd("uv", ()) == [
        "uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--emit-index-url",
        "--format", "requirements-txt",
    ]


@pytest.mark.parametrize(
    "manager,flag",
    [("uv", "--extra"), ("poetry", "--extras"), ("pipenv", "--categories"), ("pdm", "--group")],
)
def test_export_cmd_appends_extra_flags(manager: str, flag: str):
    cmd = _export_cmd(manager, ("gui", "extra"))
    # Each extra becomes a repeated selector flag, in order, after the base command.
    assert cmd[-4:] == [flag, "gui", flag, "extra"]


def test_resolve_requirements_extras_ignored_for_requirements_txt(tmp_path: Path, sample_config):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wh"
    wheelhouse.mkdir()
    cfg = dataclasses.replace(
        sample_config, project_dir=project, manager="requirements.txt", extras=("gui",)
    )
    msgs: list[str] = []

    resolve_requirements(cfg, wheelhouse, log=msgs.append)

    assert any("ignoring targets.extras" in m for m in msgs)


def test_resolve_requirements_uses_existing_file(tmp_path: Path, sample_config):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wh"
    wheelhouse.mkdir()
    cfg = dataclasses.replace(sample_config, project_dir=project, manager="requirements.txt")

    out = resolve_requirements(cfg, wheelhouse, log=lambda _m: None)

    assert out == wheelhouse / "requirements.txt"
    assert out.read_text(encoding="utf-8") == "requests==2.0\n"


def test_resolve_requirements_missing_file_errors(tmp_path: Path, sample_config):
    project = tmp_path / "proj"
    project.mkdir()
    wheelhouse = tmp_path / "wh"
    wheelhouse.mkdir()
    cfg = dataclasses.replace(sample_config, project_dir=project, manager="requirements.txt")

    with pytest.raises(BuildError, match="requirements.txt"):
        resolve_requirements(cfg, wheelhouse, log=lambda _m: None)
