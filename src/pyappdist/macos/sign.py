"""Deep code-signing of a ``.app`` bundle with ``codesign``.

All nested Mach-O files (the bundled interpreter, every ``.so``/``.dylib`` under the runtime,
the launcher) are signed first, then the bundle itself last, so the bundle seal
(``_CodeSignature/CodeResources``) is computed over the final inner signatures.

The MVP signs **ad-hoc** (``--sign -``). python-build-standalone binaries already carry
ad-hoc signatures, so ``--force`` is mandatory to re-sign them. The :class:`SignOptions`
struct is the seam for the later Developer ID phase: flip ``hardened``/``timestamp`` on and
pass a real ``identity`` + ``entitlements`` and the same code notarizes.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import BuildError

# Mach-O / universal magic numbers as they appear on disk (first 4 bytes).
_MACHO_MAGIC = frozenset({
    b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64 (LE)
    b"\xce\xfa\xed\xfe",  # MH_MAGIC (LE)
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64 (BE)
    b"\xfe\xed\xfa\xce",  # MH_MAGIC (BE)
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC
    b"\xca\xfe\xba\xbf",  # FAT_MAGIC_64
})


@dataclass(frozen=True)
class SignOptions:
    identity: str = "-"                 # "-" = ad-hoc; else a Developer ID identity
    hardened: bool = False              # --options runtime (notarization)
    entitlements: Path | None = None    # --entitlements <plist>
    timestamp: bool = False             # secure timestamp (notarization) vs --timestamp=none


def deep_sign(app: Path, opts: SignOptions | None = None, *, log=print) -> None:
    """Sign every Mach-O inside ``app`` (deepest first), then the bundle itself."""
    opts = opts or SignOptions()
    machos = sorted(_iter_machos(app), key=lambda p: len(p.parts), reverse=True)
    log(f"macos: codesign ({'ad-hoc' if opts.identity == '-' else opts.identity}) "
        f"{len(machos)} mach-o + bundle -> {app.name}")
    for path in machos:
        _codesign(path, opts)
    _codesign(app, opts)  # bundle last


def _iter_machos(root: Path):
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with open(path, "rb") as f:
                if f.read(4) in _MACHO_MAGIC:
                    yield path
        except OSError:
            continue


def _codesign(path: Path, opts: SignOptions) -> None:
    cmd = ["codesign", "--force", "--sign", opts.identity]
    cmd.append("--timestamp" if opts.timestamp else "--timestamp=none")
    if opts.hardened:
        cmd += ["--options", "runtime"]
    if opts.entitlements is not None:
        cmd += ["--entitlements", str(opts.entitlements)]
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"codesign failed ({proc.returncode}): {path}\n{proc.stderr.strip()}")
