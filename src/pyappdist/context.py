"""Container for paths and settings shared across the whole build."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class BuildContext:
    config: Config
    out_dir: Path    # appdist/<target>/        — final artifacts (dist)
    build_dir: Path  # .appdist-build/<target>/ — build intermediates

    # --- build intermediates (under build_dir) ---
    @property
    def wheelhouse(self) -> Path:
        return self.build_dir / "wheelhouse"

    @property
    def runtime_dir(self) -> Path:
        return self.build_dir / "runtime"

    @property
    def image_dir(self) -> Path:
        return self.build_dir / "image"

    @property
    def launcher_build_dir(self) -> Path:
        return self.build_dir / "_launcher_build"

    @property
    def app_build_dir(self) -> Path:
        return self.build_dir / "_app_build"

    @property
    def wxs_path(self) -> Path:
        return self.build_dir / f"{self.config.dist_name}.wxs"

    # --- final artifacts (under out_dir) ---
    @property
    def dist_dir(self) -> Path:
        return self.out_dir / "dist"
