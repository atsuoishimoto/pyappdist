# pyvisionmarker

"Vision Inspector" — a pyappdist GUI sample that runs **local object detection**
with a Hugging Face model (`facebook/detr-resnet-50`) and no network AI API.
The UI is a Gradio app served on `127.0.0.1:7860` from a daemon thread, wrapped
in a native desktop window by pywebview.

The launcher is `gui = true`, so the distribution launches without a console
window.

## What it demonstrates

**A GUI backend selected by environment marker.** The pywebview backend is
picked in `[project.dependencies]`, not with per-target `extras`:

```toml
dependencies = [
    "pywebview>=6.2.1; sys_platform != 'linux'",
    "pywebview[qt]>=6.2.1; sys_platform == 'linux'",
]
```

Linux gets `pywebview[qt]` (PyQt6 / QtWebEngine, a Chromium-based webview);
Windows uses WebView2 and macOS WebKit through the plain package. Because
pyappdist exports the lockfile for the *target* platform, each target resolves
the marker on its own and installs only its backend — no target-level config
needed. Compare with `niceguidemo`, which selects its backend with per-target
`extras` instead.

It also exercises a heavyweight dependency stack — torch, torchvision,
transformers, timm, safetensors — installed into the runtime as ordinary
wheels, plus a **license dialog in the MSI** (`license = "LICENSE.rtf"`).

## License

GPL-3.0-only (`LICENSE`). The Linux distribution ships PyQt6/QtWebEngine, which
is GPL v3. `LICENSE.rtf` is the same text in the RTF form WiX needs for the
installer's license page.

## Build the distributions

pyappdist is **not** in a dev dependency group here: gradio pins
`tomlkit<0.15` and pyappdist requires `>=0.15`, so they cannot share one
environment. Run it isolated instead:

```bash
uvx pyappdist build win32-msi      # Windows MSI (with the license dialog)
uvx pyappdist build linux          # Linux .run installer
uvx pyappdist build darwin-arm-dmg # macOS .dmg
```

Targets exist for Windows x86_64, Linux x86_64/aarch64 and macOS arm64. There
are no `windows-arm64` or `macos-x86_64` targets because torch/torchvision
publish no cp314 wheels for them.

> **Note:** the dependency stack is large. On Linux x86_64 the PyPI `torch`
> wheel pulls the `nvidia-*` CUDA runtime packages, so the installer is several
> GB. The app runs on the GPU when CUDA is available and on the CPU otherwise.

## Run from source

```bash
uv sync
uv run pyvisionmarker
```
