"""PyTorch sample (CPU and CUDA 13 builds).

Runs a tiny matrix computation. Device selection is CUDA GPU -> Apple MPS ->
CPU, so the same code runs on every target. It is a console app, so pyappdist
ships it with ``gui = false`` (launched via python.exe).

Which torch build ships is chosen per pyappdist target via the ``cpu`` /
``cuda`` extras, configured in ``pyproject.toml`` under
``[project.optional-dependencies]`` / ``[tool.uv.sources]`` /
``[[tool.uv.index]]``. For the CUDA build the runtime libraries ship inside
the wheels, so no separate CUDA toolkit install is required on the target
machine — only an NVIDIA driver new enough for CUDA 13.
"""

from __future__ import annotations

import torch


def main() -> int:
    if torch.cuda.is_available():
        device = torch.device("cuda")
        backend = f"GPU ({torch.cuda.get_device_name(device)})"
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        backend = "Apple MPS"
    else:
        device = torch.device("cpu")
        backend = "CPU"

    build = f"CUDA build {torch.version.cuda}" if torch.version.cuda else "CPU build"
    print(f"torch {torch.__version__} / {build}")
    print(f"running on: {backend}")

    a = torch.arange(9, dtype=torch.float32, device=device).reshape(3, 3)
    b = torch.eye(3, device=device) * 2
    c = a @ b

    print("\nA @ (2*I) =")
    print(c.cpu().numpy())
    return 0
