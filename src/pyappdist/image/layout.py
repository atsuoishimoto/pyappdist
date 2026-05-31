"""Constants for the image directory structure (single source of truth).

image/
  python/        <- copy of the runtime (python.exe / bin/python3, standard library, site-packages)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..targets import Target


@dataclass(frozen=True)
class ImageLayout:
    image_dir: Path
    target: Target
    minor: str  # "3.12"

    @property
    def python_dir(self) -> Path:
        return self.image_dir / "python"

    @property
    def python_exe(self) -> Path:
        if self.target.os == "windows":
            return self.python_dir / "python.exe"
        return self.python_dir / "bin" / "python3"

    @property
    def site_packages(self) -> Path:
        if self.target.os == "windows":
            return self.python_dir / "Lib" / "site-packages"
        return self.python_dir / "lib" / f"python{self.minor}" / "site-packages"
