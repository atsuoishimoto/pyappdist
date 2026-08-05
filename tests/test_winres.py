"""Tests for the pure-Python Windows resource payload builders (winres)."""

from __future__ import annotations

import struct

import pytest

from pyappdist.errors import BuildError
from pyappdist.launcher import winres


# --- config blob -------------------------------------------------------------


def test_config_resource_roundtrip():
    res = winres.config_resource("python\\python.exe", "import x\nx.main()", '--flag "a b"')
    assert res.type == winres.CONFIG_TYPE
    assert res.name == winres.CONFIG_ID
    assert res.lang == winres.LANG_NEUTRAL
    fields = res.data.decode("utf-16-le").split("\0")
    # Four NUL-terminated fields -> a trailing empty element after the split.
    assert fields == [
        "PADL1", "python\\python.exe", "import x\nx.main()", '--flag "a b"', "",
    ]


def test_config_resource_rejects_nul():
    with pytest.raises(BuildError, match="NUL"):
        winres.config_resource("python\\python.exe", "bad\0boot", "")


# --- icon --------------------------------------------------------------------


def _make_ico(images: list[bytes]) -> bytes:
    """A minimal .ico wrapping ``images`` as its bitmap payloads."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    for i, img in enumerate(images):
        entries += struct.pack(
            "<BBBBHHII", 16 * (i + 1), 16 * (i + 1), 0, 0, 1, 32, len(img), offset
        )
        offset += len(img)
    return header + entries + b"".join(images)


def test_icon_resources_split_and_group():
    images = [b"AAAA", b"BBBBBBBB"]
    out = winres.icon_resources(_make_ico(images))

    icons = [r for r in out if r.type == winres.RT_ICON]
    assert [(r.name, r.data) for r in icons] == [(1, b"AAAA"), (2, b"BBBBBBBB")]

    (group,) = [r for r in out if r.type == winres.RT_GROUP_ICON]
    assert group.name == 1
    reserved, kind, count = struct.unpack_from("<HHH", group.data)
    assert (reserved, kind, count) == (0, 1, 2)
    # Each 14-byte entry mirrors the file's directory with the offset replaced
    # by the RT_ICON id.
    entry1 = struct.unpack_from("<BBBBHHIH", group.data, 6)
    entry2 = struct.unpack_from("<BBBBHHIH", group.data, 6 + 14)
    assert entry1 == (16, 16, 0, 0, 1, 32, 4, 1)
    assert entry2 == (32, 32, 0, 0, 1, 32, 8, 2)


def test_icon_resources_extra_group_name():
    """The same directory is emitted once per requested group name."""
    out = winres.icon_resources(
        _make_ico([b"AAAA"]), group_names=(1, winres.QT_ICON_NAME)
    )
    groups = [r for r in out if r.type == winres.RT_GROUP_ICON]
    assert [r.name for r in groups] == [1, "IDI_ICON1"]
    assert groups[0].data == groups[1].data
    # Both point at the single RT_ICON entry, which is emitted only once.
    assert len([r for r in out if r.type == winres.RT_ICON]) == 1


@pytest.mark.parametrize(
    "data",
    [
        b"",                                   # truncated header
        struct.pack("<HHH", 0, 2, 1),          # not an icon (a cursor)
        struct.pack("<HHH", 0, 1, 0),          # empty
        struct.pack("<HHH", 0, 1, 1),          # truncated directory
        _make_ico([b"AAAA"])[:-2],             # image data out of bounds
    ],
)
def test_icon_resources_rejects_invalid(data: bytes):
    with pytest.raises(BuildError, match="ico"):
        winres.icon_resources(data)


# --- VS_VERSIONINFO ----------------------------------------------------------


def _parse_block(data: bytes, offset: int = 0):
    """Parse one version block; returns (key, wtype, value, children, end)."""
    length, value_length, wtype = struct.unpack_from("<HHH", data, offset)
    end = offset + length
    pos = offset + 6
    chars = []
    while True:
        (ch,) = struct.unpack_from("<H", data, pos)
        pos += 2
        if ch == 0:
            break
        chars.append(chr(ch))
    key = "".join(chars)
    pos += -(pos - offset) % 4
    value_bytes = value_length * 2 if wtype == 1 else value_length
    value = data[pos:pos + value_bytes]
    pos += value_bytes
    children = []
    while pos < end:
        pos += -(pos - offset) % 4
        child, new_pos = _parse_block(data, pos)
        assert new_pos > pos, "malformed block (zero length)"
        pos = new_pos
        children.append(child)
    return (key, wtype, value, children), end


def test_version_resource_structure():
    # "1.10" makes a value whose byte length is ≡ 2 (mod 4), covering the
    # inter-child alignment padding.
    strings = {
        "CompanyName": "Example Inc.",
        "FileVersion": "1.10",
        "ProductName": "App",
    }
    res = winres.version_resource((1, 10, 0, 0), strings)
    assert res.type == winres.RT_VERSION
    assert res.name == 1
    assert res.lang == winres.LANG_EN_US

    (key, wtype, fixed, children), end = _parse_block(res.data)
    assert end == len(res.data)
    assert (key, wtype) == ("VS_VERSION_INFO", 0)

    info = struct.unpack("<13I", fixed)
    assert info[0] == 0xFEEF04BD                 # signature
    assert info[2] == (1 << 16) | 10             # FileVersionMS
    assert info[3] == 0                          # FileVersionLS
    assert info[4:6] == info[2:4]                # ProductVersion == FileVersion

    by_key = {child[0]: child for child in children}
    table = by_key["StringFileInfo"][3][0]
    assert table[0] == "040904b0"
    values = {
        name: value.decode("utf-16-le").rstrip("\0")
        for (name, _, value, _) in table[3]
    }
    assert values == strings

    (var,) = by_key["VarFileInfo"][3]
    assert var[0] == "Translation"
    assert struct.unpack("<HH", var[2]) == (0x0409, 0x04B0)


def test_version_resource_children_are_aligned():
    # Directly assert every String sibling starts on a 32-bit boundary even
    # when the preceding value has an odd WCHAR count.
    strings = {"A": "xx", "B": "y", "C": "zzzz"}
    res = winres.version_resource((0, 0, 0, 1), strings)
    (_, _, _, children), _ = _parse_block(res.data)
    # Re-walk raw offsets: find each key's UTF-16 encoding at a 4-aligned
    # position 6 bytes after its block start.
    for name in strings:
        needle = name.encode("utf-16-le") + b"\0\0"
        at = res.data.find(needle)
        assert at != -1
        assert (at - 6) % 4 == 0
    assert children  # parsed fine end to end
