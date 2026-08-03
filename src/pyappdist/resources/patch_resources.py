"""Patch resources into a prebuilt launcher .exe via the Windows UpdateResource API.

Runs on the Windows side with the *target runtime's* python.exe (standalone,
stdlib-only — pyappdist itself is not installed there). The build pipeline
stages this script, the payload files, and a JSON manifest into the launcher
build directory and runs it with that directory as cwd, so every path in the
manifest is relative (the WSL interop cwd rule; see _hostexec.py).

Manifest format:
    {
      "exe": "launcher_out.exe",
      "resources": [
        {"type": "PYAPPDIST" | <int>, "name": <int>, "lang": <int>, "file": "cfg.bin"},
        ...
      ]
    }

Usage: python patch_resources.py <manifest.json>
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes

_RETRIES = 3  # EndUpdateResource can fail transiently (e.g. AV scanners holding the file)


def _win_error(what: str) -> RuntimeError:
    code = ctypes.get_last_error()
    return RuntimeError(f"{what} failed: [WinError {code}] {ctypes.FormatError(code)}")


def _resource_id(value: int | str):
    """A resource type/name argument for UpdateResourceW.

    Integer ids are passed as MAKEINTRESOURCE (the id itself as a pointer-sized
    value); strings are passed as wide-string pointers.
    """
    if isinstance(value, int):
        return ctypes.c_void_p(value)
    return ctypes.c_wchar_p(value)


def patch(exe: str, resources: list[dict]) -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    begin = k32.BeginUpdateResourceW
    begin.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    begin.restype = wintypes.HANDLE
    update = k32.UpdateResourceW
    update.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.WORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    update.restype = wintypes.BOOL
    end = k32.EndUpdateResourceW
    end.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    end.restype = wintypes.BOOL

    payloads = []
    for entry in resources:
        with open(entry["file"], "rb") as f:
            payloads.append((entry, f.read()))
    last_error: RuntimeError | None = None
    for attempt in range(_RETRIES):
        if attempt:
            time.sleep(1.0)
        handle = begin(exe, False)
        if not handle:
            last_error = _win_error(f"BeginUpdateResource({exe})")
            continue
        ok = True
        for entry, data in payloads:
            buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
            if not update(
                handle,
                _resource_id(entry["type"]),
                _resource_id(entry["name"]),
                entry["lang"],
                buf,
                len(data),
            ):
                last_error = _win_error(f"UpdateResource({entry['type']}/{entry['name']})")
                ok = False
                break
        if not ok:
            end(handle, True)  # discard
            continue
        if end(handle, False):
            return
        last_error = _win_error("EndUpdateResource")
    raise last_error if last_error else RuntimeError("resource patching failed")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: patch_resources.py <manifest.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        manifest = json.load(f)
    try:
        patch(manifest["exe"], manifest["resources"])
    except (RuntimeError, OSError) as exc:
        print(f"patch_resources: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
