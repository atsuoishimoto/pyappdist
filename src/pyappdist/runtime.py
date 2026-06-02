"""Fetching, extracting, and verifying the python-build-standalone runtime (fetch-runtime).

URLs do not depend on uv and are built solely from python-build-standalone's stable
spec. The resolution procedure corresponds to PLAN.md "runtime fetch (fetch-runtime) spec".
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
    root: Path         # extraction destination (python.exe / bin/python3 directly under this)

    @property
    def python_exe(self) -> Path:
        # OS is determined from the triple
        if "windows" in self.triple:
            return self.root / "python.exe"
        return self.root / "bin" / "python3"


def fetch_runtime(
    target: Target,
    python: str,
    dest: Path,
    *,
    runtime_release: str | None = None,
    cache_dir: Path | None = None,
    log=print,
) -> RuntimeInfo:
    """Extract the runtime into ``dest`` and return RuntimeInfo."""
    minor = ".".join(python.split(".")[:2])
    cache_dir = cache_dir or (Path.home() / ".cache" / "pyappdist" / "runtime")

    # Idempotency: skip if already extracted under the same conditions
    existing = _read_marker(dest)
    if existing and existing["triple"] == target.triple and existing["minor"] == minor:
        if not runtime_release or existing["tag"] == runtime_release:
            log(f"runtime: reusing existing ({existing['version']} @ {dest})")
            return _info_from_marker(dest, existing)

    if dest.exists():
        shutil.rmtree(dest)

    # 1. determine release tag and asset_url_prefix
    tag, prefix = _resolve_release(runtime_release, log)

    # 2. resolve full version and sha256 from SHA256SUMS
    filename, sha256, version = _select_asset(prefix, target.triple, minor, log)

    # 3. download + verify (cache)
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / filename
    url = f"{prefix}/{filename}"
    _download_verified(url, archive, sha256, log)

    # 4. extract
    _extract_install_only(archive, dest, log)

    # 5. verify + marker
    info = RuntimeInfo(version=version, minor=minor, tag=tag, triple=target.triple, root=dest)
    _verify(info)
    _write_marker(dest, info, sha256)
    log(f"runtime: ready {version} ({target.triple}) -> {dest}")
    return info


# --- internal implementation ---------------------------------------------


def _resolve_release(pinned: str | None, log) -> tuple[str, str]:
    if pinned:
        prefix = (
            "https://github.com/astral-sh/python-build-standalone/"
            f"releases/download/{pinned}"
        )
        return pinned, prefix
    log("runtime: fetching latest-release.json")
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
            f"no matching runtime found: python {minor} / {triple} / {FLAVOR}"
        )
    candidates.sort()
    _, name, sha, ver = candidates[-1]
    log(f"runtime: selected {name}")
    return name, sha, ver


def _extract_install_only(archive: Path, dest: Path, log) -> None:
    """Strip the leading ``python/`` and extract directly under dest."""
    log(f"runtime: extracting {archive.name} -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(archive, "r:*") as tf:
            # The archive is a sha256-verified official python-build-standalone build, so
            # the "tar" filter is the right trust level: it applies path-traversal safety
            # and strips setuid/setgid/sticky + group/other-write bits, while preserving
            # the things the runtime needs (executable bits, symlinks) and not rejecting
            # or re-owning members the way the stricter "data" filter does.
            #
            # Note: extracting a Linux runtime onto a case-insensitive volume (DrvFs, i.e.
            # a Windows /mnt path) fails regardless of filter — the terminfo database has
            # case-colliding symlinks (e.g. N/NCR... vs n/ncr...) that loop. Build Linux
            # targets on a native (case-sensitive) filesystem.
            tf.extractall(tmp_path, filter="tar")
        inner = tmp_path / "python"
        if not inner.is_dir():
            raise BuildError(f"unexpected archive layout (no python/): {archive}")
        shutil.move(str(inner), str(dest))


def _verify(info: RuntimeInfo) -> None:
    py = info.python_exe
    if not py.exists():
        raise BuildError(f"runtime verification failed: python executable missing {py}")
    if "windows" in info.triple:
        dll = info.root / f"python{info.minor.replace('.', '')}.dll"
        if not dll.exists():
            raise BuildError(f"runtime verification failed: {dll.name} is missing")
        lib = info.root / "Lib"
    else:
        lib = info.root / "lib" / f"python{info.minor}"
    if not lib.is_dir():
        raise BuildError(f"runtime verification failed: standard library missing {lib}")


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
        log(f"runtime: cache hit {dest.name}")
        return
    log(f"runtime: download {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    actual = _sha256(tmp)
    if actual != sha256:
        tmp.unlink(missing_ok=True)
        raise BuildError(f"sha256 mismatch: {url}\n  expected {sha256}\n  actual   {actual}")
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
