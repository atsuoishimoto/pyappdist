# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

pyappdist turns a Python app into a native installer — a Windows `.msi`/`.msix` (plus a portable `.zip`), or a macOS `.app`/`.dmg`. It does **not** freeze code into an exe. Instead it installs the app into a real, dedicated python-build-standalone runtime exactly as `pip` would, then ships that tree. Because the install layout is real, most apps (C extensions, abi3 wheels, Qt plugins, tkinter) run unmodified.

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

`cli.py::cmd_build` loops over the selected targets; for each it orchestrates six stages in order (each is also its own subcommand). State flows through a frozen `BuildContext` (`context.py`) that owns a per-target `out_dir` (`appdist/<target-name>/`) and derives `wheelhouse/`, `runtime/`, `image/`, `dist/` under it.

1. **fetch-runtime** (`runtime.py`) — download + extract the python-build-standalone runtime into `appdist/runtime`. URLs are built purely from the python-build-standalone spec (`FLAVOR = install_only_stripped`), independent of uv. Cached and checksum-verified.
2. **build-wheels** (`wheels.py`, `deps.py`) — `deps.py` exports `requirements.txt` from the project's lockfile (auto-detect order: uv → poetry → pipenv → pdm, overridable via `[tool.pyappdist].manager`), then `pip wheel -r` runs **with the target runtime's python** so wheels match the target. Output: `appdist/wheelhouse`.
3. **build-image** (`image/`) — copy runtime → `image/python`, `pip install` the wheelhouse into it, then `compileall` (`image/compile.py`). Produces the real install tree in `appdist/image`.
4. **build-launchers** (`launcher/build.py`) — for each `[[launchers]]` entry, generate `pyappdist_launcher_config.h` + a `.rc` (icon + VERSIONINFO), then compile `launcher.c` with MSVC (`rc` + `cl`) into `image/<name>.exe`. Build artifacts go in `appdist/_launcher_build`.
5. **gen-wix** (`wix/`) — `scan.py` walks the image into a `DirNode`/`FileNode` tree, `guid.py` derives stable component GUIDs, `generate.py` emits the `.wxs`. A stable `upgrade_code` is generated and persisted back into `pyproject.toml` if unset (`ensure_upgrade_code`).
6. **package** — `cli._build_one` branches on the target's `format`:
   - `"msi"` (default): `wix/build.py` `wix build`s the `.wxs` into `<target>/dist/<name>-<version>.msi`. Also a portable zip (`image/make_portable_zip`).
   - `"msix"`: `msix/manifest.py` emits `AppxManifest.xml` (full-trust Win32, `runFullTrust`, one `<Application>` per launcher) and `msix/build.py` stages logos + `makeappx pack`s the image into `<target>/dist/<name>-<version>.msix` (unsigned — the Store signs on ingestion; local install needs Developer Mode). No portable zip for msix.
   - `"app"`/`"dmg"` (macOS): handled by `cli._build_macos`, which is **native-only** (`sys.platform == "darwin"` + arm64 host; otherwise skipped/errored — the target python can't run cross-OS). The macOS launcher is a clang-compiled Mach-O stub (`resources/launcher_mac.c`, built via the `macos` branch in `launcher/build.py`) that `execv`s the bundled `python3`. The new `macos/` module then assembles one `.app` per launcher (`bundle.py`: runtime → `Contents/Resources/python`, launcher → `Contents/MacOS/<name>`, `Info.plist` via `plistlib`, `AppIcon.icns` via `icns.py` `sips`+`iconutil`), deep-signs inner→outer (`sign.py` `deep_sign`; `resolve_sign_options` picks **ad-hoc `codesign -s -`** by default or **Developer ID** — hardened runtime + secure timestamp + entitlements — when `signing_identity`/`PYAPPDIST_SIGNING_IDENTITY` is set), and for `dmg` wraps the bundles in a UDZO disk image (`package.py` `hdiutil`). When a Developer ID identity **and** `notary_profile`/`PYAPPDIST_NOTARY_PROFILE` are set, `notarize.py` submits via `notarytool --wait` and `stapler staple`s (the dmg directly; for `app` it zips the bundle to submit, then staples the bundle). Ad-hoc signatures skip notarization (Apple won't notarize them). No portable zip.
   The Windows formats return `None` (skipped) on a non-Windows target; optional extra signing via `sign.py` (`PYAPPDIST_SIGN_CMD`).

## Config

`pyproject.toml` `[tool.pyappdist]` is the single source of truth. App-level keys (`name`, `python`, `identifier`, `launchers`, `manager`) live there — `identifier` is the reverse-DNS `CFBundleIdentifier`, **required for macOS targets** and unused on Windows. Each output package is one `[[tool.pyappdist.targets]]` entry (`platform`, optional `name`, `format` = `"msi"`(default)/`"msix"`/`"app"`/`"dmg"`, plus format-specific keys — MSI: `manufacturer`/`upgrade_code`/`scope`/`license`; MSIX: `identity_name`/`publisher`/`display_name`/`logo`; macOS: `icon`/`min_macos`/`category` + the deferred `signing_identity`/`team_id`/`notary_profile`/`entitlements` signing seam). `config.py::load_configs` resolves the app-level keys + each selected target into a flat, frozen `Config` (one per target) — so the build stages stay single-target. `targets.py` maps a `platform` (`windows-x86_64`, `linux-x86_64`, `macos-arm64`) to the python-build-standalone triple and the `wix build -arch` value (`wix_arch` is `""` for non-Windows). `scope` is `"user"` (default; per-user `%LocalAppData%\Programs`, `Scope="perUser"`) or `"machine"` (Program Files, `Scope="perMachine"`). The `linux-x86_64` platform exists mainly to validate the non-MSI parts of the pipeline on Linux. macOS targets are native-only (Apple Silicon).

## Errors

All raised errors subclass `PyappdistError` (`errors.py`): `ConfigError` for bad config, `BuildError` for pipeline failures. `cli.main` catches `PyappdistError` and prints `error: ...` with exit 1 — raise these rather than letting raw exceptions escape.

## Tests

pytest, fixtures in `tests/conftest.py` (`sample_config`, `sample_tree`). `test_generate.py` is a **golden test** against `tests/golden/sample.wxs` built from a synthetic (not real-image) tree so it stays deterministic — if a `.wxs` format change is intentional, regenerate the golden file. The E2E `pyappdist build` of a sample is the real integration test and requires the Windows toolchain.
