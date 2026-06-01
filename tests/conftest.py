"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import Config, LauncherConfig, MacosConfig, MsixConfig, WixConfig
from pyappdist.targets import get_target
from pyappdist.wix.scan import DirNode, FileNode

UPGRADE_CODE = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6F"


@pytest.fixture
def sample_config() -> Config:
    return Config(
        project_dir=Path("/proj"),
        name="Hello World",
        dist_name="helloworld",
        version="1.2.3",
        python="3.12",
        identifier="com.example.helloworld",
        target=get_target("windows-x86_64"),
        target_name="windows-x86_64",
        format="msi",
        launchers=(LauncherConfig(name="helloworld", entry="helloworld:main"),),
        wix=WixConfig(
            manufacturer="Example Inc.",
            upgrade_code=UPGRADE_CODE,
        ),
        msix=MsixConfig(),
        macos=MacosConfig(),
        manager=None,
    )


@pytest.fixture
def sample_tree() -> DirNode:
    """A small deterministic tree (synthetic rather than a real image, so the golden stays stable)."""
    return DirNode(
        name="",
        rel="",
        subdirs=(
            DirNode(
                name="python",
                rel="python",
                subdirs=(
                    DirNode(
                        name="Lib",
                        rel="python/Lib",
                        subdirs=(),
                        files=(FileNode(src=Path("x"), name="os.py", rel="python/Lib/os.py"),),
                    ),
                ),
                files=(
                    FileNode(src=Path("x"), name="python.exe", rel="python/python.exe"),
                    FileNode(src=Path("x"), name="python312.dll", rel="python/python312.dll"),
                ),
            ),
        ),
        files=(FileNode(src=Path("x"), name="helloworld.exe", rel="helloworld.exe"),),
    )
