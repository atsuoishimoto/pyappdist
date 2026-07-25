"""Build the ``image`` deliverable: an archive of the run-in-place image tree.

Unlike the other formats, no installer is produced — the image tree itself is the
artifact, archived under a single top-level directory ``<dist_name>-<version>/`` so
extracting doesn't scatter files. Windows targets get a ``.zip``; Linux/macOS targets
get a ``.tar.gz`` (symlinks and permissions matter there, which zip cannot carry).

Launchers follow the target OS: Windows images carry the compiled ``.exe`` launchers
(built by ``build_launchers`` before this runs, as for MSI), while Linux/macOS images
get the same relocatable POSIX shell wrappers as the ``.run`` installer — written here,
without freedesktop integration. With ``no-launcher`` the archive contains just the
installed tree.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .config import Config
from .image.layout import ImageLayout
from .posix.build import targz_bytes, write_launchers


def build_archive(
    config: Config, layout: ImageLayout, dist_dir: Path, *, log=print
) -> list[Path]:
    """Archive the image tree into ``dist_dir`` and return the artifact path."""
    image_dir = layout.image_dir
    if config.target.os in ("linux", "macos") and not config.no_launcher:
        write_launchers(config, image_dir, desktop=False, log=log)

    dist_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{config.dist_name}-{config.version}"
    base = f"{prefix}-{config.target_name}"

    if config.target.os == "windows":
        out = dist_dir / f"{base}.zip"
        _write_zip(image_dir, out, prefix)
    else:
        out = dist_dir / f"{base}.tar.gz"
        out.write_bytes(targz_bytes(image_dir, mode="gz", prefix=prefix, log=log))
    log(f"image: archive -> {out}")
    return [out]


def _write_zip(src_dir: Path, out: Path, prefix: str) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            rel = path.relative_to(src_dir).as_posix()
            if path.is_dir():
                zf.writestr(f"{prefix}/{rel}/", b"")
            else:
                zf.write(path, arcname=f"{prefix}/{rel}")
