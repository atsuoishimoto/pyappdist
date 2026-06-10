"""Pack the image into an MSIX via the Windows SDK ``makeappx`` tool.

The image tree (runtime + launcher exes) is the package payload. We write
``AppxManifest.xml`` and ``Assets/`` logos into the image, then ``makeappx pack`` it.
Paths are passed relative to a common ancestor with ``cwd`` set there, so WSL interop
resolves them cross-OS (same approach as ``wix/build.py``). The package is left
**unsigned**: the Microsoft Store signs on ingestion, and a Developer-Mode machine can
install it unsigned for testing.
"""

from __future__ import annotations

import glob
import os
import struct
import subprocess
import zlib
from pathlib import Path

from .._hostexec import target_relpath
from ..config import Config
from ..errors import BuildError
from .manifest import generate_manifest

_LOGO_FILES = ("StoreLogo.png", "Square150x150Logo.png", "Square44x44Logo.png")


def build_msix(config: Config, image_dir: Path, out_msix: Path, *, log=print) -> Path | None:
    """Build an MSIX from the image. Returns None for non-Windows targets."""
    target = config.target
    if target.os != "windows":
        log("msix: skipping because the target is not Windows")
        return None

    makeappx = _find_makeappx(target)
    out_msix.parent.mkdir(parents=True, exist_ok=True)

    (image_dir / "AppxManifest.xml").write_text(generate_manifest(config), encoding="utf-8")
    _stage_logos(config, image_dir, log=log)

    log(f"msix: makeappx pack -> {out_msix}")
    base = Path(os.path.commonpath([str(image_dir), str(out_msix)]))
    cmd = [
        makeappx, "pack", "/o",
        "/d", target_relpath(target, image_dir, base),
        "/p", target_relpath(target, out_msix, base),
    ]
    proc = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True, errors="replace")
    if proc.returncode != 0 or not out_msix.exists():
        raise BuildError(
            f"makeappx pack failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return out_msix


def _stage_logos(config: Config, image_dir: Path, *, log) -> None:
    """Write the logo PNGs the manifest references into <image>/Assets/.

    A single source logo is copied to every slot (Windows scales it); when no logo is
    configured a solid-colour placeholder is generated so the build always succeeds.
    """
    assets = image_dir / "Assets"
    assets.mkdir(parents=True, exist_ok=True)
    if config.msix.logo:
        src = (config.project_dir / config.msix.logo).resolve()
        if not src.is_file():
            raise BuildError(
                f"logo not found ([[tool.pyappdist.targets]].logo): {src}"
            )
        data = src.read_bytes()
    else:
        data = _solid_png(256, 256, (0, 120, 212))
        log("msix: no logo set; using a generated placeholder (supply 'logo' for real art)")
    for name in _LOGO_FILES:
        (assets / name).write_bytes(data)


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Minimal solid-colour RGB PNG encoder (avoids a Pillow dependency)."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, colour type 2 (RGB)
    row = b"\x00" + bytes(rgb) * width  # filter byte 0 + pixels
    idat = zlib.compress(row * height, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _find_makeappx(target) -> str:
    override = os.environ.get("PYAPPDIST_MAKEAPPX")
    if override:
        return override
    import shutil

    found = shutil.which("makeappx.exe") or shutil.which("makeappx")
    if found:
        return found
    roots = [
        "/mnt/c/Program Files (x86)/Windows Kits/10/bin",
        "C:\\Program Files (x86)\\Windows Kits\\10\\bin",
    ]
    cands: list[str] = []
    for root in roots:
        cands += glob.glob(os.path.join(root, "*", "x64", "makeappx.exe"))
    if cands:
        return sorted(cands)[-1]  # newest SDK version
    raise BuildError(
        "makeappx not found. Install the Windows SDK, or set PYAPPDIST_MAKEAPPX to its path."
    )
