"""Build the macOS deliverables: a portable tarball plus a self-extracting .run.

The packaging logic is shared with Linux in :mod:`pyappdist.posix`; this is a thin
``os_kind="macos"`` wrapper. macOS has no freedesktop ``.desktop`` equivalent, so
``desktop`` is disabled (launcher ``icon``/``gui`` are ignored — symlinks only), and the
default compression is ``gzip`` because ``xz`` is not preinstalled on macOS.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..image.layout import ImageLayout
from ..posix.build import build_posix


def build_macos(
    config: Config, layout: ImageLayout, dist_dir: Path, *, log=print
) -> list[Path] | None:
    """Build the .tar.gz and .run from the image. Returns None for non-macOS targets."""
    return build_posix(
        config,
        layout,
        dist_dir,
        os_kind="macos",
        desktop=False,
        compression=config.macos.compression,
        log=log,
    )
