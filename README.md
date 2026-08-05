# pyappdist

**Ship your Python app as a native installer straight from `pyproject.toml`.
If it installs with `pip`, it almost certainly ships with pyappdist.**

📖 **Documentation: https://pyappdist.readthedocs.io/**

pyappdist bridges the Python packaging ecosystem and native application
distribution. It reads your application's `pyproject.toml` and builds setup
packages for Windows, macOS, and Linux:

- Windows: MSI / MSIX
- macOS: DMG / `.app` bundle, PKG installer, or a self-extracting installer
- Linux: self-extracting installer

For example, to build a Windows MSI, configure `pyproject.toml` like this:

```toml
[tool.pyappdist]
name = "My App"
python = "3.12"

[[tool.pyappdist.launchers]]
name = "myapp"              # produces myapp.exe (or a shell wrapper on Linux/macOS)
entry = "myapp:main"        # module:callable
# gui = true                # use pythonw.exe (no console window) on Windows
# icon = { windows = "assets/app.ico" }   # per-OS launcher icon table
# args = "--serve"          # fixed leading arguments

[[tool.pyappdist.targets]]
name = "windows"
platform = "windows-x86_64"
format = "msi"
manufacturer = "Example Inc."
# scope = "user"            # "user" (default, no admin) or "machine" (Program Files)
```

Then build the MSI package (on Windows):

```
uvx pyappdist build
```

The result lands under `appdist/<target>/dist/`.

## How it works

pyappdist creates a dedicated Python runtime directory and installs your
application and its dependencies into it with `pip`. That runtime directory
itself becomes the setup package. The Python runtime comes from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone),
the same distribution Astral's uv uses to build its environments.

With this approach, binary files such as a package's DLLs and related files
such as images are placed in the proper directories according to the Python
language specification and the PyPA specifications. Because this environment
is used for the setup package as-is, most applications can be expected to run
unmodified, with no per-application adjustments. If your app runs under
`uv run`, it almost certainly runs after `pyappdist build`.

## Why pyappdist

Tools such as PyInstaller and Nuitka analyze your code, select only the
necessary files from the Python interpreter and dependency packages, and
build an executable or a directory from that minimal set of files.

The problem is that the selection is not always correct. Static analysis
cannot reliably find dynamically imported modules, data files, or plugins,
so these tools often need per-application adjustments — hidden-import
declarations, data-file lists, and library-specific hooks — and adding a
new dependency can break the build again.

Those tools trade complexity for smaller distributions. A typical Python
runtime adds roughly 100–150 MB. That used to matter more than it does today.

pyappdist makes the opposite trade-off: it builds a complete environment
according to the Python and PyPA specifications and creates the distribution
package from it. **What your application and its dependencies contain does
not matter** — there is nothing to hunt down and nothing to adjust per
application. It also does not build a one-binary executable — it only
provides small launcher executables where needed. Through this design,
pyappdist creates a stable application environment that end users can
rely on.


## What it produces

Each `[[tool.pyappdist.targets]]` entry describes one output package,
selected by its `platform` and `format`:

| `format` | Platform | Output |
| --- | --- | --- |
| `msi`    | Windows | `.msi` installer |
| `msix`   | Windows | `.msix` package (Microsoft Store / sideloading) |
| `linux`  | Linux   | self-extracting `.run` installer |
| `macos`  | macOS   | self-extracting `.run` installer |
| `macapp` | macOS   | `.app` bundle |
| `dmg`    | macOS   | `.dmg` disk image |
| `pkg`    | macOS   | `.pkg` installer |
| `image`  | any     | plain `.zip` / `.tar.gz` archive of the install tree |

Supported `platform` values: `windows-x86_64`, `windows-arm64`,
`linux-x86_64`, `linux-aarch64`, `macos-x86_64`, `macos-aarch64`.
The macOS formats (`macapp` / `dmg` / `pkg`) support code-signing and
notarization.

## Samples

Runnable example apps live under [`samples/`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples),
each with its own `[tool.pyappdist]` config:

- [`helloworld`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/helloworld) — smallest config, no dependencies; a good starting template
- [`pandascli`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pandascli) — pandas + numpy (C extensions)
- [`datafiles`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/datafiles) — ships a bundled data file, located via `sysconfig`
- [`multiprocessingdemo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/multiprocessingdemo) — `multiprocessing` with `spawn` works unmodified
- [`pytorchdemo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pytorchdemo) — CUDA PyTorch via a per-index pin (Windows/Linux)
- [`matplotlibdemo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/matplotlibdemo) — TkAgg GUI using the bundled tkinter
- [`pygamedemo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pygamedemo) — pygame-ce GUI (C extensions)
- [`pyside6demo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pyside6demo) — PySide6 (large abi3 wheel, Qt plugins)
- [`niceguidemo`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/niceguidemo) — NiceGUI + pywebview, per-target `extras` for backend selection
- [`pyvisonmarker`](https://github.com/atsuoishimoto/pyappdist/tree/main/samples/pyvisonmarker) — Gradio + pywebview object detection; environment markers pick the backend, MSI license dialog

### Status

Beta: Core packaging workflows are ready for real-world use, although configuration details may still change before 1.0.
