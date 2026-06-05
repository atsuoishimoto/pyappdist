"""Assemble ``.app`` bundles from a built image.

The image's ``python/`` tree (runtime + installed app) becomes ``Contents/Resources/python``;
each launcher Mach-O (built into the image dir by ``launcher/build.py``) becomes a bundle's
``Contents/MacOS/<name>`` / ``CFBundleExecutable``. Because a ``.app`` has exactly one
``CFBundleExecutable``, multiple launchers produce one ``.app`` each (all packed into one DMG
later). Info.plist is written with ``plistlib``; the icon is generated via :mod:`.icns`.
"""

from __future__ import annotations

import plistlib
import shutil
import tempfile
from pathlib import Path

from ..config import Config
from ..errors import BuildError
from .icns import make_icns
from .sign import _MACHO_MAGIC

_ICON_BASENAME = "AppIcon"  # Contents/Resources/AppIcon.icns; CFBundleIconFile omits the extension

_AR_MAGIC = b"!<arch>\n"  # static-library (ar) archive magic


def build_macos_apps(config: Config, image_dir: Path, out_dir: Path, *, log=print) -> list[Path]:
    """Build one ``.app`` per launcher under ``out_dir``; return the bundle paths."""
    python_src = image_dir / "python"
    if not python_src.is_dir():
        raise BuildError(f"image python tree missing: {python_src}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Some wheels (notably PySide6's Qt) ship build leftovers — Mach-O object files
    # (.o) and static archives (.a) — that are never loaded at runtime but cannot carry
    # a valid code signature, so notarization rejects them ("binary is not signed").
    # Remove them up front (Apple's recommended fix); harmless for ad-hoc builds too.
    _prune_unsignable(python_src, log=log)

    # Generate the icon once and reuse it across bundles.
    icon_src = (config.project_dir / config.macos.icon).resolve() if config.macos.icon else None
    with tempfile.TemporaryDirectory() as tmp:
        shared_icns = make_icns(icon_src, Path(tmp) / f"{_ICON_BASENAME}.icns", log=log)
        single = len(config.launchers) == 1
        apps: list[Path] = []
        for spec in config.launchers:
            launcher_bin = image_dir / spec.name
            if not launcher_bin.is_file():
                raise BuildError(f"launcher binary missing: {launcher_bin} (run build-launchers first)")
            label = config.name if single else spec.name
            identifier = config.identifier if single else f"{config.identifier}.{spec.name}"
            app = _assemble_one(
                config, spec.name, label, identifier, python_src, launcher_bin, shared_icns, out_dir, log
            )
            apps.append(app)
    return apps


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
