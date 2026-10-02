"""Optional GPU/Sionna RT capability report; safe on CPU-only hosts."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from typing import Any


def detect_capabilities() -> dict[str, Any]:
    """Report detected runtime capabilities without making them a requirement.

    GPU availability is based on a visible NVIDIA device (`nvidia-smi`) or a
    CUDA device reported by PyTorch. CUDA and Sionna are checked independently.
    This is an environment probe, not a simulation result.
    """
    gpu_type = None
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            result = subprocess.run(
                [smi, "--query-gpu=name", "--format=csv,noheader"],
                check=False, capture_output=True, text=True, timeout=5,
            )
            names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if result.returncode == 0 and names:
                gpu_type = "; ".join(names)
        except (OSError, subprocess.TimeoutExpired):
            pass

    cuda_available = False
    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is not None:
        try:
            import torch  # optional dependency
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available and gpu_type is None:
                gpu_type = "; ".join(
                    torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                )
        except (ImportError, RuntimeError, OSError):
            cuda_available = False

    # Sionna RT is an optional experiment. Check for its import spec only; do
    # not import the package, initialize CUDA, or download/cache model assets.
    try:
        sionna_available = importlib.util.find_spec("sionna.rt") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        sionna_available = False
    return {
        "GPU_AVAILABLE": gpu_type is not None or cuda_available,
        "GPU_TYPE": gpu_type or "NONE_DETECTED",
        "CUDA_AVAILABLE": cuda_available,
        "SIONNA_AVAILABLE": sionna_available,
        "experiment": "OPTIONAL_GPU_EXPERIMENT",
        "status": "AVAILABLE" if sionna_available and cuda_available else "SKIPPED_OPTIONAL",
        "result_status": "ENVIRONMENT_CAPABILITY_ONLY",
    }


if __name__ == "__main__":
    print(json.dumps(detect_capabilities(), sort_keys=True))
