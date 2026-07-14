"""Cross-vendor Windows GPU detection and inference runtime selection."""

import csv
import io
import json
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Sequence

NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=name,memory.total,driver_version,compute_cap",
    "--format=csv,noheader",
)
POWERSHELL_ADAPTER_COMMAND = (
    "powershell",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,PNPDeviceID,DriverVersion,AdapterRAM,VideoProcessor | "
        "ConvertTo-Json -Compress"
    ),
)
VENDOR_IDS = {"10de": "nvidia", "1002": "amd", "8086": "intel"}


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str]], CommandOutput]


@dataclass(frozen=True)
class GPUAdapter:
    index: int
    name: str
    vendor: str = "unknown"
    vendor_id: str | None = None
    driver_version: str | None = None
    memory_mib: int | None = None
    compute_capability: str | None = None
    pnp_device_id: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HardwareReport:
    platform: str
    windows_build: int | None
    adapters: tuple[GPUAdapter, ...]

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "windows_build": self.windows_build,
            "adapters": [adapter.as_dict() for adapter in self.adapters],
        }


@dataclass(frozen=True)
class RuntimeVariant:
    runtime_id: str
    backend: str
    priority: int = 0
    platform: str = "win_amd64"
    vendors: tuple[str, ...] = ()
    min_windows_build: int | None = None
    min_driver: str | None = None
    compute_capabilities: tuple[str, ...] = ()
    min_memory_mib: int | None = None


@dataclass(frozen=True)
class RuntimeSelection:
    variant: RuntimeVariant
    adapter: GPUAdapter | None
    reason: str

    def as_dict(self) -> dict:
        return {
            "runtime_id": self.variant.runtime_id,
            "backend": self.variant.backend,
            "adapter": self.adapter.as_dict() if self.adapter else None,
            "reason": self.reason,
        }


BUILTIN_RUNTIME_VARIANTS = (
    RuntimeVariant(
        runtime_id="cuda-cu132",
        backend="cuda",
        priority=300,
        vendors=("nvidia",),
        min_driver="580.00",
        compute_capabilities=("7.5", "8.0", "8.6", "8.9", "9.0", "10.0"),
    ),
    RuntimeVariant(
        runtime_id="cuda-cu126",
        backend="cuda",
        priority=200,
        vendors=("nvidia",),
        min_driver="525.00",
    ),
    RuntimeVariant(
        runtime_id="winml-onnx",
        backend="winml",
        priority=100,
        vendors=("amd", "intel"),
        min_windows_build=26100,
    ),
    RuntimeVariant(runtime_id="cpu", backend="cpu", priority=0),
)


def detect_hardware(
    *,
    command_runner: CommandRunner | None = None,
    system_name: str | None = None,
    windows_build: int | None = None,
) -> HardwareReport:
    """Detect Windows display adapters without importing Torch.

    The generic display adapter query finds AMD/Intel/NVIDIA hardware. NVIDIA's own
    tool then enriches the matching adapter with CUDA driver, compute capability,
    and reliable dedicated-memory information.
    """

    system_name = system_name or platform.system()
    platform_name = "win_amd64" if system_name == "Windows" else sys.platform
    if system_name != "Windows":
        return HardwareReport(platform_name, None, ())

    runner = command_runner or _run_command
    detected_build = windows_build if windows_build is not None else _windows_build()
    adapters = _parse_windows_adapters(_run(runner, POWERSHELL_ADAPTER_COMMAND).stdout)
    nvidia_adapters = _parse_nvidia_smi(_run(runner, NVIDIA_SMI_COMMAND).stdout)
    return HardwareReport(
        platform_name,
        detected_build,
        tuple(_merge_nvidia_details(adapters, nvidia_adapters)),
    )


def select_runtime(
    report: HardwareReport,
    variants: Iterable[RuntimeVariant] = BUILTIN_RUNTIME_VARIANTS,
) -> RuntimeSelection:
    """Select the best compatible runtime, always keeping a CPU fallback."""

    candidates = tuple(variants)
    cpu_variants = [variant for variant in candidates if variant.backend == "cpu"]
    if not cpu_variants:
        raise ValueError("运行时清单必须提供 CPU 回退")
    cpu = max(cpu_variants, key=lambda variant: variant.priority)

    matches: list[tuple[RuntimeVariant, GPUAdapter]] = []
    for adapter in report.adapters:
        for variant in candidates:
            if variant.backend == "cpu" or not _matches_variant(variant, adapter, report):
                continue
            matches.append((variant, adapter))
    if matches:
        variant, adapter = max(
            matches,
            key=lambda item: (item[0].priority, item[1].memory_mib or 0),
        )
        return RuntimeSelection(variant, adapter, f"检测到兼容的 {adapter.name}")

    if not report.adapters:
        reason = "未检测到可用显示适配器，使用 CPU 本地识别"
    else:
        reason = "未检测到兼容 GPU 运行时，使用 CPU 本地识别"
    return RuntimeSelection(cpu, None, reason)


def _matches_variant(variant: RuntimeVariant, adapter: GPUAdapter, report: HardwareReport) -> bool:
    if variant.platform != report.platform:
        return False
    if variant.vendors and adapter.vendor not in variant.vendors:
        return False
    if variant.min_windows_build and (report.windows_build or 0) < variant.min_windows_build:
        return False
    if variant.min_driver and not _version_at_least(adapter.driver_version, variant.min_driver):
        return False
    if (
        variant.compute_capabilities
        and adapter.compute_capability not in variant.compute_capabilities
    ):
        return False
    return not (variant.min_memory_mib and (adapter.memory_mib or 0) < variant.min_memory_mib)


def _run(runner: CommandRunner, command: Sequence[str]) -> CommandOutput:
    try:
        return runner(command)
    except (OSError, subprocess.SubprocessError):
        return CommandOutput(returncode=1)


def _run_command(command: Sequence[str]) -> CommandOutput:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    return CommandOutput(completed.returncode, completed.stdout, completed.stderr)


def _windows_build() -> int | None:
    getter = getattr(sys, "getwindowsversion", None)
    return getter().build if getter else None


def _parse_windows_adapters(raw: str) -> list[GPUAdapter]:
    if not raw.strip():
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []

    adapters = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "未知显卡").strip()
        pnp_device_id = str(item.get("PNPDeviceID") or "") or None
        vendor_id = _vendor_id_from_pnp(pnp_device_id)
        vendor = VENDOR_IDS.get(vendor_id or "", _vendor_from_name(name))
        adapters.append(
            GPUAdapter(
                index=index,
                name=name,
                vendor=vendor,
                vendor_id=vendor_id,
                driver_version=_none_or_text(item.get("DriverVersion")),
                memory_mib=_memory_mib(item.get("AdapterRAM")),
                pnp_device_id=pnp_device_id,
            )
        )
    return adapters


def _parse_nvidia_smi(raw: str) -> list[GPUAdapter]:
    adapters = []
    for index, row in enumerate(csv.reader(io.StringIO(raw))):
        if len(row) < 4:
            continue
        adapters.append(
            GPUAdapter(
                index=index,
                name=row[0].strip(),
                vendor="nvidia",
                vendor_id="10de",
                memory_mib=_memory_mib(row[1]),
                driver_version=_none_or_text(row[2]),
                compute_capability=_none_or_text(row[3]),
            )
        )
    return adapters


def _merge_nvidia_details(
    adapters: list[GPUAdapter], nvidia_adapters: list[GPUAdapter]
) -> list[GPUAdapter]:
    merged = list(adapters)
    nvidia_indexes = [index for index, adapter in enumerate(merged) if adapter.vendor == "nvidia"]
    for nvidia_index, nvidia in enumerate(nvidia_adapters):
        if nvidia_index < len(nvidia_indexes):
            index = nvidia_indexes[nvidia_index]
            base = merged[index]
            merged[index] = GPUAdapter(
                index=base.index,
                name=base.name or nvidia.name,
                vendor="nvidia",
                vendor_id="10de",
                driver_version=nvidia.driver_version or base.driver_version,
                memory_mib=nvidia.memory_mib or base.memory_mib,
                compute_capability=nvidia.compute_capability,
                pnp_device_id=base.pnp_device_id,
            )
        else:
            merged.append(GPUAdapter(**(asdict(nvidia) | {"index": len(merged)})))
    return merged


def _vendor_id_from_pnp(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"VEN_([0-9A-Fa-f]{4})", value)
    return match.group(1).lower() if match else None


def _vendor_from_name(name: str) -> str:
    normalized = name.lower()
    if "nvidia" in normalized:
        return "nvidia"
    if "amd" in normalized or "radeon" in normalized:
        return "amd"
    if "intel" in normalized:
        return "intel"
    return "unknown"


def _memory_mib(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    text = str(value).lower()
    if "gib" in text or "gb" in text:
        return int(number * 1024)
    if "mib" in text or "mb" in text:
        return int(number)
    return int(number / 1024 / 1024)


def _none_or_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _version_at_least(actual: str | None, minimum: str) -> bool:
    if not actual:
        return False

    def parts(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", value))

    actual_parts, minimum_parts = parts(actual), parts(minimum)
    length = max(len(actual_parts), len(minimum_parts))
    return actual_parts + (0,) * (length - len(actual_parts)) >= minimum_parts + (0,) * (
        length - len(minimum_parts)
    )
