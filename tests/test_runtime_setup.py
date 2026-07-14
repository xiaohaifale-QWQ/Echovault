from pathlib import Path

import pytest

from core.runtime_detection import GPUAdapter, HardwareReport, RuntimeSelection, RuntimeVariant
from core.runtime_manager import (
    RuntimeInstallResult,
    RuntimeManagerError,
    RuntimePackage,
    RuntimePart,
)
from core.runtime_setup import RuntimeSetupService


def _cuda_selection() -> RuntimeSelection:
    variant = RuntimeVariant("cuda-cu132", "cuda", priority=300, vendors=("nvidia",))
    adapter = GPUAdapter(0, "RTX", vendor="nvidia", driver_version="596.49")
    return RuntimeSelection(variant, adapter, "检测到 NVIDIA GPU")


def _cpu_selection() -> RuntimeSelection:
    return RuntimeSelection(RuntimeVariant("cpu", "cpu"), None, "使用 CPU")


def _report() -> HardwareReport:
    return HardwareReport("win_amd64", 26100, ())


def _package(backend: str = "cuda") -> RuntimePackage:
    return RuntimePackage(
        runtime_id="cuda-cu132",
        backend=backend,
        version="1.0.0",
        archive_size=1,
        archive_sha256="a" * 64,
        installed_size=1,
        worker_path="worker.exe",
        parts=(RuntimePart("part", "https://github.com/example/part", 1, "a" * 64),),
    )


def test_setup_falls_back_to_cpu_without_downloading():
    service = RuntimeSetupService(
        detector=_report,
        selector=lambda _report: _cpu_selection(),
        package_loader=lambda _runtime_id: pytest.fail("CPU must not download a runtime"),
    )

    result = service.configure()

    assert result.uses_gpu is False
    assert result.install_result is None


def test_setup_loads_matching_runtime_and_activates_it(tmp_path):
    calls = {}

    def installer(package, runtime_root, **kwargs):
        calls["package"] = package
        calls["root"] = runtime_root
        calls["activate"] = kwargs["activate"]
        calls["validator"] = kwargs["validator"]
        return RuntimeInstallResult(Path(tmp_path / "runtime"), cached=False, activated=True)

    service = RuntimeSetupService(
        detector=_report,
        selector=lambda _report: _cuda_selection(),
        package_loader=lambda _runtime_id: _package(),
        installer=installer,
        runtime_root=tmp_path,
    )

    result = service.configure()

    assert result.uses_gpu is True
    assert calls["package"].runtime_id == "cuda-cu132"
    assert calls["root"] == tmp_path
    assert calls["activate"] is True
    assert callable(calls["validator"])


def test_setup_rejects_release_with_mismatched_backend():
    service = RuntimeSetupService(
        detector=_report,
        selector=lambda _report: _cuda_selection(),
        package_loader=lambda _runtime_id: _package(backend="winml"),
    )

    with pytest.raises(RuntimeManagerError, match="后端不匹配"):
        service.configure()
