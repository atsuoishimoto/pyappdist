"""pyappdist CLI.

Each subcommand operates on one or more targets (``[[tool.pyappdist.targets]]``).
Positional arguments select targets by name; with none given, all targets are built.
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
import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from . import image as image_mod
from .config import ensure_upgrade_code, load_configs
from .context import BuildContext
from .errors import BuildError, PyappdistError
from .launcher import build_launchers
from .macos import (
    build_dmg,
    build_macos_apps,
    deep_sign,
    notarize_and_staple,
    notarize_app,
    resolve_notary_profile,
    resolve_sign_options,
    sign_file,
)
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
        runtime_source=Path(args.runtime_source) if args.runtime_source else None,
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


def _build_macos(ctx: BuildContext, args: argparse.Namespace) -> None:
    """Build a macOS .app (and, for format=dmg, a .dmg). Native-only: needs a macOS host."""
    cfg = ctx.config
    tag = _tag(ctx)
    if sys.platform != "darwin":
        print(f"OK [{tag}]: skipped ({cfg.format} requires a macOS host)")
        return
    if platform.machine() != "arm64":
        raise BuildError(
            f"{cfg.target_name} build requires an arm64 (Apple Silicon) host; got {platform.machine()!r}"
        )

    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(cfg, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)
    build_launchers(cfg, layout, ctx.out_dir / "_launcher_build")  # Mach-O into image/<name>

    build_dir = ctx.out_dir / "_app_build"
    sign_opts = resolve_sign_options(cfg, build_dir)
    apps = build_macos_apps(cfg, layout.image_dir, build_dir)
    for app in apps:
        deep_sign(app, sign_opts)

    # Notarization requires a real Developer ID signature; ad-hoc cannot be notarized.
    profile = resolve_notary_profile(cfg)
    notarize = profile is not None and not sign_opts.adhoc
    if profile is not None and sign_opts.adhoc:
        print(f"OK [{tag}]: notarization skipped (ad-hoc signature; set signing_identity for Developer ID)")

    if cfg.format == "app":
        ctx.dist_dir.mkdir(parents=True, exist_ok=True)
        finals: list[Path] = []
        for app in apps:
            dest = ctx.dist_dir / app.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(app, dest, symlinks=True)
            finals.append(dest)
        if notarize:
            for dest in finals:
                notarize_app(dest, profile)  # zip-submit, then staple the bundle
        print(f"OK [{tag}]: {len(finals)} .app -> {ctx.dist_dir}")
        return

    dmg = build_dmg(cfg, apps, ctx.dist_dir / f"{cfg.dist_name}-{cfg.version}.dmg")
    if not sign_opts.adhoc:
        sign_file(dmg, sign_opts)  # sign the disk image itself with the Developer ID
    sign_artifact(dmg)  # optional extra signing via PYAPPDIST_SIGN_CMD
    if notarize:
        notarize_and_staple(dmg, profile)
    print(f"OK [{tag}]: dmg -> {dmg} ({len(apps)} app)")


def _build_one(ctx: BuildContext, args: argparse.Namespace) -> None:
    if ctx.config.format in ("app", "dmg"):
        _build_macos(ctx, args)
        return

    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)
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
    for ctx in contexts:
        if len(contexts) > 1:
            print(f"=== target: {ctx.config.target_name} ===")
        _build_one(ctx, args)
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "targets", nargs="*",
        help="target names to build (from [[tool.pyappdist.targets]]); default: all",
    )
    p.add_argument("-C", "--project", default=".", help="the app's project directory")
    p.add_argument("--out-dir", help="output base directory (default: <project>/appdist)")


def _add_runtime_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--runtime-release", help="pin the python-build-standalone release tag")
    p.add_argument("--runtime-source", help="local runtime tar.gz (offline)")


def _version() -> str:
    try:
        return _pkg_version("pyappdist")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyappdist", description="Create a native distribution (Windows .msi/.msix, macOS .app/.dmg) of a Python app")
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
