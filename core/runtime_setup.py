"""Orchestrate one-click CPU/CUDA/WinML inference runtime setup."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .asr.worker_client import WorkerClient, WorkerClientError
from .runtime_detection import HardwareReport, RuntimeSelection, detect_hardware, select_runtime
from .runtime_manager import (
    RuntimeInstallResult,
    RuntimeManagerError,
    RuntimePackage,
    install_runtime,
)
from .runtime_release import fetch_default_runtime_package

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]
PackageLoader = Callable[[str], RuntimePackage]
Installer = Callable[..., RuntimeInstallResult]
RuntimeValidator = Callable[[Path, RuntimePackage], None]


@dataclass(frozen=True)
class RuntimeSetupResult:
    report: HardwareReport
    selection: RuntimeSelection
    install_result: RuntimeInstallResult | None

    @property
    def uses_gpu(self) -> bool:
        return self.selection.variant.backend != "cpu"


class RuntimeSetupService:
    """Coordinates detection, package selection, installation, and activation."""

    def __init__(
        self,
        *,
        detector: Callable[[], HardwareReport] = detect_hardware,
        selector: Callable[[HardwareReport], RuntimeSelection] = select_runtime,
        package_loader: PackageLoader = fetch_default_runtime_package,
        installer: Installer = install_runtime,
        validator: RuntimeValidator | None = None,
        runtime_root: str | Path | None = None,
    ) -> None:
        self._detector = detector
        self._selector = selector
        self._package_loader = package_loader
        self._installer = installer
        self._validator = validator or _validate_worker_runtime
        self._runtime_root = runtime_root

    def configure(
        self,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ) -> RuntimeSetupResult:
        progress = progress or (lambda _percent, _message: None)
        cancelled = cancelled or (lambda: False)
        if cancelled():
            raise RuntimeManagerError("运行时配置已取消")
        progress(0, "正在检测本机硬件...")
        report = self._detector()
        selection = self._selector(report)
        if selection.variant.backend == "cpu":
            progress(100, selection.reason)
            return RuntimeSetupResult(report, selection, None)

        if cancelled():
            raise RuntimeManagerError("运行时配置已取消")
        progress(2, f"已选择 {selection.variant.runtime_id}，正在读取发布清单...")
        package = self._package_loader(selection.variant.runtime_id)
        if package.backend != selection.variant.backend:
            raise RuntimeManagerError("运行时 Release 与本机选择的推理后端不匹配")
        result = self._installer(
            package,
            self._runtime_root,
            progress=progress,
            cancelled=cancelled,
            validator=lambda staging: self._validator(staging, package),
            activate=True,
        )
        return RuntimeSetupResult(report, selection, result)


def _validate_worker_runtime(staging_dir: Path, package: RuntimePackage) -> None:
    """Run the staged worker before it is atomically enabled."""

    worker_path = staging_dir.joinpath(*Path(package.worker_path).parts)
    client = WorkerClient([str(worker_path)], cwd=str(staging_dir))
    try:
        report = client.request("doctor", timeout=30)
    except WorkerClientError as exc:
        raise RuntimeManagerError(f"运行时自检失败，ASR Worker 无法启动：{exc}") from exc
    finally:
        client.close(force=True)

    if not report.get("torch_installed"):
        raise RuntimeManagerError("运行时自检失败：未检测到 Torch")
    if package.backend == "cuda" and not report.get("cuda_available"):
        raise RuntimeManagerError("运行时自检失败：CUDA 运行时无法使用当前 NVIDIA 显卡")
    if package.backend == "winml":
        raise RuntimeManagerError("运行时自检失败：WinML Worker 尚未发布")
