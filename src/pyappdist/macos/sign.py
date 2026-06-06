"""Deep code-signing of a ``.app`` bundle with ``codesign``.

All nested Mach-O files (the bundled interpreter, every ``.so``/``.dylib`` under the
runtime, the launcher) are signed first, then the bundle itself last, so the bundle seal
(``_CodeSignature/CodeResources``) is computed over the final inner signatures.

Two modes, selected by :func:`resolve_sign_options`:

* **ad-hoc** (``--sign -``) — the default; runs locally but is rejected by Gatekeeper on
  other machines. python-build-standalone binaries already carry ad-hoc signatures, so
  ``--force`` is mandatory to re-sign them.
* **Developer ID** — when ``signing-identity`` (or ``PYAPPDIST_SIGNING_IDENTITY``) is set:
  adds the hardened runtime (``--options runtime``), a secure ``--timestamp``, and
  entitlements. This is the signature notarization requires (see :mod:`.notarize`).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..errors import BuildError

_IDENTITY_ENV = "PYAPPDIST_SIGNING_IDENTITY"

# Hardened-runtime entitlements for a bundled CPython. The one entitlement a relocated
# interpreter genuinely needs is disable-library-validation: it lets the hardened binary
# load .so/.dylib files signed by a *different* identity (or only ad-hoc) — i.e. every
# third-party wheel's extension module. We intentionally keep the default to just this one
# (least privilege). Apps that actually JIT (e.g. some ML/runtime libraries) can supply
# their own plist via the ``entitlements`` config key adding, e.g.:
#   com.apple.security.cs.allow-jit
#   com.apple.security.cs.allow-unsigned-executable-memory
_DEFAULT_ENTITLEMENTS = {
    "com.apple.security.cs.disable-library-validation": True,
}

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

    @property
    def adhoc(self) -> bool:
        return self.identity == "-"


def entitlements_plist() -> bytes:
    """The default hardened-runtime entitlements payload for a bundled python."""
    return plistlib.dumps(_DEFAULT_ENTITLEMENTS)


def resolve_sign_options(config: Config, build_dir: Path, *, log=print) -> SignOptions:
    """Decide ad-hoc vs Developer ID signing from the config + environment.

    ``signing-identity`` (or ``PYAPPDIST_SIGNING_IDENTITY``) selects Developer ID, which
    turns on the hardened runtime + secure timestamp and resolves entitlements (the
    configured ``entitlements`` plist, else a bundled-python default written into
    ``build_dir``). With no identity set, returns ad-hoc options.
    """
    identity = config.macos.signing_identity or os.environ.get(_IDENTITY_ENV)
    if not identity:
        log("macos: signing ad-hoc (set signing-identity / PYAPPDIST_SIGNING_IDENTITY for Developer ID)")
        return SignOptions()

    if config.macos.entitlements:
        ent = (config.project_dir / config.macos.entitlements).resolve()
        if not ent.is_file():
            raise BuildError(f"entitlements file not found: {ent}")
    else:
        build_dir.mkdir(parents=True, exist_ok=True)
        ent = build_dir / "entitlements.plist"
        ent.write_bytes(entitlements_plist())
    log(f"macos: signing with Developer ID identity {identity!r} (hardened runtime + timestamp)")
    return SignOptions(identity=identity, hardened=True, entitlements=ent, timestamp=True)


def deep_sign(app: Path, opts: SignOptions | None = None, *, log=print) -> None:
    """Sign every Mach-O inside ``app`` (deepest first), then the bundle itself."""
    opts = opts or SignOptions()
    machos = sorted(_iter_machos(app), key=lambda p: len(p.parts), reverse=True)
    log(f"macos: codesign ({'ad-hoc' if opts.adhoc else opts.identity}) "
        f"{len(machos)} mach-o + bundle -> {app.name}")
    for path in machos:
        _codesign(path, opts)
    _codesign(app, opts)  # bundle last


def sign_file(path: Path, opts: SignOptions, *, log=print) -> None:
    """Sign a single artifact (e.g. the .dmg). The hardened runtime / entitlements apply
    to executable code, not a disk image, so they are dropped here."""
    log(f"macos: codesign ({'ad-hoc' if opts.adhoc else opts.identity}) {path.name}")
    _codesign(path, SignOptions(identity=opts.identity, timestamp=opts.timestamp))


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
