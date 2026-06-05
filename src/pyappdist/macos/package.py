"""Wrap ``.app`` bundles into a distributable ``.dmg`` via ``hdiutil``.

A staging folder holding the bundles plus an ``Applications`` symlink (the classic
drag-to-install layout) is imaged into a compressed read-only (UDZO) disk image.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import Config
from ..errors import BuildError


def build_dmg(config: Config, apps: list[Path], out_dmg: Path, *, log=print) -> Path:
    """Create ``out_dmg`` from the given ``.app`` bundles."""
    if not apps:
        raise BuildError("no .app bundles to package into a dmg")
    out_dmg.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        for app in apps:
            shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")

        log(f"macos: hdiutil create -> {out_dmg}")
        if out_dmg.exists():
            out_dmg.unlink()
        cmd = [
            "hdiutil", "create",
            "-volname", config.name,
            "-srcfolder", str(stage),
            "-fs", "HFS+",
            "-format", "UDZO",
            "-ov",
            str(out_dmg),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if proc.returncode != 0 or not out_dmg.exists():
            raise BuildError(
                f"hdiutil create failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            )
    return out_dmg
