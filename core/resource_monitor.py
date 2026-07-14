"""Low-overhead resource sampling for the local ASR status bar."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from core.process_utils import hidden_window_kwargs


@dataclass(frozen=True)
class ResourceUsage:
    cpu_percent: float | None
    memory_percent: float | None
    gpu_percent: float | None = None
    gpu_memory_used_mib: int | None = None
    gpu_memory_total_mib: int | None = None


def sample_resource_usage() -> ResourceUsage:
    """Read system CPU/RAM and NVIDIA GPU usage without showing a console window."""
    try:
        import psutil

        cpu_percent = float(psutil.cpu_percent(interval=None))
        memory_percent = float(psutil.virtual_memory().percent)
    except (ImportError, OSError):
        cpu_percent = None
        memory_percent = None

    gpu_percent, gpu_used, gpu_total = _sample_nvidia_gpu()
    return ResourceUsage(cpu_percent, memory_percent, gpu_percent, gpu_used, gpu_total)


def format_resource_usage(usage: ResourceUsage) -> str:
    """Format one compact status-bar line."""
    cpu = "CPU --" if usage.cpu_percent is None else f"CPU {usage.cpu_percent:.0f}%"
    memory = (
        "内存 --" if usage.memory_percent is None else f"内存 {usage.memory_percent:.0f}%"
    )
    if usage.gpu_percent is None:
        gpu = "GPU --"
    elif usage.gpu_memory_used_mib is None or usage.gpu_memory_total_mib is None:
        gpu = f"GPU {usage.gpu_percent:.0f}%"
    else:
        gpu = (
            f"GPU {usage.gpu_percent:.0f}% · 显存 "
            f"{usage.gpu_memory_used_mib}/{usage.gpu_memory_total_mib} MiB"
        )
    return f"{cpu}  |  {memory}  |  {gpu}"


def _sample_nvidia_gpu() -> tuple[float | None, int | None, int | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            **hidden_window_kwargs(),
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None, None, None
    if result.returncode != 0:
        return None, None, None
    rows = [_parse_nvidia_row(row) for row in result.stdout.splitlines()]
    valid_rows = [row for row in rows if row is not None]
    if not valid_rows:
        return None, None, None
    # On multi-GPU machines show the busiest device, which is normally the inference GPU.
    return max(valid_rows, key=lambda row: row[0])


def _parse_nvidia_row(row: str) -> tuple[float, int, int] | None:
    fields = [field.strip() for field in row.split(",")]
    if len(fields) != 3:
        return None
    try:
        return float(fields[0]), int(float(fields[1])), int(float(fields[2]))
    except ValueError:
        return None
