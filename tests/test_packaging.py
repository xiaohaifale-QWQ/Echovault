from pathlib import Path


def test_desktop_package_bundles_resource_monitor_dependency():
    spec = (Path(__file__).resolve().parents[1] / "Echovault.spec").read_text(encoding="utf-8")

    hidden_imports = spec.split("hidden_imports = [", 1)[1].split("]", 1)[0]

    assert '"psutil"' in hidden_imports
    assert '"psutil"' not in spec.split("excludes = [", 1)[1]


def test_desktop_package_defaults_to_lite_profile():
    spec = (Path(__file__).resolve().parents[1] / "Echovault.spec").read_text(encoding="utf-8")

    assert 'os.environ.get("ECHOVAULT_BUILD_PROFILE", "lite")' in spec
    assert 'if not full_build:' in spec
    for module in ("argostranslate", "audio_separator", "torch", "whisper"):
        assert f'"{module}"' in spec.split("if not full_build:", 1)[1]


def test_full_profile_collects_offline_ai_runtimes():
    spec = (Path(__file__).resolve().parents[1] / "Echovault.spec").read_text(encoding="utf-8")
    full_section = spec.split("if full_build:", 1)[1].split("a = Analysis(", 1)[0]

    assert 'collect_submodules("argostranslate")' in spec
    assert 'collect_data_files("argostranslate")' in spec
    assert 'collect_submodules("whisper")' in full_section
    assert 'copy_metadata("audio-separator")' in full_section
