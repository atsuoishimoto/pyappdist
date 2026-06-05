#!/usr/bin/env python3
"""Generate the macOS launcher icons (``assets/<launcher>.png``) for the samples + e2e.

For a project that already ships a Windows ``.ico``, the PNG is derived from it with
``sips`` so the macOS icon matches the existing art. For projects without an icon, a
distinct rounded-square gradient PNG is synthesized (deterministic from the launcher
name, no third-party dependency — same spirit as ``macos/icns.py``'s placeholder).

Run from the repo root:  ``python3 samples/tools/gen_mac_icons.py``
Idempotent; commit the resulting PNGs.
"""

from __future__ import annotations

import hashlib
import struct
import subprocess
import zlib
from pathlib import Path

# (project dir, launcher name) — the PNG is written to <project>/assets/<name>.png.
PROJECTS = [
    ("samples/helloworld", "helloworld"),
    ("samples/datafiles", "datafiles"),
    ("samples/pandascli", "pandascli"),
    ("samples/matplotlibdemo", "matplotlibdemo"),
    ("samples/pygamedemo", "pygamedemo"),
    ("samples/pyside6demo", "pyside6demo"),
    ("e2e/smoke", "smoke"),
]

_SIZE = 1024
_RADIUS = int(_SIZE * 0.2237)  # macOS-ish continuous-corner radius


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def _gradient_icon(name: str) -> bytes:
    """A 1024x1024 RGBA PNG: a rounded square with a vertical two-tone gradient."""
    hue = int(hashlib.md5(name.encode()).hexdigest(), 16) % 360 / 360
    top = _hsv_to_rgb(hue, 0.55, 0.95)
    bottom = _hsv_to_rgb((hue + 0.07) % 1.0, 0.75, 0.62)

    rows = bytearray()
    for y in range(_SIZE):
        t = y / (_SIZE - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        # Horizontal span of the rounded rectangle at this row.
        if y < _RADIUS:
            dy = _RADIUS - y
        elif y >= _SIZE - _RADIUS:
            dy = y - (_SIZE - 1 - _RADIUS)
        else:
            dy = 0
        pad = _RADIUS - int((_RADIUS * _RADIUS - dy * dy) ** 0.5) if dy else 0
        rows.append(0)  # PNG filter byte (none)
        inside = bytes((r, g, b, 255))
        clear = bytes((0, 0, 0, 0))
        rows += clear * pad + inside * (_SIZE - 2 * pad) + clear * pad
    return _png_rgba(_SIZE, _SIZE, bytes(rows))


def _png_rgba(width: int, height: int, raw_with_filter_bytes: bytes) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(raw_with_filter_bytes, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    for rel, name in PROJECTS:
        assets = root / rel / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        out = assets / f"{name}.png"
        ico = assets / f"{name}.ico"
        if ico.is_file():
            subprocess.run(
                ["sips", "-s", "format", "png", str(ico), "--out", str(out)],
                check=True, capture_output=True, text=True,
            )
            print(f"{out}  (from {ico.name} via sips)")
        else:
            out.write_bytes(_gradient_icon(name))
            print(f"{out}  (generated gradient)")


if __name__ == "__main__":
    main()
