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

    torch_cuda_available = False
    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is not None:
        try:
            import torch  # optional dependency
            torch_cuda_available = bool(torch.cuda.is_available())
            if torch_cuda_available and gpu_type is None:
                gpu_type = "; ".join(
                    torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                )
        except (ImportError, RuntimeError, OSError):
            torch_cuda_available = False

    # Sionna RT is optional. Import it only when installed so its documented
    # automatic backend selection can be reported; this may initialize CUDA,
    # but does not start a simulation or download assets.
    sionna_available = False
    drjit_cuda_available = False
    mitsuba_variant = None
    try:
        sionna_available = importlib.util.find_spec("sionna.rt") is not None
        if sionna_available:
            # Sionna RT selects Mitsuba/Dr.Jit automatically. Probe that
            # backend directly: Sionna RT can be installed without PyTorch.
            import drjit
            import mitsuba as mi
            import sionna.rt  # noqa: F401

            drjit_cuda_available = bool(drjit.has_backend(drjit.JitBackend.CUDA))
            mitsuba_variant = mi.variant()
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError, ValueError):
        sionna_available = False
        drjit_cuda_available = False
        mitsuba_variant = None
    # For Sionna, the solver's Dr.Jit backend is authoritative. PyTorch CUDA
    # alone does not prove that Mitsuba/Sionna can use the GPU.
    cuda_available = drjit_cuda_available if sionna_available else torch_cuda_available
    return {
        "GPU_AVAILABLE": gpu_type is not None or cuda_available,
        "GPU_TYPE": gpu_type or "NONE_DETECTED",
        "CUDA_AVAILABLE": cuda_available,
        "SIONNA_AVAILABLE": sionna_available,
        "DRJIT_CUDA_AVAILABLE": drjit_cuda_available,
        "MITSUBA_VARIANT": mitsuba_variant,
        "experiment": "OPTIONAL_GPU_EXPERIMENT",
        "status": "AVAILABLE" if sionna_available and cuda_available else "SKIPPED_OPTIONAL",
        "result_status": "ENVIRONMENT_CAPABILITY_ONLY",
    }


if __name__ == "__main__":
    print(json.dumps(detect_capabilities(), sort_keys=True))
