"""Container for paths and settings shared across the whole build."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class BuildContext:
    config: Config
    out_dir: Path  # appdist/

    @property
    def wheelhouse(self) -> Path:
        return self.out_dir / "wheelhouse"

    @property
    def runtime_dir(self) -> Path:
        return self.out_dir / "runtime"

    @property
    def image_dir(self) -> Path:
        return self.out_dir / "image"

    @property
    def dist_dir(self) -> Path:
        return self.out_dir / "dist"
