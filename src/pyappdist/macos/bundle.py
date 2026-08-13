"""Assemble ``.app`` bundles from a built image.

The image's ``python/`` tree (runtime + installed app) becomes ``Contents/Resources/python``;
each launcher Mach-O (built into the image dir by ``launcher/build.py``) becomes a bundle's
``Contents/MacOS/<name>`` / ``CFBundleExecutable``. Because a ``.app`` has exactly one
``CFBundleExecutable``, multiple launchers produce one ``.app`` each (all packed into one DMG
later). Info.plist is written with ``plistlib``; the icon is generated via :mod:`.icns`.

Launchers with ``app-entry = false`` are the exception: they get no bundle of their own
(anything under ``/Applications`` shows up in Launchpad), so their executable — and, for a
prebuilt stub, its sidecar config — is embedded into the first visible launcher's bundle,
next to its main executable. The stub finds the bundled python and its own sidecar relative
to its location, so an embedded copy needs no separate configuration; the deep-signing pass
picks it up like any other Mach-O in the bundle.
"""

from __future__ import annotations

import plistlib
import shutil
import tempfile
from pathlib import Path

from ..config import Config, LauncherConfig
from ..errors import BuildError
from .icns import make_icns
from .sign import _MACHO_MAGIC

_ICON_BASENAME = "AppIcon"  # Contents/Resources/AppIcon.icns; CFBundleIconFile omits the extension

_AR_MAGIC = b"!<arch>\n"  # static-library (ar) archive magic


def bundle_label(config: Config, spec: LauncherConfig) -> str:
    """Name (without ``.app``) of the bundle holding ``spec``'s executable.

    Mirrors :func:`build_macos_apps`: one bundle per ``app-entry`` launcher, named
    after the launcher's ``title`` when set, else after the app when it is the only
    visible launcher, else after the launcher; a hidden launcher's executable lives
    inside the first visible launcher's bundle.
    """
    visible = [s for s in config.launchers if s.app_entry]
    if not visible:
        raise BuildError(_ALL_HIDDEN_ERROR)
    host = spec if spec.app_entry else visible[0]
    if host.title:
        return host.title
    return config.name if len(visible) == 1 else host.name


_ALL_HIDDEN_ERROR = (
    "all launchers set app-entry = false; a .app build needs at least one "
    "launcher with an app entry to hold the bundle"
)


def build_macos_apps(config: Config, image_dir: Path, out_dir: Path, *, log=print) -> list[Path]:
    """Build one ``.app`` per ``app-entry`` launcher under ``out_dir``; return the bundle paths.

    Launchers with ``app-entry = false`` produce no bundle; their executables are
    embedded into the first visible launcher's bundle (see the module docstring).
    """
    python_src = image_dir / "python"
    if not python_src.is_dir():
        raise BuildError(f"image python tree missing: {python_src}")
    visible = [spec for spec in config.launchers if spec.app_entry]
    hidden = [spec for spec in config.launchers if not spec.app_entry]
    if not visible:
        raise BuildError(_ALL_HIDDEN_ERROR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Some wheels (notably PySide6's Qt) ship build leftovers — Mach-O object files
    # (.o) and static archives (.a) — that are never loaded at runtime but cannot carry
    # a valid code signature, so notarization rejects them ("binary is not signed").
    # Remove them up front (Apple's recommended fix); harmless for ad-hoc builds too.
    _prune_unsignable(python_src, log=log)

    # Each launcher gets its own icon (from its icon["macos"] PNG, else a placeholder),
    # so multiple launchers can have distinct .app icons.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        single = len(visible) == 1
        apps: list[Path] = []
        for spec in visible:
            launcher_bin = _launcher_bin(image_dir, spec.name)
            icon_rel = spec.icon_for("macos")
            icon_src = (config.project_dir / icon_rel).resolve() if icon_rel else None
            icns = make_icns(icon_src, tmp_path / f"{spec.name}.icns", log=log)
            label = bundle_label(config, spec)
            # A launcher name may hold characters an identifier may not (a space, say),
            # so the last segment is the base32 of the name — legal and unique whatever
            # the name is (see LauncherConfig.identifier_segment).
            identifier = (
                config.identifier if single
                else f"{config.identifier}.{spec.identifier_segment}"
            )
            app = _assemble_one(
                config, spec.name, label, identifier, python_src, launcher_bin, icns, out_dir, log
            )
            apps.append(app)
        for spec in hidden:
            _embed_hidden(image_dir, spec.name, apps[0], log)
    return apps


def _launcher_bin(image_dir: Path, name: str) -> Path:
    launcher_bin = image_dir / name
    if not launcher_bin.is_file():
        raise BuildError(f"launcher binary missing: {launcher_bin} (run build-launchers first)")
    return launcher_bin


def _embed_hidden(image_dir: Path, name: str, app: Path, log) -> None:
    """Place a hidden launcher's executable (and sidecar) into the host bundle.

    The executable goes to ``Contents/MacOS/<name>`` next to the host's main
    executable — the stub's relative paths (``../Resources/python``, its
    ``<name>.launcher.json`` sidecar) resolve identically from there.
    """
    launcher_bin = _launcher_bin(image_dir, name)
    log(f"macos: embedding {name} into {app.name} (app-entry = false)")
    dest = app / "Contents" / "MacOS" / name
    shutil.copy2(launcher_bin, dest)
    dest.chmod(0o755)
    sidecar = launcher_bin.parent / f"{name}.launcher.json"
    if sidecar.is_file():
        shutil.copy2(sidecar, app / "Contents" / "Resources" / f"{name}.launcher.json")


def _prune_unsignable(root: Path, *, log) -> int:
    """Delete Mach-O object files (``.o``) and static archives (``.a``) under ``root``.

    These are compiler/build artifacts found in some wheels; Python never loads them, and
    they fail notarization because an object file / static lib cannot hold a Developer ID
    signature with a secure timestamp. The magic bytes are checked so only genuine Mach-O
    objects / ``ar`` archives are removed (not unrelated files that happen to end in .o/.a).
    """
    removed = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix not in (".o", ".a"):
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(8)
        except OSError:
            continue
        if head[:4] in _MACHO_MAGIC or head == _AR_MAGIC:
            path.unlink()
            removed += 1
    if removed:
        log(f"macos: pruned {removed} unsignable Mach-O object/archive file(s) (.o/.a)")
    return removed


def _assemble_one(
    config: Config, exe_name: str, label: str, identifier: str,
    python_src: Path, launcher_bin: Path, icns: Path, out_dir: Path, log,
) -> Path:
    app = out_dir / f"{label}.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    log(f"macos: assembling {app.name}")
    shutil.copytree(python_src, resources / "python", symlinks=True)
    shutil.copy2(launcher_bin, macos / exe_name)
    (macos / exe_name).chmod(0o755)
    shutil.copy2(icns, resources / f"{_ICON_BASENAME}.icns")

    # A prebuilt launcher stub keeps its per-app config in a sidecar written
    # next to it in the image dir; stage it where the stub looks it up —
    # Contents/Resources/<exe>.launcher.json, sealed by the bundle's code
    # signature (per-executable, so several launchers can share one bundle). A
    # source-built launcher has the config compiled in and no sidecar.
    sidecar = launcher_bin.parent / f"{exe_name}.launcher.json"
    if sidecar.is_file():
        shutil.copy2(sidecar, resources / f"{exe_name}.launcher.json")

    plist = info_plist(config, executable=exe_name, identifier=identifier, display_name=label)
    (contents / "Info.plist").write_bytes(plist)
    return app


def info_plist(config: Config, *, executable: str, identifier: str, display_name: str) -> bytes:
    """Build the Info.plist payload for a bundle (pure; returned as bytes)."""
    keys: dict[str, object] = {
        "CFBundleExecutable": executable,
        "CFBundleIdentifier": identifier,
        "CFBundleName": display_name,
        "CFBundleDisplayName": display_name,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": config.version,
        "CFBundleVersion": config.version,
        "CFBundleIconFile": _ICON_BASENAME,
        "LSMinimumSystemVersion": config.macos.min_macos,
        "NSHighResolutionCapable": True,
    }
    if config.macos.category:
        keys["LSApplicationCategoryType"] = config.macos.category
    return plistlib.dumps(keys)
