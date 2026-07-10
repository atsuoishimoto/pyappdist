"""Copy the runtime to assemble an image."""

from __future__ import annotations

import shutil

from ..context import BuildContext
from ..runtime import _MARKER, RuntimeInfo
from .layout import ImageLayout


def assemble_runtime(ctx: BuildContext, runtime: RuntimeInfo, *, log=print) -> ImageLayout:
    """Copy the runtime to image/python and return an ImageLayout."""
    image_dir = ctx.image_dir
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True)
    python_dir = image_dir / "python"
    log(f"image: copying runtime -> {python_dir}")
    # The runtime marker is build-cache metadata; keep it out of the shipped image.
    shutil.copytree(
        runtime.root, python_dir, symlinks=True, ignore=shutil.ignore_patterns(_MARKER)
    )
    return ImageLayout(image_dir=image_dir, target=ctx.config.target, minor=runtime.minor)
