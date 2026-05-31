"""Determinism tests for image scanning."""

from __future__ import annotations

from pathlib import Path

from pyappdist.wix.scan import scan_image


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def test_scan_builds_sorted_tree(tmp_path: Path):
    _touch(tmp_path / "helloworld.exe")
    _touch(tmp_path / "python" / "python.exe")
    _touch(tmp_path / "python" / "Lib" / "os.py")

    root = scan_image(tmp_path)

    assert root.rel == "" and root.name == ""
    assert [f.name for f in root.files] == ["helloworld.exe"]
    assert [d.name for d in root.subdirs] == ["python"]

    python = root.subdirs[0]
    assert python.rel == "python"
    # stable by name order (the Lib directory and python.exe)
    assert [f.rel for f in python.files] == ["python/python.exe"]
    assert python.subdirs[0].files[0].rel == "python/Lib/os.py"
