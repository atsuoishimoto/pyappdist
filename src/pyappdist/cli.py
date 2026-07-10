"""pyappdist CLI.

Each subcommand operates on one or more targets (``[[tool.pyappdist.targets]]``).
Positional arguments select targets by name. With none given, the pipeline stages
default to all targets, while ``build`` builds the sole target if only one is defined
and otherwise requires an explicit selection (so it doesn't build every target at once).
Build intermediates go to ``<build-dir>/<target-name>/`` (default
``<project>/.appdist-build/<target-name>``); final artifacts go to
``<appdist-dir>/<target-name>/dist/`` (default ``<project>/appdist/<target-name>/dist``).

Subcommands:
  build-wheels    app + dependency wheels into <target>/wheelhouse
  fetch-runtime   python-build-standalone runtime into <target>/runtime
  build-image     runtime + install + compileall + launcher into <target>/image
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
from .launcher.build import macos_arch
from .linux import build_linux
from .macos import build_macos
from .macos.bundle import build_macos_apps
from .macos.notarize import notarize_and_staple, notarize_app, resolve_notary_profile
from .macos.package import build_dmg
from .macos.sign import deep_sign, resolve_sign_options, sign_file
from .msix import build_msix
from .runtime import fetch_runtime
from .sign import env_sign_command, resolve_msi_sign_command, sign_artifact
from .wheels import build_wheelhouse
from .wix import build_msi, generate_wxs, scan_image


def _contexts(args: argparse.Namespace) -> list[BuildContext]:
    """Resolve the selected targets into one BuildContext each (own output subdir)."""
    project_dir = Path(args.project).resolve()
    configs = load_configs(project_dir, select=args.targets or None)
    appdist_base = Path(args.appdist_dir).resolve() if args.appdist_dir else project_dir / "appdist"
    build_base = Path(args.build_dir).resolve() if args.build_dir else project_dir / ".appdist-build"
    return [
        BuildContext(
            config=c,
            out_dir=appdist_base / c.target_name,
            build_dir=build_base / c.target_name,
        )
        for c in configs
    ]


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
        exes = build_launchers(ctx.config, layout, ctx.launcher_build_dir)
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
        exes = build_launchers(ctx.config, layout, ctx.launcher_build_dir)
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
    wxs = ctx.wxs_path
    wxs.parent.mkdir(parents=True, exist_ok=True)
    wxs.write_text(xml, encoding="utf-8")
    return wxs


def cmd_gen_wix(args: argparse.Namespace) -> int:
    for ctx in _contexts(args):
        # Only MSI uses a .wxs; running on other formats would emit a meaningless
        # file and, worse, persist an MSI-only upgrade-code into their pyproject.toml
        # entry (via ensure_upgrade_code in _write_wxs).
        if ctx.config.format != "msi":
            print(f"skip [{_tag(ctx)}]: gen-wix applies to msi targets only "
                  f"(format is {ctx.config.format!r})")
            continue
        if not ctx.image_dir.is_dir():
            raise BuildError(f"image is missing: {ctx.image_dir} (run build-image first)")
        wxs = _write_wxs(ctx)
        print(f"OK [{_tag(ctx)}]: wxs -> {wxs}")
    return 0


def _build_one(ctx: BuildContext, args: argparse.Namespace) -> None:
    # A full build starts from a clean intermediates tree (unlike the individual stages,
    # which stay incremental). The downloaded runtime cache lives elsewhere, so this does
    # not trigger a re-download.
    if ctx.build_dir.exists():
        shutil.rmtree(ctx.build_dir)
    info = _do_fetch_runtime(ctx, args)
    build_wheelhouse(ctx.config, info, ctx.wheelhouse)
    layout = image_mod.build_image(ctx, info, compile_pyc=not args.no_compile)

    if ctx.config.format in ("linux", "macos"):
        # Linux/macOS launchers are shell wrappers (no MSVC); the builder writes them into
        # the image and produces the self-extracting .run installer.
        fmt = ctx.config.format
        build = build_linux if fmt == "linux" else build_macos
        arts = build(ctx.config, layout, ctx.dist_dir)
        if arts is not None:
            print(f"OK [{_tag(ctx)}]: {fmt} -> {', '.join(str(a) for a in arts)}")
        else:
            os_name = "Linux" if fmt == "linux" else "macOS"
            print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} ({fmt} skipped on non-{os_name})")
        return

    if ctx.config.format in ("macapp", "dmg"):
        # macOS .app bundle (GUI distribution). Native-only, so the host check happens
        # before clang runs; reuses the image built above.
        _build_macos_bundle(ctx, layout)
        return

    # MSI signs the launcher .exe + .msi when code_sign is set (env > config > default);
    # MSIX keeps the legacy env-only behaviour.
    sign_cmd = (
        resolve_msi_sign_command(ctx.config.wix)
        if ctx.config.format == "msi"
        else env_sign_command()
    )
    exes = build_launchers(ctx.config, layout, ctx.launcher_build_dir)
    for exe in exes:
        sign_artifact(exe, sign_cmd)

    if ctx.config.format == "msix":
        # MSIX packs the image directly; no portable zip (the .msix is the deliverable).
        msix_name = f"{ctx.config.dist_name}-{ctx.config.version}.msix"
        pkg = build_msix(ctx.config, ctx.image_dir, ctx.dist_dir / msix_name)
        if pkg is not None:
            sign_artifact(pkg, sign_cmd)
            print(f"OK [{_tag(ctx)}]: msix -> {pkg} ({len(exes)} launcher)")
        else:
            print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} (msix skipped on non-Windows)")
        return

    wxs = _write_wxs(ctx)
    msi_name = f"{ctx.config.dist_name}-{ctx.config.version}.msi"
    msi = build_msi(ctx.config, ctx.image_dir, wxs, ctx.dist_dir / msi_name)
    if msi is not None:
        sign_artifact(msi, sign_cmd)
        print(f"OK [{_tag(ctx)}]: msi -> {msi} ({len(exes)} launcher)")
    else:
        print(f"OK [{_tag(ctx)}]: image -> {layout.image_dir} (msi skipped on non-Windows)")


def _build_macos_bundle(ctx: BuildContext, layout: image_mod.ImageLayout) -> None:
    """Assemble, sign, and package the macOS ``.app``/``.dmg`` from an already-built image.

    Native-only (codesign/hdiutil/clang are macOS tools), so on a non-macOS host it skips
    with a note — the same courtesy msi/msix extend on non-Windows. The launchers are built
    here (Mach-O via clang) rather than earlier, so the host check precedes the toolchain.
    """
    cfg = ctx.config
    tag = _tag(ctx)
    if sys.platform != "darwin":
        print(f"OK [{tag}]: image -> {layout.image_dir} ({cfg.format} skipped on non-macOS)")
        return

    host = platform.machine()
    target_arch = macos_arch(cfg.target)
    if host != target_arch:
        print(f"warning [{tag}]: building {target_arch} on a {host} host; the .app cannot "
              "be run or signature-verified locally (notarization still works)")

    # Mach-O launchers (CFBundleExecutable of each bundle) into the image dir.
    build_launchers(cfg, layout, ctx.launcher_build_dir)

    build_dir = ctx.app_build_dir
    sign_opts = resolve_sign_options(cfg, build_dir)
    apps = build_macos_apps(cfg, layout.image_dir, build_dir)
    for app in apps:
        deep_sign(app, sign_opts)

    # Notarization needs a real Developer ID signature; ad-hoc cannot be notarized.
    profile = resolve_notary_profile(cfg)
    notarize = profile is not None and not sign_opts.adhoc
    if profile is not None and sign_opts.adhoc:
        print(f"OK [{tag}]: notarization skipped (ad-hoc signature; set signing-identity "
              "for Developer ID)")

    ctx.dist_dir.mkdir(parents=True, exist_ok=True)
    if cfg.format == "macapp":
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
    sign_artifact(dmg, env_sign_command())  # optional extra signing via PYAPPDIST_SIGN_CMD
    if notarize:
        notarize_and_staple(dmg, profile)
    print(f"OK [{tag}]: dmg -> {dmg} ({len(apps)} app)")


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
    p.add_argument(
        "--appdist-dir",
        help="artifacts base directory (default: <project>/appdist)",
    )
    p.add_argument(
        "--build-dir",
        help="build intermediates base directory (default: <project>/.appdist-build)",
    )


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
