# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

pyappdist turns a Python app into a Windows `.msi` installer (plus a portable `.zip`). It does **not** freeze code into an exe. Instead it installs the app into a real, dedicated python-build-standalone runtime exactly as `pip` would, then ships that tree. Because the install layout is real, most apps (C extensions, abi3 wheels, Qt plugins, tkinter) run unmodified.

Status: **Alpha** — config schema, CLI, and output layout may still change.

## Commands

```bash
# Unit tests
uv run pytest -q
uv run pytest tests/test_generate.py            # one file
uv run pytest tests/test_config.py -k upgrade   # by keyword

# End-to-end build of a sample (exercises the real Windows toolchain via WSL interop)
cd samples/helloworld && uv run pyappdist build

# Individual pipeline stages (all take an optional project dir, default ".")
uv run pyappdist fetch-runtime | build-wheels | build-image | build-launchers | gen-wix | build
```

Docs are Sphinx (`docs/`, published to readthedocs); build with `make -C docs html`.

## Build environment: cross-building from WSL

This is the central architectural constraint. A Windows distribution is built **from a Linux host (WSL)**. The Windows toolchain — `python.exe`, `uv.exe`, MSVC `cl.exe`/`rc`, `wix.exe`, `dotnet` — is invoked through the WSL/Windows interop bridge by calling the `.exe` directly.

- Do **not** share a single `.venv` between the Linux and Windows sides.
- **Path handling rule** (`src/pyappdist/_hostexec.py`): never convert paths with `wslpath`. Instead, run each tool with `cwd=` set to a common ancestor of its inputs/outputs and pass paths **relative** to that cwd — WSL interop converts the cwd to the Windows side, so relative arguments resolve correctly cross-OS. Use `target_relpath(target, path, start)` (normalizes separators to the target OS) and set `cwd=start` on the `subprocess.run`. Inputs that live outside the working tree (bundled `launcher.c`, the user's icon) must be **staged into the build dir** by the caller before the tool runs. `is_cross_windows(target)` gates Windows-only behavior (e.g. choosing `wix.exe` vs `wix`).

When editing any code that shells out to a Windows tool, preserve this cwd + relative-path pattern; reintroducing absolute or `wslpath`-converted paths breaks cross-builds.

### Dev tips: `uv` vs `uv.exe` and the toolchain

The dev box is WSL2 with the repo on a **Windows volume** (`/mnt/d/...`), so Windows `.exe`s run directly from WSL and Windows-side testing is fully local (CI is not required to validate a change).

- **`uv run` (no `.exe`) → Linux uv → the repo's Linux `.venv`.** Use this for developing pyappdist itself: `uv run pytest`, etc.
- **`uv.exe run python` → Windows uv (msvc) → Windows CPython.** Use this only when you need to run something *on the Windows side*.
- **The two `.venv`s are not interchangeable.** The repo `.venv` at `/mnt/d/src/pyappdist` is pinned to Linux; Linux uv puts a `lib64` symlink in it, and touching that venv with `uv.exe` fails with "access denied (os error 5)". When you genuinely need a Windows venv, copy the project into a scratch dir and `uv.exe sync` there — never point `uv.exe` at the repo `.venv`.
- **The pipeline itself never calls `uv.exe`.** `deps.py` uses plain `uv export` (and poetry/pipenv/pdm) for lockfile → `requirements.txt` — pure, OS-independent metadata, so the Linux `uv` is correct. Everything that produces or touches Windows binaries runs the **target runtime's `python.exe`** via interop (`runtime.python_exe` / `layout.python_exe` with `-m pip wheel|install` / `-m compileall`), not uv. `image/install.py` deliberately uses `python -m pip install --no-index` rather than uv to avoid uv's cache/index behavior. Keep this split: lockfile/metadata → plain `uv`; anything emitting Windows artifacts → the runtime's `python.exe`.

Windows toolchain available from this WSL session (used by the launcher/MSI stages):
- **MSVC** `cl.exe` / `rc.exe` are not on `PATH` — resolve them via `vcvars` (or `vswhere`). VS Community 2026 lives at `C:\Program Files\Microsoft Visual Studio\18\Community`.
- **WiX** is a dotnet global tool: `dotnet.exe tool install --global wix` (dotnet 10).

## Pipeline architecture

`cli.py::cmd_build` orchestrates six stages in order; each is also its own subcommand. State flows through a frozen `BuildContext` (`context.py`) that owns `out_dir` (`appdist/`) and derives `wheelhouse/`, `runtime/`, `image/`, `dist/` paths.

1. **fetch-runtime** (`runtime.py`) — download + extract the python-build-standalone runtime into `appdist/runtime`. URLs are built purely from the python-build-standalone spec (`FLAVOR = install_only_stripped`), independent of uv. Cached and checksum-verified.
2. **build-wheels** (`wheels.py`, `deps.py`) — `deps.py` exports `requirements.txt` from the project's lockfile (auto-detect order: uv → poetry → pipenv → pdm, overridable via `[tool.pyappdist].manager`), then `pip wheel -r` runs **with the target runtime's python** so wheels match the target. Output: `appdist/wheelhouse`.
3. **build-image** (`image/`) — copy runtime → `image/python`, `pip install` the wheelhouse into it, then `compileall` (`image/compile.py`). Produces the real install tree in `appdist/image`.
4. **build-launchers** (`launcher/build.py`) — for each `[[launchers]]` entry, generate `pyappdist_launcher_config.h` + a `.rc` (icon + VERSIONINFO), then compile `launcher.c` with MSVC (`rc` + `cl`) into `image/<name>.exe`. Build artifacts go in `appdist/_launcher_build`.
5. **gen-wix** (`wix/`) — `scan.py` walks the image into a `DirNode`/`FileNode` tree, `guid.py` derives stable component GUIDs, `generate.py` emits the `.wxs`. A stable `upgrade_code` is generated and persisted back into `pyproject.toml` if unset (`ensure_upgrade_code`).
6. **build-msi** (`wix/build.py`) — `wix build` the `.wxs` into `appdist/dist/<name>-<version>.msi`. Returns `None` (MSI skipped) on a non-Windows target. Also: portable zip (`image/make_portable_zip`) and optional signing (`sign.py`, driven by `PYAPPDIST_SIGN_CMD`).

## Config

`pyproject.toml` `[tool.pyappdist]` is the single source of truth, normalized into the frozen `Config` dataclass in `config.py`. `targets.py` maps a target name (`windows-x86_64`, `linux-x86_64`) to the python-build-standalone triple and the `wix build -arch` value. The `linux-x86_64` target exists mainly to validate the non-MSI parts of the pipeline on Linux.

## Errors

All raised errors subclass `PyappdistError` (`errors.py`): `ConfigError` for bad config, `BuildError` for pipeline failures. `cli.main` catches `PyappdistError` and prints `error: ...` with exit 1 — raise these rather than letting raw exceptions escape.

## Tests

pytest, fixtures in `tests/conftest.py` (`sample_config`, `sample_tree`). `test_generate.py` is a **golden test** against `tests/golden/sample.wxs` built from a synthetic (not real-image) tree so it stays deterministic — if a `.wxs` format change is intentional, regenerate the golden file. The E2E `pyappdist build` of a sample is the real integration test and requires the Windows toolchain.
