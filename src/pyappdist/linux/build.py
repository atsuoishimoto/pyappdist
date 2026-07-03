"""Build the Linux deliverable: a self-extracting .run installer.

The packaging logic is shared with macOS in :mod:`pyappdist.posix`; this is a thin
``os_kind="linux"`` wrapper that enables freedesktop ``.desktop`` generation.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..image.layout import ImageLayout
from ..posix.build import build_posix


def build_linux(
    config: Config, layout: ImageLayout, dist_dir: Path, *, log=print
) -> list[Path] | None:
    """Build the .run installer from the image. Returns None for non-Linux targets."""
    return build_posix(
        config,
        layout,
        dist_dir,
        os_kind="linux",
        desktop=True,
        compression=config.linux.compression,
        categories=config.linux.categories,
        log=log,
    )
