"""pyappdist CLI.

Subcommands:
  build-wheels   app + dependency wheels into appdist/wheelhouse
  fetch-runtime  python-build-standalone runtime into appdist/runtime
  build-image    runtime + install + compileall + launcher + portable zip into appdist/image
  build-launchers build launcher.exe inside the image (Windows, MSVC)
  gen-wix        scan the image and generate WiX XML (.wxs)
  build          run wheels->runtime->image->launcher->wix->MSI in one go
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import image as image_mod
from .config import load_config
from .context import BuildContext
from .errors import BuildError, PyappdistError
from .launcher import build_launchers
from .runtime import fetch_runtime
from .sign import sign_artifact
from .wheels import build_wheelhouse
from .wix import build_msi, generate_wxs, scan_image


def _build_context(args: argparse.Namespace) -> BuildContext:
    project_dir = Path(args.project).resolve()
    config = load_config(project_dir, target_override=args.target)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else project_dir / "appdist"
    return BuildContext(config=config, out_dir=out_dir)


def _do_fetch_runtime(ctx: BuildContext, args: argparse.Namespace):
    return fetch_runtime(
        ctx.config.target,
        ctx.config.python,
        ctx.runtime_dir,
        runtime_source=Path(args.runtime_source) if args.runtime_source else None,
        runtime_release=args.runtime_release,
    )


def cmd_build_wheels(args: argparse.Namespace) -> int:
    ctx = _build_context(args)
    # Dependencies are resolved with the target runtime's python, so prepare the runtime first.
    info = _do_fetch_runtime(ctx, args)
    wheels = build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    print(f"OK: {len(wheels)} wheel -> {ctx.wheelhouse}")
    return 0


def cmd_fetch_runtime(args: argparse.Namespace) -> int:
    ctx = _build_context(args)
    info = _do_fetch_runtime(ctx, args)
    print(f"OK: runtime {info.version} -> {ctx.runtime_dir}")
    return 0


def cmd_build_image(args: argparse.Namespace) -> int:
    ctx = _build_context(args)
    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)
    exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
    # The zip includes launcher.exe, so do it after the launcher build.
    if not args.no_zip:
        image_mod.make_portable_zip(ctx)
    print(f"OK: image -> {layout.image_dir} ({len(exes)} launcher)")
    return 0


def cmd_build_launchers(args: argparse.Namespace) -> int:
    ctx = _build_context(args)
    if not ctx.image_dir.is_dir():
        raise BuildError(
            f"image is missing: {ctx.image_dir} (run build-image first)"
        )
    layout = image_mod.ImageLayout(
        image_dir=ctx.image_dir,
        target=ctx.config.target,
        minor=ctx.config.python_minor,
    )
    exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
    print(f"OK: {len(exes)} launcher -> {layout.image_dir}")
    return 0


def _write_wxs(ctx: BuildContext) -> Path:
    tree = scan_image(ctx.image_dir)
    xml = generate_wxs(ctx.config, tree)
    wxs = ctx.out_dir / f"{ctx.config.dist_name}.wxs"
    wxs.write_text(xml, encoding="utf-8")
    return wxs


def cmd_gen_wix(args: argparse.Namespace) -> int:
    ctx = _build_context(args)
    if not ctx.image_dir.is_dir():
        raise BuildError(f"image is missing: {ctx.image_dir} (run build-image first)")
    wxs = _write_wxs(ctx)
    print(f"OK: wxs -> {wxs}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Run wheelhouse -> runtime -> image -> launcher -> wix -> MSI in one go (Phase 5)."""
    ctx = _build_context(args)
    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)
    exes = build_launchers(ctx.config, layout, ctx.out_dir / "_launcher_build")
    for exe in exes:
        sign_artifact(exe)
    if not args.no_zip:
        image_mod.make_portable_zip(ctx)

    wxs = _write_wxs(ctx)
    msi = build_msi(ctx.config, ctx.image_dir, wxs, ctx.dist_dir / f"{ctx.config.dist_name}.msi")
    if msi is not None:
        sign_artifact(msi)
        print(f"OK: msi -> {msi} ({len(exes)} launcher)")
    else:
        print(f"OK: image -> {layout.image_dir} (msi skipped on non-Windows)")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("project", nargs="?", default=".", help="the app's project directory")
    p.add_argument("--target", help="distribution target (e.g. windows-x86_64 / linux-x86_64)")
    p.add_argument("--out-dir", help="output directory (default: <project>/appdist)")


def _add_runtime_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--runtime-release", help="pin the python-build-standalone release tag")
    p.add_argument("--runtime-source", help="local runtime tar.gz (offline)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyappdist", description="Create a Windows distribution of a Python app")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-wheels", help="wheels into appdist/wheelhouse")
    _add_common(p)
    _add_runtime_opts(p)
    p.set_defaults(func=cmd_build_wheels)

    p = sub.add_parser("fetch-runtime", help="runtime into appdist/runtime")
    _add_common(p)
    _add_runtime_opts(p)
    p.set_defaults(func=cmd_fetch_runtime)

    p = sub.add_parser("build-image", help="image into appdist/image")
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
