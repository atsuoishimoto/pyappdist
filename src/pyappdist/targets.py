"""配布ターゲットの定義。

`target` 名（例 ``windows-x86_64``）から、python-build-standalone の
target triple や uv / pip のプラットフォーム指定子へのマッピングを提供する。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class Target:
    name: str          # 設定で使う名前 (windows-x86_64)
    triple: str        # python-build-standalone の target triple
    os: str            # "windows" | "linux" | "macos"
    wix_arch: str      # wix build -arch に渡す値 (x64 / arm64)。MSI を 64bit パッケージにする


TARGETS: dict[str, Target] = {
    "windows-x86_64": Target(
        name="windows-x86_64",
        triple="x86_64-pc-windows-msvc",
        os="windows",
        wix_arch="x64",
    ),
    # Linux 版は主に Linux 上での代替検証 (Phase 2) に使う。
    "linux-x86_64": Target(
        name="linux-x86_64",
        triple="x86_64-unknown-linux-gnu",
        os="linux",
        wix_arch="x64",
    ),
}


def get_target(name: str) -> Target:
    try:
        return TARGETS[name]
    except KeyError:
        known = ", ".join(sorted(TARGETS))
        raise ConfigError(
            f"未知の target: {name!r}（対応: {known}）"
        ) from None
