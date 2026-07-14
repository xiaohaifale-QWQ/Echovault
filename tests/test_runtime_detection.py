from core.runtime_detection import (
    BUILTIN_RUNTIME_VARIANTS,
    CommandOutput,
    GPUAdapter,
    HardwareReport,
    detect_hardware,
    select_runtime,
)


def test_detect_hardware_merges_generic_adapter_and_nvidia_details():
    def runner(command):
        if command[0] == "powershell":
            return CommandOutput(
                0,
                '[{"Name":"NVIDIA GeForce RTX 3060 Ti","PNPDeviceID":"PCI\\\\VEN_10DE&DEV_2486",'
                '"DriverVersion":"596.49","AdapterRAM":8589934592},'
                '{"Name":"Intel UHD Graphics","PNPDeviceID":"PCI\\\\VEN_8086&DEV_9BC4",'
                '"DriverVersion":"31.0.101.1","AdapterRAM":1073741824}]',
            )
        return CommandOutput(0, "NVIDIA GeForce RTX 3060 Ti, 8192 MiB, 596.49, 8.6\n")

    report = detect_hardware(command_runner=runner, system_name="Windows", windows_build=26100)

    assert len(report.adapters) == 2
    nvidia, intel = report.adapters
    assert nvidia.vendor == "nvidia"
    assert nvidia.compute_capability == "8.6"
    assert nvidia.memory_mib == 8192
    assert intel.vendor == "intel"


def test_selection_prefers_cuda_132_for_current_development_gpu():
    report = HardwareReport(
        "win_amd64",
        26100,
        (
            GPUAdapter(
                0,
                "RTX 3060 Ti",
                vendor="nvidia",
                driver_version="596.49",
                memory_mib=8192,
                compute_capability="8.6",
            ),
        ),
    )

    selection = select_runtime(report)

    assert selection.variant.runtime_id == "cuda-cu132"
    assert selection.adapter is not None


def test_selection_uses_cuda_126_when_driver_is_not_new_enough_for_132():
    report = HardwareReport(
        "win_amd64",
        22631,
        (
            GPUAdapter(
                0,
                "RTX 2060",
                vendor="nvidia",
                driver_version="551.76",
                compute_capability="7.5",
            ),
        ),
    )

    assert select_runtime(report).variant.runtime_id == "cuda-cu126"


def test_selection_uses_winml_for_amd_or_intel_on_supported_windows():
    report = HardwareReport(
        "win_amd64", 26100, (GPUAdapter(0, "AMD Radeon", vendor="amd", memory_mib=8192),)
    )

    assert select_runtime(report).variant.runtime_id == "winml-onnx"


def test_selection_falls_back_to_cpu_for_unsupported_hardware():
    report = HardwareReport("win_amd64", 19045, (GPUAdapter(0, "Unknown GPU"),))

    selection = select_runtime(report, BUILTIN_RUNTIME_VARIANTS)

    assert selection.variant.backend == "cpu"
    assert selection.adapter is None
