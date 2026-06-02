"""pyappdist CLI.

Each subcommand operates on one or more targets (``[[tool.pyappdist.targets]]``).
Positional arguments select targets by name. With none given, the pipeline stages
default to all targets, while ``build`` builds the sole target if only one is defined
and otherwise requires an explicit selection (so it doesn't build every target at once).
Output goes to ``<out-dir>/<target-name>/`` (default ``<project>/appdist/<target-name>``).

Subcommands:
  build-wheels    app + dependency wheels into <target>/wheelhouse
  fetch-runtime   python-build-standalone runtime into <target>/runtime
  build-image     runtime + install + compileall + launcher + portable zip into <target>/image
  build-launchers build launcher.exe inside the image (Windows, MSVC)
  gen-wix         scan the image and generate WiX XML (.wxs)
  build           run wheels->runtime->image->launcher->wix->MSI in one go
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from . import image as image_mod
from .config import ensure_upgrade_code, load_configs
from .context import BuildContext
from .errors import BuildError, PyappdistError
from .launcher import build_launchers
from .linux import build_linux
from .macos import build_macos
from .msix import build_msix
from .runtime import fetch_runtime
from .sign import sign_artifact
from .wheels import build_wheelhouse
from .wix import build_msi, generate_wxs, scan_image


def _contexts(args: argparse.Namespace) -> list[BuildContext]:
    """Resolve the selected targets into one BuildContext each (own output subdir)."""
    project_dir = Path(args.project).resolve()
    configs = load_configs(project_dir, select=args.targets or None)
    base = Path(args.out_dir).resolve() if args.out_dir else project_dir / "appdist"
    return [BuildContext(config=c, out_dir=base / c.target_name) for c in configs]


def _do_fetch_runtime(ctx: BuildContext, args: argparse.Namespace):
    return fetch_runtime(
        ctx.config.target,
        ctx.config.python,
        ctx.runtime_dir,
        runtime_release=args.runtime_release,
    )


def _tag(ctx: BuildContext) -> str:
    return ctx.config.target_name


def cmd_build_wheels(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        # Dependencies are resolved with the target runtime's python, so prepare it first.
        info = _do_fetch_runtime(ctx, args)
        wheels = build_wheelhouse(ctx.config, info, ctx.wheelhouse)
        print(f"OK [{_tag(ctx)}]: {len(wheels)} wheel -> {ctx.wheelhouse}")
    return 0


def cmd_fetch_runtime(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        info = _do_fetch_runtime(ctx, args)
        print(f"OK [{_tag(ctx)}]: runtime {info.version} -> {ctx.runtime_dir}")
    return 0


def cmd_build_image(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        info = _do_fetch_runtime(ctx, args)
        build_wheelhouse(ctx.config, info, ctx.wheelhouse)
        layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)
        exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
        # The zip includes launcher.exe, so do it after the launcher build.
        if not args.no_zip:
            image_mod.make_portable_zip(ctx)
        print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} ({len(exes)} launcher)")
    return 0


def cmd_build_launchers(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        if not ctx.image_dir.is_dir():
            raise BuildError(f"image is missing: {ctx.image_dir} (run build-image first)")
        layout = image_mod.ImageLayout(
            image_dir=ctx.image_dir,
            target=ctx.config.target,
            minor=ctx.config.python_minor,
        )
        exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
        print(f"OK [{_tag(ctx)}]: {len(exes)} launcher -> {layout.image_dir}")
    return 0


def _write_wxs(ctx: BuildContext) -> Path:
    # Ensure a stable per-target upgrade_code exists (persisted to pyproject.toml if unset).
    upgrade_code = ensure_upgrade_code(ctx.config.project_dir, ctx.config.target_name)
    config = ctx.config
    if config.wix.upgrade_code != upgrade_code:
        config = dataclasses.replace(
            config, wix=dataclasses.replace(config.wix, upgrade_code=upgrade_code)
        )
    tree = scan_image(ctx.image_dir)
    xml = generate_wxs(config, tree)
    wxs = ctx.out_dir / f"{ctx.config.dist_name}.wxs"
    wxs.write_text(xml, encoding="utf-8")
    return wxs


def cmd_gen_wix(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        if not ctx.image_dir.is_dir():
            raise BuildError(f"image is missing: {ctx.image_dir} (run build-image first)")
        wxs = _write_wxs(ctx)
        print(f"OK [{_tag(ctx)}]: wxs -> {wxs}")
    return 0


def _build_one(ctx: BuildContext, args: argparse.Namespace) -> None:
    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)

    if ctx.config.format in ("linux", "macos"):
        # Linux/macOS launchers are shell wrappers (no MSVC); the builder writes them into
        # the image and produces the portable tarball + self-extracting .run.
        fmt = ctx.config.format
        build = build_linux if fmt == "linux" else build_macos
        arts = build(ctx.config, layout, ctx.dist_dir)
        if arts is not None:
            print(f"OK [{_tag(ctx)}]: {fmt} -> {', '.join(str(a) for a in arts)}")
        else:
            os_name = "Linux" if fmt == "linux" else "macOS"
            print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} ({fmt} skipped on non-{os_name})")
        return

    exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
    for exe in exes:
        sign_artifact(exe)

    if ctx.config.format == "msix":
        # MSIX packs the image directly; no portable zip (the .msix is the deliverable).
        msix_name = f"{ctx.config.dist_name}-{ctx.config.version}.msix"
        pkg = build_msix(ctx.config, ctx.image_dir, ctx.dist_dir / msix_name)
        if pkg is not None:
            sign_artifact(pkg)
            print(f"OK [{_tag(ctx)}]: msix -> {pkg} ({len(exes)} launcher)")
        else:
            print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} (msix skipped on non-Windows)")
        return

    if not args.no_zip:
        image_mod.make_portable_zip(ctx)

    wxs = _write_wxs(ctx)
    msi_name = f"{ctx.config.dist_name}-{ctx.config.version}.msi"
    msi = build_msi(ctx.config, ctx.image_dir, wxs, ctx.dist_dir / msi_name)
    if msi is not None:
        sign_artifact(msi)
        print(f"OK [{_tag(ctx)}]: msi -> {msi} ({len(exes)} launcher)")
    else:
        print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} (msi skipped on non-Windows)")


def cmd_build(args: argparse.Namespace) -> int:
    """Run wheelhouse -> runtime -> image -> launcher -> wix -> MSI for each target."""
    contexts = _contexts(args)
    # Unlike the individual pipeline stages, build doesn't fan out over every target by
    # default: with several defined, an explicit selection is required so we don't build
    # them all at once. A sole target may still be built with no argument.
    if not args.targets and len(contexts) > 1:
        names = [ctx.config.target_name for ctx in contexts]
        raise BuildError(
            f"multiple targets are defined ({names}); specify which target(s) to build"
        )
    for ctx in contexts:
        if len(contexts) > 1:
            print(f"=== target: {ctx.config.target_name} ===")
        _build_one(ctx, args)
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "targets", nargs="*",
        help="target names (from [[tool.pyappdist.targets]]); default: all defined "
             "(build: the sole target, else a selection is required)",
    )
    p.add_argument("-C", "--project", default=".", help="the app's project directory")
    p.add_argument("--out-dir", help="output base directory (default: <project>/appdist)")


def _add_runtime_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--runtime-release", help="pin the python-build-standalone release tag")


def _version() -> str:
    try:
        return _pkg_version("pyappdist")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyappdist", description="Create a Windows distribution of a Python app")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-wheels", help="wheels into <target>/wheelhouse")
    _add_common(p)
    _add_runtime_opts(p)
    p.set_defaults(func=cmd_build_wheels)

    p = sub.add_parser("fetch-runtime", help="runtime into <target>/runtime")
    _add_common(p)
    _add_runtime_opts(p)
    p.set_defaults(func=cmd_fetch_runtime)

    p = sub.add_parser("build-image", help="image into <target>/image")
    _add_common(p)
    _add_runtime_opts(p)
    p.add_argument("--no-compile", action="store_true", help="skip compileall")
    p.add_argument("--no-zip", action="store_true", help="do not create a portable zip")
    p.set_defaults(func=cmd_build_image)

    p = sub.add_parser("build-launchers", help="build launcher.exe into the image (Windows)")
    _add_common(p)
    p.set_defaults(func=cmd_build_launchers)

    p = sub.add_parser("gen-wix", help="generate WiX XML (.wxs) from the image")
    _add_common(p)
    p.set_defaults(func=cmd_gen_wix)

    p = sub.add_parser("build", help="run wheels->runtime->image->launcher->wix->MSI in one go")
    _add_common(p)
    _add_runtime_opts(p)
    p.add_argument("--no-compile", action="store_true")
    p.add_argument("--no-zip", action="store_true")
    p.set_defaults(func=cmd_build)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PyappdistError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
