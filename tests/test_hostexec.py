"""Tests for host/target path handling in _hostexec."""

from __future__ import annotations

from pathlib import Path

from pyappdist._hostexec import extended_length_path, target_relpath
from pyappdist.targets import get_target

WIN = get_target("windows-x86_64")
LIN = get_target("linux-x86_64")


def test_target_relpath_windows_uses_backslashes():
    # appdist/_launcher_build/app -> appdist/image/app.exe
    start = Path("/proj/appdist/_launcher_build/app")
    exe = Path("/proj/appdist/image/app.exe")
    assert target_relpath(WIN, exe, start) == "..\\..\\image\\app.exe"


def test_target_relpath_same_dir_is_basename():
    start = Path("/proj/appdist/image")
    sp = Path("/proj/appdist/image/python/Lib/site-packages")
    assert target_relpath(WIN, sp, start) == "python\\Lib\\site-packages"


def test_target_relpath_linux_keeps_forward_slashes():
    start = Path("/proj/appdist/image")
    sp = Path("/proj/appdist/image/python/lib/python3.12/site-packages")
    assert target_relpath(LIN, sp, start) == "python/lib/python3.12/site-packages"


def test_extended_length_path_drive():
    assert extended_length_path("D:\\proj\\appdist\\image") == "\\\\?\\D:\\proj\\appdist\\image"


def test_extended_length_path_unc():
    assert (
        extended_length_path("\\\\wsl.localhost\\Ubuntu\\home\\u\\proj\\image")
        == "\\\\?\\UNC\\wsl.localhost\\Ubuntu\\home\\u\\proj\\image"
    )


def test_extended_length_path_already_extended():
    assert extended_length_path("\\\\?\\D:\\proj\\image") == "\\\\?\\D:\\proj\\image"
