"""テスト共通フィクスチャ。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyappdist.config import Config, InstallerConfig, LauncherConfig
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
        target=get_target("windows-x86_64"),
        identifier="com.example.helloworld",
        launchers=(LauncherConfig(name="helloworld", entry="helloworld:main"),),
        installer=InstallerConfig(
            backend="wix",
            manufacturer="Example Inc.",
            upgrade_code=UPGRADE_CODE,
        ),
    )


@pytest.fixture
def sample_tree() -> DirNode:
    """小さな決定的ツリー（実 image ではなくゴールデンが安定するように合成）。"""
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
