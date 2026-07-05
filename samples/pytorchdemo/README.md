# pytorchdemo

A pyappdist sample that ships **PyTorch built for CUDA 13** (`cu130`). It runs a
tiny matrix computation on the GPU when a CUDA device is available and falls
back to the CPU otherwise:

```
torch 2.12.1+cu130 / CUDA build 13.0
running on: GPU (NVIDIA GeForce RTX 4090)

A @ (2*I) =
[[ 0.  2.  4.]
 [ 6.  8. 10.]
 [12. 14. 16.]]
```

The launcher is `gui = false`, so the distribution launches via `python.exe`
(console shown).

## How the CUDA build is selected

`torch` is pinned to the PyTorch CUDA 13.0 wheel index in `pyproject.toml`:

```toml
[tool.uv.sources]
torch = [
    { index = "pytorch-cu130", marker = "sys_platform == 'win32' or sys_platform == 'linux'" },
]

[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true
```

pyappdist exports these pins from `uv.lock` and installs the matching wheels
into the target runtime, so the shipped app carries the CUDA build of PyTorch.
The CUDA runtime libraries live inside the wheels — the target machine only
needs an NVIDIA driver new enough for CUDA 13; no CUDA toolkit install is
required. On a machine without a GPU (or without a compatible driver) the same
build runs on the CPU.

CUDA wheels are published only for Windows and Linux, so this sample targets
those two platforms. macOS has no CUDA build.

> **Note:** CUDA-enabled PyTorch wheels are large (~2–3 GB installed), so the
> resulting installer/archive is correspondingly large.

## Build the distribution

```bash
pyappdist build
```
