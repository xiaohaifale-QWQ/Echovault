from core.resource_monitor import ResourceUsage, _parse_nvidia_row, format_resource_usage


def test_parse_nvidia_smi_row():
    assert _parse_nvidia_row("42, 1234, 8192") == (42.0, 1234, 8192)
    assert _parse_nvidia_row("not a gpu row") is None


def test_resource_status_text_includes_cpu_memory_and_gpu():
    text = format_resource_usage(ResourceUsage(12.4, 56.7, 42.0, 1234, 8192))

    assert "CPU 12%" in text
    assert "内存 57%" in text
    assert "GPU 42%" in text
    assert "1234/8192 MiB" in text
