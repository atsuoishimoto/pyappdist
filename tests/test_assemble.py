"""Tests for image assembly from an extracted runtime."""

from __future__ import annotations

from pyappdist import runtime
from pyappdist.context import BuildContext
from pyappdist.image.assemble import assemble_runtime


def test_assemble_excludes_runtime_marker(sample_config, tmp_path):
    # The build-cache marker must not ship inside the packaged image.
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "python.exe").write_bytes(b"")
    (root / runtime._MARKER).write_text("{}", encoding="utf-8")
    info = runtime.RuntimeInfo(
        version="3.12.11",
        minor="3.12",
        tag="20250106",
        triple="x86_64-pc-windows-msvc",
        root=root,
    )
    ctx = BuildContext(
        config=sample_config, out_dir=tmp_path / "out", build_dir=tmp_path / "build"
    )
    layout = assemble_runtime(ctx, info, log=lambda m: None)
    python_dir = layout.image_dir / "python"
    assert (python_dir / "python.exe").exists()
    assert not (python_dir / runtime._MARKER).exists()
