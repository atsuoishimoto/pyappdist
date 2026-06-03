"""Distribution target definitions.

Provides a mapping from a `target` name (e.g. ``windows-x86_64``) to the
python-build-standalone target triple and the wix build architecture.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class Target:
    name: str          # name used in config (windows-x86_64)
    triple: str        # python-build-standalone target triple
    os: str            # "windows" | "linux" | "macos"
    wix_arch: str      # value passed to wix build -arch (x64 / arm64). Makes the MSI a 64-bit package


TARGETS: dict[str, Target] = {
    "windows-x86_64": Target(
        name="windows-x86_64",
        triple="x86_64-pc-windows-msvc",
        os="windows",
        wix_arch="x64",
    ),
    # The Linux variant is mainly used for alternative validation on Linux (Phase 2).
    "linux-x86_64": Target(
        name="linux-x86_64",
        triple="x86_64-unknown-linux-gnu",
        os="linux",
        wix_arch="x64",
    ),
    # macOS variants ship the same POSIX tarball + .run as Linux (wix_arch is unused).
    "macos-aarch64": Target(
        name="macos-aarch64",
        triple="aarch64-apple-darwin",
        os="macos",
        wix_arch="arm64",
    ),
    "macos-x86_64": Target(
        name="macos-x86_64",
        triple="x86_64-apple-darwin",
        os="macos",
        wix_arch="x64",
    ),
}


def get_target(name: str) -> Target:
    try:
        return TARGETS[name]
    except KeyError:
        known = ", ".join(sorted(TARGETS))
        raise ConfigError(
            f"unknown target: {name!r} (supported: {known})"
        ) from None
