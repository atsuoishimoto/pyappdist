"""Image assembly (Phase 2).

build_image: copy runtime -> install -> compileall.
"""

from __future__ import annotations

from ..context import BuildContext
from ..runtime import RuntimeInfo
from .assemble import assemble_runtime
from .compile import compile_site_packages
from .install import install_app
from .layout import ImageLayout

__all__ = ["ImageLayout", "build_image"]


def build_image(
    ctx: BuildContext,
    runtime: RuntimeInfo,
    *,
    compile_pyc: bool = True,
    log=print,
) -> ImageLayout:
    """Copy the runtime and assemble an image with install + compileall applied.

    Building launcher.exe is the caller's (cli's) responsibility.
    """
    layout = assemble_runtime(ctx, runtime, log=log)
    install_app(layout, ctx.wheelhouse, log=log)
    if compile_pyc:
        compile_site_packages(layout, log=log)
    return layout
