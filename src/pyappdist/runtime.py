"""python-build-standalone runtime の取得・展開・検証（fetch-runtime）。

URL は uv に依存せず、python-build-standalone の安定仕様のみで構成する。
解決手順は PLAN.md「runtime 取得（fetch-runtime）仕様」に対応。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError
from .targets import Target

LATEST_RELEASE_URL = (
    "https://raw.githubusercontent.com/astral-sh/"
    "python-build-standalone/latest-release/latest-release.json"
)
FLAVOR = "install_only_stripped"
_MARKER = ".pyappdist-runtime.json"


@dataclass(frozen=True)
class RuntimeInfo:
    version: str       # full version "3.12.13"
    minor: str         # "3.12"
    tag: str           # release tag "20260310"
    triple: str
    root: Path         # 展開先 (この直下に python.exe / bin/python3)

    @property
    def python_exe(self) -> Path:
        # OS 判定は triple から
        if "windows" in self.triple:
            return self.root / "python.exe"
        return self.root / "bin" / "python3"


def fetch_runtime(
    target: Target,
    python: str,
    dest: Path,
    *,
    runtime_source: Path | None = None,
    runtime_release: str | None = None,
    cache_dir: Path | None = None,
    log=print,
) -> RuntimeInfo:
    """runtime を ``dest`` へ展開し RuntimeInfo を返す。"""
    minor = ".".join(python.split(".")[:2])
    cache_dir = cache_dir or (Path.home() / ".cache" / "pyappdist" / "runtime")

    # 冪等性: 既に同条件で展開済みならスキップ
    existing = _read_marker(dest)
    if existing and existing["triple"] == target.triple and existing["minor"] == minor:
        if not runtime_release or existing["tag"] == runtime_release:
            log(f"runtime: 既存を再利用 ({existing['version']} @ {dest})")
            return _info_from_marker(dest, existing)

    if dest.exists():
        shutil.rmtree(dest)

    # 1. オフライン源 / 同梱 tarball
    if runtime_source is not None:
        info = _from_local(Path(runtime_source), target, minor, dest, log)
        if info is not None:
            return info

    # 2. release tag と asset_url_prefix を決定
    tag, prefix = _resolve_release(runtime_release, log)

    # 3. SHA256SUMS から full version と sha256 を確定
    filename, sha256, version = _select_asset(prefix, target.triple, minor, log)

    # 4. download + 検証 (キャッシュ)
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / filename
    url = f"{prefix}/{filename}"
    _download_verified(url, archive, sha256, log)

    # 5. 展開
    _extract_install_only(archive, dest, log)

    # 6. 検証 + marker
    info = RuntimeInfo(version=version, minor=minor, tag=tag, triple=target.triple, root=dest)
    _verify(info)
    _write_marker(dest, info, sha256)
    log(f"runtime: 準備完了 {version} ({target.triple}) -> {dest}")
    return info


# --- 内部実装 -------------------------------------------------------------


def _resolve_release(pinned: str | None, log) -> tuple[str, str]:
    if pinned:
        prefix = (
            "https://github.com/astral-sh/python-build-standalone/"
            f"releases/download/{pinned}"
        )
        return pinned, prefix
    log("runtime: latest-release.json を取得")
    data = json.loads(_http_get(LATEST_RELEASE_URL))
    return data["tag"], data["asset_url_prefix"]


def _select_asset(prefix: str, triple: str, minor: str, log) -> tuple[str, str, str]:
    text = _http_get(f"{prefix}/SHA256SUMS").decode("utf-8", "replace")
    pat = re.compile(
        r"^(?P<sha>[0-9a-f]{64})\s+\*?"
        r"(?P<name>cpython-(?P<ver>\d+\.\d+\.\d+)\+\d+-"
        + re.escape(triple)
        + r"-" + re.escape(FLAVOR) + r"\.tar\.gz)\s*$"
    )
    candidates: list[tuple[tuple[int, ...], str, str, str]] = []
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        ver = m.group("ver")
        if ".".join(ver.split(".")[:2]) != minor:
            continue
        key = tuple(int(p) for p in ver.split("."))
        candidates.append((key, m.group("name"), m.group("sha"), ver))
    if not candidates:
        raise BuildError(
            f"対応 runtime が見つからない: python {minor} / {triple} / {FLAVOR}"
        )
    candidates.sort()
    _, name, sha, ver = candidates[-1]
    log(f"runtime: 選択 {name}")
    return name, sha, ver


def _from_local(source: Path, target: Target, minor: str, dest: Path, log) -> RuntimeInfo | None:
    if not source.is_file():
        return None
    m = re.match(
        r"cpython-(\d+\.\d+\.\d+)\+(\d+)-" + re.escape(target.triple) + r"-",
        source.name,
    )
    if not m:
        return None
    version, tag = m.group(1), m.group(2)
    if ".".join(version.split(".")[:2]) != minor:
        return None
    log(f"runtime: ローカル源を使用 {source.name}")
    sha256 = _sha256(source)
    _extract_install_only(source, dest, log)
    info = RuntimeInfo(version=version, minor=minor, tag=tag, triple=target.triple, root=dest)
    _verify(info)
    _write_marker(dest, info, sha256)
    return info


def _extract_install_only(archive: Path, dest: Path, log) -> None:
    """先頭 ``python/`` を剥がして dest 直下へ展開する。"""
    log(f"runtime: 展開 {archive.name} -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(archive, "r:*") as tf:
            # 標準フィルタ(data/tar)は symlink を realpath 検証するため、DrvFs
            # (Windows ボリューム)上の Linux runtime の terminfo symlink で ELOOP
            # になる。公式アーカイブは信頼できるため検証なしのパススルーで展開する。
            tf.extractall(tmp_path, filter=_passthrough_filter)
        inner = tmp_path / "python"
        if not inner.is_dir():
            raise BuildError(f"想定外の archive レイアウト（python/ が無い）: {archive}")
        shutil.move(str(inner), str(dest))


def _passthrough_filter(member, path):  # noqa: ARG001
    # 信頼できる公式アーカイブのみに使用。標準フィルタの realpath 検証を回避する。
    return member


def _verify(info: RuntimeInfo) -> None:
    py = info.python_exe
    if not py.exists():
        raise BuildError(f"runtime 検証失敗: python 実行ファイルが無い {py}")
    if "windows" in info.triple:
        dll = info.root / f"python{info.minor.replace('.', '')}.dll"
        if not dll.exists():
            raise BuildError(f"runtime 検証失敗: {dll.name} が無い")
        lib = info.root / "Lib"
    else:
        lib = info.root / "lib" / f"python{info.minor}"
    if not lib.is_dir():
        raise BuildError(f"runtime 検証失敗: 標準ライブラリが無い {lib}")


def _write_marker(dest: Path, info: RuntimeInfo, sha256: str) -> None:
    (dest / _MARKER).write_text(
        json.dumps(
            {
                "version": info.version,
                "minor": info.minor,
                "tag": info.tag,
                "triple": info.triple,
                "sha256": sha256,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _read_marker(dest: Path) -> dict | None:
    f = dest / _MARKER
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _info_from_marker(dest: Path, m: dict) -> RuntimeInfo:
    return RuntimeInfo(
        version=m["version"], minor=m["minor"], tag=m["tag"],
        triple=m["triple"], root=dest,
    )


def _download_verified(url: str, dest: Path, sha256: str, log) -> None:
    if dest.is_file() and _sha256(dest) == sha256:
        log(f"runtime: キャッシュ命中 {dest.name}")
        return
    log(f"runtime: download {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    actual = _sha256(tmp)
    if actual != sha256:
        tmp.unlink(missing_ok=True)
        raise BuildError(f"sha256 不一致: {url}\n  expected {sha256}\n  actual   {actual}")
    tmp.replace(dest)


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:  # noqa: S310
        return r.read()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
