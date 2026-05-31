"""Copy the runtime to assemble an image and generate a portable zip."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..context import BuildContext
from ..runtime import RuntimeInfo
from .layout import ImageLayout


def assemble_runtime(ctx: BuildContext, runtime: RuntimeInfo, *, log=print) -> ImageLayout:
    """Copy the runtime to image/python and return an ImageLayout."""
    image_dir = ctx.image_dir
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True)
    python_dir = image_dir / "python"
    log(f"image: copying runtime -> {python_dir}")
    shutil.copytree(runtime.root, python_dir, symlinks=True)
    return ImageLayout(image_dir=image_dir, target=ctx.config.target, minor=runtime.minor)


def make_portable_zip(ctx: BuildContext, *, log=print) -> Path:
    ctx.dist_dir.mkdir(parents=True, exist_ok=True)
    base = ctx.dist_dir / f"{ctx.config.dist_name}-{ctx.config.version}-portable"
    log(f"image: generating portable zip -> {base}.zip")
    archive = shutil.make_archive(str(base), "zip", root_dir=ctx.image_dir)
    return Path(archive)
