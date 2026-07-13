# pytorchdemo

A pyappdist sample that ships **PyTorch in two flavors from one project**: a
small CPU-only build and a **CUDA 13** (`cu130`) build, selected per target.
It runs a tiny matrix computation on the best available device — CUDA GPU,
Apple MPS, or CPU:

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

## How the CPU / CUDA build is selected

`torch` lives in two mutually exclusive extras, each pinned to the matching
PyTorch wheel index in `pyproject.toml` (the pattern from
[Using uv with PyTorch](https://docs.astral.sh/uv/guides/integration/pytorch/)):

```toml
[project.optional-dependencies]
cpu = ["torch>=2.9"]
cuda = ["torch>=2.9"]

[tool.uv]
conflicts = [[{ extra = "cpu" }, { extra = "cuda" }]]

[tool.uv.sources]
torch = [
    { index = "pytorch-cpu", extra = "cpu", marker = "sys_platform != 'darwin'" },
    { index = "pytorch-cu130", extra = "cuda" },
]
```

Each `[[tool.pyappdist.targets]]` entry then picks its flavor with `extras`:
`win32-msi`, `win32-store`, `linux`, and `darwin-arm` ship the CPU build
(`extras = ["cpu"]`), while `win32-msi-cuda`, `win32-store-cuda`, and
`linux-cuda` ship the CUDA build (`extras = ["cuda"]`).

pyappdist exports `uv.lock` as a PEP 751 `pylock.toml`, which records each
package's exact wheel URLs — so these per-package index pins survive into the
build as locked, and each target carries exactly the torch build it selected.
For GPU builds of PyTorch, managing the project with **uv** is recommended.

Notes:

- On macOS the `cpu` extra resolves torch from PyPI (the macOS wheels there
  are the CPU build with MPS support). CUDA wheels exist only for Windows and
  Linux, so there is no `-cuda` macOS target — and only arm64 is targeted,
  since PyTorch no longer publishes Intel macOS wheels.
- For the CUDA targets, the CUDA runtime libraries live inside the wheels —
  the target machine only needs an NVIDIA driver new enough for CUDA 13; no
  CUDA toolkit install is required. On a machine without a GPU (or without a
  compatible driver) the same build runs on the CPU.

> **Note:** CUDA-enabled PyTorch wheels are large (~2–3 GB installed), so the
> `-cuda` installers/archives are correspondingly large. The CPU targets stay
> far smaller.

## Build the distributions

With more than one target defined, `pyappdist build` takes the target names to
build:

```bash
pyappdist build win32-msi          # CPU MSI
pyappdist build win32-msi-cuda     # CUDA MSI
pyappdist build darwin-arm         # macOS .run installer (CPU/MPS)
```
