# pyappdist

**Turn a Python app into a Windows installer — and it just works.**

> ⚠️ **Alpha.** pyappdist is under active development. It works end-to-end today, but the
> config schema, CLI, and output layout may still change without notice.

pyappdist does **not** freeze your code. Instead of bundling Python and your app into a
single executable (and fighting hidden imports, data files, and plugins along the way),
it installs your app into a real, dedicated Python runtime — exactly the way `pip` would —
and ships that.

Because the runtime is a normal Python environment, **most apps run as-is**: no hooks, no
`--hidden-import`, no `--add-data`, no per-library workarounds. If it runs under `uv run`,
it almost certainly runs after `pyappdist build`.

## Why "just works"

Freezers reconstruct your app by static analysis, so anything dynamic tends to break and
needs manual patching. pyappdist skips all of that:

- **Real install layout** — `dist-info`, entry points, `.pth` files, and package data are
  exactly where the package authors put them. `importlib.metadata` / `importlib.resources`
  behave identically to a normal install.
- **Real binary wheels** — C extensions and platform wheels (incl. `abi3`) are installed
  unmodified, with the real interpreter and DLL search paths. No bundling guesswork.
- **Real GUI stacks** — Qt plugins ship in PySide6's normal wheel layout; matplotlib's
  TkAgg backend uses the runtime's bundled tkinter. They just load.

The launcher is a tiny C stub that starts the bundled `python.exe` / `pythonw.exe` as a
subprocess, so there is no `pythonXX.dll` embedding and no C-API version risk — the stub
never changes when the Python version does.

## How it works

```
your app  ──uv build──▶  app wheel ─┐
                                     ├─▶ wheelhouse ──pip install──▶ runtime image ──┬─▶ portable .zip
dependencies ─uv pip download(win)──┘   (python-build-standalone)   + launcher.exe   └─▶ WiX ──▶ .msi
```

Everything lands under `appdist/` (`wheelhouse/`, `runtime/`, `image/`, `dist/`).

## Quick start

Add a `[tool.pyappdist]` section to your app's `pyproject.toml`:

```toml
[project]
name = "myapp"
version = "1.0.0"

[tool.pyappdist]
name = "My App"
identifier = "com.example.myapp"
python = "3.12"
target = "windows-x86_64"

[[tool.pyappdist.launchers]]
name = "myapp"              # produces myapp.exe
entry = "myapp:main"        # module:callable
gui = false                 # true -> pythonw.exe (no console)
# icon = "assets/app.ico"   # optional
# args = "--profile default"# optional fixed arguments

[tool.pyappdist.wix]
manufacturer = "Example Inc."
upgrade_code = "PUT-A-REAL-GUID-HERE"   # stable GUID for upgrades
```

Add pyappdist to your project's dev dependencies and build:

```bash
uv add --dev pyappdist
uv run pyappdist build .          # wheels -> runtime -> image -> launcher -> wix -> MSI
```

Or run the pipeline step by step:

```bash
uv run pyappdist build-wheels    .   # app + deps -> appdist/wheelhouse
uv run pyappdist fetch-runtime   .   # python-build-standalone -> appdist/runtime
uv run pyappdist build-image     .   # install into the runtime + build launcher(s) + portable zip
uv run pyappdist build-launchers .   # (re)build launcher.exe into the image
uv run pyappdist gen-wix         .   # generate the WiX .wxs from the image
```

The image directory itself is a portable app — `appdist/dist/<name>-<version>-portable.zip`
is shippable on its own.

## Samples

Real-world dependencies, built and verified end-to-end (see `sample/`):

| sample            | shows                                  | launcher  |
| ----------------- | -------------------------------------- | --------- |
| `helloworld`      | minimal, no dependencies               | console   |
| `pandascli`       | pandas + numpy (C extensions)          | console   |
| `pygamedemo`      | pygame-ce (SDL)                        | GUI       |
| `pyside6demo`     | PySide6 / Qt (large `abi3` wheels)     | GUI       |
| `matplotlibdemo`  | matplotlib (TkAgg, bundled tkinter)    | GUI       |

```bash
uv run pyappdist build sample/pandascli
```

## GUI startup errors

GUI launchers run under `pythonw.exe` with no console, so a failed import would otherwise
vanish silently. For `gui = true` launchers, pyappdist wraps the entry-point import and, on
failure, shows the error in a message box (via `ctypes`). Errors raised *after* your app
starts are your app's responsibility.

## Requirements

pyappdist itself only needs `pip` (one of its dependencies) — it builds wheels and resolves
dependencies entirely through `python -m pip`, so it works with **any PEP 517/621 project**
regardless of how you manage it (uv, poetry, hatch, pdm, plain pip). Dependencies are resolved
by the *target* runtime's own `python.exe`, so platform-specific markers (e.g. pandas'
`tzdata; sys_platform == "win32"`) resolve correctly even when cross-building from Linux.

To produce the native artifacts you also need:

- **MSVC C++ build tools** (`cl.exe` / `rc.exe`) — compiles `launcher.exe`. Found via `vswhere`.
- **[WiX v5](https://wixtoolset.org/)** (`dotnet tool install --global wix --version 5.0.2`) — builds the MSI.

The Python runtime is fetched from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone) and cached.

## Code signing (optional)

Artifacts are unsigned by default. Set `PYAPPDIST_SIGN_CMD` to sign each `.exe` and the
`.msi`; `{file}` is replaced with the artifact path:

```bash
export PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'
```

## Status

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the config
schema, CLI, and output layout as it matures.

Windows x64 is the current target. macOS/Linux packaging, auto-update, and code-signing
certificates are out of scope for now. Distributed apps are not obfuscated, and unsigned
installers will trigger a SmartScreen warning.
