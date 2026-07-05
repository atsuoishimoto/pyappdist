"""PyTorch (CUDA 13) sample.

Runs a tiny matrix computation. If a CUDA GPU is available it runs on the GPU,
otherwise it falls back to the CPU. It is a console app, so pyappdist ships it
with ``gui = false`` (launched via python.exe).

The wheels come from the PyTorch CUDA 13.0 index (``cu130``), configured in
``pyproject.toml`` under ``[tool.uv.sources]`` / ``[[tool.uv.index]]``. The CUDA
runtime libraries ship inside the wheels, so no separate CUDA toolkit install is
required on the target machine — only an NVIDIA driver new enough for CUDA 13.
"""

from __future__ import annotations

import torch


def main() -> int:
    if torch.cuda.is_available():
        device = torch.device("cuda")
        backend = f"GPU ({torch.cuda.get_device_name(device)})"
    else:
        device = torch.device("cpu")
        backend = "CPU"

    print(f"torch {torch.__version__} / CUDA build {torch.version.cuda}")
    print(f"running on: {backend}")

    a = torch.arange(9, dtype=torch.float32, device=device).reshape(3, 3)
    b = torch.eye(3, device=device) * 2
    c = a @ b

    print("\nA @ (2*I) =")
    print(c.cpu().numpy())
    return 0
