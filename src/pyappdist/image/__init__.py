"""image 組み立て（Phase 2）。

build_image: runtime コピー → install → compileall → portable zip。
"""

from __future__ import annotations

from pathlib import Path

from ..context import BuildContext
from ..runtime import RuntimeInfo
from .assemble import assemble_runtime, make_portable_zip
from .compile import compile_site_packages
from .install import install_app
from .layout import ImageLayout

__all__ = ["ImageLayout", "build_image", "make_portable_zip"]


def build_image(
    ctx: BuildContext,
    runtime: RuntimeInfo,
    *,
    compile_pyc: bool = True,
    log=print,
) -> ImageLayout:
    """runtime をコピーして install + compileall した image を組み立てる。

    launcher.exe のビルドと portable zip 化は呼び出し側（cli）が担う。
    zip は launcher を含めるため launcher ビルド後に行う必要がある。
    """
    layout = assemble_runtime(ctx, runtime, log=log)
    install_app(layout, ctx.wheelhouse, log=log)
    if compile_pyc:
        compile_site_packages(layout, log=log)
    return layout
