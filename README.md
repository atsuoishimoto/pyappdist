# pyappdist

**Turn a Python app into a native installer — and it just works.**

> ⚠️ **Alpha.** pyappdist is under active development. It works end-to-end today, but the
> config schema, CLI, and output layout may still change without notice.

pyappdist does **not** freeze your code. Instead of bundling Python and your app into a
single executable (and fighting hidden imports, data files, and plugins along the way),
it installs your app into a real, dedicated Python runtime — exactly the way `pip` would —
and ships that.

Because the runtime is a normal Python environment, **most apps run as-is**: no hooks, no
`--hidden-import`, no `--add-data`, no per-library workarounds. If it runs under `uv run`,
it almost certainly runs after `pyappdist build`. C extensions, `abi3` wheels, Qt plugins,
and tkinter-based GUIs work unmodified because the install layout is real.

## What it produces

One `pyproject.toml` can describe several output packages — each is a
`[[tool.pyappdist.targets]]` entry with its own `platform` and `format`:

| `format` | Platform | Output |
| --- | --- | --- |
| `msi`   | `windows-x86_64`                | `.msi` installer (per-user or machine-wide) + portable `.zip` |
| `msix`  | `windows-x86_64`                | `.msix` package for the Microsoft Store / sideloading |
| `linux` | `linux-x86_64`                  | `.tar.gz` + self-extracting `.run` installer (per-user, no root) |
| `macos` | `macos-aarch64` / `macos-x86_64` | `.tar.gz` + self-extracting `.run` installer (per-user, no root) |

The Windows packages are **cross-built from a Linux host (WSL)** by driving the Windows
toolchain (`python.exe`, `uv.exe`, MSVC, WiX) through the WSL interop bridge. The Linux and
macOS packages are built natively on their respective OS.

## Quick start

Add a `[tool.pyappdist]` section to your app's `pyproject.toml`:

```toml
[tool.pyappdist]
name = "My App"
python = "3.12"

[[tool.pyappdist.launchers]]
name = "myapp"              # produces myapp.exe (or a shell wrapper on Linux/macOS)
entry = "myapp:main"        # module:callable
# gui = true                # use pythonw.exe (no console window) on Windows
# icon = "assets/app.ico"   # launcher icon
# args = "--serve"          # fixed leading arguments

[[tool.pyappdist.targets]]
platform = "windows-x86_64"
format = "msi"
manufacturer = "Example Inc."
# scope = "user"            # "user" (default, no admin) or "machine" (Program Files)
```

Then add pyappdist and build:

```bash
uv add --dev pyappdist
uv run pyappdist build      # builds the sole target: wheels -> runtime -> image -> launcher -> wix -> MSI
```

The result lands under `appdist/<target>/dist/`.

### Multiple targets

Declare several targets to ship more than one package from the same config:

```toml
[[tool.pyappdist.targets]]
platform = "windows-x86_64"
format = "msi"
manufacturer = "Example Inc."

[[tool.pyappdist.targets]]
name = "linux"
platform = "linux-x86_64"
format = "linux"

[[tool.pyappdist.targets]]
name = "macos-arm"
platform = "macos-aarch64"
format = "macos"
```

When several targets are defined, `build` requires you to name the one(s) to build (so it
doesn't build them all at once); the individual pipeline stages default to all targets:

```bash
uv run pyappdist build linux           # build just the "linux" target
uv run pyappdist build windows-x86_64  # build the Windows MSI
```

## CLI

`build` runs the whole pipeline; each stage is also its own subcommand if you need to run
them individually (each takes an optional project dir via `-C`, default `.`):

```bash
uv run pyappdist fetch-runtime    # download the python-build-standalone runtime
uv run pyappdist build-wheels     # app + dependency wheels -> <target>/wheelhouse
uv run pyappdist build-image      # runtime + pip install + compileall -> <target>/image
uv run pyappdist build-launchers  # compile launcher(s) into the image (Windows, MSVC)
uv run pyappdist gen-wix          # scan the image -> WiX .wxs
uv run pyappdist build            # all of the above -> the package(s) in <target>/dist
```

## Documentation

Full documentation: **https://pyappdist.readthedocs.io/en/latest/**

- [Installation & requirements](https://pyappdist.readthedocs.io/en/latest/installation.html)
- [Quick start](https://pyappdist.readthedocs.io/en/latest/quickstart.html)
- [How it works](https://pyappdist.readthedocs.io/en/latest/how-it-works.html)
- [Configuration reference](https://pyappdist.readthedocs.io/en/latest/configuration.html)
- [CLI reference](https://pyappdist.readthedocs.io/en/latest/cli.html)
- [Dependency resolution](https://pyappdist.readthedocs.io/en/latest/dependencies.html)
- [Code signing](https://pyappdist.readthedocs.io/en/latest/signing.html)
- [Samples](https://pyappdist.readthedocs.io/en/latest/samples.html)

## Samples

Runnable example apps live under [`samples/`](samples/), each with its own
`[tool.pyappdist]` config:

- **helloworld** — minimal console app (msi + linux + macos targets)
- **datafiles** — bundled package data / resources
- **pandascli** — a CLI built on a C-extension dependency
- **matplotlibdemo** — matplotlib's TkAgg backend via the runtime's tkinter
- **pygamedemo** — a pygame GUI
- **pyside6demo** — a PySide6 (Qt) GUI, plugins and all

## Status

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the config
schema, CLI, and output layout as it matures.

Targets today are Windows x64 (`msi`, `msix`), Linux x64 (`linux`), and macOS arm64/x64
(`macos`). Auto-update and code-signing certificates are out of scope for now; optional
signing of the Windows artifacts is available via `PYAPPDIST_SIGN_CMD`
([docs](https://pyappdist.readthedocs.io/en/latest/signing.html)). Distributed apps are not
obfuscated, and unsigned Windows installers will trigger a SmartScreen warning.
