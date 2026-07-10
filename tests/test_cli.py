from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.cli import _contexts, build_parser
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


def test_out_dir_option_removed():
    # --out-dir was replaced by --appdist-dir/--build-dir; argparse should reject it.
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build", "--out-dir", "x"])


def test_default_dirs_split_artifacts_and_intermediates(tmp_path: Path):
    # Artifacts default to <project>/appdist, intermediates to <project>/.appdist-build.
    (tmp_path / "pyproject.toml").write_text(_MULTI, encoding="utf-8")
    args = build_parser().parse_args(["build", "-C", str(tmp_path), "win-user"])
    (ctx,) = _contexts(args)
    assert ctx.out_dir == tmp_path / "appdist" / "win-user"
    assert ctx.build_dir == tmp_path / ".appdist-build" / "win-user"
    assert ctx.dist_dir == ctx.out_dir / "dist"
    assert ctx.image_dir == ctx.build_dir / "image"


def test_appdist_and_build_dir_options_override(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(_MULTI, encoding="utf-8")
    args = build_parser().parse_args(
        ["build", "-C", str(tmp_path),
         "--appdist-dir", str(tmp_path / "art"),
         "--build-dir", str(tmp_path / "bld"),
         "win-user"]
    )
    (ctx,) = _contexts(args)
    assert ctx.out_dir == tmp_path / "art" / "win-user"
    assert ctx.build_dir == tmp_path / "bld" / "win-user"


_LINUX_ONLY = """
[project]
name = "helloworld"
version = "0.1.0"

[tool.pyappdist]
python = "3.12"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "lin"
platform = "linux-x86_64"
format = "linux"
"""


def test_gen_wix_skips_non_msi_targets(tmp_path: Path, capsys):
    # gen-wix on a linux target must be a no-op: no .wxs, and crucially no
    # MSI-only upgrade-code persisted into the target's pyproject.toml entry.
    (tmp_path / "pyproject.toml").write_text(_LINUX_ONLY, encoding="utf-8")
    args = build_parser().parse_args(["gen-wix", "-C", str(tmp_path)])
    assert args.func(args) == 0
    assert "skip" in capsys.readouterr().out
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == _LINUX_ONLY
    assert not list(tmp_path.rglob("*.wxs"))
