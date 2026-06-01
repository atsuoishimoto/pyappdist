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
    wix_arch: str      # value passed to wix build -arch (x64 / arm64). Windows-only; "" elsewhere.


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
    # macOS: native-only build of a .app/.dmg (no cross-build). wix_arch is unused.
    "macos-arm64": Target(
        name="macos-arm64",
        triple="aarch64-apple-darwin",
        os="macos",
        wix_arch="",
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
