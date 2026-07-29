from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist import cli
from pyappdist.cli import _check_common_root, _contexts, build_parser
from pyappdist.errors import BuildError, ConfigError

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


def test_split_drive_dirs_rejected_at_startup(tmp_path: Path, monkeypatch):
    # On a native Windows host, --appdist-dir and --build-dir on different drives make
    # os.path.commonpath raise ValueError deep inside the packagers. Simulate the
    # Windows path semantics on any host and check the failure surfaces as a
    # ConfigError before any building starts.
    import ntpath
    import os as _os

    monkeypatch.setattr(_os.path, "commonpath", ntpath.commonpath)
    with pytest.raises(ConfigError, match="common root"):
        _check_common_root(Path("C:/artifacts"), Path("D:/build"))


def test_common_root_accepted(tmp_path: Path):
    # The default layout (both under the project dir) always shares a root.
    (tmp_path / "pyproject.toml").write_text(_MULTI, encoding="utf-8")
    args = build_parser().parse_args(["build", "-C", str(tmp_path), "win-user"])
    assert len(_contexts(args)) == 1


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


def test_main_reports_interrupt(monkeypatch, capsys):
    # Ctrl+C during a long stage must not dump a traceback.
    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_build", interrupted)
    assert cli.main(["build", "-C", "."]) == 130
    assert capsys.readouterr().err.strip() == "interrupted"


def test_main_reports_pyappdist_error(monkeypatch, capsys):
    def failing(args):
        raise BuildError("boom")

    monkeypatch.setattr(cli, "cmd_build", failing)
    assert cli.main(["build", "-C", "."]) == 1
    assert "error: boom" in capsys.readouterr().err


_NO_TOOL_VERSION = """
[project]
name = "helloworld"
dynamic = ["version"]

[tool.pyappdist]
python = "3.12"
launchers = [ { name = "helloworld", entry = "helloworld:main" } ]

[[tool.pyappdist.targets]]
name = "win"
platform = "windows-x86_64"
format = "msi"
"""


def _wheel_version_ctx(tmp_path: Path, wheel: str | None):
    (tmp_path / "pyproject.toml").write_text(_NO_TOOL_VERSION, encoding="utf-8")
    args = build_parser().parse_args(["build", "-C", str(tmp_path)])
    (ctx,) = _contexts(args)
    if wheel is not None:
        ctx.wheelhouse.mkdir(parents=True)
        (ctx.wheelhouse / wheel).write_bytes(b"")
    return ctx


def test_resolve_version_from_app_wheel(tmp_path: Path, capsys):
    # Without [tool.pyappdist].version, the version is filled in from the app
    # wheel build-wheels produced; the resolved config no longer carries the flag.
    ctx = _wheel_version_ctx(tmp_path, "helloworld-1.2.3-py3-none-any.whl")
    assert ctx.config.version_from_wheel
    ctx = cli._resolve_version(ctx)
    assert ctx.config.version == "1.2.3"
    assert not ctx.config.version_from_wheel
    assert "1.2.3" in capsys.readouterr().out


def test_resolve_version_explicit_is_noop(tmp_path: Path):
    text = _MULTI.replace("[tool.pyappdist]", '[tool.pyappdist]\nversion = "0.1.0"')
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    args = build_parser().parse_args(["build", "-C", str(tmp_path), "win-user"])
    (ctx,) = _contexts(args)
    assert cli._resolve_version(ctx) is ctx


def test_resolve_version_requires_wheelhouse(tmp_path: Path):
    ctx = _wheel_version_ctx(tmp_path, None)
    with pytest.raises(BuildError, match="run build-wheels first"):
        cli._resolve_version(ctx)


def test_resolve_version_enforces_msi_rule(tmp_path: Path):
    # The msi/msix dotted-numeric check was deferred at load time (the version
    # was unknown); it must fire against the resolved version.
    ctx = _wheel_version_ctx(tmp_path, "helloworld-1.2.3.dev4+g1a2b3c-py3-none-any.whl")
    with pytest.raises(ConfigError, match="dotted numeric"):
        cli._resolve_version(ctx)
