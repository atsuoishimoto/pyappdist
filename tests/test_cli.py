from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.cli import build_parser
from pyappdist.errors import BuildError

_MULTI = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "win-user"
platform = "windows-x86_64"
format = "msi"
scope = "user"

[[tool.pyappdist.targets]]
name = "win-machine"
platform = "windows-x86_64"
format = "msi"
scope = "machine"
"""


def _run_build(project: Path, *targets: str) -> int:
    args = build_parser().parse_args(["build", "-C", str(project), *targets])
    return args.func(args)


def test_build_requires_selection_with_multiple_targets(tmp_path: Path):
    # build refuses to fan out over every target; the check fires before any building.
    (tmp_path / "pyproject.toml").write_text(_MULTI, encoding="utf-8")
    with pytest.raises(BuildError, match="multiple targets are defined"):
        _run_build(tmp_path)
