"""Build Windows resource payloads for the prebuilt launcher (pure Python).

A prebuilt ``launcher.exe`` stub carries no app-specific data; the pipeline
patches it in as resources instead of compiling it in with MSVC. This module
builds the raw resource payloads — the pyappdist config block, ``RT_ICON``/
``RT_GROUP_ICON`` entries from a ``.ico`` file, and a ``VS_VERSIONINFO``
structure — on the build host (no Windows API needed). Applying them to the
``.exe`` is Windows-only (``UpdateResource``) and is done by the bundled
``patch_resources.py`` script run with the target runtime's ``python.exe``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..errors import BuildError

# Windows predefined resource types (winuser.h RT_*).
RT_ICON = 3
RT_GROUP_ICON = 14
RT_VERSION = 16

# The launcher's config resource: custom type, id 1, language-neutral
# (launcher.c looks it up with FindResourceW(NULL, MAKEINTRESOURCEW(1), L"PYAPPDIST")).
CONFIG_TYPE = "PYAPPDIST"
CONFIG_ID = 1
LANG_NEUTRAL = 0

# rc.exe's default resource language (en-US), used for icon/version resources.
LANG_EN_US = 0x0409


@dataclass(frozen=True)
class Resource:
    """One resource to patch into the stub: (type, name id, language, payload)."""

    type: int | str
    name: int
    lang: int
    data: bytes


def config_resource(pyexe: str, bootstrap: str, fixed_args: str) -> Resource:
    """The launcher config blob (see load_resource_config in launcher.c).

    UTF-16LE, four NUL-terminated fields back to back: the format magic
    ``PADL1``, the interpreter path relative to the launcher, the ``-c``
    bootstrap program, and the pre-quoted fixed-args fragment.
    """
    fields = ("PADL1", pyexe, bootstrap, fixed_args)
    for field in fields:
        if "\0" in field:
            raise BuildError(f"launcher config value contains NUL: {field!r}")
    blob = "".join(f"{field}\0" for field in fields).encode("utf-16-le")
    return Resource(CONFIG_TYPE, CONFIG_ID, LANG_NEUTRAL, blob)


# --- icon (.ico -> RT_ICON + RT_GROUP_ICON) ---------------------------------

_ICONDIR = struct.Struct("<HHH")        # reserved, type (1 = icon), count
_ICONDIRENTRY = struct.Struct("<BBBBHHII")  # w, h, colors, rsvd, planes, bpp, size, offset
_GRPICONDIRENTRY = struct.Struct("<BBBBHHIH")  # ...same, but the offset is a WORD icon id


def icon_resources(ico: bytes, *, first_id: int = 1) -> list[Resource]:
    """Split a ``.ico`` file into ``RT_ICON`` entries plus one ``RT_GROUP_ICON``.

    The group directory mirrors the file's directory, with each entry's file
    offset replaced by the id of the ``RT_ICON`` resource holding that image —
    exactly what rc.exe produces for an ``ICON`` statement.
    """
    if len(ico) < _ICONDIR.size:
        raise BuildError("invalid .ico file: truncated header")
    reserved, kind, count = _ICONDIR.unpack_from(ico)
    if reserved != 0 or kind != 1 or count == 0:
        raise BuildError("invalid .ico file: not an icon resource")
    if len(ico) < _ICONDIR.size + count * _ICONDIRENTRY.size:
        raise BuildError("invalid .ico file: truncated directory")

    out: list[Resource] = []
    group = [_ICONDIR.pack(0, 1, count)]
    for i in range(count):
        entry = _ICONDIRENTRY.unpack_from(ico, _ICONDIR.size + i * _ICONDIRENTRY.size)
        w, h, colors, rsvd, planes, bpp, size, offset = entry
        if offset + size > len(ico):
            raise BuildError("invalid .ico file: image data out of bounds")
        icon_id = first_id + i
        out.append(Resource(RT_ICON, icon_id, LANG_EN_US, ico[offset:offset + size]))
        group.append(_GRPICONDIRENTRY.pack(w, h, colors, rsvd, planes, bpp, size, icon_id))
    # Group icon id 1 = what launcher.rc declared ("1 ICON ..."), and the icon
    # Explorer picks (lowest id) for the .exe.
    out.append(Resource(RT_GROUP_ICON, 1, LANG_EN_US, b"".join(group)))
    return out


# --- VS_VERSIONINFO ----------------------------------------------------------

_FIXEDFILEINFO = struct.Struct("<13I")


def _vs_block(key: str, wtype: int, value: bytes, value_length: int,
              children: list[bytes]) -> bytes:
    """One node of the VS_VERSIONINFO tree.

    Layout (Microsoft's pseudo-struct): wLength, wValueLength, wType, szKey
    (UTF-16 + NUL), padding to a 32-bit boundary, Value, padding, Children.
    ``value_length`` is in bytes for binary values (wType 0) and in WCHARs for
    text values (wType 1).
    """
    key_bytes = key.encode("utf-16-le") + b"\0\0"
    head_len = 6 + len(key_bytes)
    # Alignment is relative to the block start (blocks themselves always start
    # 32-bit aligned): the value is padded to start on a boundary, and so is
    # each child — a child's length may be ≡ 2 (mod 4) (an even-length UTF-16
    # value), so siblings need padding between them too.
    body = bytearray(b"\0" * (-head_len % 4) + value)
    for child in children:
        body += b"\0" * (-(head_len + len(body)) % 4)
        body += child
    return struct.pack("<HHH", head_len + len(body), value_length, wtype) \
        + key_bytes + bytes(body)


def _vs_string(name: str, value: str) -> bytes:
    data = value.encode("utf-16-le") + b"\0\0"
    return _vs_block(name, 1, data, len(data) // 2, [])


def version_resource(quad: tuple[int, int, int, int], strings: dict[str, str]) -> Resource:
    """A ``VS_VERSIONINFO`` resource equivalent to launcher/build.py's .rc block.

    ``quad`` is the numeric FILEVERSION/PRODUCTVERSION; ``strings`` the
    StringFileInfo values (CompanyName, FileVersion, ...), emitted into the
    standard en-US/Unicode ``040904b0`` table with a matching Translation var.
    """
    fixed = _FIXEDFILEINFO.pack(
        0xFEEF04BD,               # dwSignature
        0x00010000,               # dwStrucVersion
        (quad[0] << 16) | quad[1],  # dwFileVersionMS
        (quad[2] << 16) | quad[3],  # dwFileVersionLS
        (quad[0] << 16) | quad[1],  # dwProductVersionMS
        (quad[2] << 16) | quad[3],  # dwProductVersionLS
        0x3F,                     # dwFileFlagsMask
        0,                        # dwFileFlags
        0x40004,                  # dwFileOS (VOS_NT_WINDOWS32)
        0x1,                      # dwFileType (VFT_APP)
        0, 0, 0,                  # dwFileSubtype, dwFileDate MS/LS
    )
    table = _vs_block(
        "040904b0", 1, b"", 0,
        [_vs_string(name, value) for name, value in strings.items()],
    )
    string_info = _vs_block("StringFileInfo", 1, b"", 0, [table])
    translation = _vs_block(
        "Translation", 0, struct.pack("<HH", LANG_EN_US, 0x04B0), 4, []
    )
    var_info = _vs_block("VarFileInfo", 1, b"", 0, [translation])
    blob = _vs_block("VS_VERSION_INFO", 0, fixed, len(fixed), [string_info, var_info])
    return Resource(RT_VERSION, 1, LANG_EN_US, blob)
