# pyappdist

**Ship your Python app as a native installer straight from `pyproject.toml`.
If it installs with `pip`, it ships with pyappdist.**

pyappdist reads your Python application's `pyproject.toml` and builds setup
packages for distribution:

- Windows: MSI / MSIX
- macOS: DMG / `.app` bundle, or a self-extracting installer
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

📖 **Documentation: https://pyappdist.readthedocs.io/**

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

One `pyproject.toml` can describe several output packages — each is a
`[[tool.pyappdist.targets]]` entry with its own `platform` and `format`:

| `format` | Platform | Output |
| --- | --- | --- |
| `msi`   | `windows-x86_64`                | `.msi` installer (per-user or machine-wide) |
| `msix`  | `windows-x86_64`                | `.msix` package for the Microsoft Store / sideloading |
| `linux` | `linux-x86_64`                  | self-extracting `.run` installer (per-user, no root) |
| `macos` | `macos-aarch64` / `macos-x86_64` | self-extracting `.run` installer (per-user, no root) |
| `dmg`   | `macos-aarch64` / `macos-x86_64` | `.dmg` disk image (code-signing / notarization supported) |
| `macapp` | `macos-aarch64` / `macos-x86_64` | `.app` bundle (code-signing / notarization supported) |
| `image` | any of the above                | plain archive of the install tree — `.zip` (Windows) / `.tar.gz` (Linux, macOS), no installer |

## Samples

Runnable example apps live under [`samples/`](samples/), each with its own
`[tool.pyappdist]` config. They double as smoke tests for tricky cases (C
extensions, GUI stacks, data files, per-target extras):

| Sample | Kind | What it shows |
| --- | --- | --- |
| [`helloworld`](samples/helloworld) | CLI | Smallest possible config — no dependencies. A good starting template; builds for every format (`msi`/`msix`/`linux`/`macos`/`dmg`). |
| [`pandascli`](samples/pandascli) | CLI | pandas + numpy (C extensions) collected as binary wheels and installed into the runtime. Console launcher (`gui = false`). |
| [`datafiles`](samples/datafiles) | CLI | Ships a bundled data file (`data/ebi.jpeg`) via `[tool.uv.build-backend].data` and reads it through `sysconfig`; opens it with Pillow. |
| [`multiprocessingdemo`](samples/multiprocessingdemo) | CLI | Runs a `multiprocessing.Pool` across worker processes. The launcher runs the bundled interpreter directly, so `spawn` re-launches it correctly — no dependencies. |
| [`pytorchdemo`](samples/pytorchdemo) | CLI | Ships PyTorch built for CUDA 13 (`cu130`) via a per-index `[tool.uv.sources]` pin; runs on the GPU when available, CPU otherwise. Windows/Linux only. |
| [`matplotlibdemo`](samples/matplotlibdemo) | GUI | matplotlib plot with the **TkAgg** backend — uses the runtime's bundled tkinter/tcl-tk, no extra GUI deps. |
| [`pygamedemo`](samples/pygamedemo) | GUI | A bouncing ball with pygame-ce (C extensions) collected as Windows wheels.|
| [`pyside6demo`](samples/pyside6demo) | GUI | A Qt window with PySide6 — a large `abi3` wheel (`cp39-abi3`) installed into the cp312 runtime, Qt plugins and all. |
| [`niceguidemo`](samples/niceguidemo) | GUI (web) | "Weather Panel" built with NiceGUI + pywebview + requests; uses per-target `extras` (`gtk`/`qt`/`gui`) to pick the webview backend per platform. |

### Status

Beta: Core packaging workflows are ready for real-world use, although configuration details may still change before 1.0.
