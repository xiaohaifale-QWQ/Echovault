from pathlib import Path


def test_desktop_package_bundles_resource_monitor_dependency():
    spec = (Path(__file__).resolve().parents[1] / "Echovault.spec").read_text(encoding="utf-8")

    hidden_imports = spec.split("hidden_imports = [", 1)[1].split("]", 1)[0]
    excludes = spec.split("excludes=[", 1)[1].split("]", 1)[0]

    assert '"psutil"' in hidden_imports
    assert '"psutil"' not in excludes
