"""安定 GUID の決定性・回帰テスト。"""

from __future__ import annotations

from pyappdist.wix.guid import is_guid, stable_guid

UC = "7E3F9A2C-5B1D-4E8A-9C6F-1A2B3C4D5E6F"


def test_stable_guid_is_deterministic():
    assert stable_guid(UC, "python/python.exe") == stable_guid(UC, "python/python.exe")


def test_stable_guid_differs_by_path():
    assert stable_guid(UC, "a.txt") != stable_guid(UC, "b.txt")


def test_stable_guid_differs_by_upgrade_code():
    other = "11111111-2222-3333-4444-555555555555"
    assert stable_guid(UC, "a.txt") != stable_guid(other, "a.txt")


def test_stable_guid_regression():
    # 値が変わると既存インストールの MajorUpgrade 同一性が壊れるため固定する
    assert stable_guid(UC, "helloworld.exe") == "9641F219-56EF-59DC-9F26-84A56E0379B2"


def test_is_guid():
    assert is_guid(UC)
    assert not is_guid("PUT-GUID-HERE")
    assert not is_guid(None)
