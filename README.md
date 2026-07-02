# pyappdist

**Build native installers for Python apps without hunting down hidden imports, data files, or plugins.**

pyappdist packages your Python application into a native installer:

- Windows: MSI / MSIX
- macOS: DMG(notarization supported)
- Linux: Self-extracting installers

pyappdist does **not** freeze your code. Instead of bundling Python and your app into a
single executable (and fighting hidden imports, data files, and plugins along the way),
it installs your app into a real, dedicated Python runtime — exactly the way `pip` would —
and ships that.

Because the runtime is a normal Python environment, **most apps run as-is**: no hooks, no
`--hidden-import`, no `--add-data`, no per-library workarounds. If it runs under `uv run`,
it almost certainly runs after `pyappdist build`. C extensions, `abi3` wheels, Qt plugins,
and tkinter-based GUIs work unmodified because the install layout is real.


📖 **Documentation:** https://pyappdist.readthedocs.io/

## Status

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the config
schema, CLI, and output layout as it matures.

## What it produces

One `pyproject.toml` can describe several output packages — each is a
`[[tool.pyappdist.targets]]` entry with its own `platform` and `format`:

| `format` | Platform | Output |
| --- | --- | --- |
| `msi`   | `windows-x86_64`                | `.msi` installer (per-user or machine-wide) + portable `.zip` |
| `msix`  | `windows-x86_64`                | `.msix` package for the Microsoft Store / sideloading |
| `linux` | `linux-x86_64`                  | `.tar.gz` + self-extracting `.run` installer (per-user, no root) |
| `macos` | `macos-aarch64` | `.tar.gz` + self-extracting `.run` installer (per-user, no root) |
| `dmg`   | `macos-aarch64`  | `.dmg` disk image (code-signing / notarization supported) |
| `macapp` | `macos-aarch64`  | `.app` bundle (code-signing / notarization supported) |

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
name = "windows"
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
name = "windows"
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

## Samples

Runnable example apps live under [`samples/`](samples/), each with its own
`[tool.pyappdist]` config. They double as smoke tests for tricky cases (C
extensions, GUI stacks, data files, per-target extras):

| Sample | Kind | What it shows |
| --- | --- | --- |
| [`helloworld`](samples/helloworld) | CLI | Smallest possible config — no dependencies. A good starting template; builds for every format (`msi`/`msix`/`linux`/`macos`/`dmg`). |
| [`pandascli`](samples/pandascli) | CLI | pandas + numpy (C extensions) collected as binary wheels and installed into the runtime. Console launcher (`gui = false`). |
| [`datafiles`](samples/datafiles) | CLI | Ships a bundled data file (`data/ebi.jpeg`) via `[tool.uv.build-backend].data` and reads it through `sysconfig`; opens it with Pillow. |
| [`matplotlibdemo`](samples/matplotlibdemo) | GUI | matplotlib plot with the **TkAgg** backend — uses the runtime's bundled tkinter/tcl-tk, no extra GUI deps. |
| [`pygamedemo`](samples/pygamedemo) | GUI | A bouncing ball with pygame-ce (C extensions) collected as Windows wheels.|
| [`pyside6demo`](samples/pyside6demo) | GUI | A Qt window with PySide6 — a large `abi3` wheel (`cp39-abi3`) installed into the cp312 runtime, Qt plugins and all. |
| [`niceguidemo`](samples/niceguidemo) | GUI (web) | "Weather Panel" built with NiceGUI + pywebview + requests; uses per-target `extras` (`gtk`/`qt`/`gui`) to pick the webview backend per platform. |


