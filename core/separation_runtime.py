"""GPU runtime selection for Demucs separation jobs."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .runtime_manager import active_worker_command


class SeparationRuntimeError(RuntimeError):
    """Raised when the selected Demucs runtime cannot be prepared."""


@dataclass(frozen=True)
class SeparationGpuRuntime:
    runtime_id: str
    internal_path: Path
    worker_path: Path


_DLL_HANDLES = []


def active_separation_gpu_runtime() -> SeparationGpuRuntime | None:
    """Return the active CUDA worker's reusable Torch directory, if installed."""

    command = active_worker_command()
    if not command:
        return None
    worker_path = Path(command[0]).resolve()
    runtime_dir = worker_path.parent.parent
    metadata_path = runtime_dir / "runtime.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if metadata.get("backend") != "cuda":
        return None
    internal_path = worker_path.parent / "_internal"
    if not (internal_path / "torch").is_dir():
        return None
    return SeparationGpuRuntime(
        str(metadata.get("runtime_id") or runtime_dir.name),
        internal_path,
        worker_path,
    )


def separation_gpu_available() -> bool:
    """Whether Demucs can start in an isolated process with a CUDA Torch runtime."""

    if active_separation_gpu_runtime() is not None:
        return True
    try:
        import torch

        return bool(torch.cuda.is_available())
    except (ImportError, OSError):
        return False


def prepare_separation_cuda() -> dict:
    """Prepend the active external CUDA Torch before importing Demucs."""

    existing = sys.modules.get("torch")
    if existing is not None:
        try:
            if existing.cuda.is_available():
                return {
                    "torch_version": existing.__version__,
                    "gpu_name": existing.cuda.get_device_name(0),
                }
        except (AttributeError, RuntimeError):
            pass
        raise SeparationRuntimeError("GPU 分离进程过早加载了 CPU Torch，请重新启动软件")

    runtime = active_separation_gpu_runtime()
    if runtime is None:
        raise SeparationRuntimeError("未安装或启用可供 Demucs 使用的 CUDA 运行时")

    dll_paths = (runtime.internal_path, runtime.internal_path / "torch" / "lib")
    os.environ["PATH"] = os.pathsep.join(
        [str(path) for path in dll_paths] + [os.environ.get("PATH", "")]
    )
    for path in dll_paths:
        if hasattr(os, "add_dll_directory") and path.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(path)))
    sys.path.insert(0, str(runtime.internal_path))

    try:
        import torch
    except (ImportError, OSError) as exc:
        raise SeparationRuntimeError(f"无法加载外置 CUDA Torch：{exc}") from exc
    if not torch.cuda.is_available():
        raise SeparationRuntimeError("外置 CUDA Torch 已加载，但没有检测到可用 NVIDIA GPU")
    return {
        "runtime_id": runtime.runtime_id,
        "torch_version": torch.__version__,
        "gpu_name": torch.cuda.get_device_name(0),
    }
