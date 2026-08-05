#!/usr/bin/env python3
"""Delete one sample target's build intermediates after it has been packaged.

A CI helper for the ``build-samples`` matrix, not part of pyappdist. The matrix
builds every sample for every target of the host OS, and a build tree holds
several copies of the installed app (the image, the ``.app`` staging area, the
``.pkg`` payload) plus the wheelhouse -- roughly 4 GB per target for the torch
samples. GitHub's macOS runners ship only ~14 GB of free disk, so leaving each
tree behind fills the disk partway through the matrix; the runner then dies with
"No space left on device", losing even its own job log.

``pyappdist build`` deliberately keeps the tree (it is what you inspect when a
build goes wrong), so the removal lives here, in the matrix's build command, and
runs only after a successful build. The finished packages are in
``appdist/<target>/dist/`` and are untouched; the runtime download cache lives
outside the build tree, so nothing is re-downloaded.

Usage, from a sample's directory (see ``[tool.uv-matrix.tasks.build-sample]``)::

    python ../clean_build.py <target>
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(f"usage: {Path(__file__).name} <target>", file=sys.stderr)
        return 2
    # Mirrors pyappdist's own --build-dir default resolution.
    base = Path(os.environ.get("PYAPPDIST_BUILD_DIR") or ".appdist-build")
    build_dir = base / argv[0]
    if build_dir.is_dir():
        shutil.rmtree(build_dir, ignore_errors=True)
        print(f"clean: removed {build_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
